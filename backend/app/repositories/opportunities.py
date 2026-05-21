from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.schemas.opportunity import OpportunityCreate, OpportunityUpdate
from app.utils.exceptions import DuplicateRecordError
from app.utils.opportunity_lifecycle import ARCHIVE_CUTOFF_DAYS
from app.utils.set_asides import normalize_set_aside, set_aside_display_label
from app.utils.utc import utcnow


class OpportunityRepository:
    def __init__(self, db: Session, organization_id: int | None = None):
        self.db = db
        self.organization_id = organization_id

    def _scoped_query(self):
        query = self.db.query(Opportunity)
        if self.organization_id is not None:
            query = query.filter(Opportunity.organization_id == self.organization_id)
        return query

    def _parse_legacy_dibbs_date(self, value: str | None):
        text = str(value or "").strip()
        if not text:
            return None
        for fmt in ("%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None

    def _backfill_dibbs_dates(self, items: list[Opportunity]) -> list[Opportunity]:
        changed = False
        for opp in items:
            if opp.source != "DIBBS" or opp.due_at is not None:
                continue
            raw_payload = opp.raw_payload or {}
            if not isinstance(raw_payload, dict):
                continue
            dibbs_detail = raw_payload.get("dibbs_detail") or {}
            if not isinstance(dibbs_detail, dict):
                continue
            structured = dibbs_detail.get("structured") if isinstance(dibbs_detail.get("structured"), dict) else dibbs_detail
            solicitations = structured.get("solicitations") or []
            first = solicitations[0] if solicitations else {}
            parsed_due = self._parse_legacy_dibbs_date(first.get("return_by_date"))
            parsed_posted = self._parse_legacy_dibbs_date(first.get("issue_date"))
            if parsed_due is not None:
                opp.due_at = parsed_due
                changed = True
            if parsed_posted is not None and opp.posted_at is None:
                opp.posted_at = parsed_posted
                changed = True
        if changed:
            self.db.commit()
            for opp in items:
                self.db.refresh(opp)
        return items

    def get(self, opportunity_id: int) -> Opportunity | None:
        opp = self._scoped_query().filter(Opportunity.id == opportunity_id).first()
        if not opp:
            return None
        return self._backfill_dibbs_dates([opp])[0]

    def get_by_source_id(self, source: str, source_id: str) -> Opportunity | None:
        return (
            self._scoped_query()
            .filter(Opportunity.source == source, Opportunity.source_opportunity_id == source_id)
            .first()
        )

    def get_by_source_and_solicitation(self, source: str, solicitation_number: str) -> Opportunity | None:
        return (
            self._scoped_query()
            .filter(Opportunity.source == source, Opportunity.solicitation_number == solicitation_number)
            .first()
        )

    def find_dedupe_candidates(self, source: str, agency: str | None = None, limit: int = 100) -> list[Opportunity]:
        q = self._scoped_query().filter(Opportunity.source == source)
        if agency:
            q = q.filter(Opportunity.agency == agency)
        return q.order_by(Opportunity.id.desc()).limit(limit).all()

    def _apply_filters(
        self,
        query,
        *,
        q: str | None = None,
        source: str | None = None,
        set_aside_type: str | None = None,
        due_window: str | None = None,
        nsn: str | None = None,
        agency: str | None = None,
        state: str | None = None,
        naics_codes: list[str] | None = None,
        fsc_codes: list[str] | None = None,
    ):
        def _clean_codes(values: list[str] | None) -> list[str]:
            return [str(value or "").strip() for value in (values or []) if str(value or "").strip()]

        if source:
            query = query.filter(Opportunity.source == source)

        set_aside_value = normalize_set_aside(set_aside_type)
        if set_aside_value == "none":
            query = query.filter(or_(Opportunity.set_aside.is_(None), Opportunity.set_aside == ""))
        elif set_aside_value:
            tokens = self.SET_ASIDE_FILTERS.get(set_aside_value)
            if tokens:
                query = query.filter(or_(*[Opportunity.set_aside.ilike(f"%{token}%") for token in tokens]))
            else:
                query = query.filter(Opportunity.set_aside.ilike(f"%{set_aside_value}%"))

        if q:
            pattern = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    Opportunity.title.ilike(pattern),
                    Opportunity.agency.ilike(pattern),
                    Opportunity.solicitation_number.ilike(pattern),
                    Opportunity.naics.ilike(pattern),
                    Opportunity.fsc.ilike(pattern),
                    Opportunity.set_aside.ilike(pattern),
                    Opportunity.place_of_performance.ilike(pattern),
                    Opportunity.raw_text.ilike(pattern),
                )
            )

        if nsn:
            normalized = "".join(ch for ch in str(nsn) if ch.isdigit())
            if normalized:
                compact_db_nsn = (
                    func.replace(
                        func.replace(
                            func.replace(Opportunity.solicitation_number, "-", ""),
                            " ",
                            "",
                        ),
                        ".",
                        "",
                    )
                )
                query = query.filter(compact_db_nsn.ilike(f"%{normalized}%"))
            else:
                query = query.filter(Opportunity.solicitation_number.ilike(f"%{nsn.strip()}%"))

        if agency:
            query = query.filter(Opportunity.agency.ilike(f"%{agency.strip()}%"))

        if state:
            query = query.filter(Opportunity.place_of_performance.ilike(f"%{state.strip()}%"))

        cleaned_naics = _clean_codes(naics_codes)
        if cleaned_naics:
            query = query.filter(Opportunity.naics.in_(cleaned_naics))

        cleaned_fsc = _clean_codes(fsc_codes)
        if cleaned_fsc:
            query = query.filter(Opportunity.fsc.in_(cleaned_fsc))

        if due_window:
            from datetime import datetime, timedelta

            now = utcnow()
            archive_cutoff = now - timedelta(days=ARCHIVE_CUTOFF_DAYS)
            if due_window == "7d":
                query = query.filter(Opportunity.due_at.is_not(None), Opportunity.due_at >= now, Opportunity.due_at <= now + timedelta(days=7))
            elif due_window == "30d":
                query = query.filter(Opportunity.due_at.is_not(None), Opportunity.due_at >= now, Opportunity.due_at <= now + timedelta(days=30))
            elif due_window == "open":
                query = query.filter(or_(Opportunity.due_at.is_(None), Opportunity.due_at >= now))
            elif due_window == "closed":
                query = query.filter(Opportunity.due_at.is_not(None), Opportunity.due_at < now)
            elif due_window == "recently_closed":
                query = query.filter(Opportunity.due_at.is_not(None), Opportunity.due_at < now, Opportunity.due_at >= archive_cutoff)
            elif due_window == "archived":
                query = query.filter(Opportunity.due_at.is_not(None), Opportunity.due_at < archive_cutoff)
            elif due_window == "intelligence":
                query = query.filter(Opportunity.due_at.is_not(None), Opportunity.due_at < now)
            elif due_window == "award_followup":
                query = query.filter(Opportunity.due_at.is_not(None), Opportunity.due_at <= now - timedelta(days=90))

        return query

    def filter_options(self) -> dict:
        query = self._scoped_query()
        set_asides = [
            row[0]
            for row in query.with_entities(Opportunity.set_aside)
            .filter(Opportunity.set_aside.is_not(None), Opportunity.set_aside != "")
            .distinct()
            .order_by(Opportunity.set_aside.asc())
            .limit(200)
            .all()
        ]
        exact_labels = []
        seen_exact = set()
        for item in set_asides:
            value = str(item or "").strip()
            if not value or value in seen_exact:
                continue
            seen_exact.add(value)
            exact_labels.append({"value": value, "label": set_aside_display_label(value) or value})
        sources = [
            row[0]
            for row in self._scoped_query()
            .with_entities(Opportunity.source)
            .filter(Opportunity.source.is_not(None), Opportunity.source != "")
            .distinct()
            .order_by(Opportunity.source.asc())
            .all()
        ]
        return {
            "sources": sources,
            "set_asides": set_asides,
            "set_aside_categories": [
                {"value": "small_business", "label": "Small Business"},
                {"value": "8a", "label": "8(a)"},
                {"value": "sdvosb", "label": "SDVOSB"},
                {"value": "wosb", "label": "WOSB"},
                {"value": "edwosb", "label": "EDWOSB"},
                {"value": "hubzone", "label": "HUBZone"},
                {"value": "veteran", "label": "Veteran-Owned"},
                {"value": "unrestricted", "label": "Full and Open"},
                {"value": "none", "label": "No Set-Aside"},
            ],
            "set_aside_exact_labels": exact_labels,
            "status_filters": [
                {"value": "open", "label": "Active"},
                {"value": "7d", "label": "Closing Soon"},
                {"value": "30d", "label": "Due in 30 Days"},
                {"value": "closed", "label": "Closed / Intelligence"},
                {"value": "recently_closed", "label": "Recently Closed"},
                {"value": "archived", "label": "Archived"},
                {"value": "award_followup", "label": "Award Follow-Up Due"},
                {"value": "all", "label": "All Records"},
            ],
        }

    def list(
        self,
        limit: int = 100,
        offset: int = 0,
        q: str | None = None,
        source: str | None = None,
        set_aside_type: str | None = None,
        due_window: str | None = None,
        nsn: str | None = None,
        agency: str | None = None,
        state: str | None = None,
        naics_codes: list[str] | None = None,
        fsc_codes: list[str] | None = None,
    ) -> list[Opportunity]:
        query = self._apply_filters(
            self._scoped_query(),
            q=q,
            source=source,
            set_aside_type=set_aside_type,
            due_window=due_window,
            nsn=nsn,
            agency=agency,
            state=state,
            naics_codes=naics_codes,
            fsc_codes=fsc_codes,
        )
        items = query.order_by(Opportunity.id.desc()).offset(offset).limit(limit).all()
        return self._backfill_dibbs_dates(items)

    def search(
        self,
        *,
        page: int = 1,
        page_size: int = 25,
        q: str | None = None,
        source: str | None = None,
        set_aside_type: str | None = None,
        due_window: str | None = None,
        nsn: str | None = None,
        agency: str | None = None,
        state: str | None = None,
        naics_codes: list[str] | None = None,
        fsc_codes: list[str] | None = None,
        sort_by: str | None = None,
        sort_order: str = "asc",
    ) -> tuple[list[Opportunity], int]:
        base_query = self._apply_filters(
            self._scoped_query(),
            q=q,
            source=source,
            set_aside_type=set_aside_type,
            due_window=due_window,
            nsn=nsn,
            agency=agency,
            state=state,
            naics_codes=naics_codes,
            fsc_codes=fsc_codes,
        )
        total = base_query.count()
        open_first = case(
            (Opportunity.due_at.is_(None), 1),
            (Opportunity.due_at < utcnow(), 2),
            else_=0,
        )
        sort_map = {
            "due_at": Opportunity.due_at,
            "nsn": Opportunity.solicitation_number,
            "solicitation_number": Opportunity.solicitation_number,
            "title": Opportunity.title,
            "agency": Opportunity.agency,
            "source": Opportunity.source,
            "fsc": Opportunity.fsc,
            "naics": Opportunity.naics,
        }
        sort_column = sort_map.get(str(sort_by or "").strip())
        sort_direction = str(sort_order or "asc").lower()
        if sort_column is not None:
            ordering = sort_column.desc() if sort_direction == "desc" else sort_column.asc()
            order_by = [ordering, Opportunity.id.desc()]
        else:
            order_by = [open_first.asc(), Opportunity.due_at.asc(), Opportunity.id.desc()]
        items = (
            base_query
            .order_by(*order_by)
            .offset(max(page - 1, 0) * page_size)
            .limit(page_size)
            .all()
        )
        return self._backfill_dibbs_dates(items), total

    def create(self, opp: OpportunityCreate) -> Opportunity:
        payload = opp.model_dump()
        db_opp = Opportunity(
            organization_id=self.organization_id,
            source=payload["source"],
            source_opportunity_id=payload.get("source_opportunity_id"),
            solicitation_number=payload.get("solicitation_number") or "",
            title=payload["title"],
            agency=payload.get("agency") or "",
            sub_agency=payload.get("sub_agency"),
            office=payload.get("office"),
            url=(payload.get("url") or "")[:500],
            posted_at=payload.get("posted_at"),
            due_at=payload.get("due_at"),
            naics=payload.get("naics_code"),
            fsc=payload.get("fsc_code"),
            set_aside=payload.get("set_aside_type"),
            place_of_performance=payload.get("place_of_performance"),
            raw_text=payload.get("description"),
            raw_payload=payload.get("raw_payload"),
            status=payload.get("status", "new").value if hasattr(payload.get("status"), "value") else str(payload.get("status", "new")),
        )
        self.db.add(db_opp)
        self.db.commit()
        self.db.refresh(db_opp)
        return db_opp

    def update(self, opportunity_id: int, opp_update: OpportunityUpdate) -> Opportunity | None:
        db_opp = self.get(opportunity_id)
        if not db_opp:
            return None
        update_data = opp_update.model_dump(exclude_unset=True)
        field_map = {
            "source_opportunity_id": "source_opportunity_id",
            "solicitation_number": "solicitation_number",
            "title": "title",
            "agency": "agency",
            "sub_agency": "sub_agency",
            "office": "office",
            "url": "url",
            "posted_at": "posted_at",
            "due_at": "due_at",
            "set_aside_type": "set_aside",
            "naics_code": "naics",
            "fsc_code": "fsc",
            "place_of_performance": "place_of_performance",
            "description": "raw_text",
            "raw_payload": "raw_payload",
            "status": "status",
        }
        for key, value in update_data.items():
            if value is None:
                continue
            attr = field_map.get(key)
            if not attr:
                continue
            if key == "status" and hasattr(value, "value"):
                value = value.value
            setattr(db_opp, attr, value)
        self.db.commit()
        self.db.refresh(db_opp)
        return db_opp

    def upsert(self, opp: OpportunityCreate) -> tuple[Opportunity, str]:
        existing = None
        if opp.source_opportunity_id:
            existing = self.get_by_source_id(opp.source, opp.source_opportunity_id)
        if not existing and opp.solicitation_number:
            existing = self.get_by_source_and_solicitation(opp.source, opp.solicitation_number)
        if existing:
            updated = self.update(existing.id, OpportunityUpdate(**opp.model_dump()))
            return updated, "updated"
        try:
            created = self.create(opp)
            return created, "inserted"
        except IntegrityError:
            self.db.rollback()
            key = opp.source_opportunity_id or opp.solicitation_number or opp.title
            raise DuplicateRecordError(f"Duplicate opportunity detected for {opp.source}/{key}")
    SET_ASIDE_FILTERS = {
        "SMALL_BUSINESS": ["small business", "small_business", "total small", "sbsa"],
        "EIGHT_A": ["8(a)", "8a", "eight_a"],
        "8a": ["8(a)", "8a", "eight_a"],
        "sdvosb": ["sdvosb", "service-disabled"],
        "SDVOSB": ["sdvosb", "service-disabled", "service_disabled"],
        "wosb": ["wosb", "women-owned", "woman-owned"],
        "WOSB": ["wosb", "women-owned", "woman-owned"],
        "edwosb": ["edwosb", "economically disadvantaged women"],
        "EDWOSB": ["edwosb", "economically disadvantaged women"],
        "hubzone": ["hubzone", "hub zone"],
        "HUBZONE": ["hubzone", "hub zone"],
        "veteran": ["veteran-owned", "veteran_owned", "vosb"],
        "VOSB": ["veteran-owned", "veteran_owned", "vosb"],
        "unrestricted": ["unrestricted", "full and open", "not set aside"],
        "UNRESTRICTED": ["unrestricted", "full and open", "not set aside"],
    }
