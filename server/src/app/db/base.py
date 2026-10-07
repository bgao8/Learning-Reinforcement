from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base; every model subclasses this.

    Alembic reads ``Base.metadata`` to autogenerate migrations, so every
    model module must be imported before Alembic runs (see migrations/env.py).
    """
