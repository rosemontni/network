from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

import requests


NAME_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b")
ADDRESS_PATTERN = re.compile(
    r"\b\d{1,6}\s+[A-Z0-9][A-Za-z0-9.\- ]+\s(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct)\b",
    re.IGNORECASE,
)


@dataclass
class ExtractedPerson:
    canonical_name: str
    aliases: list[str]
    primary_position: str | None
    primary_organization: str | None
    primary_address: str | None
    home_location: str | None
    notes: str | None
    mention_count: int
    confidence: float | None
    role_in_article: str | None
    organization: str | None
    address: str | None
    location_context: str | None
    quote_text: str | None
    summary: str | None
    metadata: dict


def fallback_extract_people(text: str) -> list[ExtractedPerson]:
    counts = Counter(match.group(1) for match in NAME_PATTERN.finditer(text))
    addresses = ADDRESS_PATTERN.findall(text)
    people: list[ExtractedPerson] = []
    for name, count in counts.most_common(25):
        if name.lower().startswith(("frederick ", "maryland ", "county ", "city ")):
            continue
        people.append(
            ExtractedPerson(
                canonical_name=name,
                aliases=[name],
                primary_position=None,
                primary_organization=None,
                primary_address=addresses[0] if addresses else None,
                home_location="Frederick, Maryland" if "Frederick" in text else None,
                notes="Fallback regex extraction.",
                mention_count=count,
                confidence=0.25,
                role_in_article=None,
                organization=None,
                address=addresses[0] if addresses else None,
                location_context="Frederick, Maryland" if "Frederick" in text else None,
                quote_text=None,
                summary="Mentioned in article text.",
                metadata={"extractor": "fallback-regex"},
            )
        )
    return people


def build_prompt(article: dict) -> str:
    return f"""
You are extracting structured public-information records from one news article.

Return strict JSON with this shape:
{{
  "people": [
    {{
      "canonical_name": "string",
      "aliases": ["string"],
      "primary_position": "string or null",
      "primary_organization": "string or null",
      "primary_address": "string or null",
      "home_location": "string or null",
      "notes": "string or null",
      "mention_count": 1,
      "confidence": 0.0,
      "role_in_article": "string or null",
      "organization": "string or null",
      "address": "string or null",
      "location_context": "string or null",
      "quote_text": "string or null",
      "summary": "string or null",
      "metadata": {{
        "source_basis": ["facts copied or normalized from article only"],
        "article_entities": ["related organizations, offices, or places"]
      }}
    }}
  ]
}}

Rules:
- Only include people explicitly present in the article.
- Do not invent addresses. Use null unless the article directly states an address or public office location tied to that person.
- Prefer public-facing roles, titles, offices, employers, elected positions, affiliations, neighborhoods, and institutions.
- If the article gives only a city or neighborhood, put that in home_location or location_context, not in address.
- Keep summaries short and factual.

Article title: {article["title"]}
Article publisher: {article["publisher"] or ""}
Article published_at: {article["published_at"] or ""}
Article summary: {article["summary"] or ""}

Article body:
{article["body_text"] or ""}
""".strip()


def llm_extract_people(article: dict, api_key: str, model: str, timeout_seconds: int) -> list[ExtractedPerson]:
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "input": build_prompt(article),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "article_people",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "people": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "canonical_name": {"type": "string"},
                                        "aliases": {"type": "array", "items": {"type": "string"}},
                                        "primary_position": {"type": ["string", "null"]},
                                        "primary_organization": {"type": ["string", "null"]},
                                        "primary_address": {"type": ["string", "null"]},
                                        "home_location": {"type": ["string", "null"]},
                                        "notes": {"type": ["string", "null"]},
                                        "mention_count": {"type": "integer"},
                                        "confidence": {"type": ["number", "null"]},
                                        "role_in_article": {"type": ["string", "null"]},
                                        "organization": {"type": ["string", "null"]},
                                        "address": {"type": ["string", "null"]},
                                        "location_context": {"type": ["string", "null"]},
                                        "quote_text": {"type": ["string", "null"]},
                                        "summary": {"type": ["string", "null"]},
                                        "metadata": {"type": "object"},
                                    },
                                    "required": [
                                        "canonical_name",
                                        "aliases",
                                        "primary_position",
                                        "primary_organization",
                                        "primary_address",
                                        "home_location",
                                        "notes",
                                        "mention_count",
                                        "confidence",
                                        "role_in_article",
                                        "organization",
                                        "address",
                                        "location_context",
                                        "quote_text",
                                        "summary",
                                        "metadata"
                                    ],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "required": ["people"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            },
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    text_output = payload["output"][0]["content"][0]["text"]
    parsed = json.loads(text_output)
    return [ExtractedPerson(**person) for person in parsed.get("people", [])]


def extract_people(article: dict, api_key: str | None, model: str, timeout_seconds: int) -> list[ExtractedPerson]:
    text = article.get("body_text") or article.get("summary") or ""
    if not text.strip():
        return []

    if api_key:
        try:
            return llm_extract_people(article, api_key=api_key, model=model, timeout_seconds=timeout_seconds)
        except Exception:  # noqa: BLE001
            return fallback_extract_people(text)

    return fallback_extract_people(text)
