import logging
logging.basicConfig(level=logging.INFO)

from fastapi import FastAPI

from fastapi.middleware.cors import CORSMiddleware

from app.api.sessions import router as sessions_router
from app.api.questions import router as questions_router
from app.api.users import router as users_router

# FastAPI server, receives requests and sends responses
app = FastAPI(title="Learning Reinforcement API")
# give FastAPI the routes from sessions.py, questions.py and users.py
app.include_router(sessions_router)
app.include_router(questions_router)
app.include_router(users_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["null", "file://"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
