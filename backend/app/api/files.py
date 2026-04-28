from __future__ import annotations

from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_current_user, get_db
from app.models.opportunity import Opportunity
from app.models.opportunity_file import OpportunityFile
from app.schemas.files import OpportunityFileOut, OpportunityFileInsightsOut
from app.services import document_pipeline
from app.services.document_parser import parse_opportunity_file
from app.services.document_pipeline import process_opportunity_documents, process_opportunity_file
from app.services.file_retention import classify_opportunity_file_retention, mark_opportunity_files_processing_complete
from app.services.intelligence.nsn_intelligence_service import run_nsn_intelligence
from app.services.pdf_service import download_pdfs_for_opportunity
from app.services.providers.pdf_cage_extractor import extract_providers_from_opportunity_pdfs
from app.services.search_jobs import start_search_job
from app.services.storage import delete_reference, download_response as build_storage_download_response, file_exists, local_temp_path
from app.services.workspace_service import generate_submission_package


router = APIRouter(prefix="/api/files", tags=["files"])


def _scoped_opportunity_query(db: Session, opportunity_id: int, org_id: int | None):
    query = db.query(Opportunity).filter(Opportunity.id == opportunity_id)
    if org_id is not None:
        query = query.filter(
            or_(
                Opportunity.organization_id == org_id,
                Opportunity.organization_id.is_(None),
            )
        )
    return query


def _scoped_file_query(db: Session, org_id: int | None):
    query = db.query(OpportunityFile)
    if org_id is not None:
        query = query.filter(
            or_(
                OpportunityFile.organization_id == org_id,
                OpportunityFile.organization_id.is_(None),
            )
        )
    return query


def _file_out(file_record: OpportunityFile) -> OpportunityFileOut:
    parsed_metadata = getattr(file_record, "parsed_metadata", None) or {}
    pipeline = parsed_metadata.get("_pipeline") or {}
    processing_status = pipeline.get("status")
    if not processing_status:
        processing_status = "completed" if parsed_metadata else "downloaded"
    retention = classify_opportunity_file_retention(file_record, getattr(file_record, "opportunity", None))
    return OpportunityFileOut(
        id=file_record.id,
        opportunity_id=file_record.opportunity_id,
        file_type=file_record.file_type,
        filename=file_record.filename,
        source_url=file_record.source_url,
        file_path=file_record.file_path,
        created_at=file_record.created_at,
        has_extracted_text=bool(getattr(file_record, "extracted_text", None)),
        has_parsed_metadata=bool(getattr(file_record, "parsed_metadata", None)),
        processing_status=processing_status,
        document_type=parsed_metadata.get("document_type"),
        review_required=bool(pipeline.get("review_required")),
        storage_class=retention.storage_class,
        retention_status=retention.retention_status,
        retention_reason=retention.reason,
        prune_eligible=retention.prune_eligible,
    )


def _file_insights_out(file_record: OpportunityFile) -> OpportunityFileInsightsOut:
    extracted_text = getattr(file_record, "extracted_text", None)
    parsed_metadata = getattr(file_record, "parsed_metadata", None) or {}
    pipeline = parsed_metadata.get("_pipeline") or {}
    processing_status = pipeline.get("status")
    if not processing_status:
        processing_status = "completed" if parsed_metadata else "downloaded"
    retention = classify_opportunity_file_retention(file_record, getattr(file_record, "opportunity", None))
    return OpportunityFileInsightsOut(
        id=file_record.id,
        opportunity_id=file_record.opportunity_id,
        file_type=file_record.file_type,
        filename=file_record.filename,
        source_url=file_record.source_url,
        created_at=file_record.created_at,
        has_extracted_text=bool(extracted_text),
        has_parsed_metadata=bool(getattr(file_record, "parsed_metadata", None)),
        extracted_text=extracted_text,
        text_preview=(extracted_text[:1600] if extracted_text else None),
        parsed_metadata=parsed_metadata,
        processing_status=processing_status,
        document_type=parsed_metadata.get("document_type"),
        review_required=bool(pipeline.get("review_required")),
        storage_class=retention.storage_class,
        retention_status=retention.retention_status,
        retention_reason=retention.reason,
        prune_eligible=retention.prune_eligible,
    )


