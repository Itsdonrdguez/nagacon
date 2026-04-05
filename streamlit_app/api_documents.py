from __future__ import annotations

from api_client import post


def parse_file(file_id: int) -> dict:
    return post(f'/api/files/parse/{file_id}', {})
