from __future__ import annotations

import argparse
from datetime import date

from frederick_pipeline.analyze import infer_connections, render_report
from frederick_pipeline.config import Settings, ensure_directories, load_sources
from frederick_pipeline.db import (
    clear_article_people,
    clear_connections_for_date,
    connect,
    fetch_pending_articles,
    initialize,
    insert_connection,
    mark_article_failed,
    mark_article_processed,
    prune_orphan_people,
    upsert_alias,
    upsert_article,
    upsert_article_person,
    upsert_person,
)
from frederick_pipeline.extract import extract_people
from frederick_pipeline.fetch import fetch_source


def command_fetch(settings: Settings) -> None:
    ensure_directories(settings)
    initialize(settings.db_path)
    sources = load_sources(settings)

    with connect(settings.db_path) as conn:
        for source in sources:
            articles = fetch_source(
                source,
                timeout_seconds=settings.article_timeout_seconds,
                cache_dir=settings.cache_dir,
                max_article_chars=settings.max_article_chars,
            )
            for article in articles:
                upsert_article(conn, article.__dict__)


def command_extract(settings: Settings, limit: int | None = None) -> None:
    ensure_directories(settings)
    initialize(settings.db_path)

    with connect(settings.db_path) as conn:
        pending_articles = fetch_pending_articles(conn, limit=limit)
        for article in pending_articles:
            try:
                people = extract_people(
                    dict(article),
                    api_key=settings.openai_api_key,
                    model=settings.openai_model,
                    timeout_seconds=settings.article_timeout_seconds,
                )
                seen_at = article["published_at"] or article["fetched_at"]
                clear_article_people(conn, int(article["id"]))
                for extracted in people:
                    if extracted.confidence is None or extracted.confidence < settings.min_person_confidence:
                        continue
                    person_payload = {
                        "person_key": extracted.person_key,
                        "canonical_name": extracted.canonical_name,
                        "primary_position": extracted.primary_position,
                        "primary_organization": extracted.primary_organization,
                        "primary_address": extracted.primary_address,
                        "home_location": extracted.home_location,
                        "notes": extracted.notes,
                        "metadata": extracted.metadata,
                    }
                    person_id = upsert_person(conn, person_payload, seen_at=seen_at)
                    for alias in extracted.aliases:
                        upsert_alias(conn, person_id, alias)
                    upsert_article_person(
                        conn,
                        article_id=int(article["id"]),
                        person_id=person_id,
                        mention={
                            "mention_count": extracted.mention_count,
                            "confidence": extracted.confidence,
                            "role_in_article": extracted.role_in_article,
                            "organization": extracted.organization,
                            "address": extracted.address,
                            "location_context": extracted.location_context,
                            "quote_text": extracted.quote_text,
                            "summary": extracted.summary,
                            "metadata": extracted.metadata,
                        },
                    )
                mark_article_processed(conn, int(article["id"]))
            except Exception as exc:  # noqa: BLE001
                mark_article_failed(conn, int(article["id"]), str(exc))
        prune_orphan_people(conn)


def command_report(settings: Settings, run_date: str) -> None:
    ensure_directories(settings)
    initialize(settings.db_path)

    with connect(settings.db_path) as conn:
        clear_connections_for_date(conn, run_date)

        article_rows = list(
            conn.execute(
                """
                SELECT *
                FROM articles
                WHERE substr(COALESCE(published_at, fetched_at), 1, 10) = ?
                ORDER BY published_at DESC, id DESC
                """,
                (run_date,),
            ).fetchall()
        )
        people_rows = list(
            conn.execute(
                """
                SELECT DISTINCT p.*
                FROM people p
                JOIN article_people ap ON ap.person_id = p.id
                JOIN articles a ON a.id = ap.article_id
                WHERE substr(COALESCE(a.published_at, a.fetched_at), 1, 10) = ?
                  AND ap.confidence >= ?
                ORDER BY p.last_seen_at DESC, p.canonical_name ASC
                """,
                (run_date, settings.min_person_confidence),
            ).fetchall()
        )
        mention_rows = list(
            conn.execute(
                """
                SELECT
                    ap.article_id,
                    ap.person_id,
                    ap.confidence,
                    ap.organization,
                    ap.address,
                    p.canonical_name
                FROM article_people ap
                JOIN people p ON p.id = ap.person_id
                JOIN articles a ON a.id = ap.article_id
                WHERE substr(COALESCE(a.published_at, a.fetched_at), 1, 10) = ?
                """,
                (run_date,),
            ).fetchall()
        )

        connections = infer_connections(
            [dict(row) for row in mention_rows],
            run_date=run_date,
            min_confidence=settings.min_connection_confidence,
        )
        for connection in connections:
            insert_connection(conn, connection)

        named_connections = []
        for connection in connections:
            person_a = conn.execute("SELECT canonical_name FROM people WHERE id = ?", (connection["person_a_id"],)).fetchone()
            person_b = conn.execute("SELECT canonical_name FROM people WHERE id = ?", (connection["person_b_id"],)).fetchone()
            named_connections.append(
                {
                    **connection,
                    "person_a_name": person_a["canonical_name"],
                    "person_b_name": person_b["canonical_name"],
                }
            )

        report_text = render_report(
            run_date=run_date,
            articles=[dict(row) for row in article_rows],
            people=[dict(row) for row in people_rows],
            connections=named_connections,
        )
        report_path = settings.discovery_dir / f"{run_date}.md"
        report_path.write_text(report_text, encoding="utf-8")


def command_daily_run(settings: Settings) -> None:
    command_fetch(settings)
    command_extract(settings)
    command_report(settings, run_date=date.today().isoformat())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Frederick population intelligence pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("fetch")

    extract_parser = subparsers.add_parser("extract")
    extract_parser.add_argument("--limit", type=int, default=None)

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--date", required=True)

    subparsers.add_parser("daily-run")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = Settings()

    if args.command == "fetch":
        command_fetch(settings)
    elif args.command == "extract":
        command_extract(settings, limit=args.limit)
    elif args.command == "report":
        command_report(settings, run_date=args.date)
    elif args.command == "daily-run":
        command_daily_run(settings)


if __name__ == "__main__":
    main()
