from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.config import settings

engine = create_engine(settings.sqlalchemy_url, future=True)

# Call SessionLocal() to get a unit-of-work session:
#   with SessionLocal() as db:
#       db.scalars(select(User)).all()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
