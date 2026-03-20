from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

import requests


NAME_PATTERN = re.compile(r"\b([A-Z][A-Za-z]+(?:[-'][A-Za-z]+)?(?:\s+(?:[A-Z][A-Za-z]+(?:[-'][A-Za-z]+)?|[A-Z]\.)){1,3})\b")
ADDRESS_PATTERN = re.compile(
    r"\b\d{1,6}\s+[A-Z0-9][A-Za-z0-9.\- ]+\s(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct)\b",
    re.IGNORECASE,
)
PERSON_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
TITLE_PREFIXES = {
    "councilman",
    "councilmember",
    "councilwoman",
    "delegate",
    "dr",
    "chief",
    "commissioner",
    "director",
    "mayor",
    "mr",
    "mrs",
    "ms",
    "officer",
    "president",
    "secretary",
    "senator",
    "sheriff",
}
ORGANIZATION_SUFFIXES = {
    "association",
    "associates",
    "commission",
    "conservancy",
    "council",
    "department",
    "division",
    "hotel",
    "inc",
    "initiative",
    "library",
    "office",
    "partners",
    "society",
    "stoppers",
    "systems",
    "team",
    "unit",
}
NON_PERSON_FIRST_TOKENS = {
    "america",
    "annual",
    "crime",
    "design",
    "emergency",
    "free",
    "for",
    "go",
    "got",
    "how",
    "monday",
    "mount",
    "national",
    "neighborhood",
    "on",
    "read",
    "several",
    "starting",
    "stay",
    "text",
    "top",
    "tornado",
    "to",
}
NON_PERSON_LAST_TOKENS = {
    "act",
    "aid",
    "alert",
    "analysts",
    "application",
    "cake",
    "center",
    "commission",
    "conservancy",
    "councils",
    "element",
    "hospital",
    "management",
    "more",
    "noon",
    "office",
    "partners",
    "planning",
    "road",
    "sportswear",
    "stories",
    "street",
    "survey",
    "tannery",
    "thunderstorm",
    "warning",
}
NON_PERSON_TERMS = {
    "annual",
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
    "historic",
    "hospitality",
    "hotel",
    "library",
    "local",
    "manager",
    "operations",
    "paramedic",
    "police",
    "planner",
    "program",
    "project",
    "public",
    "rescue",
    "room",
    "satisfaction",
    "scene",
    "street",
    "survey",
    "services",
    "state",
    "supervisors",
    "spring",
    "university",
    "volunteer",
    "work",
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
    if lowered[0] in NON_PERSON_FIRST_TOKENS or lowered[-1] in NON_PERSON_LAST_TOKENS:
        return False
    if tokens[0].lower() == "the":
        return False
    for token in tokens:
        cleaned = re.sub(r"[^A-Za-z'.-]", "", token)
        if not cleaned:
            return False
        if token.lower() not in PERSON_SUFFIXES and not cleaned[0].isupper():
            return False
    return True


def normalize_candidate_name(name: str) -> tuple[str, str | None]:
    tokens = [token for token in re.split(r"\s+", name.strip()) if token]
    if not tokens:
        return "", None
    prefix = re.sub(r"[^a-z]", "", tokens[0].lower())
    role = None
    if prefix in TITLE_PREFIXES:
        role = tokens[0]
        tokens = tokens[1:]
    if len(tokens) < 2:
        return "", role
    cleaned = " ".join(tokens)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned, role


def extract_occurrence_snippets(text: str, name: str) -> list[str]:
    snippets: list[str] = []
    for match in re.finditer(re.escape(name), text):
        start = max(0, match.start() - 120)
        end = min(len(text), match.end() + 120)
        snippet = re.sub(r"\s+", " ", text[start:end]).strip()
        if snippet and snippet not in snippets:
            snippets.append(snippet)
        if len(snippets) >= 3:
            break
    return snippets


def infer_fields_from_occurrence(text: str, name: str, prefixed_role: str | None) -> tuple[str | None, str | None, str | None, str | None]:
    role = prefixed_role
    organization = None
    address = None
    location_context = "Frederick, Maryland" if "Frederick" in text else None

    pattern = re.compile(rf"{re.escape(name)},\s*([^.,;\n]{{3,100}})")
    role_match = pattern.search(text)
    if role_match and not role:
        candidate = role_match.group(1).strip()
        if len(candidate.split()) <= 12:
            role = candidate

    org_match = re.search(rf"{re.escape(name)}[^.\n]{{0,80}}\b(?:of|with|from|at)\s+([A-Z][A-Za-z&.\- ]{{3,80}})", text)
    if org_match:
        organization = org_match.group(1).strip(" ,.;")

    address_match = ADDRESS_PATTERN.search(text)
    if address_match:
        address = address_match.group(0)

    return role, organization, address, location_context


def calculate_bootstrap_confidence(
    name: str,
    mention_count: int,
    role: str | None,
    organization: str | None,
    address: str | None,
    snippets: list[str],
) -> float:
    confidence = 0.15
    if mention_count >= 2:
        confidence += 0.1
    if role:
        confidence += 0.15
    if organization:
        confidence += 0.1
    if address:
        confidence += 0.05
    if any("@" in snippet or re.search(r"\b\d{3}[-.)\s]\d{3}[-.\s]\d{4}\b", snippet) for snippet in snippets):
        confidence += 0.1
    if len(name.split()) >= 2:
        confidence += 0.05
    return round(min(confidence, 0.6), 2)


def is_plausible_person_record(
    name: str,
    role: str | None,
    organization: str | None,
    snippets: list[str],
    confidence: float,
) -> bool:
    lowered_tokens = [re.sub(r"[^a-z]", "", token.lower()) for token in name.split()]
    if not lowered_tokens:
        return False

    if lowered_tokens[-1] in ORGANIZATION_SUFFIXES:
        return False

    if len(lowered_tokens) == 2 and all(len(token) <= 2 for token in lowered_tokens):
        return False

    text_blob = " ".join(snippets).lower()
    has_contact_cue = any(marker in text_blob for marker in ("@", "contact", "phone", "call", "director", "manager", "planner"))
    has_person_shape = len(lowered_tokens) >= 2 and all(token and token[0].isalpha() for token in lowered_tokens)

    if role or has_contact_cue:
        return True

    if confidence >= 0.4 and has_person_shape and lowered_tokens[-1] not in NON_PERSON_LAST_TOKENS:
        return True

    return False


def fallback_extract_people(text: str) -> list[ExtractedPerson]:
    counts = Counter()
    prefixed_roles: dict[str, str | None] = {}
    for match in NAME_PATTERN.finditer(text):
        raw_name = match.group(1)
        normalized_name, prefixed_role = normalize_candidate_name(raw_name)
        if not normalized_name:
            continue
        counts[normalized_name] += 1
        prefixed_roles.setdefault(normalized_name, prefixed_role)

    people: list[ExtractedPerson] = []
    for name, count in counts.most_common(25):
        if name.lower().startswith(("frederick ", "maryland ", "county ", "city ")):
            continue
        if not looks_like_person_name(name):
            continue
        role, organization, address, location_context = infer_fields_from_occurrence(text, name, prefixed_roles.get(name))
        home_location = location_context
        snippets = extract_occurrence_snippets(text, name)
        confidence = calculate_bootstrap_confidence(
            name=name,
            mention_count=count,
            role=role,
            organization=organization,
            address=address,
            snippets=snippets,
        )
        if not is_plausible_person_record(
            name=name,
            role=role,
            organization=organization,
            snippets=snippets,
            confidence=confidence,
        ):
            continue
        metadata = {
            "extractor": "fallback-regex",
            "occurrence_snippets": snippets,
        }
        people.append(
            ExtractedPerson(
                person_key=normalize_person_key(name, organization, address, home_location),
                canonical_name=name,
                aliases=[name],
                primary_position=role,
                primary_organization=organization,
                primary_address=address,
                home_location=home_location,
                notes="Bootstrap extraction from repeated full-name occurrences and nearby context.",
                mention_count=count,
                confidence=confidence,
                role_in_article=role,
                organization=organization,
                address=address,
                location_context=home_location,
                quote_text=None,
                summary=snippets[0] if snippets else "Mentioned in article text.",
                metadata=metadata,
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
        try:
            return llm_extract_people(article, api_key=api_key, model=model, timeout_seconds=timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            fallback_people = fallback_extract_people(text)
            for person in fallback_people:
                person.metadata["llm_error"] = str(exc)
            return fallback_people

    return fallback_extract_people(text)
