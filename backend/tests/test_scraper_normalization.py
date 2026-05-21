import json
from pathlib import Path

import pytest

from app.services.scrapers.dibbs_scraper import _derive_item_signals, _normalize_fsc, _normalize_nsn, fetch_dibbs_opportunities
from app.services.scrapers import dibbs_scraper as dibbs_scraper_module
from app.services.scrapers.sam_scraper import SamScraperError, _build_query_params, _normalize_opp, fetch_sam_opportunities
from app.services.scrapers import sam_scraper as sam_scraper_module
from app.utils.title_normalizer import build_summary_text, normalize_title

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_sam_build_query_params_prefers_ccode_and_date_defaults():
    params = _build_query_params({"ccode": "1560,1680", "limit": 25}, "sam-key")
    assert params["api_key"] == "sam-key"
    assert params["ccode"] == "1560,1680"
    assert params["limit"] == 25
    assert "postedFrom" in params
    assert "postedTo" in params


def test_sam_normalize_opp_extracts_core_fields():
    raw = _normalize_opp(
        {
            "noticeId": "abc-123",
            "solicitationNumber": "W91XYZ",
            "title": "Logistics Support Services",
            "organizationInfo": [{"name": "Army Contracting Command"}],
            "postedDate": "2026-04-01",
            "responseDeadLine": "2026-04-12",
            "classificationCode": "R425",
            "uiLink": "https://sam.gov/opp/abc-123",
            "description": [{"body": "Support services requirement"}],
            "naics": [{"code": ["541614"]}],
        }
    )
    assert raw.source == "SAM"
    assert raw.source_opportunity_id == "abc-123"
    assert raw.naics_code == "541614"
    assert raw.fsc_code == "R425"
    assert raw.agency == "Army Contracting Command"


def test_dibbs_helpers_normalize_ids_and_signals():
    assert _normalize_nsn("8470016987150") == "8470-01-698-7150"
    assert _normalize_fsc("FSC 1560") == "1560"
    signals = _derive_item_signals("RETAINER PLATE 8470016987150", "https://dibbs?value=8470016987150", "1560")
    assert signals["nsn"] == "8470-01-698-7150"
    assert signals["fsc_code"] == "1560"
    assert "RETAINER" in signals["title_keywords"]


def test_title_normalizer_prefers_dibbs_nomenclature_and_summary():
    title = normalize_title(
        source="DIBBS",
        raw_title="8470016987150",
        source_opportunity_id="8470016987150",
        raw_payload={"dibbs_detail": {"nomenclature": "Retainer Plate"}},
        parsed_json={"approved_sources": [{"cage": "1ABC1"}]},
    )
    summary = build_summary_text(
        "Item: Retainer Plate | FSC: 1560",
        parsed_json={"nsn": "8470016987150", "nomenclature": "Retainer Plate"},
        raw_payload={},
    )
    assert title == "Retainer Plate - 8470-01-698-7150"
    assert "NSN 8470-01-698-7150" in summary


def test_fetch_sam_opportunities_from_fixture_payload(monkeypatch):
    fixture = json.loads((FIXTURES / "sam_search_response.json").read_text(encoding="utf-8"))

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return fixture

    monkeypatch.setattr(sam_scraper_module.settings, "SAM_API_KEY", "fixture-key")
    monkeypatch.setattr(sam_scraper_module.requests, "get", lambda *args, **kwargs: FakeResponse())

    rows = fetch_sam_opportunities({"ccode": "4820", "limit": 10})

    assert len(rows) == 1
    assert rows[0].source == "SAM"
    assert rows[0].fsc_code == "4820"
    assert rows[0].naics_code == "332911"
    assert rows[0].agency == "Army Contracting Command"


def test_fetch_sam_opportunities_retries_transient_500_then_succeeds(monkeypatch):
    fixture = json.loads((FIXTURES / "sam_search_response.json").read_text(encoding="utf-8"))
    attempts = {"count": 0}

    class FakeResponse:
        def __init__(self, status_code=200, text=""):
            self.status_code = status_code
            self.text = text

        def raise_for_status(self):
            if self.status_code >= 400:
                from requests import HTTPError

                raise HTTPError(response=self)
            return None

        def json(self):
            return fixture

    def fake_get(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            return FakeResponse(500, '{"code":"101500","message":"Runtime Error"}')
        return FakeResponse(200, "")

    monkeypatch.setattr(sam_scraper_module.settings, "SAM_API_KEY", "fixture-key")
    monkeypatch.setattr(sam_scraper_module.requests, "get", fake_get)
    monkeypatch.setattr(sam_scraper_module.time, "sleep", lambda seconds: None)

    rows = fetch_sam_opportunities({"ncode": "561730", "limit": 10})

    assert attempts["count"] == 3
    assert len(rows) == 1


def test_fetch_sam_opportunities_raises_clean_error_after_repeated_500s(monkeypatch):
    class FakeResponse:
        status_code = 500
        text = '{"code":"101500","message":"Runtime Error","description":"Error in Sender"}'

        def raise_for_status(self):
            from requests import HTTPError

            raise HTTPError(response=self)

    monkeypatch.setattr(sam_scraper_module.settings, "SAM_API_KEY", "fixture-key")
    monkeypatch.setattr(sam_scraper_module.requests, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(sam_scraper_module.time, "sleep", lambda seconds: None)

    with pytest.raises(SamScraperError) as exc_info:
        fetch_sam_opportunities({"ncode": "561730", "limit": 10})

    assert "failed after retries with transient HTTP 500" in str(exc_info.value)


def test_fetch_dibbs_opportunities_from_fixture_payload(monkeypatch):
    fixture = json.loads((FIXTURES / "dibbs_pull_items.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(dibbs_scraper_module, "pull_dibbs_by_fsc", lambda **kwargs: (fixture["items"], {"used_codes": ["1560"]}))

    rows = fetch_dibbs_opportunities({"fsc": "1560", "limit": 10})

    assert len(rows) == 1
    assert rows[0].source == "DIBBS"
    assert rows[0].source_opportunity_id == "8470-01-698-7150"
    assert rows[0].fsc_code == "1560"
    assert rows[0].raw_payload["dibbs_detail"]["nomenclature"] == "RETAINER,PLATE"
