
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
import json
import re

from app.services.document_security import document_max_bytes, document_page_limit, document_parser_timeout_seconds, validate_file_size_bytes

logger = logging.getLogger(__name__)


def _strip_html(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"\\s+", " ", text)
    return text.strip()


def _read_text_like_file(file_path: str) -> dict | None:
    suffix = Path(file_path).suffix.lower()
    if suffix not in {".txt", ".text", ".md", ".html", ".htm", ".json", ".xml", ".csv"}:
        return None
    try:
        raw = Path(file_path).read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        logger.warning(f"Text file parsing failed: {exc}")
        return None

    if suffix == ".json":
        try:
            payload = json.loads(raw)
            pretty = json.dumps(payload, indent=2, ensure_ascii=False)
            return {
                "parser": "json",
                "text": pretty,
            }
        except Exception:
            pass

    if suffix in {".html", ".htm"}:
        return {
            "parser": "html_text",
            "text": _strip_html(raw),
        }

    return {
        "parser": "text",
        "text": raw,
    }


def _parse_file_now(file_path: str) -> dict:
    extracted_text = ""

    text_result = _read_text_like_file(file_path)
    if text_result is not None:
        return text_result

    try:
        import fitz

        doc = fitz.open(file_path)
        try:
            page_total = int(getattr(doc, "page_count", 0) or 0)
            page_limit = document_page_limit()
            pages = []
            for index, page in enumerate(doc):
                if index >= page_limit:
                    break
                pages.append(page.get_text())
            extracted_text = "\n".join(pages)
            return {
                "parser": "pymupdf",
                "text": extracted_text,
                "page_count": page_total,
                "page_limit_applied": page_total > page_limit,
            }
        finally:
            doc.close()

    except Exception as pymupdf_error:
        logger.warning(f"PyMuPDF parsing failed: {pymupdf_error}")

    try:
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        pages = []
        page_total = len(reader.pages)
        page_limit = document_page_limit()
        for page in reader.pages[:page_limit]:
            pages.append(page.extract_text() or "")
        extracted_text = "\n".join(pages)
        return {
            "parser": "pypdf",
            "text": extracted_text,
            "page_count": page_total,
            "page_limit_applied": page_total > page_limit,
        }

    except Exception as pypdf_error:
        logger.warning(f"PyPDF parsing failed: {pypdf_error}")

    return {
        "parser": "none",
        "text": "",
        "error": "No parser succeeded"
    }


def parse_opportunity_file(file_path: str) -> dict:
    '''
    Safe document parsing wrapper.
    Attempts to extract text from files but fails gracefully so the API never crashes.
    '''
    path = Path(file_path)
    if not path.exists():
        return {"parser": "none", "text": "", "error": "File not found"}

    valid_size, size_error = validate_file_size_bytes(path.stat().st_size)
    if not valid_size:
        return {"parser": "none", "text": "", "error": size_error}

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_parse_file_now, file_path)
        try:
            return future.result(timeout=document_parser_timeout_seconds())
        except FutureTimeoutError:
            return {"parser": "none", "text": "", "error": "Document parsing timed out"}
