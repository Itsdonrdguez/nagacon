from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.dibbs.pdf_bulk_export import DEFAULT_DIBBS_PDF_EXPORT_DIR, export_dibbs_pdfs_for_fscs


def _parse_fscs(value: str) -> list[str]:
    fscs: list[str] = []
    seen: set[str] = set()
    for part in value.split(","):
        digits = re.sub(r"\D", "", part)
        if len(digits) < 4:
            continue
        fsc = digits[:4]
        if fsc in seen:
            continue
        seen.add(fsc)
        fscs.append(fsc)
    return fscs


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk-download main DIBBS solicitation PDFs by selected FSC.")
    parser.add_argument("--fsc", required=True, help="Comma-separated selected FSC codes, for example: 6520,5998,6515")
    parser.add_argument("--output-dir", default=str(DEFAULT_DIBBS_PDF_EXPORT_DIR), help="Root output folder. Defaults to backend/exports/dibbs_pdfs")
    parser.add_argument("--limit", type=int, default=25, help="Max PDFs per FSC. Default 25.")
    parser.add_argument("--include-past-due", action="store_true", help="Include past-due RFQs. Default exports open/current RFQs only.")
    parser.add_argument("--headed", action="store_true", help="Show the browser while searching DIBBS.")
    parser.add_argument("--download-timeout", type=int, default=60, help="PDF download timeout in seconds.")
    parser.add_argument("--pause", type=float, default=0.25, help="Seconds to pause between PDF downloads.")
    args = parser.parse_args()

    fscs = _parse_fscs(args.fsc)
    if not fscs:
        print("No valid FSC codes were provided.")
        return 2

    summary = export_dibbs_pdfs_for_fscs(
        fscs=fscs,
        output_dir=Path(args.output_dir).resolve(),
        limit_per_fsc=max(args.limit, 1),
        include_past_due=bool(args.include_past_due),
        headless=not bool(args.headed),
        download_timeout=max(args.download_timeout, 5),
        pause_seconds=max(args.pause, 0),
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
