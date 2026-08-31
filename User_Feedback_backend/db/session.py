from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,    # survive Cloud SQL Auth Proxy restarts
    pool_size=10,
    max_overflow=20,
    echo=False,            # set True to log SQL in dev
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


def get_db():
    """FastAPI dependency — yields a DB session, always closes on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