@router.get("/list", response_model=list[OpportunityFileOut])
def list_files(opportunity_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    org_id = getattr(current_org, "id", None)
    opp = _scoped_opportunity_query(db, opportunity_id, org_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    file_query = _scoped_file_query(db, org_id).filter(OpportunityFile.opportunity_id == opportunity_id)
    files = file_query.order_by(OpportunityFile.id.asc()).all()
    return [_file_out(file_record) for file_record in files]


@router.get("/prune-candidates")
def list_prune_candidates(opportunity_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    org_id = getattr(current_org, "id", None)
    opp = _scoped_opportunity_query(db, opportunity_id, org_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    file_query = _scoped_file_query(db, org_id).filter(OpportunityFile.opportunity_id == opportunity_id)
    files = file_query.order_by(OpportunityFile.id.asc()).all()
    candidates = []
    for file_record in files:
        retention = classify_opportunity_file_retention(file_record, opp)
        if retention.prune_eligible:
            candidates.append(
                {
                    "id": file_record.id,
                    "filename": file_record.filename,
                    "file_type": file_record.file_type,
                    "storage_class": retention.storage_class,
                    "retention_status": retention.retention_status,
                    "retention_reason": retention.reason,
                }
            )
    return {
        "opportunity_id": opportunity_id,
        "count": len(candidates),
        "items": candidates,
    }


@router.post("/prune")
def prune_files(
    opportunity_id: int | None = Query(default=None),
    file_id: int | None = Query(default=None),
    dry_run: bool = False,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    org_id = getattr(current_org, "id", None)
    if opportunity_id is None and file_id is None:
        raise HTTPException(status_code=422, detail="opportunity_id or file_id is required")

    query = _scoped_file_query(db, org_id)
    opportunity = None
    if file_id is not None:
        query = query.filter(OpportunityFile.id == file_id)
    else:
        opportunity = _scoped_opportunity_query(db, opportunity_id, org_id).first()
        if not opportunity:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        query = query.filter(OpportunityFile.opportunity_id == opportunity_id)
    files = query.order_by(OpportunityFile.id.asc()).all()
    if not files:
        raise HTTPException(status_code=404, detail="No matching files found")

    if opportunity is None:
        opp_id = getattr(files[0], "opportunity_id", None)
        opportunity = _scoped_opportunity_query(db, opp_id, org_id).first() if opp_id is not None else None

    items = []
    pruned_count = 0
    skipped_count = 0

    for file_record in files:
        retention = classify_opportunity_file_retention(file_record, opportunity)
        if not retention.prune_eligible:
            skipped_count += 1
            items.append(
                {
                    "id": file_record.id,
                    "filename": file_record.filename,
                    "status": "skipped",
                    "reason": retention.reason,
                }
            )
            continue

        if dry_run:
            items.append(
                {
                    "id": file_record.id,
                    "filename": file_record.filename,
                    "status": "eligible",
                    "reason": retention.reason,
                }
            )
            continue

        original_ref = file_record.file_path
        deleted = delete_reference(original_ref)
        metadata = dict(getattr(file_record, "parsed_metadata", None) or {})
        metadata["_retention"] = {
            "status": "pruned",
            "reason": retention.reason,
            "pruned_at": datetime.utcnow().isoformat(),
            "original_file_path": original_ref,
            "deleted_from_storage": bool(deleted),
        }
        file_record.file_path = f"pruned://opportunity-file/{file_record.id}"
        file_record.parsed_metadata = metadata
        db.add(file_record)
        pruned_count += 1
        items.append(
            {
                "id": file_record.id,
                "filename": file_record.filename,
                "status": "pruned",
                "reason": retention.reason,
                "deleted_from_storage": bool(deleted),
            }
        )

    if not dry_run:
        db.commit()

    return {
        "opportunity_id": getattr(opportunity, "id", opportunity_id),
        "file_id": file_id,
        "dry_run": dry_run,
        "pruned_count": pruned_count,
        "skipped_count": skipped_count,
        "items": items,
    }


@router.get("/{file_id}/insights", response_model=OpportunityFileInsightsOut)
def get_file_insights(file_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    org_id = getattr(current_org, "id", None)
    file_record = _scoped_file_query(db, org_id).filter(OpportunityFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    return _file_insights_out(file_record)


@router.post("/download_pdfs")
def download_pdfs(
    opportunity_id: int | None = Query(default=None),
    body: dict | None = Body(default=None),
    always_snapshot: bool = True,
    prefer_dibbs_solicitation_detail: bool = True,
    run_inline: bool = False,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    if opportunity_id is None and body:
        opportunity_id = body.get("opportunity_id") or body.get("opp_id")
    if opportunity_id is None:
        raise HTTPException(status_code=422, detail="opportunity_id or opp_id is required")
    org_id = getattr(current_org, "id", None)
    opp = _scoped_opportunity_query(db, opportunity_id, org_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    if not run_inline:
        return start_search_job(
            "workspace_intake",
            {
                "opportunity_id": opportunity_id,
                "organization_id": org_id,
                "user_id": getattr(current_user, "id", None),
                "download_documents": True,
                "run_usaspending": True,
            },
        )
    try:
        out = download_pdfs_for_opportunity(
            db,
            opportunity_id,
            always_snapshot=always_snapshot,
            prefer_dibbs_solicitation_detail=prefer_dibbs_solicitation_detail,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    processing = None
    provider_vendor_sync = None
    nsn_intelligence = None
    submission_package = None

    try:
        processing = process_opportunity_documents(db, opportunity_id, force=False)
    except Exception as e:
        db.rollback()
        processing = {"status": "failed", "error": str(e)}

    try:
        provider_vendor_sync = extract_providers_from_opportunity_pdfs(
            db,
            opp,
            enrich_with_sam=True,
            organization_id=org_id,
            user_id=getattr(current_user, "id", None),
        ).model_dump()
    except Exception as e:
        db.rollback()
        provider_vendor_sync = {"status": "failed", "error": str(e)}

    try:
        nsn_intelligence = run_nsn_intelligence(
            db,
            opp,
            seed_awardees=False,
            create_summary_artifact=True,
        )
    except Exception as e:
        db.rollback()
        nsn_intelligence = {"status": "failed", "error": str(e)}

    try:
        artifact = generate_submission_package(db, opp)
        submission_package = {"artifact_id": artifact.id, "status": "refreshed"}
    except Exception as e:
        db.rollback()
        submission_package = {"status": "failed", "error": str(e)}

    out.update(
        {
            "processing": processing,
            "provider_vendor_sync": provider_vendor_sync,
            "nsn_intelligence": nsn_intelligence,
            "submission_package": submission_package,
        }
    )
    mark_opportunity_files_processing_complete(
        db,
        opp.id,
        completed=all(
            (step or {}).get("status") != "failed"
            for step in [processing, provider_vendor_sync, nsn_intelligence, submission_package]
        ),
        source="download_pdfs_inline",
        details={
            "processing": (processing or {}).get("status"),
            "provider_vendor_sync": (provider_vendor_sync or {}).get("status", "completed"),
            "nsn_intelligence": (nsn_intelligence or {}).get("status", "completed"),
            "submission_package": (submission_package or {}).get("status", "completed"),
        },
    )
    return out


@router.get("/download/{file_id}")
def download_file(file_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    org_id = getattr(current_org, "id", None)
    f = _scoped_file_query(db, org_id).filter(OpportunityFile.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    if not f.file_path:
        raise HTTPException(status_code=404, detail="File path is empty")
    try:
        return build_storage_download_response(f.file_path, filename=f.filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File missing from configured storage")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"File download unavailable: {exc}")


@router.post("/parse/{file_id}")
def parse_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    org_id = getattr(current_org, "id", None)
    f = _scoped_file_query(db, org_id).filter(OpportunityFile.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    if not f.file_path:
        raise HTTPException(status_code=404, detail="File path is empty")
    if not file_exists(f.file_path):
        raise HTTPException(status_code=404, detail="File missing from configured storage")
    try:
        document_pipeline.parse_opportunity_file = parse_opportunity_file
        try:
            result = process_opportunity_file(db, file_id, force=True)
        except AttributeError:
            with local_temp_path(f.file_path, suffix=Path(f.filename or f.file_path).suffix) as p:
                parsed_doc = parse_opportunity_file(str(p))
                f.extracted_text = parsed_doc.get("text") or f.extracted_text
                f.parsed_metadata = {**(getattr(f, "parsed_metadata", None) or {}), **parsed_doc}
                db.add(f)
                db.commit()
                db.refresh(f)
                result = {"file_id": file_id, "status": "completed", "document_type": parsed_doc.get("kind")}
        if getattr(f, "opportunity_id", None) is not None:
            process_opportunity_documents(db, f.opportunity_id, force=False)
        opp = _scoped_opportunity_query(db, f.opportunity_id, org_id).first() if getattr(f, "opportunity_id", None) is not None else None
        provider_vendor_sync = None
        if opp:
            provider_vendor_sync = extract_providers_from_opportunity_pdfs(
                db,
                opp,
                enrich_with_sam=True,
                organization_id=org_id,
                user_id=getattr(current_user, "id", None),
            ).model_dump()
            mark_opportunity_files_processing_complete(
                db,
                opp.id,
                completed=False,
                source="parse_file_inline",
                details={
                    "processing": result.get("status"),
                    "provider_vendor_sync": (provider_vendor_sync or {}).get("status", "completed"),
                    "note": "File parse completed, but full downstream workspace extraction has not been confirmed.",
                },
            )
        refreshed = _scoped_file_query(db, org_id).filter(OpportunityFile.id == file_id).first()
        parsed = dict(getattr(refreshed, "parsed_metadata", None) or {})
        if getattr(refreshed, "extracted_text", None) and "text" not in parsed:
            parsed["text"] = refreshed.extracted_text
        return {
            "file_id": file_id,
            "filename": f.filename,
            "parsed": parsed,
            "processing": result,
            "provider_vendor_sync": provider_vendor_sync,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Parse failed: {e}")
