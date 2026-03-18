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
PERSON_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
NON_PERSON_TERMS = {
    "battalion",
    "board",
    "bureau",
    "chief",
    "city",
    "council",
    "county",
    "department",
    "director",
    "division",
    "engagement",
    "field",
    "fire",
    "government",
    "health",
    "operations",
    "paramedic",
    "police",
    "program",
    "public",
    "rescue",
    "services",
    "state",
    "university",
    "volunteer",
}


@dataclass
class ExtractedPerson:
    person_key: str
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


def normalize_person_key(name: str, organization: str | None, address: str | None, home_location: str | None) -> str:
    def clean(value: str | None) -> str:
        return re.sub(r"\s+", " ", (value or "").strip()).lower()

    name_key = clean(name)
    org_key = clean(organization)
    address_key = clean(address)
    location_key = clean(home_location)
    parts = [name_key]
    if org_key:
        parts.append(f"org:{org_key}")
    elif address_key:
        parts.append(f"addr:{address_key}")
    elif location_key:
        parts.append(f"loc:{location_key}")
    return "|".join(parts)


def looks_like_person_name(name: str) -> bool:
    tokens = [token for token in re.split(r"\s+", name.strip()) if token]
    if len(tokens) < 2:
        return False
    lowered = [re.sub(r"[^a-z]", "", token.lower()) for token in tokens]
    if any(token in NON_PERSON_TERMS for token in lowered):
        return False
    if tokens[0].lower() == "the":
        return False
    return all(token[0].isupper() for token in tokens if token and token.lower() not in PERSON_SUFFIXES)


def fallback_extract_people(text: str) -> list[ExtractedPerson]:
    counts = Counter(match.group(1) for match in NAME_PATTERN.finditer(text))
    addresses = ADDRESS_PATTERN.findall(text)
    people: list[ExtractedPerson] = []
    for name, count in counts.most_common(25):
        if name.lower().startswith(("frederick ", "maryland ", "county ", "city ")):
            continue
        if not looks_like_person_name(name):
            continue
        address = addresses[0] if addresses else None
        home_location = "Frederick, Maryland" if "Frederick" in text else None
        people.append(
            ExtractedPerson(
                person_key=normalize_person_key(name, None, address, home_location),
                canonical_name=name,
                aliases=[name],
                primary_position=None,
                primary_organization=None,
                primary_address=address,
                home_location=home_location,
                notes="Fallback regex extraction. Low-confidence person record.",
                mention_count=count,
                confidence=0.25,
                role_in_article=None,
                organization=None,
                address=address,
                location_context=home_location,
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
      "person_key": "string",
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
- Set person_key to a stable lowercase key using the person's name plus the best available disambiguator from organization, address, or home location.
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
                                        "person_key": {"type": "string"},
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
                                        "person_key",
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
        return llm_extract_people(article, api_key=api_key, model=model, timeout_seconds=timeout_seconds)

    return fallback_extract_people(text)
