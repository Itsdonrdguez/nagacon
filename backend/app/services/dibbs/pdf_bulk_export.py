from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import requests

from app.services.dibbs.custom_query_search import search_dibbs_custom_query_by_fsc
from app.services.dibbs.session import dibbs_page

BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DIBBS_PDF_EXPORT_DIR = BACKEND_ROOT / "exports" / "dibbs_pdfs"
PDF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*",
}


ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass
class DibbsPdfExportRecord:
    fsc: str
    solicitation_number: str | None
    nsn: str | None
    nomenclature: str | None
    issue_date: str | None
    return_by_date: str | None
    quantity: str | None
    pdf_url: str | None
    status: str
    file_path: str | None = None
    error: str | None = None


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return re.sub(r"\s+", " ", text) or None


def _normalize_sol(value: str | None) -> str | None:
    value = _clean(value)
    if not value:
        return None
    return re.sub(r"[^A-Z0-9]", "", value.upper()) or None


def _safe_filename(value: str | None, fallback: str) -> str:
    value = _clean(value) or fallback
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._-")
    return value[:140] or fallback


def _parse_fscs(values: list[str] | None) -> list[str]:
    fscs: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        digits = re.sub(r"\D", "", str(value or ""))
        if len(digits) < 4:
            continue
        fsc = digits[:4]
        if fsc in seen:
            continue
        seen.add(fsc)
        fscs.append(fsc)
    return fscs


def _derive_pdf_url(row: dict[str, Any]) -> str | None:
    pdf_url = _clean(row.get("pdf_url"))
    if pdf_url:
        return pdf_url
    sol = _normalize_sol(row.get("solicitation_number") or row.get("normalized_solicitation_number"))
    if not sol:
        return None
    return f"https://dibbs2.bsm.dla.mil/Downloads/RFQ/{sol[-1]}/{sol}.PDF"


def _versioned_path(folder: Path, stem: str, suffix: str = ".pdf") -> Path:
    candidate = folder / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    version = 2
    while True:
        candidate = folder / f"{stem}_v{version}{suffix}"
        if not candidate.exists():
            return candidate
        version += 1


def _is_pdf_bytes(path: Path) -> bool:
    try:
        return path.read_bytes()[:5] == b"%PDF-"
    except Exception:
        return False


def _accept_dibbs2_warning(pdf_url: str, headless: bool = True) -> dict[str, str]:
    with dibbs_page(headless=headless) as (_, context, page):
        page.goto(pdf_url, wait_until="domcontentloaded", timeout=60000)
        agree = page.locator("#butAgree")
        if agree.count() > 0:
            agree.first.click()
            page.wait_for_timeout(1000)
        return {cookie["name"]: cookie["value"] for cookie in context.cookies("https://dibbs2.bsm.dla.mil")}


def _download_pdf(
    url: str,
    destination: Path,
    *,
    session: requests.Session,
    timeout: int = 60,
) -> None:
    with session.get(url, headers={**PDF_HEADERS, "Referer": url}, timeout=timeout, stream=True) as response:
        response.raise_for_status()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    handle.write(chunk)
    if destination.stat().st_size == 0:
        raise ValueError("Downloaded file was empty")
    if not _is_pdf_bytes(destination):
        try:
            destination.unlink()
        except Exception:
            pass
        raise ValueError("DIBBS returned a non-PDF response instead of the solicitation PDF")


def _record_from_row(
    fsc: str,
    row: dict[str, Any],
    status: str,
    file_path: Path | None = None,
    error: str | None = None,
) -> DibbsPdfExportRecord:
    return DibbsPdfExportRecord(
        fsc=fsc,
        solicitation_number=_clean(row.get("solicitation_number")),
        nsn=_clean(row.get("nsn")),
        nomenclature=_clean(row.get("nomenclature")),
        issue_date=_clean(row.get("issue_date")),
        return_by_date=_clean(row.get("return_by_date")),
        quantity=_clean(row.get("quantity")),
        pdf_url=_derive_pdf_url(row),
        status=status,
        file_path=str(file_path) if file_path else None,
        error=error,
    )


def _write_manifest(records: list[DibbsPdfExportRecord], output_dir: Path, run_id: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"manifest_{run_id}.csv"
    jsonl_path = output_dir / f"manifest_{run_id}.jsonl"
    fieldnames = list(DibbsPdfExportRecord.__dataclass_fields__.keys())
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(record.__dict__)
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.__dict__, ensure_ascii=False) + "\n")
    return csv_path, jsonl_path


