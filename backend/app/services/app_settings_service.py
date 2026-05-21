from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting


def get_setting(
    db: Session,
    setting_key: str,
    default: str | None = None,
    organization_id: int | None = None,
    user_id: int | None = None,
) -> str | None:
    try:
        query = db.query(AppSetting).filter(AppSetting.setting_key == setting_key)
        if organization_id is not None:
            query = query.filter(AppSetting.organization_id == organization_id)
        else:
            query = query.filter(AppSetting.organization_id.is_(None))
        if user_id is not None:
            query = query.filter(AppSetting.user_id == user_id)
        else:
            query = query.filter(AppSetting.user_id.is_(None))
        record = query.first()
    except Exception:
        if hasattr(db, "rollback"):
            db.rollback()
        return default
    return record.setting_value if record else default


def upsert_setting(
    db: Session,
    setting_key: str,
    setting_value: str | None,
    organization_id: int | None = None,
    user_id: int | None = None,
) -> AppSetting | None:
    try:
        query = db.query(AppSetting).filter(AppSetting.setting_key == setting_key)
        if organization_id is not None:
            query = query.filter(AppSetting.organization_id == organization_id)
        else:
            query = query.filter(AppSetting.organization_id.is_(None))
        if user_id is not None:
            query = query.filter(AppSetting.user_id == user_id)
        else:
            query = query.filter(AppSetting.user_id.is_(None))
        record = query.first()
    except Exception:
        if hasattr(db, "rollback"):
            db.rollback()
        return None
    if not record:
        record = AppSetting(setting_key=setting_key, setting_value=setting_value, organization_id=organization_id, user_id=user_id)
        db.add(record)
    else:
        record.setting_value = setting_value
        record.user_id = user_id
        db.add(record)
    db.commit()
    db.refresh(record)
    return record
