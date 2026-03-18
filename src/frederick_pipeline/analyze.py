from __future__ import annotations

from collections import defaultdict


def infer_connections(rows: list[dict], run_date: str) -> list[dict]:
    article_to_people: dict[int, list[dict]] = defaultdict(list)
    org_to_people: dict[str, list[dict]] = defaultdict(list)
    address_to_people: dict[str, list[dict]] = defaultdict(list)

    for row in rows:
        article_to_people[row["article_id"]].append(row)
        if row["organization"]:
            org_to_people[row["organization"].strip().lower()].append(row)
        if row["address"]:
            address_to_people[row["address"].strip().lower()].append(row)

    connections: list[dict] = []

    for article_id, mentions in article_to_people.items():
        mentions = sorted(mentions, key=lambda item: item["person_id"])
        for index, left in enumerate(mentions):
            for right in mentions[index + 1 :]:
                connections.append(
                    {
                        "run_date": run_date,
                        "person_a_id": left["person_id"],
                        "person_b_id": right["person_id"],
                        "connection_type": "co_mentioned_in_article",
                        "weight": 1.0,
                        "rationale": f"Both people were mentioned in article {article_id}.",
                        "source_article_ids": [article_id],
                    }
                )

    for organization, mentions in org_to_people.items():
        mentions = sorted(mentions, key=lambda item: item["person_id"])
        for index, left in enumerate(mentions):
            for right in mentions[index + 1 :]:
                connections.append(
                    {
                        "run_date": run_date,
                        "person_a_id": left["person_id"],
                        "person_b_id": right["person_id"],
                        "connection_type": "shared_organization",
                        "weight": 2.0,
                        "rationale": f"Both people were linked to {organization}.",
                        "source_article_ids": sorted({left["article_id"], right["article_id"]}),
                    }
                )

    for address, mentions in address_to_people.items():
        mentions = sorted(mentions, key=lambda item: item["person_id"])
        for index, left in enumerate(mentions):
            for right in mentions[index + 1 :]:
                connections.append(
                    {
                        "run_date": run_date,
                        "person_a_id": left["person_id"],
                        "person_b_id": right["person_id"],
                        "connection_type": "shared_address",
                        "weight": 3.0,
                        "rationale": f"Both people were linked to {address}.",
                        "source_article_ids": sorted({left["article_id"], right["article_id"]}),
                    }
                )

    return connections


def render_report(run_date: str, articles: list[dict], people: list[dict], connections: list[dict]) -> str:
    lines = [
        f"# Frederick Daily Network Report - {run_date}",
        "",
        "## Overview",
        f"- Articles reviewed: {len(articles)}",
        f"- Documented individuals: {len(people)}",
        f"- Inferred connections: {len(connections)}",
        "",
        "## People Seen Today",
    ]

    for person in people[:30]:
        details = " | ".join(
            part
            for part in [
                person["canonical_name"],
                person.get("primary_position") or "",
                person.get("primary_organization") or "",
                person.get("primary_address") or "",
            ]
            if part
        )
        lines.append(f"- {details}")

    lines.extend(["", "## Interesting Connections"])

    if not connections:
        lines.append("- No strong connections were inferred today.")
    else:
        for connection in connections[:50]:
            lines.append(
                f"- {connection['person_a_name']} <-> {connection['person_b_name']} | {connection['connection_type']} | {connection['rationale']}"
            )

    return "\n".join(lines) + "\n"
