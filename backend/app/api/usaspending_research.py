
from fastapi import APIRouter
from app.services.research.usaspending_research import search_similar_awards

router = APIRouter(prefix="/api/research/usaspending", tags=["Research"])

@router.post("/opportunities/{opportunity_id}")
def research_opportunity(opportunity_id: int):
    # Placeholder — normally you'd pull NAICS, agency, keywords from DB
    naics = "339112"
    agency = "Department of Defense"
    keywords = "medical"

    awards = search_similar_awards(naics=naics, agency=agency, keywords=keywords)

    vendors = {}
    for a in awards:
        name = a.get("Recipient Name")
        vendors.setdefault(name, 0)
        vendors[name] += 1

    ranked = sorted(
        [{"vendor": k, "award_count": v} for k, v in vendors.items()],
        key=lambda x: x["award_count"],
        reverse=True
    )

    return {
        "opportunity_id": opportunity_id,
        "awards_found": len(awards),
        "likely_vendors": ranked[:25],
        "awards": awards[:20]
    }
