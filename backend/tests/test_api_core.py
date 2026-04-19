from datetime import datetime
from types import SimpleNamespace

from app.api import opportunities as opportunities_api
from app.api import integrations as integrations_api
from app.api import workspace as workspace_api
from app.api.routes import company as company_api
from app.api.routes import pipeline as pipeline_api
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
    assert payload["external_api_keys"] == ["alpha", "beta"]
    assert payload["organization"]["slug"] == "default"


def test_current_organization_route_returns_default_org(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.organizations.ensure_default_organization",
        lambda db: SimpleNamespace(id=1, name="Default Organization", slug="default", is_default=True),
    )

    response = client.get("/api/organizations/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["slug"] == "default"


def test_auth_me_returns_current_user_and_org(client):
    response = client.get("/api/auth/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["email"] == "owner@nagacon.local"
    assert payload["organization"]["slug"] == "default"
