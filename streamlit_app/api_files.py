from __future__ import annotations

import os
import requests

API_BASE = os.getenv("NAGACON_API_BASE", "http://127.0.0.1:8000")


def files_list(opportunity_id: int) -> list[dict]:
    r = requests.get(f"{API_BASE}/api/files/list", params={"opportunity_id": opportunity_id}, timeout=60)
    r.raise_for_status()
    return r.json()


def files_download_pdfs(
    opportunity_id: int,
    always_snapshot: bool = True,
    prefer_dibbs_solicitation_detail: bool = True,
) -> dict:
    r = requests.post(
        f"{API_BASE}/api/files/download_pdfs",
        params={
            "opportunity_id": opportunity_id,
            "always_snapshot": str(always_snapshot).lower(),
            "prefer_dibbs_solicitation_detail": str(prefer_dibbs_solicitation_detail).lower(),
        },
        timeout=1200,
    )
    r.raise_for_status()
    return r.json()


def files_download(file_id: int) -> bytes:
    r = requests.get(f"{API_BASE}/api/files/download/{file_id}", timeout=120)
    r.raise_for_status()
    return r.content


def files_download_url(file_id: int) -> str:
    return f"{API_BASE}/api/files/download/{file_id}"
