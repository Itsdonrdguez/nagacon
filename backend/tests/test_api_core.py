from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from app.api import opportunities as opportunities_api
from app.api import data_health as data_health_api
from app.api import integrations as integrations_api
from app.api import notifications as notifications_api
from app.api import saas_readiness as saas_readiness_api
from app.api import source_freshness as source_freshness_api
from app.api import workspace as workspace_api
from app.api import work_queue as work_queue_api
from app.api import files as files_api
from app.api.routes import company as company_api
from app.api.routes import nsn as nsn_api
from app.api.routes import pipeline as pipeline_api
from app.api.routes import providers as providers_api
from app.api.routes import auth as auth_api
from app.repositories import providers as providers_repository
from app.core import security as security_core
from app.schemas.company import CompanyProfileCreate
from app.utils.enums import PipelineStatus
from app.services.research.usaspending_research_service import _rank_vendors


def test_opportunities_search_returns_paginated_payload(client, monkeypatch):
    class FakeOpportunityRepository:
        def __init__(self, db):
            self.db = db

        def search(self, **kwargs):
            assert kwargs["q"] == "radar"
            item = SimpleNamespace(
                id=7,
                source="SAM",
                source_opportunity_id="SAM-7",
                solicitation_number="SOL-7",
                title="Radar Sustainment",
                agency="USAF",
                sub_agency=None,
                office=None,
                url="https://example.test/opps/7",
                posted_at=None,
                due_at=None,
                naics="541330",
                fsc="1560",
                set_aside="Small Business",
                place_of_performance=None,
                raw_text=None,
                parsed_json=None,
                raw_payload=None,
                status="new",
                workspace_url="/workspace/7",
                workspace_api_url="/api/workspace/summary?opp_id=7",
                raw_title="Radar Sustainment",
                display_title="Radar Sustainment",
                source_uniform_title="Radar Sustainment",
                summary_text="Summary",
            )
            return [item], 1

    monkeypatch.setattr(opportunities_api, "OpportunityRepository", FakeOpportunityRepository)

    response = client.get("/api/opportunities/search", params={"q": "radar", "page": 1, "page_size": 25})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == 7
    assert payload["items"][0]["workspace_url"] == "/workspace/7"
    assert payload["items"][0]["solicitation_status"] == "OPEN"


def test_company_profile_create_uses_repository(client, monkeypatch):
    expected = {
        "id": 3,
        "legal_name": "Acme Federal",
        "uei": "ABC123XYZ789",
        "cage": "1A2B3",
        "website": "https://acme.test",
        "primary_contact_name": None,
        "primary_contact_email": None,
        "primary_contact_phone": None,
        "address_line1": None,
        "address_line2": None,
        "city": None,
        "state": None,
        "postal_code": None,
        "country": None,
        "naics_codes": ["541330"],
        "certifications": ["SDVOSB"],
        "capability_statement_url": None,
        "core_competencies": None,
        "differentiators": None,
        "past_performance_summary": None,
        "annual_revenue": None,
        "created_at": "2026-04-06T12:00:00",
        "updated_at": "2026-04-06T12:00:00",
    }

    class FakeCompanyRepository:
        def __init__(self, db):
            self.db = db

        def create_profile(self, item):
            assert isinstance(item, CompanyProfileCreate)
            return expected

    monkeypatch.setattr(company_api, "CompanyRepository", FakeCompanyRepository)

    response = client.post(
        "/api/company/profile",
        json={
            "legal_name": "Acme Federal",
            "uei": "ABC123XYZ789",
            "cage": "1A2B3",
            "website": "https://acme.test",
            "naics_codes": ["541330"],
            "certifications": ["SDVOSB"],
        },
    )

    assert response.status_code == 200
    assert response.json()["legal_name"] == "Acme Federal"


