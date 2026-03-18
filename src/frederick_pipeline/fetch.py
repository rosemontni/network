from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser
import requests
import trafilatura
from bs4 import BeautifulSoup
from dateutil import parser as date_parser


USER_AGENT = "FrederickPopulationPipeline/0.1 (+public-interest research)"


@dataclass
class ArticleRecord:
    source_name: str
    publisher: str | None
    title: str
    normalized_url: str
    raw_url: str
    published_at: str | None
    location_focus: str | None
    summary: str | None
    author: str | None
    body_text: str | None
    article_hash: str | None
    fetched_at: str
    metadata: dict


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    cleaned = parsed._replace(query=urlencode(query), fragment="")
    return urlunparse(cleaned)


def extract_article_text(html: str, url: str) -> tuple[str | None, dict]:
    downloaded = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
        favor_recall=True,
        output_format="json",
    )
    if downloaded:
        payload = json.loads(downloaded)
        return payload.get("text"), payload

    soup = BeautifulSoup(html, "html.parser")
    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    text = "\n".join(p for p in paragraphs if p)
    return text or None, {"fallback": "beautifulsoup"}


def make_article_hash(title: str, body_text: str | None) -> str:
    digest = hashlib.sha256()
    digest.update(title.encode("utf-8", errors="ignore"))
    digest.update((body_text or "").encode("utf-8", errors="ignore"))
    return digest.hexdigest()


def fetch_url(url: str, timeout_seconds: int) -> requests.Response:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout_seconds)
    response.raise_for_status()
    return response


def parse_published_at(entry: feedparser.FeedParserDict) -> str | None:
    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if value:
            try:
                return date_parser.parse(value).isoformat()
            except (ValueError, TypeError, OverflowError):
                continue
    return None


def strip_html(value: str | None) -> str | None:
    if not value:
        return None
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip() or None


def fetch_source(source: dict, timeout_seconds: int, cache_dir: Path, max_article_chars: int) -> list[ArticleRecord]:
    if source["kind"] != "rss":
        raise ValueError(f"Unsupported source kind: {source['kind']}")

    feed = feedparser.parse(source["url"])
    articles: list[ArticleRecord] = []

    for entry in feed.entries:
        raw_url = entry.get("link", "")
        if not raw_url:
            continue

        normalized_url = normalize_url(raw_url)
        fetched_at = utcnow_iso()
        body_text = None
        metadata = {
            "feed_title": feed.feed.get("title"),
            "source_tags": source.get("tags", []),
            "entry_id": entry.get("id"),
        }

        try:
            response = fetch_url(raw_url, timeout_seconds=timeout_seconds)
            html = response.text
            body_text, extraction_metadata = extract_article_text(html, raw_url)
            if body_text:
                body_text = body_text[:max_article_chars]
            metadata["content_extraction"] = extraction_metadata

            cache_path = cache_dir / f"{hashlib.sha1(normalized_url.encode('utf-8')).hexdigest()}.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "url": raw_url,
                        "normalized_url": normalized_url,
                        "fetched_at": fetched_at,
                        "title": entry.get("title"),
                        "html_excerpt": html[:5000],
                    },
                    ensure_ascii=True,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            metadata["fetch_error"] = str(exc)

        summary = strip_html(entry.get("summary")) or strip_html(entry.get("description"))
        title = strip_html(entry.get("title")) or normalized_url

        articles.append(
            ArticleRecord(
                source_name=source["name"],
                publisher=source.get("publisher"),
                title=title,
                normalized_url=normalized_url,
                raw_url=raw_url,
                published_at=parse_published_at(entry),
                location_focus=source.get("location_focus"),
                summary=summary,
                author=strip_html(entry.get("author")),
                body_text=body_text,
                article_hash=make_article_hash(title, body_text),
                fetched_at=fetched_at,
                metadata=metadata,
            )
        )

    return articles
