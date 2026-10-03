from fastapi import FastAPI
from sqlalchemy import select

from server.db.models import User
from server.db.session import SessionLocal

app = FastAPI(title="Learning Reinforcement API")


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
