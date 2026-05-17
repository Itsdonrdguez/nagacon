
import logging
from pathlib import Path
import json
import re

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


def parse_opportunity_file(file_path: str) -> dict:
    '''
    Safe document parsing wrapper.
    Attempts to extract text from files but fails gracefully so the API never crashes.
    '''

    extracted_text = ""

    text_result = _read_text_like_file(file_path)
    if text_result is not None:
        return text_result

    try:
        # Try PyMuPDF first
        import fitz
        doc = fitz.open(file_path)
        pages = []
        for page in doc:
            pages.append(page.get_text())
        extracted_text = "\n".join(pages)
        doc.close()
        return {
            "parser": "pymupdf",
            "text": extracted_text
        }

    except Exception as pymupdf_error:
        logger.warning(f"PyMuPDF parsing failed: {pymupdf_error}")

    try:
        # Fallback to pypdf
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        extracted_text = "\n".join(pages)
        return {
            "parser": "pypdf",
            "text": extracted_text
        }

    except Exception as pypdf_error:
        logger.warning(f"PyPDF parsing failed: {pypdf_error}")

    return {
        "parser": "none",
        "text": "",
        "error": "No parser succeeded"
    }
