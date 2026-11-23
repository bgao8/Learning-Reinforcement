"""User routes (#33). GET /users/me: who the token in the Authorization header belongs to."""
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.api.deps import get_current_user
from app.db.models import User

router = APIRouter(prefix="/users", tags=["users"])


class UserOut(BaseModel):
    # only these fields leave the server; preferences and anything added to User later stay in
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    user_name: str
    email: str


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    """The signed-in user. The app calls this on startup: 200 means its token still works, 401 means sign in again."""
    return user
