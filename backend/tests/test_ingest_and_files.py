from pathlib import Path
from types import SimpleNamespace

from app.api import files as files_api
from app.services import opportunity_ingest
from app.services import opportunity_intake_pipeline
from app.schemas.opportunity import RawOpportunity


TEST_TEMP_DIR = Path(__file__).resolve().parent / "_tmp"


def _make_local_temp_file(filename: str, content: bytes | str) -> Path:
    TEST_TEMP_DIR.mkdir(exist_ok=True)
    file_path = TEST_TEMP_DIR / filename
    if isinstance(content, bytes):
        file_path.write_bytes(content)
    else:
        file_path.write_text(content, encoding="utf-8")
    return file_path


def test_find_existing_scopes_to_source():
    same_source = SimpleNamespace(id=1, source="DIBBS", solicitation_number="SOL-1", url="https://example.test/a")
    other_source = SimpleNamespace(id=2, source="SAM", solicitation_number="SOL-1", url="https://example.test/a")

    class FakeQuery:
        def __init__(self, rows):
            self.rows = list(rows)

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return next((row for row in self.rows if row.source == "DIBBS"), None)

    class FakeDB:
        def query(self, model):
            return FakeQuery([other_source, same_source])

    raw = RawOpportunity(
        source="DIBBS",
        solicitation_number="SOL-1",
        title="Bearing",
        agency="DLA",
        url="https://example.test/a",
    )

    existing = opportunity_ingest._find_existing(FakeDB(), raw)

    assert existing is same_source


def test_prepare_value_trims_long_strings():
    trimmed = opportunity_ingest._prepare_value("solicitation_number", "X" * 200)
    assert len(trimmed) == 120


def test_download_file_uses_guessed_mime_type(client, monkeypatch):
    file_path = _make_local_temp_file("sample.pdf", b"%PDF-1.4 test")

    file_record = SimpleNamespace(
        id=9,
        filename="sample.pdf",
        file_path=str(file_path),
    )

    class FakeQuery:
        def __init__(self, result):
            self.result = result

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return self.result

    class FakeDB:
        def query(self, model):
            return FakeQuery(file_record)

    def override_get_db():
        yield FakeDB()

    client.app.dependency_overrides[files_api.get_db] = override_get_db
    response = client.get("/api/files/download/9")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")


def test_parse_file_returns_parsed_payload(client):
    file_path = _make_local_temp_file("sample.txt", "line one")

    file_record = SimpleNamespace(
        id=11,
        filename="sample.txt",
        file_path=str(file_path),
        parsed_metadata=None,
        extracted_text=None,
    )

    class FakeQuery:
        def __init__(self, result):
            self.result = result

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return self.result

    class FakeDB:
        def query(self, model):
            return FakeQuery(file_record)

        def add(self, item):
            return None

        def commit(self):
            return None

        def refresh(self, item):
            return None

        def rollback(self):
            return None

    def override_get_db():
        yield FakeDB()

    client.app.dependency_overrides[files_api.get_db] = override_get_db
    original_parser = files_api.parse_opportunity_file
    files_api.parse_opportunity_file = lambda path: {"text": "parsed body", "kind": "text"}
    try:
        response = client.post("/api/files/parse/11")
    finally:
        files_api.parse_opportunity_file = original_parser

    assert response.status_code == 200
    payload = response.json()
    assert payload["parsed"]["text"] == "parsed body"
    assert payload["filename"] == "sample.txt"


def test_parse_opportunity_file_rejects_oversized_document(monkeypatch):
    from app.services import document_parser

    file_path = _make_local_temp_file("oversized.txt", "A" * 32)
    monkeypatch.setattr(
        document_parser,
        "validate_file_size_bytes",
        lambda size: (False, "file exceeds maximum size of 8 bytes"),
    )

    parsed = document_parser.parse_opportunity_file(str(file_path))

    assert parsed["parser"] == "none"
    assert "maximum size" in parsed["error"]


def test_save_downloaded_file_records_security_metadata(monkeypatch):
    from app.services import pdf_service

    created = []

    class FakeDB:
        def add(self, item):
            created.append(item)

        def commit(self):
            return None

    monkeypatch.setattr(pdf_service, "_matching_file_records", lambda *args, **kwargs: [])
    monkeypatch.setattr(pdf_service, "store_bytes", lambda path, data, content_type=None: "C:/tmp/spec.pdf")
    monkeypatch.setattr(pdf_service, "validate_file_size_bytes", lambda size: (True, None))

    opp = SimpleNamespace(id=3, organization_id=1)
    count, filename = pdf_service._save_downloaded_file(
        FakeDB(),
        opp,
        TEST_TEMP_DIR,
        "spec.pdf",
        "https://example.test/spec.pdf",
        b"%PDF-1.4 test",
        "DIBBS_ATTACHMENT",
    )

    assert count == 1
    assert filename == "spec.pdf"
    assert created[0].parsed_metadata["_security"]["status"] == "not_scanned"


def test_allowed_download_content_type_rejects_html_without_file_extension():
    from app.services.document_security import is_allowed_download_content_type

    assert is_allowed_download_content_type("text/html", "notice") is False
    assert is_allowed_download_content_type("application/pdf", "notice") is True


def test_list_files_includes_parse_status_flags(client):
    file_record = SimpleNamespace(
        id=21,
        opportunity_id=7,
        file_type="PDF",
        filename="spec.pdf",
        source_url="https://example.test/spec.pdf",
        file_path="C:/tmp/spec.pdf",
        created_at="2026-04-06T12:00:00",
        extracted_text="parsed text",
        parsed_metadata={"kind": "pdf"},
    )
    opportunity = SimpleNamespace(id=7)

    class FakeQuery:
        def __init__(self, result):
            self.result = result

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def first(self):
            return self.result if not isinstance(self.result, list) else None

        def all(self):
            return self.result if isinstance(self.result, list) else [self.result]

    class FakeDB:
        def query(self, model):
            if model.__name__ == "Opportunity":
                return FakeQuery(opportunity)
            return FakeQuery([file_record])

    def override_get_db():
        yield FakeDB()

    client.app.dependency_overrides[files_api.get_db] = override_get_db
    response = client.get("/api/files/list", params={"opportunity_id": 7})

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["has_extracted_text"] is True
    assert payload[0]["has_parsed_metadata"] is True


def test_opportunity_intake_rollback_skips_non_active_transaction():
    calls = []

    class FakeTransaction:
        is_active = False

    class FakeDB:
        def get_transaction(self):
            return FakeTransaction()

        def rollback(self):
            calls.append("rollback")

    opportunity_intake_pipeline._rollback_if_active(FakeDB())

    assert calls == []


def test_get_file_insights_returns_preview_and_metadata(client):
    file_record = SimpleNamespace(
        id=31,
        opportunity_id=9,
        file_type="PDF",
        filename="award.pdf",
        source_url="https://example.test/award.pdf",
        created_at="2026-04-06T12:00:00",
        extracted_text="A" * 2000,
        parsed_metadata={"nsn": "8470-01-692-9779"},
    )

    class FakeQuery:
        def __init__(self, result):
            self.result = result

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return self.result

    class FakeDB:
        def query(self, model):
            return FakeQuery(file_record)

    def override_get_db():
        yield FakeDB()

    client.app.dependency_overrides[files_api.get_db] = override_get_db
    response = client.get("/api/files/31/insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["has_extracted_text"] is True
    assert payload["has_parsed_metadata"] is True
    assert payload["parsed_metadata"]["nsn"] == "8470-01-692-9779"
    assert len(payload["text_preview"]) == 1600
