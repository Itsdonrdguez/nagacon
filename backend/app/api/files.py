from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Body, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models.opportunity import Opportunity
from app.models.opportunity_file import OpportunityFile
from app.schemas.files import OpportunityFileOut
from app.services.pdf_service import download_pdfs_for_opportunity
from app.services.document_parser import parse_opportunity_file


router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/list", response_model=list[OpportunityFileOut])
def list_files(opportunity_id: int, db: Session = Depends(get_db)):
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return (
        db.query(OpportunityFile)
        .filter(OpportunityFile.opportunity_id == opportunity_id)
        .order_by(OpportunityFile.id.asc())
        .all()
    )


@router.post("/download_pdfs")
def download_pdfs(
    opportunity_id: int | None = Query(default=None),
    body: dict | None = Body(default=None),
    always_snapshot: bool = True,
    prefer_dibbs_solicitation_detail: bool = True,
    db: Session = Depends(get_db),
):
    if opportunity_id is None and body:
        opportunity_id = body.get("opportunity_id") or body.get("opp_id")
    if opportunity_id is None:
        raise HTTPException(status_code=422, detail="opportunity_id or opp_id is required")
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    try:
        out = download_pdfs_for_opportunity(
            db,
            opportunity_id,
            always_snapshot=always_snapshot,
            prefer_dibbs_solicitation_detail=prefer_dibbs_solicitation_detail,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return out


@router.get("/download/{file_id}")
def download_file(file_id: int, db: Session = Depends(get_db)):
    f = db.query(OpportunityFile).filter(OpportunityFile.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    if not f.file_path:
        raise HTTPException(status_code=404, detail="File path is empty")

    p = Path(f.file_path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail=f"File missing on disk: {p}")

    media_type = "application/pdf"
    suffix = p.suffix.lower()
    if suffix == ".zip":
        media_type = "application/zip"
    elif suffix == ".json":
        media_type = "application/json"

    return FileResponse(path=str(p), filename=f.filename or p.name, media_type=media_type)


@router.post("/parse/{file_id}")
def parse_file(file_id: int, db: Session = Depends(get_db)):
    f = db.query(OpportunityFile).filter(OpportunityFile.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    if not f.file_path:
        raise HTTPException(status_code=404, detail="File path is empty")
    p = Path(f.file_path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail=f"File missing on disk: {p}")
    try:
        parsed = parse_opportunity_file(str(p))
        try:
            if hasattr(f, "parsed_metadata"):
                f.parsed_metadata = parsed
            if hasattr(f, "extracted_text") and isinstance(parsed, dict):
                f.extracted_text = parsed.get("text") or f.extracted_text
            db.add(f)
            db.commit()
            db.refresh(f)
        except Exception:
            db.rollback()
        return {"file_id": file_id, "filename": f.filename, "parsed": parsed}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Parse failed: {e}")
