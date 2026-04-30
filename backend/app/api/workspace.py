from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_current_user, get_db
from app.models.bid_submission import BidSubmission
from app.models.opportunity import Opportunity
from app.models.opportunity import OpportunityAnalysis
from app.models.opportunity_file import OpportunityFile
from app.models.vendor import VendorLead
from app.models.workspace import WorkspaceArtifact, WorkspaceTask
from app.repositories.agents import AgentRunRepository
from app.repositories.company import CompanyRepository
from app.repositories.vendor_matches import VendorMatchRepository
from app.repositories.pipeline import PipelineRepository
from app.schemas.agent import AgentRunCreate, AgentRunUpdate
from app.schemas.workspace import ArtifactOut, ArtifactUpdate, GenerateIn, TaskCreate, TaskOut, TaskUpdate
from app.services.dibbs.detail_enrichment_playwright import enrich_dibbs_opportunity
from app.services.agents.workspace_agents import PHASE_AGENT_MAP, run_workspace_agent, workspace_agent_type
from app.services.bid_submission_service import get_submission
from app.services.recommendation_engine import build_workspace_recommendation
from app.services.opportunity_intake_pipeline import run_opportunity_intake_pipeline
from app.services.sam_capability_match import build_sam_capability_match
from app.services.research.usaspending_research_service import search_usaspending_for_opportunity, seed_usaspending_vendors_into_leads
from app.services.intelligence.nsn_intelligence_service import get_nsn_intelligence, run_nsn_intelligence
from app.services.providers.pdf_cage_extractor import extract_providers_from_opportunity_pdfs, seed_vendor_leads_from_providers
from app.services.vendor_service import promote_vendor_lead_to_quote_request, sync_quote_status_from_outreach_artifact, sync_vendor_leads_from_parsed
from app.services.vendor_email_automation import generate_quote_request_email
from app.services.vendor_email_automation import send_email_message
from app.services.vendors.discovery import discover_vendors_for_opportunity
from app.services.workspace_service import build_normalized_facts, build_research_profile, build_sam_past_performance_map, create_artifact, ensure_parsed, generate_checklist, generate_compliance_matrix, generate_contracting_officer_email, generate_quote_email, generate_research_brief, generate_submission_package, generate_vendor_shortlist, get_best_processed_document_data, seed_proposal_tasks
from app.utils.opportunity_lifecycle import derive_opportunity_lifecycle
from app.utils.solicitation_status import derive_solicitation_status
from app.utils.title_normalizer import build_summary_text

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


def _has_legacy_requirement_phrasing(items: list[str]) -> bool:
    legacy_phrases = (
        "language is present",
        "instructions are present in the solicitation",
        "referenced in the solicitation",
        "may be present in the solicitation package",
    )
    return any(any(phrase in str(item or "").lower() for phrase in legacy_phrases) for item in items)


def _artifact_needs_document_refresh(compliance_json: dict, files: list[OpportunityFile]) -> bool:
    actions = list(compliance_json.get("required_actions") or compliance_json.get("submission_requirements") or [])
    if not files:
        return False
    if not compliance_json:
        return True
    if not actions or _has_legacy_requirement_phrasing(actions):
        return True
    best_file = None
    ranked = sorted(
        files,
        key=lambda file: (
            1 if str(getattr(file, "file_type", "") or "").upper() == "PDF_FALLBACK_SNAPSHOT" else 0,
            -1 if getattr(file, "extracted_text", None) else 0,
            -1 if getattr(file, "parsed_metadata", None) else 0,
            -(getattr(file, "created_at", None).timestamp() if getattr(file, "created_at", None) else 0),
        ),
    )
    if ranked:
        best_file = ranked[0]
    source_file = str((compliance_json.get("compliance_fields") or {}).get("source_file") or "")
    if best_file and source_file and source_file != getattr(best_file, "filename", ""):
        return True
    if best_file and not source_file:
        return True
    return False


def _query_count(query) -> int:
    if hasattr(query, "count"):
        return int(query.count())
    if hasattr(query, "all"):
        return len(query.all() or [])
    first = query.first() if hasattr(query, "first") else None
    return 1 if first else 0


def _safe_session_call(db: Session, method_name: str, *args):
    method = getattr(db, method_name, None)
    if callable(method):
        return method(*args)
    return None


def _get_opp_or_404(db: Session, opp_id: int, organization_id: int | None = None) -> Opportunity:
    opp = db.query(Opportunity).filter(Opportunity.id == opp_id)
    if organization_id is not None:
        opp = opp.filter(Opportunity.organization_id == organization_id)
    opp = opp.first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return opp


def _get_opp_scoped(db: Session, opp_id: int, organization_id: int | None = None) -> Opportunity:
    try:
        return _get_opp_or_404(db, opp_id, organization_id=organization_id)
    except TypeError:
        return _get_opp_or_404(db, opp_id)


def _vendor_match_repo(db: Session, organization_id: int | None):
    try:
        return VendorMatchRepository(db, organization_id=organization_id)
    except TypeError:
        return VendorMatchRepository(db)


def _pipeline_repo(db: Session, organization_id: int | None):
    try:
        return PipelineRepository(db, organization_id=organization_id)
    except TypeError:
        return PipelineRepository(db)


def _artifact_payload(artifact: WorkspaceArtifact) -> dict:
    content = dict(artifact.content_json or {})
    meta = dict(content.get("_meta") or {})
    history = list(content.get("_history") or [])
    outreach_log = list(content.get("_outreach_log") or [])
    return {
        "id": artifact.id,
        "artifact_type": artifact.artifact_type,
        "title": artifact.title,
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        "content_json": content,
        "artifact_category": meta.get("artifact_category"),
        "artifact_status": meta.get("artifact_status"),
        "version_history": history,
        "version_count": len(history),
        "outreach_log": outreach_log,
        "outreach_count": len(outreach_log),
    }


def _create_agent_run_safe(db: Session, opp_id: int, agent_key: str, extra_input: dict | None = None):
    repo = AgentRunRepository(db)
    try:
        run = repo.create(
            AgentRunCreate(
                opportunity_id=opp_id,
                agent_type=workspace_agent_type(agent_key),
                input_payload={"agent_key": agent_key, "opportunity_id": opp_id, **(extra_input or {})},
                status="running",
                model_name="workspace_phased_agent",
                started_at=datetime.now(timezone.utc),
            )
        )
        return repo, run
    except Exception:
        if hasattr(db, "rollback"):
            _safe_session_call(db, "rollback")
        return None, None


