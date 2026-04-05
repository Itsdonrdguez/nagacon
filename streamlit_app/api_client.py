from __future__ import annotations

import requests

BASE_URL = "http://127.0.0.1:8000"


def get_json(path: str, params: dict | None = None):
    r = requests.get(f"{BASE_URL}{path}", params=params)
    r.raise_for_status()
    return r.json()


def get_bytes(path: str, params: dict | None = None) -> bytes:
    r = requests.get(f"{BASE_URL}{path}", params=params)
    r.raise_for_status()
    return r.content


def post(path: str, payload: dict | None = None):
    r = requests.post(f"{BASE_URL}{path}", json=payload or {})
    r.raise_for_status()
    return r.json()


def patch_json(path: str, payload: dict | None = None):
    r = requests.patch(f"{BASE_URL}{path}", json=payload or {})
    r.raise_for_status()
    return r.json()


def delete_json(path: str):
    r = requests.delete(f"{BASE_URL}{path}")
    r.raise_for_status()
    return r.json() if r.content else {"ok": True}
