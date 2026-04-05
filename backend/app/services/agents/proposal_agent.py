from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.company import CompanyRepository
from app.services.opportunities.query import get_opportunity_workspace


def _select_relevant_past_performance(past_perf: list[dict[str, Any]], workspace: dict[str, Any]) -> list[dict[str, Any]]:
    opp = workspace.get("opportunity") or {}
    naics = (opp.get("naics") or opp.get("naics_code") or "").strip()
    title_desc = f'{opp.get("title") or ""} {opp.get("description") or ""}'.lower()

    scored = []
    for rec in past_perf:
        score = 0
        if naics and rec.get("naics_code") == naics:
            score += 3
        for tag in rec.get("relevance_tags") or []:
            if str(tag).lower() in title_desc:
                score += 1
        scored.append((score, rec))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:5]]


def _build_prompt(workspace: dict[str, Any], company_profile: dict[str, Any] | None, past_perf: list[dict[str, Any]]) -> str:
    opp = workspace.get("opportunity") or {}
    pipeline = workspace.get("pipeline_item") or {}
    vendors = workspace.get("vendor_matches") or []
    quotes = workspace.get("quotes") or []
    documents = workspace.get("documents") or []

    compact = {
        "opportunity": {
            "title": opp.get("title"),
            "solicitation_number": opp.get("solicitation_number"),
            "agency": opp.get("agency"),
            "source": opp.get("source"),
            "naics": opp.get("naics") or opp.get("naics_code"),
            "fsc": opp.get("fsc") or opp.get("fsc_code"),
            "due_at": opp.get("due_at"),
            "description": opp.get("description"),
            "parsed_json": opp.get("parsed_json"),
            "ai_summary": opp.get("ai_summary"),
        },
        "pipeline": pipeline,
        "company_profile": company_profile,
        "past_performance": past_perf,
        "vendors": vendors[:10],
        "quotes": quotes[:10],
        "documents": [
            {
                "filename": d.get("filename"),
                "file_type": d.get("file_type"),
                "extracted_text": (d.get("extracted_text") or "")[:6000],
            }
            for d in documents[:5]
        ],
    }

    return f"""
You are an expert government contracting proposal assistant.

Use the workspace data, company profile, and past performance records below to generate practical first-draft proposal support content.
Be specific, concise, and businesslike. Do not invent facts not supported by the input.
Where information is missing, say so clearly.

Return valid JSON with exactly these keys:
- executive_summary
- differentiators_section
- past_performance_section
- compliance_matrix_starter
- vendor_outreach_email
- pricing_notes
- risks_and_gaps

Workspace data:
{json.dumps(compact, indent=2, default=str)}
""".strip()


def _store_agent_run(db: Session, opportunity_id: int, prompt: str, output_payload: dict[str, Any], model_name: str) -> None:
    from app.repositories.agents import AgentRunRepository
    from app.schemas.agent import AgentRunCreate

    AgentRunRepository(db).create(
        AgentRunCreate(
            opportunity_id=opportunity_id,
            agent_type="proposal_assistance",
            input_payload={"prompt": prompt},
            output_payload=output_payload,
            status="success",
            model_name=model_name,
        )
    )


def generate_proposal_draft(opportunity_id: int, db: Session) -> dict[str, Any]:
    workspace = get_opportunity_workspace(opportunity_id, db)
    if not workspace:
        raise ValueError("Workspace not found")

    api_key = getattr(settings, "OPENAI_API_KEY", None)
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    company_repo = CompanyRepository(db)
    profile_rec = company_repo.get_first_profile()
    profile = None
    past_perf = []
    if profile_rec:
        profile = {
            "id": profile_rec.id,
            "legal_name": profile_rec.legal_name,
            "uei": profile_rec.uei,
            "cage": profile_rec.cage,
            "naics_codes": profile_rec.naics_codes,
            "certifications": profile_rec.certifications,
            "capability_statement_url": profile_rec.capability_statement_url,
            "core_competencies": profile_rec.core_competencies,
            "differentiators": profile_rec.differentiators,
            "past_performance_summary": profile_rec.past_performance_summary,
            "annual_revenue": profile_rec.annual_revenue,
        }
        past_perf_rows = company_repo.list_past_performance(profile_rec.id)
        raw_perf = [
            {
                "id": p.id,
                "client_name": p.client_name,
                "project_title": p.project_title,
                "project_value": p.project_value,
                "start_date": p.start_date.isoformat() if p.start_date else None,
                "end_date": p.end_date.isoformat() if p.end_date else None,
                "description": p.description,
                "naics_code": p.naics_code,
                "relevance_tags": p.relevance_tags,
            }
            for p in past_perf_rows
        ]
        past_perf = _select_relevant_past_performance(raw_perf, workspace)

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    model_name = getattr(settings, "OPENAI_PROPOSAL_MODEL", "gpt-4o-mini")

    prompt = _build_prompt(workspace, profile, past_perf)

    response = client.chat.completions.create(
        model=model_name,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You write draft GovCon proposal support content."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )

    raw = response.choices[0].message.content or "{}"
    try:
        output_payload = json.loads(raw)
    except Exception:
        output_payload = {
            "executive_summary": raw,
            "differentiators_section": "",
            "past_performance_section": "",
            "compliance_matrix_starter": "",
            "vendor_outreach_email": "",
            "pricing_notes": "",
            "risks_and_gaps": "",
        }

    _store_agent_run(db, opportunity_id, prompt, output_payload, model_name)
    return {
        "opportunity_id": opportunity_id,
        "model": model_name,
        "drafts": output_payload,
    }
