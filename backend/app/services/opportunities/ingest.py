
from typing import List
from sqlalchemy.orm import Session

from app.schemas.opportunity import RawOpportunity, IngestResult
from app.services.opportunities.normalize import normalize_raw_opportunity
from app.services.opportunities.deduplicate import find_potential_duplicate, merge_into_existing
from app.repositories.opportunities import OpportunityRepository
from app.utils.exceptions import NormalizationError, DuplicateRecordError


def ingest_raw_opportunities(db: Session, raw_records: List[RawOpportunity]) -> IngestResult:
    repo = OpportunityRepository(db)
    result = IngestResult()

    for raw in raw_records:
        try:
            normalized = normalize_raw_opportunity(raw)

            record, action = repo.upsert(normalized)

            if action == "inserted":
                dupe_id = find_potential_duplicate(db, normalized, exclude_id=record.id)

                if dupe_id:
                    merge_update = merge_into_existing(repo.get(dupe_id), normalized)
                    repo.update(dupe_id, merge_update)
                    repo.delete(record.id)

                    result.updated += 1
                else:
                    result.inserted += 1
            else:
                result.updated += 1

        except (NormalizationError, DuplicateRecordError) as e:
            result.skipped += 1
            result.errors.append(str(e))

        except Exception as e:
            result.skipped += 1
            result.errors.append(f"Unexpected: {str(e)}")

    return result