def _update_agent_run_safe(db: Session, repo: AgentRunRepository | None, run_id: int | None, status: str, output: dict | None = None, error: str | None = None, model_name: str | None = None):
    if not repo or not run_id:
        return
    try:
        repo.update(
            run_id,
            AgentRunUpdate(
                status=status,
                output_payload=output,
                error_message=error,
                model_name=model_name,
                completed_at=datetime.now(timezone.utc) if status in {"success", "failed"} else None,
            ),
        )
    except Exception:
        if hasattr(db, "rollback"):
            _safe_session_call(db, "rollback")


def _run_workspace_agent_for_user(agent_key: str, opp: Opportunity, db: Session, user_id: int | None):
    try:
        return run_workspace_agent(agent_key, opp, db, user_id=user_id)
    except TypeError:
        return run_workspace_agent(agent_key, opp, db)


@router.get("/summary")
def workspace_summary(opp_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    org_id = getattr(current_org, "id", None)
    opp = _get_opp_scoped(db, opp_id, organization_id=org_id)

    intake_pipeline = None
    if str((getattr(opp, "raw_payload", None) or {}).get("_intake_pipeline_ran") or "").lower() != "true":
        try:
            existing_artifacts = _query_count(db.query(WorkspaceArtifact).filter(WorkspaceArtifact.opportunity_id == opp_id))
            existing_leads = _query_count(db.query(VendorLead).filter(VendorLead.opportunity_id == opp_id))
            if existing_artifacts == 0 and existing_leads == 0:
                intake_pipeline = run_opportunity_intake_pipeline(
                    db,
                    opp_id,
                    organization_id=org_id,
                    download_documents=False,
                    run_usaspending=False,
                )
                _safe_session_call(db, "refresh", opp)
        except Exception as exc:
            _safe_session_call(db, "rollback")
            intake_pipeline = {"status": "failed", "error": str(exc)}
        finally:
            try:
                raw_payload = dict(getattr(opp, "raw_payload", None) or {})
                raw_payload["_intake_pipeline_ran"] = True
                opp.raw_payload = raw_payload
                _safe_session_call(db, "add", opp)
                _safe_session_call(db, "commit")
            except Exception:
                _safe_session_call(db, "rollback")

    try:
        analysis = db.query(OpportunityAnalysis).filter(OpportunityAnalysis.opportunity_id == opp_id).first()
    except Exception:
        _safe_session_call(db, "rollback")
        analysis = None

    try:
        vendor_matches = _vendor_match_repo(db, org_id).list_by_opportunity_id(opp_id)
    except Exception:
        _safe_session_call(db, "rollback")
        vendor_matches = []

    vendor_ids = [getattr(v, "vendor_id", None) for v in vendor_matches if getattr(v, "vendor_id", None) is not None]
    vendor_lookup = {}
    if vendor_ids:
        try:
            vendor_lookup = {
                lead.id: lead
                for lead in db.query(VendorLead).filter(VendorLead.id.in_(vendor_ids)).all()
            }
        except Exception:
            _safe_session_call(db, "rollback")
            vendor_lookup = {}

    vendor_matches = [
        {
            "id": getattr(v, "id", None),
            "vendor_id": getattr(v, "vendor_id", None),
            "opportunity_id": getattr(v, "opportunity_id", None),
            "vendor_name": getattr(vendor_lookup.get(getattr(v, "vendor_id", None)), "company_name", None),
            "company_name": getattr(vendor_lookup.get(getattr(v, "vendor_id", None)), "company_name", None),
            "cage_code": getattr(vendor_lookup.get(getattr(v, "vendor_id", None)), "cage", None),
            "cage": getattr(vendor_lookup.get(getattr(v, "vendor_id", None)), "cage", None),
            "status": getattr(vendor_lookup.get(getattr(v, "vendor_id", None)), "status", None),
            "source_type": getattr(vendor_lookup.get(getattr(v, "vendor_id", None)), "source_type", None),
            "match_reason": getattr(v, "match_reason", None),
            "confidence_score": getattr(v, "confidence_score", None),
            "source": getattr(v, "source", None),
        }
        if not isinstance(v, dict)
        else v
        for v in vendor_matches
    ]

    opportunity_payload = {
        "id": opp.id,
        "source": opp.source,
        "raw_title": getattr(opp, "raw_title", None),
        "display_title": getattr(opp, "display_title", None),
        "source_uniform_title": getattr(opp, "source_uniform_title", None),
        "solicitation_number": opp.solicitation_number,
        "title": opp.title,
        "agency": opp.agency,
        "url": opp.url,
        "posted_at": opp.posted_at.isoformat() if getattr(opp, "posted_at", None) else None,
        "due_at": opp.due_at.isoformat() if getattr(opp, "due_at", None) else None,
        "naics": getattr(opp, "naics", None),
        "naics_code": getattr(opp, "naics", None),
        "fsc": getattr(opp, "fsc", None),
        "fsc_code": getattr(opp, "fsc", None),
        "set_aside": getattr(opp, "set_aside", None),
        "set_aside_type": getattr(opp, "set_aside", None),
        "summary": getattr(opp, "summary_text", None) or build_summary_text(opp.raw_text, opp.parsed_json, opp.raw_payload),
        "description": getattr(opp, "description", None),
        "raw_text": getattr(opp, "raw_text", None),
        "parsed_json": getattr(opp, "parsed_json", None),
        "raw_payload": getattr(opp, "raw_payload", None),
        "workspace_url": getattr(opp, "workspace_url", None),
        "solicitation_status": derive_solicitation_status(getattr(opp, "due_at", None)),
        "opportunity_lifecycle": derive_opportunity_lifecycle(getattr(opp, "due_at", None)),
        "intake_pipeline": intake_pipeline,
    }
    is_closed = opportunity_payload["solicitation_status"] == "CLOSED"

    actions = [
        "Generate Checklist",
        "Generate Vendor Shortlist",
        "Generate Quote Email",
        "Research via USAspending",
        "Generate Research Brief",
    ]

    try:
        pipeline_item = _pipeline_repo(db, org_id).get_by_opportunity_id(opp_id)
    except Exception:
        _safe_session_call(db, "rollback")
        pipeline_item = None

    files_query = db.query(OpportunityFile).filter(OpportunityFile.opportunity_id == opp_id)
    if org_id is not None:
        files_query = files_query.filter(OpportunityFile.organization_id == org_id)
    files = files_query.order_by(OpportunityFile.created_at.desc()).all()
    document_data = get_best_processed_document_data(opp, files=files)
    artifacts_query = db.query(WorkspaceArtifact).filter(WorkspaceArtifact.opportunity_id == opp_id)
    if org_id is not None:
        artifacts_query = artifacts_query.filter(WorkspaceArtifact.organization_id == org_id)
    artifacts = artifacts_query.order_by(WorkspaceArtifact.created_at.desc()).all()
    compliance_artifact = next((artifact for artifact in artifacts if artifact.artifact_type == "COMPLIANCE_BRIEF"), None)
    compliance_json = dict(getattr(compliance_artifact, "content_json", None) or {})
    needs_document_refresh = _artifact_needs_document_refresh(compliance_json, files)
    if files:
        try:
            from app.services.document_pipeline import _build_compliance_artifact_content

            fresh_compliance = _build_compliance_artifact_content(db, opp)
            current_actions = list(compliance_json.get("required_actions") or compliance_json.get("submission_requirements") or [])
            fresh_actions = list(fresh_compliance.get("required_actions") or fresh_compliance.get("submission_requirements") or [])
            current_review = list(compliance_json.get("review_flags") or [])
            fresh_review = list(fresh_compliance.get("review_flags") or [])
            current_missing = list(compliance_json.get("missing_information") or [])
            fresh_missing = list(fresh_compliance.get("missing_information") or [])
            current_source = str((compliance_json.get("compliance_fields") or {}).get("source_file") or "")
            fresh_source = str((fresh_compliance.get("compliance_fields") or {}).get("source_file") or "")
            if (
                current_actions != fresh_actions
                or current_review != fresh_review
                or current_missing != fresh_missing
                or current_source != fresh_source
            ):
                needs_document_refresh = True
        except Exception:
            _safe_session_call(db, "rollback")
    if needs_document_refresh:
        try:
            from app.services.document_pipeline import refresh_workspace_document_outputs

            refresh_workspace_document_outputs(db, opp)
            artifacts = artifacts_query.order_by(WorkspaceArtifact.created_at.desc()).all()
            compliance_artifact = next((artifact for artifact in artifacts if artifact.artifact_type == "COMPLIANCE_BRIEF"), None)
            compliance_json = dict(getattr(compliance_artifact, "content_json", None) or {})
        except Exception:
            _safe_session_call(db, "rollback")
    if str(getattr(opp, "source", "") or "").upper() == "SAM":
        try:
            checklist_artifact = next((artifact for artifact in artifacts if artifact.artifact_type == "CHECKLIST"), None)
            if checklist_artifact is None:
                generate_checklist(db, opp)
            if compliance_json:
                generate_compliance_matrix(db, opp)
            seed_proposal_tasks(db, opp)
            artifacts = artifacts_query.order_by(WorkspaceArtifact.created_at.desc()).all()
        except Exception:
            _safe_session_call(db, "rollback")
    tasks_query = db.query(WorkspaceTask).filter(WorkspaceTask.opportunity_id == opp_id)
    if org_id is not None:
        tasks_query = tasks_query.filter(WorkspaceTask.organization_id == org_id)
    tasks = tasks_query.order_by(WorkspaceTask.created_at.desc()).all()
    try:
        agent_runs = AgentRunRepository(db).list_by_opportunity_id(opp_id)
    except Exception:
        _safe_session_call(db, "rollback")
        agent_runs = []
    submission = get_submission(db, opp_id)

    parsed = getattr(opp, "parsed_json", None) or {}
    sam_intelligence = parsed.get("sam_intelligence") if isinstance(parsed, dict) else {}
    if not isinstance(sam_intelligence, dict):
        sam_intelligence = {}
    if not parsed:
        try:
            parsed = ensure_parsed(db, opp)
        except Exception:
            _safe_session_call(db, "rollback")
            parsed = getattr(opp, "parsed_json", None) or {}
        sam_intelligence = parsed.get("sam_intelligence") if isinstance(parsed, dict) else {}
        if not isinstance(sam_intelligence, dict):
            sam_intelligence = {}
    parsed_summary = {
        "nsn": document_data.get("fields", {}).get("nsn") or parsed.get("nsn"),
        "nomenclature": document_data.get("fields", {}).get("nomenclature") or document_data.get("summary", {}).get("title") or parsed.get("nomenclature") or parsed.get("item_description"),
        "approved_source_count": len(parsed.get("approved_sources") or []),
        "cage_codes": parsed.get("cage_codes") or [],
        "part_numbers": parsed.get("part_numbers") or [],
        "solicitations": parsed.get("solicitations") or [],
        "text_source": parsed.get("text_source") or {},
        "document_source_file": document_data.get("filename"),
        "document_type": document_data.get("pipeline", {}).get("document_type"),
        "document_summary": document_data.get("summary") or {},
        "sam_intelligence": sam_intelligence,
    }
    normalized_facts = build_normalized_facts(opp, parsed, document_data, compliance_json)
    research_profile = build_research_profile(opp, parsed)
    company_profile = CompanyRepository(db).get_first_profile()
    capability_match = build_sam_capability_match(opp, company_profile) if str(getattr(opp, "source", "")).upper() == "SAM" else {}
    past_performance_map = build_sam_past_performance_map(db, opp) if str(getattr(opp, "source", "")).upper() == "SAM" else {}
    try:
        recommendation = build_workspace_recommendation(
            db,
            opp,
            parsed=parsed,
            files=files,
            submission=submission,
        )
    except Exception:
        _safe_session_call(db, "rollback")
        recommendation = {}
    opportunity_payload["solicitation_number"] = document_data.get("fields", {}).get("solicitation_number") or opportunity_payload["solicitation_number"]
    opportunity_payload["due_at"] = document_data.get("fields", {}).get("return_by") or opportunity_payload["due_at"]
    opportunity_payload["summary"] = (
        document_data.get("summary", {}).get("summary_text")
        or opportunity_payload["summary"]
    )
    opportunity_payload["document_summary"] = document_data.get("summary") or {}
    opportunity_payload["document_fields"] = document_data.get("fields") or {}
    opportunity_payload["document_source_file"] = document_data.get("filename")
    opportunity_payload["document_requirements_count"] = len(document_data.get("requirements") or [])
    opportunity_payload["prepared_summary"] = getattr(analysis, "ai_summary", None) or sam_intelligence.get("summary")
    opportunity_payload["prepared_requirements"] = sam_intelligence.get("requirements") or []
    opportunity_payload["prepared_risk_flags"] = (getattr(analysis, "risk_flags", None) if analysis else None) or sam_intelligence.get("risk_flags") or []

    recent_activity = []
    if pipeline_item and getattr(pipeline_item, "updated_at", None):
        recent_activity.append(
            {
                "type": "pipeline",
                "title": "Pipeline updated",
                "timestamp": pipeline_item.updated_at.isoformat(),
                "detail": getattr(getattr(pipeline_item, "decision_status", None), "value", getattr(pipeline_item, "decision_status", None)),
            }
        )
    for file in files[:5]:
        recent_activity.append(
            {
                "type": "file",
                "title": file.filename,
                "timestamp": file.created_at.isoformat() if file.created_at else None,
                "detail": file.file_type,
            }
        )
    for artifact in artifacts[:5]:
        artifact_payload = _artifact_payload(artifact)
        recent_activity.append(
            {
                "type": "artifact",
                "title": artifact.title,
                "timestamp": artifact.created_at.isoformat() if artifact.created_at else None,
                "detail": artifact_payload.get("artifact_status") or artifact.artifact_type,
            }
        )
    for task in tasks[:5]:
        recent_activity.append(
            {
                "type": "task",
                "title": task.task_type,
                "timestamp": task.created_at.isoformat() if task.created_at else None,
                "detail": task.status,
            }
        )
    for run in agent_runs[:5]:
        run_agent_key = None
        if isinstance(getattr(run, "input_payload", None), dict):
            run_agent_key = run.input_payload.get("agent_key")
        recent_activity.append(
            {
                "type": "agent",
                "title": f"Agent run: {run_agent_key or getattr(run.agent_type, 'value', run.agent_type)}",
                "timestamp": run.created_at.isoformat() if run.created_at else None,
                "detail": run.status,
            }
        )
    recent_activity.sort(key=lambda item: item.get("timestamp") or "", reverse=True)

    return {
        "opportunity": opportunity_payload,
        "analysis": {
            "priority_score": recommendation.get("recommendation_score") or (getattr(analysis, "priority_score", 0) if analysis else 0),
            "risk_flags": recommendation.get("risk_flags") or (getattr(analysis, "risk_flags", []) if analysis else []),
            "fit_score": (recommendation.get("score_breakdown") or {}).get("strategic_fit") or (getattr(analysis, "fit_score", 0) if analysis else 0),
            "ai_summary": recommendation.get("summary") or (getattr(analysis, "ai_summary", None) if analysis else None),
            "requirements": sam_intelligence.get("requirements") or [],
            "decision_status": getattr(opp, "decision_status", None),
            "recommendation": recommendation,
            "capability_match": capability_match,
        },
        "recommendation": recommendation,
        "capability_match": capability_match,
        "past_performance_map": past_performance_map,
        "vendor_matches": vendor_matches,
        "artifacts": [_artifact_payload(artifact) for artifact in artifacts],
        "tasks": [
            {
                "id": task.id,
                "opportunity_id": task.opportunity_id,
                "task_type": task.task_type,
                "status": task.status,
                "due_at": task.due_at.isoformat() if task.due_at else None,
                "notes": task.notes,
                "created_at": task.created_at.isoformat() if task.created_at else None,
            }
            for task in tasks
        ],
        "agent_runs": [
            {
                "id": run.id,
                "agent_type": getattr(run.agent_type, "value", run.agent_type),
                "agent_key": (run.input_payload or {}).get("agent_key") if isinstance(getattr(run, "input_payload", None), dict) else None,
                "status": run.status,
                "model_name": run.model_name,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "error_message": run.error_message,
                "output_payload": run.output_payload,
            }
            for run in agent_runs
        ],
        "files": [
            {
                "id": file.id,
                "file_type": file.file_type,
                "filename": file.filename,
                "source_url": file.source_url,
                "created_at": file.created_at.isoformat() if file.created_at else None,
            }
            for file in files
        ],
        "quotes": [],
        "parsed_summary": parsed_summary,
        "normalized_facts": normalized_facts,
        "research_profile": research_profile,
        "submission": {
            "id": submission.id,
            "opportunity_id": submission.opportunity_id,
            "status": submission.status,
            "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else None,
            "submitted_unit_price": float(submission.submitted_unit_price) if submission.submitted_unit_price is not None else None,
            "submitted_vendor_cage": submission.submitted_vendor_cage,
            "submitted_vendor_name": submission.submitted_vendor_name,
            "planned_vendor_quote_id": submission.planned_vendor_quote_id,
            "planned_vendor_cage": submission.planned_vendor_cage,
            "planned_vendor_name": submission.planned_vendor_name,
            "awarded_at": submission.awarded_at.isoformat() if submission.awarded_at else None,
            "award_amount": float(submission.award_amount) if submission.award_amount is not None else None,
            "winning_vendor_cage": submission.winning_vendor_cage,
            "winning_vendor_name": submission.winning_vendor_name,
            "outcome_summary": submission.outcome_summary,
            "notes": submission.notes,
            "created_at": submission.created_at.isoformat() if submission.created_at else None,
            "updated_at": submission.updated_at.isoformat() if submission.updated_at else None,
        } if submission else None,
        "recent_activity": recent_activity[:8],
        "pipeline_item": {
            "id": getattr(pipeline_item, "id", None),
            "opportunity_id": getattr(pipeline_item, "opportunity_id", None),
            "decision_status": getattr(getattr(pipeline_item, "decision_status", None), "value", getattr(pipeline_item, "decision_status", None)),
            "owner": getattr(pipeline_item, "owner", None),
            "priority": getattr(pipeline_item, "priority", None),
            "probability_of_win": getattr(pipeline_item, "probability_of_win", None),
            "notes": getattr(pipeline_item, "notes", None),
            "target_submit_date": getattr(getattr(pipeline_item, "target_submit_date", None), "isoformat", lambda: None)() if getattr(pipeline_item, "target_submit_date", None) else None,
        } if pipeline_item else None,
        "actions": actions,
        "agent_phases": PHASE_AGENT_MAP,
        "ui_hints": {
            "source_badge": opp.source,
            "empty_vendors_message": "No vendor matches yet. Use USAspending research or vendor discovery next.",
            "empty_artifacts_message": "No artifacts yet. Parse the opportunity or generate a checklist.",
            "workspace_mode": "research_only" if is_closed else "active",
            "closed_message": "This solicitation is closed. Keep using this workspace for research, vendor intelligence, and historical reference.",
        },
    }


@router.post("/agents/run")
def run_workspace_agent_route(
    payload: dict,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    opp_id = payload.get("opportunity_id")
    agent_key = payload.get("agent_key")
    opp = _get_opp_scoped(db, opp_id, organization_id=getattr(current_org, "id", None))
    if not agent_key:
        raise HTTPException(status_code=400, detail="agent_key is required")

    repo, run = _create_agent_run_safe(db, opp.id, agent_key)
    try:
        result = _run_workspace_agent_for_user(agent_key, opp, db, getattr(current_user, "id", None))
        _update_agent_run_safe(
            db,
            repo,
            getattr(run, "id", None),
            "success",
            output=result.get("output"),
            model_name=result.get("model_name"),
        )
        return {
            "status": "success",
            "run_id": getattr(run, "id", None),
            "agent_key": agent_key,
            "artifact": result.get("artifact"),
            "output": result.get("output"),
            "model_name": result.get("model_name") or "workspace_phased_agent",
            "persisted_run": bool(run),
            "provider_status": result.get("provider_status"),
            "fallback_reason": result.get("fallback_reason"),
            "fallback_detail": result.get("fallback_detail"),
        }
    except Exception as exc:
        _update_agent_run_safe(db, repo, getattr(run, "id", None), "failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Agent run failed: {exc}")


@router.post("/agents/run-phase")
def run_workspace_agent_phase(
    payload: dict,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    opp_id = payload.get("opportunity_id")
    phase = payload.get("phase")
    opp = _get_opp_scoped(db, opp_id, organization_id=getattr(current_org, "id", None))
    if phase not in PHASE_AGENT_MAP:
        raise HTTPException(status_code=400, detail="Unsupported phase")

    results = []
    for agent_key in PHASE_AGENT_MAP[phase]:
        repo, run = _create_agent_run_safe(db, opp.id, agent_key, extra_input={"phase": phase})
        try:
            result = _run_workspace_agent_for_user(agent_key, opp, db, getattr(current_user, "id", None))
            _update_agent_run_safe(
                db,
                repo,
                getattr(run, "id", None),
                "success",
                output=result.get("output"),
                model_name=result.get("model_name"),
            )
            results.append({
                "run_id": getattr(run, "id", None),
                "agent_key": agent_key,
                "status": "success",
                "artifact": result.get("artifact"),
                "output": result.get("output"),
                "model_name": result.get("model_name") or "workspace_phased_agent",
                "persisted_run": bool(run),
                "provider_status": result.get("provider_status"),
                "fallback_reason": result.get("fallback_reason"),
                "fallback_detail": result.get("fallback_detail"),
            })
        except Exception as exc:
            _update_agent_run_safe(db, repo, getattr(run, "id", None), "failed", error=str(exc))
            results.append({
                "run_id": getattr(run, "id", None),
                "agent_key": agent_key,
                "status": "failed",
                "error": str(exc),
                "persisted_run": bool(run),
            })

    return {
        "status": "completed",
        "phase": phase,
        "results": results,
    }


@router.post("/parse")
def workspace_parse(
    payload: dict,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    opp_id = payload.get("opportunity_id")
    opp = _get_opp_scoped(db, opp_id, organization_id=getattr(current_org, "id", None))
    enrichment = None

    if (opp.source or "").upper() == "DIBBS":
        enrichment = enrich_dibbs_opportunity(
            db,
            opp,
            debug=bool(payload.get("debug", False)),
            auto_seed_approved_sources=True,
        )
        db.refresh(opp)

    parsed = ensure_parsed(db, opp)

    lead_sync = None
    provider_sync = None
    try:
        lead_sync = sync_vendor_leads_from_parsed(db, opp)
        provider_sync = seed_vendor_leads_from_providers(
            db,
            opp,
            parsed=parsed,
            organization_id=getattr(current_org, "id", None),
            user_id=getattr(current_user, "id", None),
        )
    except Exception:
        lead_sync = None
        provider_sync = None

    return {
        "status": "parsed",
        "opportunity_id": opp.id,
        "display_title": getattr(opp, "display_title", opp.title),
        "parsed": parsed,
        "enrichment": enrichment,
        "lead_sync": lead_sync,
        "provider_sync": provider_sync,
    }


@router.post("/intake/run")
def run_workspace_intake(payload: dict, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    opp_id = payload.get("opportunity_id")
    _get_opp_scoped(db, opp_id, organization_id=getattr(current_org, "id", None))
    return run_opportunity_intake_pipeline(
        db,
        int(opp_id),
        organization_id=getattr(current_org, "id", None),
        download_documents=bool(payload.get("download_documents", True)),
        run_usaspending=bool(payload.get("run_usaspending", True)),
    )


@router.post("/generate/checklist")
def generate_checklist_route(payload: GenerateIn, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    opp_id = payload.opportunity_id
    opp = _get_opp_scoped(db, opp_id, organization_id=getattr(current_org, "id", None))
    artifact = generate_checklist(db, opp)
    return {
        "status": "checklist_generated",
        "opportunity_id": opp.id,
        "display_title": getattr(opp, "display_title", opp.title),
        "artifact": {
            "id": artifact.id,
            "artifact_type": artifact.artifact_type,
            "title": artifact.title,
            "content_json": artifact.content_json,
        },
    }


@router.post("/generate/vendors")
def generate_vendors(
    payload: dict,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    opp_id = payload.get("opportunity_id")
    opp = _get_opp_scoped(db, opp_id, organization_id=getattr(current_org, "id", None))
    parsed = ensure_parsed(db, opp)
    seed_result = None
    if (opp.source or "").upper() == "DIBBS":
        enrichment = enrich_dibbs_opportunity(
            db,
            opp,
            debug=bool(payload.get("debug", False)),
            auto_seed_approved_sources=True,
        )
        seed_result = enrichment.get("approved_source_seed") if isinstance(enrichment, dict) else None

    provider_pdf_sync = extract_providers_from_opportunity_pdfs(
        db,
        opp,
        enrich_with_sam=True,
        organization_id=getattr(current_org, "id", None),
        user_id=getattr(current_user, "id", None),
    )
    lead_sync = sync_vendor_leads_from_parsed(db, opp)
    provider_sync = seed_vendor_leads_from_providers(
        db,
        opp,
        parsed=parsed,
        organization_id=getattr(current_org, "id", None),
        user_id=getattr(current_user, "id", None),
    )
    discovery = discover_vendors_for_opportunity(opp.id, db)
    artifact = generate_vendor_shortlist(db, opp)

    return {
        "status": "vendors_generated",
        "opportunity_id": opp.id,
        "display_title": getattr(opp, "display_title", opp.title),
        "parsed": {
            "approved_source_count": len((parsed or {}).get("approved_sources") or []),
            "cage_codes": (parsed or {}).get("cage_codes") or [],
            "part_numbers": (parsed or {}).get("part_numbers") or [],
        },
        "seed_result": seed_result,
        "lead_sync": lead_sync,
        "provider_pdf_sync": provider_pdf_sync,
        "provider_sync": provider_sync,
        "discovery": discovery,
        "artifact": {
            "id": artifact.id,
            "title": artifact.title,
            "artifact_type": artifact.artifact_type,
        },
    }


@router.post("/generate/email")
def generate_email(payload: GenerateIn, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    opp_id = payload.opportunity_id
    opp = _get_opp_scoped(db, opp_id, organization_id=getattr(current_org, "id", None))
    artifact = generate_quote_email(db, opp)
    return {
        "status": "email_generated",
        "opportunity_id": opp.id,
        "display_title": getattr(opp, "display_title", opp.title),
        "artifact": {
            "id": artifact.id,
            "artifact_type": artifact.artifact_type,
            "title": artifact.title,
            "content_json": artifact.content_json,
        },
    }


@router.post("/generate/co-email")
def generate_co_email(payload: GenerateIn, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    opp_id = payload.opportunity_id
    opp = _get_opp_scoped(db, opp_id, organization_id=getattr(current_org, "id", None))
    artifact = generate_contracting_officer_email(db, opp)
    return {
        "status": "co_email_generated",
        "opportunity_id": opp.id,
        "display_title": getattr(opp, "display_title", opp.title),
        "artifact": {
            "id": artifact.id,
            "artifact_type": artifact.artifact_type,
            "title": artifact.title,
            "content_json": artifact.content_json,
        },
    }


@router.post("/generate/research-brief")
def generate_research_brief_route(payload: GenerateIn, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    opp_id = payload.opportunity_id
    opp = _get_opp_scoped(db, opp_id, organization_id=getattr(current_org, "id", None))
    artifact = generate_research_brief(db, opp)
    return {
        "status": "research_brief_generated",
        "opportunity_id": opp.id,
        "display_title": getattr(opp, "display_title", opp.title),
        "artifact": _artifact_payload(artifact),
    }


@router.post("/generate/submission-package")
def generate_submission_package_route(payload: GenerateIn, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    opp_id = payload.opportunity_id
    opp = _get_opp_scoped(db, opp_id, organization_id=getattr(current_org, "id", None))
    artifact = generate_submission_package(db, opp)
    return {
        "status": "submission_package_generated",
        "opportunity_id": opp.id,
        "display_title": getattr(opp, "display_title", opp.title),
        "artifact": _artifact_payload(artifact),
    }


@router.get("/vendors/usaspending")
def workspace_usaspending_vendors(opp_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    opp = _get_opp_scoped(db, opp_id, organization_id=getattr(current_org, "id", None))
    try:
        return search_usaspending_for_opportunity(opp, db=db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"USAspending workspace research failed: {exc}")


@router.post("/vendors/usaspending/seed")
def workspace_seed_usaspending_vendors(payload: dict, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    opp_id = payload.get("opportunity_id")
    seed_mode = payload.get("seed_mode") or "product_only"
    opp = _get_opp_scoped(db, opp_id, organization_id=getattr(current_org, "id", None))
    research = search_usaspending_for_opportunity(opp, db=db)
    return seed_usaspending_vendors_into_leads(db=db, opp=opp, research_result=research, seed_mode=seed_mode)


@router.get("/intelligence/nsn")
def workspace_get_nsn_intelligence(opp_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    opp = _get_opp_scoped(db, opp_id, organization_id=getattr(current_org, "id", None))
    return get_nsn_intelligence(db, opp)


@router.post("/intelligence/nsn/run")
def workspace_run_nsn_intelligence(payload: dict, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    opp_id = payload.get("opportunity_id")
    seed_awardees = bool(payload.get("seed_awardees", True))
    opp = _get_opp_scoped(db, opp_id, organization_id=getattr(current_org, "id", None))
    try:
        summary = run_nsn_intelligence(db, opp, seed_awardees=seed_awardees, create_summary_artifact=True)
        generate_submission_package(db, opp)
        return summary
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"NSN intelligence failed: {exc}")


@router.post("/generate/email-targeted")
def generate_targeted_email(payload: dict, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    opp_id = payload.get("opportunity_id")
    opp = _get_opp_or_404(db, opp_id, organization_id=getattr(current_org, "id", None))
    vendor_lead_id = payload.get("vendor_lead_id")
    vendor_quote_id = payload.get("vendor_quote_id")
    vendor_name = payload.get("vendor_name")
    vendor_email = payload.get("vendor_email")

    if vendor_lead_id is not None or vendor_quote_id is not None:
        draft = generate_quote_request_email(
            opportunity_id=opp.id,
            db=db,
            vendor_quote_id=vendor_quote_id,
            vendor_lead_id=vendor_lead_id,
        )
    else:
        solicitation = getattr(opp, "solicitation_number", "") or ""
        title = getattr(opp, "display_title", None) or getattr(opp, "title", "") or ""
        agency = getattr(opp, "agency", "") or ""
        draft = {
            "to": vendor_email,
            "company_name": vendor_name,
            "subject": f"Quote Request: {solicitation} {title}".strip(),
            "body": (
                f"Hello {vendor_name or 'Team'},\n\n"
                "We are reaching out regarding the following opportunity:\n\n"
                f"Solicitation: {solicitation or 'Please confirm'}\n"
                f"Title: {title or 'Opportunity'}\n"
                f"Agency: {agency or 'Agency unavailable'}\n"
                f"Due Date: {getattr(opp, 'due_at', None).isoformat() if getattr(opp, 'due_at', None) else 'Please confirm current deadline'}\n"
                f"Opportunity URL: {getattr(opp, 'url', '') or 'Available on request'}\n\n"
                "Please provide pricing, lead time, and any relevant part or availability information.\n\n"
                "Thank you,\n"
                "[Your Name]\n"
                "[Your Company]\n"
                "[Phone]\n"
                "[Email]\n"
            ),
        }

    artifact = create_artifact(
        db,
        opp.id,
        "EMAIL_DRAFT",
        f"Vendor Email Draft - {vendor_name or draft.get('company_name') or opp.solicitation_number or opp.id}",
        content_json={
            **draft,
            "target_vendor_name": vendor_name or draft.get("company_name"),
            "target_vendor_email": vendor_email or draft.get("to"),
            "vendor_lead_id": vendor_lead_id,
            "vendor_quote_id": vendor_quote_id,
            "generated_from": "workspace_targeted_outreach",
            "_meta": {
                "artifact_type": "EMAIL_DRAFT",
                "artifact_category": "OUTREACH",
                "artifact_subtype": "TARGETED_VENDOR_EMAIL",
                "artifact_status": "DRAFT",
            },
            "_outreach_log": [
                {
                    "action": "draft_created",
                    "timestamp": datetime.utcnow().isoformat(),
                    "recipient": vendor_email or draft.get("to"),
                    "vendor_name": vendor_name or draft.get("company_name"),
                }
            ],
        },
    )
    return {
        "status": "email_generated",
        "opportunity_id": opp.id,
        "artifact": _artifact_payload(artifact),
    }


@router.post("/vendors/promote")
def promote_workspace_vendor(payload: dict, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    opp_id = payload.get("opportunity_id")
    lead_id = payload.get("vendor_lead_id")
    org_id = getattr(current_org, "id", None)
    opp = _get_opp_scoped(db, opp_id, organization_id=org_id)
    promoted = promote_vendor_lead_to_quote_request(db, opp.id, lead_id, organization_id=org_id)

    task = WorkspaceTask(
        organization_id=org_id,
        opportunity_id=opp.id,
        task_type="REQUEST_QUOTE",
        status="OPEN",
        notes=f"Request quote from {promoted.get('company_name') or promoted.get('cage') or 'vendor lead'}",
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    return {
        "status": "promoted",
        "lead": promoted,
        "task": {
            "id": task.id,
            "task_type": task.task_type,
            "status": task.status,
            "notes": task.notes,
        },
    }


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(opp_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    org_id = getattr(current_org, "id", None)
    _get_opp_scoped(db, opp_id, organization_id=org_id)
    query = db.query(WorkspaceTask).filter(WorkspaceTask.opportunity_id == opp_id)
    if org_id is not None:
        query = query.filter(WorkspaceTask.organization_id == org_id)
    return query.order_by(WorkspaceTask.created_at.desc()).all()


@router.post("/tasks", response_model=TaskOut)
def create_task(payload: dict, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    opp_id = payload.get("opportunity_id")
    org_id = getattr(current_org, "id", None)
    _get_opp_scoped(db, opp_id, organization_id=org_id)
    item = TaskCreate(
        task_type=payload.get("task_type") or "FOLLOW_UP",
        due_at=payload.get("due_at"),
        notes=payload.get("notes"),
    )
    rec = WorkspaceTask(
        organization_id=org_id,
        opportunity_id=opp_id,
        task_type=item.task_type,
        status="OPEN",
        due_at=item.due_at,
        notes=item.notes,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    org_id = getattr(current_org, "id", None)
    rec = db.query(WorkspaceTask).filter(WorkspaceTask.id == task_id)
    if org_id is not None:
        rec = rec.filter(WorkspaceTask.organization_id == org_id)
    rec = rec.first()
    if not rec:
        raise HTTPException(status_code=404, detail="Task not found")
    patch = payload.model_dump(exclude_unset=True)
    for key, value in patch.items():
        setattr(rec, key, value)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


@router.patch("/artifacts/{artifact_id}", response_model=ArtifactOut)
def update_artifact(artifact_id: int, payload: ArtifactUpdate, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    org_id = getattr(current_org, "id", None)
    rec = db.query(WorkspaceArtifact).filter(WorkspaceArtifact.id == artifact_id)
    if org_id is not None:
        rec = rec.filter(WorkspaceArtifact.organization_id == org_id)
    rec = rec.first()
    if not rec:
        raise HTTPException(status_code=404, detail="Artifact not found")
    current_content = dict(rec.content_json or {})
    history = list(current_content.get("_history") or [])
    current_snapshot = {
        "title": rec.title,
        "content_json": {k: v for k, v in current_content.items() if k not in {"_history"}},
        "timestamp": datetime.utcnow().isoformat(),
        "action": "updated",
    }
    patch = payload.model_dump(exclude_unset=True)
    for key, value in patch.items():
        setattr(rec, key, value)
    if patch:
        next_content = dict(rec.content_json or {})
        history.append(current_snapshot)
        next_content["_history"] = history[-20:]
        next_content.setdefault("_meta", {})
        next_content["_meta"]["artifact_status"] = next_content["_meta"].get("artifact_status") or "ACTIVE"
        rec.content_json = next_content
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


@router.get("/artifacts/{artifact_id}/versions")
def artifact_versions(artifact_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    org_id = getattr(current_org, "id", None)
    rec = db.query(WorkspaceArtifact).filter(WorkspaceArtifact.id == artifact_id)
    if org_id is not None:
        rec = rec.filter(WorkspaceArtifact.organization_id == org_id)
    rec = rec.first()
    if not rec:
        raise HTTPException(status_code=404, detail="Artifact not found")
    content = dict(rec.content_json or {})
    return {
        "artifact_id": rec.id,
        "title": rec.title,
        "versions": list(content.get("_history") or []),
    }


@router.get("/artifacts/{artifact_id}/compare")
def artifact_compare(artifact_id: int, version_index: int = 0, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    org_id = getattr(current_org, "id", None)
    rec = db.query(WorkspaceArtifact).filter(WorkspaceArtifact.id == artifact_id)
    if org_id is not None:
        rec = rec.filter(WorkspaceArtifact.organization_id == org_id)
    rec = rec.first()
    if not rec:
        raise HTTPException(status_code=404, detail="Artifact not found")
    content = dict(rec.content_json or {})
    versions = list(content.get("_history") or [])
    if version_index < 0 or version_index >= len(versions):
        raise HTTPException(status_code=404, detail="Artifact version not found")
    target = versions[version_index]
    return {
        "artifact_id": rec.id,
        "current": {
            "title": rec.title,
            "content_json": content,
        },
        "version": target,
    }


@router.post("/artifacts/{artifact_id}/restore")
def restore_artifact_version(artifact_id: int, payload: dict, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    org_id = getattr(current_org, "id", None)
    rec = db.query(WorkspaceArtifact).filter(WorkspaceArtifact.id == artifact_id)
    if org_id is not None:
        rec = rec.filter(WorkspaceArtifact.organization_id == org_id)
    rec = rec.first()
    if not rec:
        raise HTTPException(status_code=404, detail="Artifact not found")
    content = dict(rec.content_json or {})
    versions = list(content.get("_history") or [])
    version_index = int(payload.get("version_index", -1))
    if version_index < 0 or version_index >= len(versions):
        raise HTTPException(status_code=404, detail="Artifact version not found")

    target = versions[version_index]
    current_snapshot = {
        "title": rec.title,
        "content_json": {k: v for k, v in content.items() if k not in {"_history"}},
        "timestamp": datetime.utcnow().isoformat(),
        "action": "restore_checkpoint",
    }
    versions.append(current_snapshot)
    restored_content = dict(target.get("content_json") or {})
    restored_content["_history"] = versions[-20:]
    restored_content.setdefault("_meta", {})
    restored_content["_meta"]["artifact_status"] = restored_content["_meta"].get("artifact_status") or "ACTIVE"
    rec.title = target.get("title") or rec.title
    rec.content_json = restored_content
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return {"artifact": _artifact_payload(rec)}


@router.post("/artifacts/{artifact_id}/outreach-log")
def log_artifact_outreach(artifact_id: int, payload: dict, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    org_id = getattr(current_org, "id", None)
    rec = db.query(WorkspaceArtifact).filter(WorkspaceArtifact.id == artifact_id)
    if org_id is not None:
        rec = rec.filter(WorkspaceArtifact.organization_id == org_id)
    rec = rec.first()
    if not rec:
        raise HTTPException(status_code=404, detail="Artifact not found")

    content = dict(rec.content_json or {})
    log = list(content.get("_outreach_log") or [])
    action = payload.get("action") or "logged"
    recipient = payload.get("recipient") or content.get("target_vendor_email") or content.get("to")
    vendor_name = payload.get("vendor_name") or content.get("target_vendor_name") or content.get("company_name")
    entry = {
        "action": action,
        "timestamp": datetime.utcnow().isoformat(),
        "recipient": recipient,
        "vendor_name": vendor_name,
        "notes": payload.get("notes"),
    }
    log.append(entry)
    content["_outreach_log"] = log[-30:]
    content.setdefault("_meta", {})
    if action.lower() == "sent":
        content["_meta"]["artifact_status"] = "SENT"
    elif action.lower() == "draft_saved":
        content["_meta"]["artifact_status"] = "DRAFT"
    rec.content_json = content
    db.add(rec)
    quote_status_sync = sync_quote_status_from_outreach_artifact(db, rec, action, organization_id=org_id)
    db.commit()
    db.refresh(rec)

    return {
        "artifact": _artifact_payload(rec),
        "mailto_url": f"mailto:{recipient or ''}?subject={content.get('subject') or ''}",
        "quote_status_sync": quote_status_sync,
    }


@router.post("/artifacts/{artifact_id}/send")
def send_artifact_email(artifact_id: int, payload: dict | None = None, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    org_id = getattr(current_org, "id", None)
    rec = db.query(WorkspaceArtifact).filter(WorkspaceArtifact.id == artifact_id)
    if org_id is not None:
        rec = rec.filter(WorkspaceArtifact.organization_id == org_id)
    rec = rec.first()
    if not rec:
        raise HTTPException(status_code=404, detail="Artifact not found")

    content = dict(rec.content_json or {})
    recipient = (payload or {}).get("recipient") or content.get("target_vendor_email") or content.get("to")
    subject = (payload or {}).get("subject") or content.get("subject")
    body = (payload or {}).get("body") or content.get("body")
    vendor_name = (payload or {}).get("vendor_name") or content.get("target_vendor_name") or content.get("company_name")

    if not recipient or not subject or not body:
        raise HTTPException(status_code=400, detail="Email artifact is missing recipient, subject, or body")

    try:
        send_result = send_email_message(recipient, subject, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Email send failed: {exc}")

    log = list(content.get("_outreach_log") or [])
    log.append({
        "action": "sent",
        "timestamp": datetime.utcnow().isoformat(),
        "recipient": recipient,
        "vendor_name": vendor_name,
        "notes": "smtp_send",
    })
    content["_outreach_log"] = log[-30:]
    content.setdefault("_meta", {})
    content["_meta"]["artifact_status"] = "SENT"
    rec.content_json = content
    db.add(rec)
    quote_status_sync = sync_quote_status_from_outreach_artifact(db, rec, "sent", organization_id=org_id)
    db.commit()
    db.refresh(rec)

    return {
        "artifact": _artifact_payload(rec),
        "send_result": send_result,
        "quote_status_sync": quote_status_sync,
    }
