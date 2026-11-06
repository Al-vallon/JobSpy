#!/usr/bin/env python3
"""Fusionne un export JSONL `jobspy` dans SQLite et écrit les annonces nouvelles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def _norm_url(url: str | None) -> str:
    if not url or not isinstance(url, str):
        return ""
    return url.strip().lower()


def _norm_part(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def dedup_key(record: dict[str, object]) -> str:
    job_url = _norm_url(record.get("job_url") if isinstance(record.get("job_url"), str) else None)
    if job_url:
        return hashlib.sha256(job_url.encode("utf-8")).hexdigest()
    raw = "|".join(
        [
            _norm_part(record.get("site")),
            _norm_part(record.get("title")),
            _norm_part(record.get("company")),
            _norm_part(record.get("date_posted")),
            _norm_part(record.get("location")),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            dedup_key TEXT PRIMARY KEY NOT NULL,
            payload TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def merge(
    conn: sqlite3.Connection, input_path: Path, output_new_path: Path
) -> tuple[int, int]:
    now = datetime.now(timezone.utc).isoformat()
    seen_new = 0
    total_in = 0
    lines_out: list[str] = []

    with input_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total_in += 1
            record: dict[str, object] = json.loads(line)
            key = dedup_key(record)
            payload = json.dumps(record, ensure_ascii=False, separators=(",", ":"))

            cur = conn.execute("SELECT dedup_key FROM jobs WHERE dedup_key = ?", (key,))
            exists = cur.fetchone() is not None

            if exists:
                conn.execute(
                    "UPDATE jobs SET last_seen_at = ?, payload = ? WHERE dedup_key = ?",
                    (now, payload, key),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO jobs (dedup_key, payload, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (key, payload, now, now),
                )
                seen_new += 1
                lines_out.append(payload + "\n")

    conn.commit()
    output_new_path.parent.mkdir(parents=True, exist_ok=True)
    with output_new_path.open("w", encoding="utf-8") as out:
        out.writelines(lines_out)
    return total_in, seen_new


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input_jsonl", type=Path, help="sortie JSONL de jobspy")
    p.add_argument("output_new_jsonl", type=Path, help="JSONL des annonces nouvelles pour ce run")
    p.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("JOBSPY_SQLITE_PATH", "data/jobspy_seen.sqlite")),
        help="chemin SQLite (défaut: JOBSPY_SQLITE_PATH ou data/jobspy_seen.sqlite)",
    )
    args = p.parse_args()
    db_path: Path = args.db
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if not args.input_jsonl.is_file():
        args.output_new_jsonl.parent.mkdir(parents=True, exist_ok=True)
        args.output_new_jsonl.write_text("", encoding="utf-8")
        print(
            "github_jobspy_sqlite: fichier d'entrée absent, 0 ligne",
            file=sys.stderr,
        )
        return 0
    conn = sqlite3.connect(db_path)
    try:
        init_db(conn)
        total, new_count = merge(conn, args.input_jsonl, args.output_new_jsonl)
    finally:
        conn.close()
    print(
        f"github_jobspy_sqlite: {total} ligne(s) lues, {new_count} nouvelle(s) annonce(s)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


