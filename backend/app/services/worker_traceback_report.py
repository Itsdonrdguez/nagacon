from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[2]
TRACEBACK_REPORT_DIR = BACKEND_ROOT / "audit_reports" / "worker_failures"


def write_worker_traceback_report(
    *,
    job_id: str,
    kind: str,
    payload: dict[str, Any] | None,
    error: str,
    traceback_text: str,
) -> str:
    TRACEBACK_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{timestamp}_{kind}_{job_id}.json"
    report_path = TRACEBACK_REPORT_DIR / filename
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "job_id": job_id,
        "kind": kind,
        "error": error,
        "payload": payload or {},
        "traceback": traceback_text,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return str(report_path)