def export_dibbs_pdfs_for_fscs(
    *,
    fscs: list[str],
    output_dir: Path = DEFAULT_DIBBS_PDF_EXPORT_DIR,
    limit_per_fsc: int = 25,
    include_past_due: bool = False,
    headless: bool = True,
    download_timeout: int = 60,
    pause_seconds: float = 0.25,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    selected_fscs = _parse_fscs(fscs)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    records: list[DibbsPdfExportRecord] = []
    limit = max(int(limit_per_fsc or 25), 1)
    total_steps = max(len(selected_fscs) * limit, 1)
    completed_steps = 0

    summary: dict[str, Any] = {
        "run_id": run_id,
        "output_dir": str(output_dir),
        "fscs": selected_fscs,
        "limit_per_fsc": limit,
        "found": 0,
        "downloaded": 0,
        "failed": 0,
        "missing_pdf_url": 0,
        "by_fsc": {},
    }
    pdf_session = requests.Session()
    pdf_session.headers.update(PDF_HEADERS)
    dibbs2_session_ready = False

    def _progress(source: str, label: str, raw_rows: int | None = None) -> None:
        if progress_callback:
            progress_callback(
                {
                    "source": source,
                    "label": label,
                    "raw_rows": raw_rows,
                    "completed_steps": min(completed_steps, total_steps),
                    "total_steps": total_steps,
                }
            )

    _progress("DIBBS PDFs", "Preparing bulk PDF download", None)

    for fsc in selected_fscs:
        _progress("DIBBS PDFs", f"Searching FSC {fsc}", None)
        rows, diagnostics = search_dibbs_custom_query_by_fsc(
            fsc=fsc,
            limit=limit,
            max_pages=999,
            include_past_due=include_past_due,
            all_results=True,
            headless=headless,
        )
        rows = rows[:limit]
        summary["found"] += len(rows)
        summary["by_fsc"][fsc] = {
            "found": len(rows),
            "downloaded": 0,
            "failed": 0,
            "missing_pdf_url": 0,
            "diagnostics": diagnostics,
        }

        fsc_folder = output_dir / fsc
        fsc_folder.mkdir(parents=True, exist_ok=True)

        for row in rows:
            pdf_url = _derive_pdf_url(row)
            sol = _normalize_sol(row.get("solicitation_number") or row.get("normalized_solicitation_number"))
            label = f"{fsc} {sol or _clean(row.get('nsn')) or 'PDF'}"

            if not pdf_url:
                records.append(_record_from_row(fsc, row, "missing_pdf_url", error="No main solicitation PDF URL found"))
                summary["missing_pdf_url"] += 1
                summary["by_fsc"][fsc]["missing_pdf_url"] += 1
                completed_steps += 1
                _progress("DIBBS PDFs", label, 0)
                continue

            nsn = _safe_filename(row.get("nsn"), "NO_NSN")
            stem = _safe_filename(f"{sol or 'NO_SOL'}_{nsn}", f"dibbs_{fsc}")
            destination = _versioned_path(fsc_folder, stem)

            try:
                if not dibbs2_session_ready:
                    for name, value in _accept_dibbs2_warning(pdf_url, headless=headless).items():
                        pdf_session.cookies.set(name, value, domain="dibbs2.bsm.dla.mil")
                    dibbs2_session_ready = True
                _progress("DIBBS PDFs", f"Downloading {label}", 1)
                _download_pdf(pdf_url, destination, session=pdf_session, timeout=download_timeout)
                records.append(_record_from_row(fsc, row, "downloaded", file_path=destination))
                summary["downloaded"] += 1
                summary["by_fsc"][fsc]["downloaded"] += 1
            except Exception as exc:
                records.append(_record_from_row(fsc, row, "failed", file_path=destination, error=str(exc)))
                summary["failed"] += 1
                summary["by_fsc"][fsc]["failed"] += 1
            finally:
                completed_steps += 1
                _progress("DIBBS PDFs", label, 1)

            if pause_seconds > 0:
                time.sleep(pause_seconds)

        # Count unused limit slots so the progress bar finishes even when an
        # FSC has fewer current RFQs than the configured cap.
        completed_steps += max(limit - len(rows), 0)
        _progress("DIBBS PDFs", f"Finished FSC {fsc}", len(rows))

    csv_path, jsonl_path = _write_manifest(records, output_dir, run_id)
    summary["manifest_csv"] = str(csv_path)
    summary["manifest_jsonl"] = str(jsonl_path)
    return summary
