import os
import threading
from pathlib import Path

import mysql.connector
from flask import g

from app import config

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "database" / "schema.sql"
_lock = threading.Lock()
_ready = False


def _connect(user, password):
    s = config.db_settings()
    return mysql.connector.connect(
        host=s["host"], port=s["port"], database=s["database"],
        user=user, password=password,
        connection_timeout=3, autocommit=True, charset="utf8mb4",
    )


def get_connection():
    user, password = config.db_credentials()
    try:
        return _connect(user, password)
    except mysql.connector.Error as exc:
        # 1045 = access denied: the RDS-managed password was probably rotated
        if getattr(exc, "errno", None) == 1045 and os.getenv("DB_SECRET_ARN"):
            user, password = config.db_credentials(force_refresh=True)
            return _connect(user, password)
        raise


def _statements():
    lines = [ln for ln in SCHEMA_FILE.read_text().splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def ensure_schema():
    """Create tables + seed doctors once per process. RDS is private, so the app applies
    database/schema.sql itself. The script is idempotent and safe for concurrent instances."""
    global _ready
    if _ready:
        return
    with _lock:
        if _ready:
            return
        conn = get_connection()
        try:
            cur = conn.cursor()
            for stmt in _statements():
                cur.execute(stmt)
            cur.close()
        finally:
            conn.close()
        _ready = True


def get_db():
    if "db" not in g:
        ensure_schema()
        g.db = get_connection()
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def query(sql, args=(), one=False):
    cur = get_db().cursor(dictionary=True)
    try:
        cur.execute(sql, args)
        rows = cur.fetchall()
    finally:
        cur.close()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql, args=()):
    cur = get_db().cursor()
    try:
        cur.execute(sql, args)
        return cur.lastrowid, cur.rowcount
    finally:
        cur.close()
