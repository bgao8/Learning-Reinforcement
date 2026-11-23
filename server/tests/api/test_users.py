"""GET /users/me (#33), through the real get_current_user, against the local Postgres (rolled back after each test)."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import issue_token
from app.db.models import User
from app.db.session import get_db
from app.main import app


@pytest.fixture
def api(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_me_returns_the_tokens_user_and_only_safe_fields(api, db, user):
    token = issue_token(db, user.user_id)
    db.flush()
    response = api.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"user_id": str(user.user_id), "user_name": user.user_name, "email": user.email}


def test_me_without_a_token_is_401(api):
    assert api.get("/users/me").status_code == 401


def test_the_old_list_of_every_user_is_gone(api, db, user):
    other = User(user_name="Other", email=f"{uuid4()}@example.com")
    db.add(other)
    db.flush()
    token = issue_token(db, user.user_id)
    db.flush()
    response = api.get("/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code in (404, 405)
    assert other.email not in response.text
