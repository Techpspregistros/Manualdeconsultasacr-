
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect, text

from database import ENGINE, database_url


BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def sqlite_path() -> Path | None:
    url = database_url()
    if not url.startswith("sqlite:///"):
        return None
    return Path(url[len("sqlite:///"):]).resolve()


def database_report() -> dict:
    inspector = inspect(ENGINE)
    counts = {}
    with ENGINE.connect() as conn:
        for table in sorted(inspector.get_table_names()):
            try:
                counts[table] = int(
                    conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()
                )
            except Exception:
                counts[table] = -1

    path = sqlite_path()
    return {
        "database_url_type": "SQLite" if path else "Externa",
        "database_path": str(path) if path else "DATABASE_URL",
        "exists": bool(path and path.exists()),
        "size_bytes": path.stat().st_size if path and path.exists() else 0,
        "counts": counts,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def validate_sqlite(path: Path) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        raise ValueError("La base SQLite no existe o está vacía.")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        tables = [
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
    finally:
        conn.close()
    if integrity != "ok":
        raise ValueError(f"Integridad SQLite: {integrity}")
    return {"integrity": integrity, "tables": tables}


def create_backup(label: str = "manual") -> Path:
    source = sqlite_path()
    if source is None:
        raise ValueError("Esta función solo aplica a SQLite.")
    validate_sqlite(source)

    safe = "".join(
        char if char.isalnum() or char in "_-" else "_"
        for char in label
    ) or "manual"
    target = BACKUP_DIR / (
        f"arcplus_{safe}_{datetime.now():%Y%m%d_%H%M%S}.db"
    )

    source_conn = sqlite3.connect(str(source))
    target_conn = sqlite3.connect(str(target))
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()

    validate_sqlite(target)
    return target


def export_report_json() -> bytes:
    return json.dumps(
        database_report(),
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
