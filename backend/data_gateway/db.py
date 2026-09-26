"""Engine/session setup shared by the data gateway and the M1 seed scripts.

Only this module (and code that imports it) is meant to open a DB connection.
docs/CLAUDE.md invariant 2: "All data access goes through the data gateway."
M1's generator scripts are a deliberate, temporary exception — they populate
the DB directly since no agent or token is involved yet. From M2 onward, the
gateway's HTTP API is the only path other services use.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set in .env")
    return url


def _direct_url() -> str:
    """The non-pooled connection, needed for DDL (CREATE TABLE, CREATE EXTENSION).
    Supabase's transaction-mode pooler (DATABASE_URL) doesn't support session-level
    features some migrations rely on; DIRECT_URL falls back to DATABASE_URL if unset
    (e.g. a plain local/non-pooled Postgres)."""
    return os.environ.get("DIRECT_URL") or _database_url()


# statement_cache_size=0 disables psycopg's server-side prepared-statement cache.
# Required for Supabase's transaction-mode pooler (port 6543): pooled connections
# are shared across clients between transactions, so a prepared statement from
# one caller can collide with another's ("DuplicatePreparedStatement"). Without
# this, concurrent or repeated bulk inserts intermittently fail. Not needed on
# direct_engine (port 5432, session mode, one dedicated connection).
engine = create_engine(_database_url(), pool_pre_ping=True, connect_args={"prepare_threshold": None})
direct_engine = create_engine(_direct_url(), pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
DirectSessionLocal = sessionmaker(bind=direct_engine, autoflush=False, autocommit=False)


def get_session() -> Session:
    return SessionLocal()


def get_direct_session() -> Session:
    """For one-off admin/seed scripts — a dedicated (non-pooled) connection,
    so a multi-statement transaction (delete-then-insert) behaves normally."""
    return DirectSessionLocal()
