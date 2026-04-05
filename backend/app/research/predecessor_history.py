from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity


def _extract_dibbs_value(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        return qs.get("value", [None])[0]
    except Exception:
        return None


def _norm(text: str | None) -> str:
    return (text or "").strip().lower()


def _title_tokens(title: str | None) -> set[str]:
    text = _norm(title)
    raw = text.replace(",", " ").replace("-", " ").split()
    stop = {"the", "and", "for", "with", "dental", "dent", "item", "kit", "type", "assembly"}
    return {t for t in raw if len(t) > 2 and t not in stop}


def _title_overlap_score(a: str | None, b: str | None) -> float:
    ta = _title_tokens(a)
    tb = _title_tokens(b)
    if not ta or not tb:
        return 0.0
    overlap = ta.intersection(tb)
    union = ta.union(tb)
    return len(overlap) / max(len(union), 1)


def find_predecessor_opportunities(db: Session, opportunity_id: int):
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        return []

    opp_nsn = getattr(opp, "nsn", None)
    opp_fsc = getattr(opp, "fsc", None) or getattr(opp, "fsc_code", None)
    opp_url_value = _extract_dibbs_value(getattr(opp, "url", None))
    opp_title = getattr(opp, "title", None)

    candidates = db.query(Opportunity).filter(Opportunity.id != opportunity_id).order_by(Opportunity.id.desc()).limit(300).all()

    scored = []
    for p in candidates:
        p_nsn = getattr(p, "nsn", None)
        p_fsc = getattr(p, "fsc", None) or getattr(p, "fsc_code", None)
        p_url_value = _extract_dibbs_value(getattr(p, "url", None))
        p_title = getattr(p, "title", None)

        score = 0
        reasons = []

        if opp_nsn and p_nsn and opp_nsn == p_nsn:
            score += 100
            reasons.append("same_nsn")
        if opp_url_value and p_url_value and opp_url_value == p_url_value:
            score += 90
            reasons.append("same_dibbs_value")

        overlap = _title_overlap_score(opp_title, p_title)
        if overlap >= 0.60:
            score += 40
            reasons.append(f"title_overlap={overlap:.2f}")
        elif overlap >= 0.30:
            score += 20
            reasons.append(f"title_overlap={overlap:.2f}")

        if opp_fsc and p_fsc and opp_fsc == p_fsc:
            score += 5
            reasons.append("same_fsc")

        if score >= 20:
            scored.append({
                "id": p.id,
                "solicitation_number": p.solicitation_number,
                "title": p.title,
                "agency": p.agency,
                "nsn": p_nsn,
                "fsc": p_fsc,
                "url": p.url,
                "dibbs_value": p_url_value,
                "match_score": score,
                "match_reasons": reasons,
            })

    scored.sort(key=lambda x: (-x["match_score"], -x["id"]))
    return scored[:20]
