from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    publisher TEXT,
    title TEXT NOT NULL,
    normalized_url TEXT NOT NULL UNIQUE,
    raw_url TEXT NOT NULL,
    published_at TEXT,
    location_focus TEXT,
    summary TEXT,
    author TEXT,
    body_text TEXT,
    article_hash TEXT,
    extraction_status TEXT NOT NULL DEFAULT 'pending',
    extraction_error TEXT,
    fetched_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_key TEXT,
    canonical_name TEXT NOT NULL UNIQUE,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    primary_position TEXT,
    primary_organization TEXT,
    primary_address TEXT,
    home_location TEXT,
    notes TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS person_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    alias TEXT NOT NULL,
    UNIQUE(person_id, alias),
    FOREIGN KEY (person_id) REFERENCES people(id)
);

CREATE TABLE IF NOT EXISTS article_people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL,
    person_id INTEGER NOT NULL,
    mention_count INTEGER NOT NULL DEFAULT 1,
    confidence REAL,
    role_in_article TEXT,
    organization TEXT,
    address TEXT,
    location_context TEXT,
    quote_text TEXT,
    summary TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(article_id, person_id),
    FOREIGN KEY (article_id) REFERENCES articles(id),
    FOREIGN KEY (person_id) REFERENCES people(id)
);

