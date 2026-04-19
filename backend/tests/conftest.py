from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.deps import get_current_organization, get_current_user, get_db
from app.main import app


class DummyDB:
    pass


@pytest.fixture
def dummy_db() -> DummyDB:
    return DummyDB()


@pytest.fixture
def client(dummy_db: DummyDB) -> Iterator[TestClient]:
    def override_get_db():
        yield dummy_db

    def override_current_user():
        return type("CurrentUser", (), {
            "id": 1,
            "email": "owner@nagacon.local",
            "full_name": "Default Owner",
            "role": "OWNER",
            "organization_id": 1,
            "is_active": True,
        })()

    def override_current_organization():
        return type("CurrentOrg", (), {
            "id": 1,
            "name": "Default Organization",
            "slug": "default",
            "is_default": True,
        })()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_current_organization] = override_current_organization
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
