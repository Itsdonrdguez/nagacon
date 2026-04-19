from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import get_current_organization, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
def get_me(
    current_user=Depends(get_current_user),
    current_org=Depends(get_current_organization),
):
    return {
        "user": {
            "id": getattr(current_user, "id", None),
            "email": getattr(current_user, "email", None),
            "full_name": getattr(current_user, "full_name", None),
            "role": getattr(current_user, "role", None),
            "is_active": getattr(current_user, "is_active", True),
        } if current_user else None,
        "organization": {
            "id": getattr(current_org, "id", None),
            "name": getattr(current_org, "name", None),
            "slug": getattr(current_org, "slug", None),
            "is_default": getattr(current_org, "is_default", True),
        } if current_org else None,
    }
