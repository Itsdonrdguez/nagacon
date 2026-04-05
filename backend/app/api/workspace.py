from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.opportunity import Opportunity
from app.models.opportunity import OpportunityAnalysis
from app.repositories.vendor_matches import VendorMatchRepository
from app.utils.title_normalizer import build_summary_text

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


def _get_opp_or_404(db: Session, opp_id: int) -> Opportunity:
    opp = db.query(Opportunity).filter(Opportunity.id == opp_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return opp


@router.get("/summary")
def workspace_summary(opp_id: int, db: Session = Depends(get_db)):
    opp = _get_opp_or_404(db, opp_id)

    try:
        analysis = db.query(OpportunityAnalysis).filter(OpportunityAnalysis.opportunity_id == opp_id).first()
    except Exception:
        analysis = None

    try:
        vendor_matches = VendorMatchRepository(db).list_by_opportunity_id(opp_id)
    except Exception:
        vendor_matches = []

    vendor_matches = [
        {
            "id": getattr(v, "id", None),
            "vendor_id": getattr(v, "vendor_id", None),
            "opportunity_id": getattr(v, "opportunity_id", None),
            "match_reason": getattr(v, "match_reason", None),
            "confidence_score": getattr(v, "confidence_score", None),
            "source": getattr(v, "source", None),
        } if not isinstance(v, dict) else v
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
        "fsc": getattr(opp, "fsc", None),
        "set_aside": getattr(opp, "set_aside", None),
        "summary": getattr(opp, "summary_text", None) or build_summary_text(opp.raw_text, opp.parsed_json, opp.raw_payload),
        "description": getattr(opp, "description", None),
        "raw_text": getattr(opp, "raw_text", None),
        "parsed_json": getattr(opp, "parsed_json", None),
        "raw_payload": getattr(opp, "raw_payload", None),
        "workspace_url": getattr(opp, "workspace_url", None),
    }

    actions = [
        "Parse Opportunity",
        "Generate Checklist",
        "Generate Vendor Shortlist",
        "Generate Quote Email",
        "Research via USAspending",
    ]

    return {
        "opportunity": opportunity_payload,
        "analysis": {
            "priority_score": getattr(analysis, "priority_score", 0) if analysis else 0,
            "risk_flags": getattr(analysis, "risk_flags", []) if analysis else [],
            "fit_score": getattr(analysis, "fit_score", 0) if analysis else 0,
            "ai_summary": getattr(analysis, "ai_summary", None) if analysis else None,
        },
        "vendor_matches": vendor_matches,
        "artifacts": [],
        "tasks": [],
        "files": [],
        "quotes": [],
        "agent_runs": [],
        "pipeline_item": None,
        "actions": actions,
        "ui_hints": {
            "source_badge": opp.source,
            "empty_vendors_message": "No vendor matches yet. Use USAspending research or vendor discovery next.",
            "empty_artifacts_message": "No artifacts yet. Parse the opportunity or generate a checklist.",
        },
    }


@router.post("/parse")
def workspace_parse(payload: dict, db: Session = Depends(get_db)):
    opp_id = payload.get("opportunity_id")
    opp = _get_opp_or_404(db, opp_id)
    return {"status": "parsed", "opportunity_id": opp.id, "display_title": getattr(opp, "display_title", opp.title)}


@router.post("/generate/checklist")
def generate_checklist(payload: dict, db: Session = Depends(get_db)):
    opp_id = payload.get("opportunity_id")
    opp = _get_opp_or_404(db, opp_id)
    return {"status": "checklist_generated", "opportunity_id": opp.id, "display_title": getattr(opp, "display_title", opp.title)}


@router.post("/generate/vendors")
def generate_vendors(payload: dict, db: Session = Depends(get_db)):
    opp_id = payload.get("opportunity_id")
    opp = _get_opp_or_404(db, opp_id)
    return {"status": "vendors_generated", "opportunity_id": opp.id, "display_title": getattr(opp, "display_title", opp.title)}


@router.post("/generate/email")
def generate_email(payload: dict, db: Session = Depends(get_db)):
    opp_id = payload.get("opportunity_id")
    opp = _get_opp_or_404(db, opp_id)
    return {"status": "email_generated", "opportunity_id": opp.id, "display_title": getattr(opp, "display_title", opp.title)}