CREATE TABLE IF NOT EXISTS inferred_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    person_a_id INTEGER NOT NULL,
    person_b_id INTEGER NOT NULL,
    connection_type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 0,
    rationale TEXT NOT NULL,
    source_article_ids TEXT NOT NULL DEFAULT '[]',
    UNIQUE(run_date, person_a_id, person_b_id, connection_type, rationale),
    FOREIGN KEY (person_a_id) REFERENCES people(id),
    FOREIGN KEY (person_b_id) REFERENCES people(id)
);
"""


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        _migrate_schema(conn)


def _migrate_schema(conn: sqlite3.Connection) -> None:
    article_columns = {row["name"] for row in conn.execute("PRAGMA table_info(articles)")}
    if "extractor_name" not in article_columns:
        conn.execute("ALTER TABLE articles ADD COLUMN extractor_name TEXT")

    people_columns = {row["name"] for row in conn.execute("PRAGMA table_info(people)")}
    if "person_key" not in people_columns:
        conn.execute("ALTER TABLE people ADD COLUMN person_key TEXT")

    conn.execute(
        """
        UPDATE people
        SET person_key = lower(trim(canonical_name))
        WHERE person_key IS NULL OR length(trim(person_key)) = 0
        """
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_people_person_key ON people(person_key)")


def upsert_article(conn: sqlite3.Connection, article: dict) -> int:
    metadata_json = json.dumps(article.get("metadata", {}), ensure_ascii=True)
    conn.execute(
        """
        INSERT INTO articles (
            source_name, publisher, title, normalized_url, raw_url, published_at,
            location_focus, summary, author, body_text, article_hash, fetched_at, metadata_json, extractor_name
        )
        VALUES (
            :source_name, :publisher, :title, :normalized_url, :raw_url, :published_at,
            :location_focus, :summary, :author, :body_text, :article_hash, :fetched_at, :metadata_json, :extractor_name
        )
        ON CONFLICT(normalized_url) DO UPDATE SET
            source_name=excluded.source_name,
            publisher=excluded.publisher,
            title=excluded.title,
            published_at=COALESCE(excluded.published_at, articles.published_at),
            location_focus=excluded.location_focus,
            summary=COALESCE(excluded.summary, articles.summary),
            author=COALESCE(excluded.author, articles.author),
            body_text=COALESCE(excluded.body_text, articles.body_text),
            article_hash=COALESCE(excluded.article_hash, articles.article_hash),
            fetched_at=excluded.fetched_at,
            metadata_json=excluded.metadata_json,
            extractor_name=excluded.extractor_name,
            extraction_status=CASE
                WHEN COALESCE(articles.article_hash, '') != COALESCE(excluded.article_hash, '')
                    OR COALESCE(articles.extractor_name, '') != COALESCE(excluded.extractor_name, '')
                THEN 'pending'
                ELSE articles.extraction_status
            END,
            extraction_error=CASE
                WHEN COALESCE(articles.article_hash, '') != COALESCE(excluded.article_hash, '')
                    OR COALESCE(articles.extractor_name, '') != COALESCE(excluded.extractor_name, '')
                THEN NULL
                ELSE articles.extraction_error
            END
        """,
        {**article, "metadata_json": metadata_json},
    )
    row = conn.execute(
        "SELECT id FROM articles WHERE normalized_url = ?",
        (article["normalized_url"],),
    ).fetchone()
    return int(row["id"])


def fetch_pending_articles(conn: sqlite3.Connection, limit: int | None = None) -> list[sqlite3.Row]:
    sql = """
        SELECT *
        FROM articles
        WHERE extraction_status = 'pending'
          AND body_text IS NOT NULL
          AND length(trim(body_text)) > 0
        ORDER BY published_at DESC, id DESC
    """
    params: tuple = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)
    return list(conn.execute(sql, params).fetchall())


def mark_article_processed(conn: sqlite3.Connection, article_id: int) -> None:
    conn.execute(
        "UPDATE articles SET extraction_status = 'processed', extraction_error = NULL WHERE id = ?",
        (article_id,),
    )


def mark_article_failed(conn: sqlite3.Connection, article_id: int, error: str) -> None:
    conn.execute(
        "UPDATE articles SET extraction_status = 'failed', extraction_error = ? WHERE id = ?",
        (error[:2000], article_id),
    )


def upsert_person(conn: sqlite3.Connection, person: dict, seen_at: str) -> int:
    metadata_json = json.dumps(person.get("metadata", {}), ensure_ascii=True)
    conn.execute(
        """
        INSERT INTO people (
            person_key, canonical_name, first_seen_at, last_seen_at, primary_position, primary_organization,
            primary_address, home_location, notes, metadata_json
        )
        VALUES (
            :person_key, :canonical_name, :seen_at, :seen_at, :primary_position, :primary_organization,
            :primary_address, :home_location, :notes, :metadata_json
        )
        ON CONFLICT(person_key) DO UPDATE SET
            last_seen_at=excluded.last_seen_at,
            canonical_name=excluded.canonical_name,
            primary_position=COALESCE(excluded.primary_position, people.primary_position),
            primary_organization=COALESCE(excluded.primary_organization, people.primary_organization),
            primary_address=COALESCE(excluded.primary_address, people.primary_address),
            home_location=COALESCE(excluded.home_location, people.home_location),
            notes=COALESCE(excluded.notes, people.notes),
            metadata_json=excluded.metadata_json
        """,
        {**person, "seen_at": seen_at, "metadata_json": metadata_json},
    )
    row = conn.execute(
        "SELECT id FROM people WHERE person_key = ?",
        (person["person_key"],),
    ).fetchone()
    return int(row["id"])


def upsert_alias(conn: sqlite3.Connection, person_id: int, alias: str) -> None:
    clean_alias = alias.strip()
    if not clean_alias:
        return
    conn.execute(
        "INSERT OR IGNORE INTO person_aliases (person_id, alias) VALUES (?, ?)",
        (person_id, clean_alias),
    )


def upsert_article_person(conn: sqlite3.Connection, article_id: int, person_id: int, mention: dict) -> None:
    metadata_json = json.dumps(mention.get("metadata", {}), ensure_ascii=True)
    conn.execute(
        """
        INSERT INTO article_people (
            article_id, person_id, mention_count, confidence, role_in_article, organization,
            address, location_context, quote_text, summary, metadata_json
        )
        VALUES (
            :article_id, :person_id, :mention_count, :confidence, :role_in_article, :organization,
            :address, :location_context, :quote_text, :summary, :metadata_json
        )
        ON CONFLICT(article_id, person_id) DO UPDATE SET
            mention_count=excluded.mention_count,
            confidence=excluded.confidence,
            role_in_article=excluded.role_in_article,
            organization=excluded.organization,
            address=excluded.address,
            location_context=excluded.location_context,
            quote_text=excluded.quote_text,
            summary=excluded.summary,
            metadata_json=excluded.metadata_json
        """,
        {**mention, "article_id": article_id, "person_id": person_id, "metadata_json": metadata_json},
    )


def clear_article_people(conn: sqlite3.Connection, article_id: int) -> None:
    conn.execute("DELETE FROM article_people WHERE article_id = ?", (article_id,))


def prune_orphan_people(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        DELETE FROM person_aliases
        WHERE person_id NOT IN (SELECT id FROM people)
        """
    )
    conn.execute(
        """
        DELETE FROM person_aliases
        WHERE person_id IN (
            SELECT p.id
            FROM people p
            LEFT JOIN article_people ap ON ap.person_id = p.id
            WHERE ap.person_id IS NULL
        )
        """
    )
    conn.execute(
        """
        DELETE FROM people
        WHERE id IN (
            SELECT p.id
            FROM people p
            LEFT JOIN article_people ap ON ap.person_id = p.id
            WHERE ap.person_id IS NULL
        )
        """
    )


def clear_connections_for_date(conn: sqlite3.Connection, run_date: str) -> None:
    conn.execute("DELETE FROM inferred_connections WHERE run_date = ?", (run_date,))


def insert_connection(conn: sqlite3.Connection, connection: dict) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO inferred_connections (
            run_date, person_a_id, person_b_id, connection_type, weight, rationale, source_article_ids
        )
        VALUES (
            :run_date, :person_a_id, :person_b_id, :connection_type, :weight, :rationale, :source_article_ids
        )
        """,
        {**connection, "source_article_ids": json.dumps(connection["source_article_ids"], ensure_ascii=True)},
    )
