from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import Session, User
from app.db.session import get_db


SEND_EMAIL = "bgao2005@gmail.com"
router = APIRouter(prefix="/sessions", tags=["sessions"])


class SessionCreate(BaseModel):
    title: str | None = None
    source: str | None = None


class SessionOut(BaseModel):
    # reads model as SQLAlchemy object
    model_config = ConfigDict(from_attributes=True)
    session_id: UUID
    title: str | None
    source: str | None
    started_at: datetime
    ended_at: datetime | None

def get_current_user(db: DbSession = Depends(get_db)) -> User:
    user = db.scalar(select(User).where(User.email == SEND_EMAIL))
    if user is None:
        raise HTTPException(status_code=500, detail="seed user missing; run scripts/seed.py")
    return user

# HTTP request routes
@router.post("", response_model=SessionOut, status_code=201)
def create_session(body: SessionCreate, db: DbSession = Depends(get_db), user: User = Depends(get_current_user)):
    new_session = Session(user_id=user.user_id, title=body.title, source=body.source)
    # stage new row
    db.add(new_session)
    # saves to Postgres
    db.commit()
    # reloads row
    db.refresh(new_session)
    # hands back the database object
    return new_session

@router.patch("/{session_id}/end", response_model=SessionOut)
def end_session(session_id: UUID, db: DbSession = Depends(get_db)):
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    if session.ended_at is None:
        session.ended_at = datetime.now(UTC)
        db.commit()
        db.refresh(session)

    return session