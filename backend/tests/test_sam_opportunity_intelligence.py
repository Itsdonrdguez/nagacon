from __future__ import annotations

from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from app.services.sam_opportunity_intelligence import build_sam_opportunity_intelligence


def test_build_sam_opportunity_intelligence_handles_timezone_aware_due_date():
    opp = SimpleNamespace(
        title="Janitorial Services",
        agency="GSA",
        due_at=datetime.now(timezone.utc) + timedelta(days=2),
        naics_code="561720",
        set_aside_type="SBA",
        place_of_performance="VA",
        raw_payload={"resourceLinks": ["https://example.com/doc.pdf"]},
        raw_text="Offerors shall submit a capability statement and proposal.",
    )

    result = build_sam_opportunity_intelligence(opp)

    assert result["summary"]
    assert "Response window is extremely short." in result["risk_flags"]
    assert result["requirements"]
