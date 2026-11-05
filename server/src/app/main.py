from fastapi import FastAPI
from sqlalchemy import select

from fastapi.middleware.cors import CORSMiddleware

from app.db.models import User
from app.db.session import SessionLocal
from app.api.sessions import router as sessions_router

# FastAPI server, receives requests and sends responses
app = FastAPI(title="Learning Reinforcement API")
# give FastAPI the sessions routes from sessions.py
app.include_router(sessions_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["null", "file://"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/users")
def list_users() -> list[dict]:
    with SessionLocal() as db:
        users = db.scalars(select(User)).all()
        return [
            {"user_id": str(u.user_id), "user_name": u.user_name, "email": u.email}
            for u in users
        ]