def test_pipeline_board_returns_summary(client, monkeypatch):
    class FakePipelineRepository:
        def __init__(self, db):
            self.db = db

        def list_board(self, **kwargs):
            assert kwargs["source"] == "DIBBS"
            assert kwargs["include_closed"] is False
            return [
                {
                    "id": 1,
                    "opportunity_id": 22,
                    "decision_status": "NEW",
                    "owner": "Chris",
                    "priority": "HIGH",
                    "probability_of_win": 50,
                    "target_submit_date": None,
                    "updated_at": "2026-04-06T12:00:00",
                    "opportunity": {
                        "id": 22,
                        "title": "Bearing Assembly",
                        "display_title": "Bearing Assembly",
                        "agency": "DLA",
                        "source": "DIBBS",
                        "solicitation_number": "SPE4A6",
                        "due_at": None,
                        "set_aside_type": None,
                        "solicitation_status": "OPEN",
                    },
                }
            ]

    monkeypatch.setattr(pipeline_api, "PipelineRepository", FakePipelineRepository)

    response = client.get("/api/pipeline/board", params={"source": "DIBBS"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["summary"]["NEW"] == 1


def test_workspace_summary_returns_frontend_friendly_payload(client, monkeypatch, dummy_db):
    opportunity = SimpleNamespace(
        id=15,
        source="DIBBS",
        title="Valve Body",
        solicitation_number="SPRMM1",
        agency="DLA",
        url="https://example.test/opps/15",
        posted_at=None,
        due_at=None,
        naics=None,
        fsc="4820",
        set_aside="Small Business",
        raw_text="Need valve body",
        parsed_json=None,
        raw_payload=None,
        workspace_url="/workspace/15",
        raw_title="Valve Body",
        display_title="Valve Body",
        source_uniform_title="Valve Body",
        summary_text="Need valve body",
        description=None,
    )
    analysis = SimpleNamespace(priority_score=88, risk_flags=["lead_time"], fit_score=73, ai_summary="Good fit")
    pipeline_item = SimpleNamespace(
        id=4,
        opportunity_id=15,
        decision_status=PipelineStatus.IN_PROGRESS,
        owner="Alex",
        priority="HIGH",
        probability_of_win=65.0,
        notes="Follow up with sources",
        target_submit_date=datetime(2026, 4, 20, 9, 30),
    )

    class FakeQuery:
        def __init__(self, result):
            self.result = result

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return self.result

        def first(self):
            return self.result

    class FakeDB:
        def query(self, model):
            if model is workspace_api.OpportunityAnalysis:
                return FakeQuery(analysis)
            if model is workspace_api.VendorLead:
                return FakeQuery([])
            if model is workspace_api.OpportunityFile:
                return FakeQuery([])
            if model is workspace_api.WorkspaceArtifact:
                return FakeQuery([])
            if model is workspace_api.WorkspaceTask:
                return FakeQuery([])
            if model is workspace_api.BidSubmission:
                return FakeQuery(None)
            raise AssertionError(f"Unexpected model queried: {model}")

    class FakeVendorMatchRepository:
        def __init__(self, db):
            self.db = db

        def list_by_opportunity_id(self, opp_id):
            assert opp_id == 15
            return []

    class FakePipelineRepository:
        def __init__(self, db):
            self.db = db

        def get_by_opportunity_id(self, opp_id):
            assert opp_id == 15
            return pipeline_item

    class FakeAgentRunRepository:
        def __init__(self, db):
            self.db = db

        def list_by_opportunity_id(self, opportunity_id):
            assert opportunity_id == 15
            return []

    monkeypatch.setattr(workspace_api, "_get_opp_or_404", lambda db, opp_id: opportunity)
    monkeypatch.setattr(workspace_api, "VendorMatchRepository", FakeVendorMatchRepository)
    monkeypatch.setattr(workspace_api, "PipelineRepository", FakePipelineRepository)
    monkeypatch.setattr(workspace_api, "AgentRunRepository", FakeAgentRunRepository)

    def override_get_db():
        yield FakeDB()

    client.app.dependency_overrides[workspace_api.get_db] = override_get_db

    response = client.get("/api/workspace/summary", params={"opp_id": 15})

    assert response.status_code == 200
    payload = response.json()
    assert payload["opportunity"]["set_aside_type"] == "Small Business"
    assert payload["opportunity"]["solicitation_status"] == "OPEN"
    assert payload["research_profile"]["fsc_code"] == "4820"
    assert payload["pipeline_item"]["decision_status"] == "IN_PROGRESS"
    assert payload["analysis"]["priority_score"] == 88


def test_workspace_usaspending_route_returns_research_payload(client, monkeypatch):
    opportunity = SimpleNamespace(id=21, source="SAM", title="Valve Assembly")

    monkeypatch.setattr(workspace_api, "_get_opp_or_404", lambda db, opp_id: opportunity)
    monkeypatch.setattr(
        workspace_api,
        "search_usaspending_for_opportunity",
        lambda opp, db=None: {
            "opportunity_id": opp.id,
            "likely_vendors": [{"vendor": "Acme Federal", "score": 9.0, "award_count": 3}],
        },
    )

    response = client.get("/api/workspace/vendors/usaspending", params={"opp_id": 21})

    assert response.status_code == 200
    payload = response.json()
    assert payload["opportunity_id"] == 21
    assert payload["likely_vendors"][0]["vendor"] == "Acme Federal"


def test_generate_research_brief_route_returns_artifact(client, monkeypatch):
    opportunity = SimpleNamespace(id=33, title="Valve Body", display_title="Valve Body")
    artifact = SimpleNamespace(
        id=91,
        artifact_type="RESEARCH_BRIEF",
        title="Research Brief - SOL-33",
        created_at=datetime(2026, 4, 6, 12, 0),
        content_json={"summary": {"title": "Valve Body"}},
    )

    monkeypatch.setattr(workspace_api, "_get_opp_or_404", lambda db, opp_id: opportunity)
    monkeypatch.setattr(workspace_api, "generate_research_brief", lambda db, opp: artifact)

    response = client.post("/api/workspace/generate/research-brief", json={"opportunity_id": 33})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "research_brief_generated"
    assert payload["artifact"]["artifact_type"] == "RESEARCH_BRIEF"


def test_workspace_agent_phase_route_returns_results(client, monkeypatch):
    opportunity = SimpleNamespace(id=44, title="Panel Assembly", display_title="Panel Assembly")

    monkeypatch.setattr(workspace_api, "_get_opp_or_404", lambda db, opp_id: opportunity)
    monkeypatch.setattr(workspace_api, "PHASE_AGENT_MAP", {"phase_1": ["opportunity_analyst"]})
    monkeypatch.setattr(
        workspace_api,
        "run_workspace_agent",
        lambda agent_key, opp, db: {
            "output": {"agent_key": agent_key, "summary": "ok"},
            "artifact": {"id": 1, "artifact_type": "OPPORTUNITY_ANALYSIS"},
        },
    )

    created_runs = []

    class FakeAgentRunRepository:
        def __init__(self, db):
            self.db = db

        def create(self, item):
            created_runs.append(item)
            return SimpleNamespace(id=77)

        def update(self, run_id, item):
            payload = item.model_dump(exclude_unset=True)
            return SimpleNamespace(id=run_id, status=payload.get("status"), output_payload=payload.get("output_payload"), error_message=payload.get("error_message"))

    monkeypatch.setattr(workspace_api, "AgentRunRepository", FakeAgentRunRepository)

    response = client.post("/api/workspace/agents/run-phase", json={"opportunity_id": 44, "phase": "phase_1"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["phase"] == "phase_1"
    assert payload["results"][0]["agent_key"] == "opportunity_analyst"
    assert payload["results"][0]["persisted_run"] is True


def test_workspace_agent_route_returns_output_without_persistence_table(client, monkeypatch):
    opportunity = SimpleNamespace(id=45, title="Relay", display_title="Relay")

    monkeypatch.setattr(workspace_api, "_get_opp_or_404", lambda db, opp_id: opportunity)
    monkeypatch.setattr(
        workspace_api,
        "run_workspace_agent",
        lambda agent_key, opp, db: {
            "output": {"agent_key": agent_key, "summary": "fallback ok"},
            "artifact": {"id": 2, "artifact_type": "COMPLIANCE_BRIEF"},
            "model_name": "deterministic_fallback",
        },
    )

    class FakeAgentRunRepository:
        def __init__(self, db):
            self.db = db

        def create(self, item):
            raise RuntimeError("relation \"agent_runs\" does not exist")

    monkeypatch.setattr(workspace_api, "AgentRunRepository", FakeAgentRunRepository)

    response = client.post("/api/workspace/agents/run", json={"opportunity_id": 45, "agent_key": "compliance_document"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["persisted_run"] is False
    assert payload["model_name"] == "deterministic_fallback"


def test_rank_vendors_handles_agency_sets_when_building_why_matched():
    awards = [
        {
            "recipient_name": "Acme Federal",
            "award_amount": 1000,
            "start_date": "2025-01-01",
            "awarding_agency": "DEFENSE LOGISTICS AGENCY",
            "award_id": "A1",
            "description": "NSN supply item",
            "relevance_score": 4.5,
            "seedable_product_evidence": True,
            "strict_seedable_product_evidence": True,
            "relevance_reasons": ["nsn_match"],
        }
    ]
    ctx = {
        "agency_variants": ["DLA", "DEFENSE LOGISTICS AGENCY"],
        "fsc_code": "8470",
        "approved_source_names": [],
        "manufacturers": [],
    }

    ranked = _rank_vendors(awards, ctx, strict=True)

    assert ranked[0]["vendor"] == "Acme Federal"
    assert ranked[0]["agencies"] == ["DEFENSE LOGISTICS AGENCY"]
    assert isinstance(ranked[0]["why_matched"], list)


def test_integration_routes_require_api_key(client, monkeypatch):
    monkeypatch.setattr(security_core.settings, "EXTERNAL_API_KEYS", "secret-key")

    response = client.get("/api/integrations/health")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing X-API-Key header"


def test_integration_search_allows_authorized_client(client, monkeypatch):
    monkeypatch.setattr(security_core.settings, "EXTERNAL_API_KEYS", "secret-key")

    class FakeOpportunityRepository:
        def __init__(self, db):
            self.db = db

        def search(self, **kwargs):
            assert kwargs["q"] == "helmet"
            item = SimpleNamespace(
                id=12,
                source="DIBBS",
                source_opportunity_id="D-12",
                solicitation_number="SPE1C1",
                title="Ballistic Helmet",
                agency="DLA",
                sub_agency=None,
                office=None,
                url="https://example.test/opps/12",
                posted_at=None,
                due_at=None,
                naics="339113",
                fsc="8470",
                set_aside="Small Business",
                place_of_performance=None,
                raw_text=None,
                parsed_json=None,
                raw_payload=None,
                status="new",
                workspace_url="/workspace/12",
                workspace_api_url="/api/workspace/summary?opp_id=12",
                raw_title="Ballistic Helmet",
                display_title="Ballistic Helmet",
                source_uniform_title="Ballistic Helmet",
                summary_text="Summary",
            )
            return [item], 1

    monkeypatch.setattr(integrations_api, "OpportunityRepository", FakeOpportunityRepository)

    response = client.get(
        "/api/integrations/opportunities/search",
        params={"q": "helmet"},
        headers={"X-API-Key": "secret-key"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == 12


def test_settings_route_updates_external_api_keys(client, monkeypatch):
    stored = {"value": ""}
    default_org = SimpleNamespace(id=9, name="Default Organization", slug="default")

    monkeypatch.setattr(
        "app.api.routes.settings.get_setting",
        lambda db, setting_key, default=None, organization_id=None: stored["value"] if setting_key == "external_api_keys" and organization_id == 9 else default,
    )
    monkeypatch.setattr("app.api.routes.settings.ensure_default_organization", lambda db: default_org)

    def fake_upsert(db, setting_key, setting_value, organization_id=None):
        stored["value"] = setting_value
        assert organization_id == 9
        return SimpleNamespace(id=5)

    monkeypatch.setattr("app.api.routes.settings.upsert_setting", fake_upsert)

    response = client.put("/api/settings/integrations", json={"external_api_keys_csv": "alpha, beta"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "saved"
    assert payload["external_api_keys"] == ["********", "********"]
    assert payload["external_api_keys_csv"] == ""
    assert payload["external_api_key_count"] == 2
    assert payload["organization"]["slug"] == "default"


def test_settings_route_preserves_existing_external_api_keys_on_blank_save(client, monkeypatch):
    stored = {"value": "alpha, beta"}
    default_org = SimpleNamespace(id=9, name="Default Organization", slug="default")

    monkeypatch.setattr(
        "app.api.routes.settings.get_setting",
        lambda db, setting_key, default=None, organization_id=None: stored["value"] if setting_key == "external_api_keys" and organization_id == 9 else default,
    )
    monkeypatch.setattr("app.api.routes.settings.ensure_default_organization", lambda db: default_org)

    def fake_upsert(db, setting_key, setting_value, organization_id=None):
        stored["value"] = setting_value
        return SimpleNamespace(id=5)

    monkeypatch.setattr("app.api.routes.settings.upsert_setting", fake_upsert)

    response = client.put("/api/settings/integrations", json={"external_api_keys_csv": ""})

    assert response.status_code == 200
    payload = response.json()
    assert stored["value"] == "alpha, beta"
    assert payload["external_api_keys"] == ["********", "********"]
    assert payload["external_api_key_count"] == 2


def test_provider_settings_blank_secret_fields_are_not_saved(client, monkeypatch):
    saved_keys = []
    default_org = SimpleNamespace(id=9, name="Default Organization", slug="default")

    monkeypatch.setattr("app.api.routes.settings.ensure_default_organization", lambda db: default_org)

    def fake_upsert(db, setting_key, setting_value, organization_id=None, user_id=None):
        saved_keys.append((setting_key, setting_value))
        return SimpleNamespace(id=5)

    monkeypatch.setattr("app.api.routes.settings.upsert_setting", fake_upsert)
    monkeypatch.setattr(
        "app.api.routes.settings.get_provider_settings",
        lambda db, user_id=None: {
            "organization": {"id": 9, "name": "Default Organization", "slug": "default"},
            "scope": "user",
            "user_id": user_id,
            "sam_api_key": "",
            "openai_api_key": "",
            "openai_model": "gpt-4o-mini",
            "smtp_host": "",
            "smtp_port": "",
            "smtp_from_email": "",
            "sam_configured": True,
            "openai_configured": True,
            "sam_api_key_display": "********",
            "openai_api_key_display": "********",
            "smtp_configured": False,
        },
    )

    response = client.put(
        "/api/settings/providers",
        json={"sam_api_key": "", "openai_api_key": "", "openai_model": "gpt-4o-mini"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "saved"
    assert "sam_api_key" not in [key for key, _ in saved_keys]
    assert "openai_api_key" not in [key for key, _ in saved_keys]


def test_current_organization_route_returns_default_org(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.organizations.ensure_default_organization",
        lambda db: SimpleNamespace(id=1, name="Default Organization", slug="default", is_default=True),
    )

    response = client.get("/api/organizations/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["slug"] == "default"


def test_auth_me_returns_session_user_and_org(client, monkeypatch):
    monkeypatch.setattr(
        auth_api,
        "get_user_by_session_token",
        lambda db, token: SimpleNamespace(
            id=1,
            email="owner@nagacon.local",
            full_name="Default Owner",
            role="OWNER",
            is_active=True,
            organization_id=1,
        ) if token == "session-1" else None,
    )

    client.cookies.set("nagacon_session", "session-1")
    response = client.get("/api/auth/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated"] is True
    assert payload["user"]["email"] == "owner@nagacon.local"
    assert payload["organization"]["slug"] == "default"


def test_auth_me_returns_unauthenticated_without_session(client, monkeypatch):
    monkeypatch.setattr(auth_api, "get_user_by_session_token", lambda db, token: None)

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated"] is False
    assert payload["user"] is None


def test_auth_signup_sets_session_cookie(client, monkeypatch):
    fake_user = SimpleNamespace(id=8, email="new@nagacon.test", full_name="New User", role="OWNER", is_active=True)
    monkeypatch.setattr(auth_api, "create_user_account", lambda db, email, password, full_name=None: fake_user)
    monkeypatch.setattr(auth_api, "start_user_session", lambda db, user: ("token-123", None))

    response = client.post("/api/auth/signup", json={"email": "new@nagacon.test", "password": "password123", "full_name": "New User"})

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert "nagacon_session=" in response.headers.get("set-cookie", "")


def test_auth_login_rejects_invalid_credentials(client, monkeypatch):
    monkeypatch.setattr(auth_api, "authenticate_user", lambda db, identifier, password: None)

    response = client.post("/api/auth/login", json={"email": "missing@nagacon.test", "password": "badpass"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username/email or password"


def test_auth_login_accepts_identifier_field(client, monkeypatch):
    fake_user = SimpleNamespace(id=1, email="admin@nagacon.local", full_name="Admin", role="OWNER", is_active=True)
    seen = {}

    def fake_authenticate_user(db, identifier, password):
        seen["identifier"] = identifier
        seen["password"] = password
        return fake_user

    monkeypatch.setattr(auth_api, "authenticate_user", fake_authenticate_user)
    monkeypatch.setattr(auth_api, "start_user_session", lambda db, user: ("token-123", None))

    response = client.post("/api/auth/login", json={"identifier": "admin", "password": "admin"})

    assert response.status_code == 200
    assert seen == {"identifier": "admin", "password": "admin"}
    assert response.json()["user"]["email"] == "admin@nagacon.local"


def test_auth_logout_clears_cookie(client, monkeypatch):
    fake_user = SimpleNamespace(id=1)
    cleared = []
    monkeypatch.setattr(auth_api, "get_user_by_session_token", lambda db, token: fake_user if token == "token-123" else None)
    monkeypatch.setattr(auth_api, "clear_user_session", lambda db, user: cleared.append(user.id))
    client.cookies.set("nagacon_session", "token-123")

    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    assert cleared == [1]
    assert "nagacon_session=" in response.headers.get("set-cookie", "")


def test_work_queue_today_returns_daily_actions(client, monkeypatch):
    def fake_build_daily_work_queue(db, organization_id=None, limit=200):
        assert organization_id == 1
        assert limit == 50
        return {
            "items": [
                {
                    "id": "QUOTE_FOLLOW_UP_DUE:7:100",
                    "type": "QUOTE_FOLLOW_UP_DUE",
                    "priority": "HIGH",
                    "title": "Follow up with Acme",
                    "subtitle": "Quote request is due for follow-up.",
                    "opportunity": {
                        "id": 7,
                        "title": "Valve",
                        "solicitation_number": "SOL-7",
                        "source": "DIBBS",
                        "agency": "DLA",
                        "due_at": None,
                        "workspace_url": "/workspace/7",
                    },
                    "due_at": None,
                    "action_label": "Open Workspace",
                    "action_url": "/workspace/7",
                    "meta": {"quote_id": 100},
                }
            ],
            "summary": {"HIGH": 1, "QUOTE_FOLLOW_UP_DUE": 1},
            "total": 1,
            "generated_at": "2026-04-20T12:00:00",
        }

    monkeypatch.setattr(work_queue_api, "build_daily_work_queue", fake_build_daily_work_queue)

    response = client.get("/api/work-queue/today", params={"limit": 50})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["type"] == "QUOTE_FOLLOW_UP_DUE"


def test_work_queue_queue_today_returns_background_summary(client, monkeypatch):
    def fake_queue_daily_work(db, organization_id=None, limit=200):
        assert organization_id == 1
        assert limit == 75
        return {
            "status": "ok",
            "organization_id": 1,
            "generated_at": "2026-04-21T12:00:00",
            "scanned_items": 10,
            "queueable_items": 3,
            "queued_count": 2,
            "skipped_duplicate_count": 1,
            "queued_jobs": [
                {"item_id": "a", "kind": "awardee_enrichment", "target": 7, "job_id": "job-a", "status": "queued"},
                {"item_id": "b", "kind": "nsn_build", "target": "4110015342682", "job_id": "job-b", "status": "queued"},
            ],
            "skipped_duplicates": [
                {"item_id": "c", "kind": "nsn_build", "target": "3110012739414"},
            ],
        }

    monkeypatch.setattr(work_queue_api, "queue_daily_work", fake_queue_daily_work)

    response = client.post("/api/work-queue/queue-today", params={"limit": 75})

    assert response.status_code == 200
    payload = response.json()
    assert payload["queued_count"] == 2
    assert payload["skipped_duplicate_count"] == 1
    assert payload["queued_jobs"][0]["kind"] == "awardee_enrichment"


def test_work_queue_queue_history_returns_recent_runs(client, monkeypatch):
    def fake_list_daily_queue_runs(db, organization_id=None, limit=10):
        assert organization_id == 1
        assert limit == 5
        return {
            "items": [
                {
                    "id": "batch-1",
                    "status": "success",
                    "created_at": "2026-04-21T12:00:00",
                    "completed_at": "2026-04-21T12:00:03",
                    "queued_count": 4,
                    "skipped_duplicate_count": 2,
                    "queueable_items": 6,
                    "scanned_items": 15,
                    "queued_jobs": [{"job_id": "job-1"}],
                }
            ],
            "total": 1,
            "organization_id": 1,
        }

    monkeypatch.setattr(work_queue_api, "list_daily_queue_runs", fake_list_daily_queue_runs)

    response = client.get("/api/work-queue/queue-history", params={"limit": 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["queued_count"] == 4


def test_notifications_route_returns_work_queue_alerts(client, monkeypatch):
    monkeypatch.setattr(
        notifications_api,
        "build_notifications",
        lambda db, organization_id=None, limit=20: {
            "items": [{"id": "n1", "title": "Follow up", "priority": "HIGH"}],
            "unread_count": 1,
            "generated_at": "2026-04-20T12:00:00",
        },
    )

    response = client.get("/api/notifications")

    assert response.status_code == 200
    assert response.json()["unread_count"] == 1


def test_source_freshness_route_returns_source_status(client, monkeypatch):
    monkeypatch.setattr(
        source_freshness_api,
        "build_source_freshness",
        lambda db, organization_id=None: {
            "sources": [{"key": "publog", "status": "fresh"}],
            "summary": {"fresh": 1},
            "generated_at": "2026-04-20T12:00:00",
        },
    )

    response = client.get("/api/source-freshness")

    assert response.status_code == 200
    assert response.json()["summary"]["fresh"] == 1


def test_data_health_route_returns_readiness_summary(client, monkeypatch):
    monkeypatch.setattr(
        data_health_api,
        "build_data_health",
        lambda db, organization_id=None: {
            "organization_id": organization_id,
            "summary": {"ready": 2, "thin": 1, "missing": 0},
            "counts": {"opportunities": 10, "nsn_master": 100},
            "coverage": {"references_per_nsn": 3.2},
            "categories": [{"key": "nsn_catalog", "status": "ready"}],
            "readiness_checks": [{"key": "publog_imported", "status": "ready"}],
            "generated_at": "2026-04-20T12:00:00",
        },
    )

    response = client.get("/api/data-health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["organization_id"] == 1
    assert payload["summary"]["ready"] == 2
    assert payload["counts"]["nsn_master"] == 100


def test_publog_status_route_returns_package_status(client, monkeypatch):
    monkeypatch.setattr(
        nsn_api,
        "get_publog_package_status",
        lambda db: {
            "status": "ready",
            "zip_path": "backend/PublogDVD.zip",
            "publog_dir": "backend/publog_work",
            "source_version": "2026-04",
            "latest_run": None,
        },
    )

    response = client.get("/api/nsn/publog/status")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_publog_sync_route_starts_controlled_sync(client, monkeypatch):
    def fake_sync_publog_package(db, **kwargs):
        assert kwargs["target_limit"] == 10
        assert kwargs["dry_run"] is True
        assert kwargs["force"] is False
        return {
            "status": "ok",
            "target_count": 1,
            "targets": ["4110-01-534-2682"],
            "imported": 1,
        }

    monkeypatch.setattr(nsn_api, "sync_publog_package", fake_sync_publog_package)

    response = client.post("/api/nsn/publog/sync", json={"target_limit": 10, "dry_run": True})

    assert response.status_code == 200
    assert response.json()["target_count"] == 1


def test_publog_sync_job_route_queues_background_job(client, monkeypatch):
    def fake_start_search_job(kind, payload):
        assert kind == "publog_sync"
        assert payload["organization_id"] == 1
        assert payload["target_limit"] == 5
        return {"id": "job-1", "kind": kind, "status": "queued"}

    monkeypatch.setattr(nsn_api, "start_search_job", fake_start_search_job)

    response = client.post("/api/nsn/publog/sync-job", json={"target_limit": 5})

    assert response.status_code == 200
    assert response.json()["kind"] == "publog_sync"


def test_provider_detail_route_returns_profile(client, monkeypatch):
    class FakeProviderRepo:
        def __init__(self, db, organization_id=None):
            self.db = db
            self.organization_id = organization_id

        def get_detail(self, provider_id):
            assert provider_id == 7
            return {
                "provider": {"id": 7, "company_name": "Acme Defense", "cage": "1ABC2", "status": "active"},
                "items": [{"provider_item_id": 1, "nsn": "4110-01-534-2682"}],
                "award_history": [{"award_id": "AWD-1"}],
                "nsn_award_evidence": [],
                "catalog_references": [],
                "summary": {"item_count": 1},
            }

    monkeypatch.setattr(providers_api, "ProviderRepository", FakeProviderRepo)

    response = client.get("/api/providers/7")

    assert response.status_code == 200
    assert response.json()["provider"]["company_name"] == "Acme Defense"


def test_provider_backfill_job_route_returns_job(client, monkeypatch):
    def fake_start_search_job(kind, payload):
        assert kind == "provider_backfill"
        assert payload["organization_id"] == 1
        assert payload["limit"] == 25
        return {"id": "provider-backfill-1", "kind": kind, "status": "queued", "payload": payload}

    monkeypatch.setattr(providers_api, "start_search_job", fake_start_search_job)

    response = client.post("/api/providers/backfill/job", params={"limit": 25, "enrich_websites": False})

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "provider_backfill"
    assert payload["payload"]["enrich_websites"] is False


def test_provider_award_match_reasons_accept_alias_and_normalized_name():
    reasons = providers_repository._award_match_reasons(
        recipient_name="Acme Defense LLC",
        recipient_cage="1ABC2",
        cage="1ABC2",
        exact_name_variants=["Acme Defense", "Acme Defense LLC"],
        normalized_name_keys={"acme defense"},
    )

    assert "cage" in reasons
    assert "exact_name" in reasons
    assert "normalized_name" in reasons


def test_saas_readiness_route_returns_org_scope_audit(client, monkeypatch):
    monkeypatch.setattr(
        saas_readiness_api,
        "build_org_scope_audit",
        lambda db, organization_id=None: {
            "organization_id": organization_id,
            "tables": [],
            "warnings": [],
            "summary": {"ready_for_saas": True},
        },
    )

    response = client.get("/api/saas-readiness/org-scope")

    assert response.status_code == 200
    assert response.json()["organization_id"] == 1


def test_opportunity_read_extracts_requested_quantity_from_dibbs_search_row():
    from app.schemas.opportunity import OpportunityRead

    payload = OpportunityRead.model_validate(
        {
            "id": 1,
            "source": "DIBBS",
            "source_opportunity_id": "SPE2DS26T9653",
            "solicitation_number": "6515-01-646-2617",
            "title": "TOURNIQUET, NONPNEUM",
            "raw_payload": {"dibbs_search_row": {"quantity": "8"}},
        }
    ).model_dump()

    assert payload["requested_quantity"] == "8"
    assert payload["requested_quantity_display"] == "Qty: 8"


def test_preferred_dibbs_detail_pdf_url_uses_search_row_pdf_url():
    from types import SimpleNamespace

    from app.services.pdf_service import _preferred_dibbs_detail_pdf_url

    opp = SimpleNamespace(
        solicitation_number="6515-01-555-0446",
        raw_payload={
            "dibbs_search_row": {
                "nsn": "6515015550446",
                "pdf_url": "https://dibbs2.bsm.dla.mil/Downloads/RFQ/Q/SPE2DS26T008Q.PDF",
            }
        },
    )

    assert _preferred_dibbs_detail_pdf_url(opp) == "https://dibbs2.bsm.dla.mil/Downloads/RFQ/Q/SPE2DS26T008Q.PDF"


def test_collect_dibbs_file_candidates_includes_search_row_pdf_url():
    from types import SimpleNamespace

    from app.services.pdf_service import _collect_dibbs_file_candidates

    opp = SimpleNamespace(
        raw_payload={
            "dibbs_search_row": {
                "nsn": "6515015550446",
                "pdf_url": "https://dibbs2.bsm.dla.mil/Downloads/RFQ/Q/SPE2DS26T008Q.PDF",
            }
        }
    )

    candidates = _collect_dibbs_file_candidates(opp)

    assert candidates == [
        {
            "url": "https://dibbs2.bsm.dla.mil/Downloads/RFQ/Q/SPE2DS26T008Q.PDF",
            "label": "6515015550446",
        }
    ]


def test_dibbs_maintenance_text_detection():
    from app.services.pdf_service import _looks_like_dibbs_maintenance_text

    assert _looks_like_dibbs_maintenance_text("DIBBS is temporarily unavailable due to scheduled maintenance.")
    assert _looks_like_dibbs_maintenance_text("The system is under maintenance. Please try again later.")
    assert _looks_like_dibbs_maintenance_text("Service unavailable")
    assert _looks_like_dibbs_maintenance_text("Normal solicitation detail page") is False


def test_should_create_fallback_snapshot_only_when_no_downloaded_files():
    from app.services.pdf_service import _should_create_fallback_snapshot

    assert _should_create_fallback_snapshot(True, []) is True
    assert _should_create_fallback_snapshot(False, []) is False
    assert _should_create_fallback_snapshot(True, [{"filename": "official.pdf"}]) is False


def test_save_downloaded_file_repairs_stale_existing_record(monkeypatch):
    from types import SimpleNamespace

    from app.services import pdf_service

    existing = SimpleNamespace(
        file_type="PDF_FALLBACK_SNAPSHOT",
        filename="test.pdf",
        source_url="https://old.example/test.pdf",
        file_path="s3://nagacon/missing/test.pdf",
    )
    added = []
    commits = []

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return existing

    class FakeDB:
        def query(self, model):
            return FakeQuery()

        def add(self, item):
            added.append(item)

        def commit(self):
            commits.append(True)

    monkeypatch.setattr(pdf_service, "file_exists", lambda ref: False)
    monkeypatch.setattr(pdf_service, "store_bytes", lambda path, data, content_type=None: "s3://nagacon/repaired/test.pdf")

    opp = SimpleNamespace(id=1, organization_id=1)
    created, filename = pdf_service._save_downloaded_file(
        FakeDB(),
        opp,
        Path("exports"),
        "test.pdf",
        "https://new.example/test.pdf",
        b"%PDF-new",
        "DIBBS_ATTACHMENT",
    )

    assert created == 1
    assert filename == "test.pdf"
    assert existing.file_type == "DIBBS_ATTACHMENT"
    assert existing.source_url == "https://new.example/test.pdf"
    assert existing.file_path == "s3://nagacon/repaired/test.pdf"
    assert added == [existing]
    assert commits == [True]


def test_opportunity_read_extracts_requested_quantity_from_dibbs_detail():
    from app.schemas.opportunity import OpportunityRead

    payload = OpportunityRead.model_validate(
        {
            "id": 1,
            "source": "DIBBS",
            "source_opportunity_id": "SPE2DS26T9653",
            "solicitation_number": "SPE2DS26T9653",
            "title": "TOURNIQUET, NONPNEUM",
            "raw_payload": {
                "dibbs_detail": {
                    "solicitations": [
                        {"solicitation_number": "SPE2DS26T9653", "qty": "12"},
                    ]
                }
            },
        }
    ).model_dump()

    assert payload["requested_quantity"] == "12"
    assert payload["requested_quantity_display"] == "Qty: 12"


def test_opportunity_read_marks_archived_lifecycle_after_30_days():
    from datetime import timedelta

    from app.schemas.opportunity import OpportunityRead

    payload = OpportunityRead.model_validate(
        {
            "id": 9,
            "source": "DIBBS",
            "solicitation_number": "SOL-9",
            "title": "Legacy Part",
            "due_at": datetime.utcnow() - timedelta(days=31),
        }
    ).model_dump()

    assert payload["opportunity_lifecycle"] == "ARCHIVED"
    assert payload["workflow_label"] == "Archive"
    assert payload["award_intelligence_status"] == "ARCHIVED"


def test_file_retention_marks_archived_complete_pdf_as_prune_eligible():
    from datetime import timedelta
    from types import SimpleNamespace

    from app.services.file_retention import classify_opportunity_file_retention

    opportunity = SimpleNamespace(due_at=datetime.utcnow() - timedelta(days=45))
    file_record = SimpleNamespace(
        file_type="DIBBS_ATTACHMENT",
        file_path="s3://nagacon/test.pdf",
        extracted_text="parsed text",
        parsed_metadata={
            "document_type": "SOLICITATION",
            "_pipeline": {"review_required": False},
            "_retention": {"downstream_complete": True},
        },
    )

    decision = classify_opportunity_file_retention(file_record, opportunity)

    assert decision.storage_class == "core"
    assert decision.retention_status == "eligible_for_prune"
    assert decision.prune_eligible is True


def test_file_retention_keeps_archived_pdf_until_downstream_processing_is_complete():
    from datetime import timedelta
    from types import SimpleNamespace

    from app.services.file_retention import classify_opportunity_file_retention

    opportunity = SimpleNamespace(due_at=datetime.utcnow() - timedelta(days=45))
    file_record = SimpleNamespace(
        file_type="DIBBS_ATTACHMENT",
        file_path="s3://nagacon/test.pdf",
        extracted_text="parsed text",
        parsed_metadata={"document_type": "SOLICITATION", "_pipeline": {"review_required": False}},
    )

    decision = classify_opportunity_file_retention(file_record, opportunity)

    assert decision.storage_class == "core"
    assert decision.retention_status == "retain"
    assert decision.reason == "downstream_processing_incomplete"
    assert decision.prune_eligible is False


def test_files_prune_candidates_returns_only_eligible_items(client, monkeypatch):
    opportunity = SimpleNamespace(id=5, due_at=datetime.utcnow())
    keep_file = SimpleNamespace(id=1, opportunity_id=5, filename="keep.pdf", file_type="DIBBS_ATTACHMENT", file_path="s3://nagacon/keep.pdf", parsed_metadata={}, extracted_text=None)
    prune_file = SimpleNamespace(id=2, opportunity_id=5, filename="prune.pdf", file_type="DIBBS_ATTACHMENT", file_path="s3://nagacon/prune.pdf", parsed_metadata={}, extracted_text="ok")

    class FakeQuery:
        def __init__(self, result):
            self.result = result

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return self.result

        def first(self):
            if isinstance(self.result, list):
                return self.result[0] if self.result else None
            return self.result

    monkeypatch.setattr(files_api, "_scoped_opportunity_query", lambda db, opportunity_id, org_id: FakeQuery(opportunity))
    monkeypatch.setattr(files_api, "_scoped_file_query", lambda db, org_id: FakeQuery([keep_file, prune_file]))
    monkeypatch.setattr(
        files_api,
        "classify_opportunity_file_retention",
        lambda file_record, opp: SimpleNamespace(
            storage_class="core",
            retention_status="eligible_for_prune" if file_record.id == 2 else "retain",
            reason="archived_and_extracted" if file_record.id == 2 else "active_or_recently_closed",
            prune_eligible=file_record.id == 2,
        ),
    )

    response = client.get("/api/files/prune-candidates", params={"opportunity_id": 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["id"] == 2


def test_files_prune_marks_only_eligible_files(client, monkeypatch):
    opportunity = SimpleNamespace(id=7, due_at=datetime.utcnow())
    keep_file = SimpleNamespace(id=1, opportunity_id=7, filename="keep.pdf", file_type="DIBBS_ATTACHMENT", file_path="s3://nagacon/keep.pdf", parsed_metadata={}, extracted_text=None)
    prune_file = SimpleNamespace(id=2, opportunity_id=7, filename="prune.pdf", file_type="DIBBS_ATTACHMENT", file_path="s3://nagacon/prune.pdf", parsed_metadata={}, extracted_text="ok")
    commits = []

    class FakeQuery:
        def __init__(self, result):
            self.result = result

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return self.result

        def first(self):
            if isinstance(self.result, list):
                return self.result[0] if self.result else None
            return self.result

    class FakeDB:
        def add(self, item):
            return None

        def commit(self):
            commits.append(True)

    def override_get_db():
        yield FakeDB()

    client.app.dependency_overrides[files_api.get_db] = override_get_db
    monkeypatch.setattr(files_api, "_scoped_opportunity_query", lambda db, opportunity_id, org_id: FakeQuery(opportunity))
    monkeypatch.setattr(files_api, "_scoped_file_query", lambda db, org_id: FakeQuery([keep_file, prune_file]))
    monkeypatch.setattr(
        files_api,
        "classify_opportunity_file_retention",
        lambda file_record, opp: SimpleNamespace(
            storage_class="core",
            retention_status="eligible_for_prune" if file_record.id == 2 else "retain",
            reason="archived_and_extracted" if file_record.id == 2 else "active_or_recently_closed",
            prune_eligible=file_record.id == 2,
        ),
    )
    monkeypatch.setattr(files_api, "delete_reference", lambda ref: ref == "s3://nagacon/prune.pdf")

    response = client.post("/api/files/prune", params={"opportunity_id": 7})

    assert response.status_code == 200
    payload = response.json()
    assert payload["pruned_count"] == 1
    assert payload["skipped_count"] == 1
    assert prune_file.file_path == "pruned://opportunity-file/2"
    assert prune_file.parsed_metadata["_retention"]["deleted_from_storage"] is True
    assert commits == [True]
    client.app.dependency_overrides.pop(files_api.get_db, None)


def test_download_file_returns_storage_response_without_exists_precheck(client, monkeypatch):
    file_record = SimpleNamespace(
        id=34,
        opportunity_id=1116,
        file_path="s3://nagacon/6515-01-685-4670/documents/6515-01-685-4670_fallback_snapshot.pdf",
        filename="6515-01-685-4670_fallback_snapshot.pdf",
    )

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return file_record

    monkeypatch.setattr(files_api, "_scoped_file_query", lambda db, org_id: FakeQuery())
    monkeypatch.setattr(files_api, "build_storage_download_response", lambda ref, filename=None: {"ok": True, "ref": ref, "filename": filename})
    monkeypatch.setattr(files_api, "file_exists", lambda ref: False)

    response = client.get("/api/files/download/34")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["ref"] == file_record.file_path


def test_storage_local_references_still_work_when_backend_is_s3(monkeypatch):
    import tempfile
    from pathlib import Path

    from app.services import storage as storage_service

    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    temp.write(b"%PDF-legacy")
    temp.flush()
    temp.close()
    local_file = Path(temp.name)

    monkeypatch.setattr(storage_service.settings, "STORAGE_BACKEND", "s3", raising=False)
    monkeypatch.setattr(storage_service.settings, "S3_BUCKET", "", raising=False)

    try:
        assert storage_service.file_exists(str(local_file)) is True

        with storage_service.local_temp_path(str(local_file), suffix=".pdf") as resolved:
            assert resolved.read_bytes() == b"%PDF-legacy"
    finally:
        local_file.unlink(missing_ok=True)
