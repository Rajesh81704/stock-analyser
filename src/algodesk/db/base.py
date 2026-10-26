"""
SQLAlchemy Database Base & Connection Management.

Provides database engine, declarative base, session factories,
and database initialization helpers.
"""

from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from src.algodesk.config.settings import settings

Base = declarative_base()

def get_engine(database_url: str = None):
    """Creates a SQLAlchemy engine. Fallbacks to sqlite if postgres is unavailable."""
    url = database_url or settings.database_url
    # SQLite requires check_same_thread=False for multithreading
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)

engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for yielding database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db(target_engine=None):
    """Initializes all database tables registered with Base."""
    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)
