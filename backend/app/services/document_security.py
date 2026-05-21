from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import settings


def document_max_bytes() -> int:
    try:
        return max(1024, int(getattr(settings, "DOCUMENT_MAX_BYTES", 25 * 1024 * 1024) or (25 * 1024 * 1024)))
    except Exception:
        return 25 * 1024 * 1024


def document_page_limit() -> int:
    try:
        return max(1, int(getattr(settings, "DOCUMENT_PARSER_PAGE_LIMIT", 200) or 200))
    except Exception:
        return 200


def document_parser_timeout_seconds() -> float:
    try:
        return max(1.0, float(getattr(settings, "DOCUMENT_PARSER_TIMEOUT_SECONDS", 30) or 30))
    except Exception:
        return 30.0


def malware_scan_metadata(*, file_path: str | None = None, filename: str | None = None) -> dict[str, Any]:
    provider = str(getattr(settings, "MALWARE_SCAN_PROVIDER", "") or "").strip() or None
    return {
        "status": "not_scanned",
        "provider": provider,
        "file_path": file_path,
        "filename": filename,
        "hook_ready": True,
    }


def validate_file_size_bytes(size_bytes: int) -> tuple[bool, str | None]:
    limit = document_max_bytes()
    if int(size_bytes or 0) > limit:
        return False, f"file exceeds maximum size of {limit} bytes"
    return True, None


def is_allowed_download_content_type(content_type: str | None, filename: str | None = None) -> bool:
    normalized = str((content_type or "").split(";")[0]).strip().lower()
    suffix = Path(str(filename or "")).suffix.lower()
    if suffix in {".pdf", ".txt", ".text", ".md", ".csv", ".json", ".xml", ".html", ".htm", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".rtf"}:
        return True
    if not normalized:
        return False
    if normalized == "text/html":
        return False
    allowed = {
        "application/pdf",
        "text/plain",
        "text/csv",
        "application/json",
        "application/xml",
        "text/xml",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/zip",
        "application/x-zip-compressed",
        "application/rtf",
        "text/rtf",
    }
    return normalized in allowed
