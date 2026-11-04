from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

STOP = {
    "the",
    "a",
    "an",
    "of",
    "to",
    "and",
    "or",
    "in",
    "on",
    "for",
    "with",
    "is",
    "be",
    "this",
    "that",
    "的",
    "了",
    "和",
    "与",
    "或",
    "在",
    "是",
    "不",
    "一个",
}


def normalize_file(value: object) -> str | None:
    if not value or not isinstance(value, str):
        return None
    text = value.replace("\\", "/").strip()
    if text.startswith("./"):
        text = text[2:]
    if not text or text.startswith("/") or ".." in text.split("/"):
        return None
    return text


def _tokens(text: str) -> set[str]:
    lowered = text.lower()
    cleaned = re.sub(r"[^\w\s]", " ", lowered, flags=re.UNICODE)
    words = {word for word in cleaned.split() if word not in STOP and len(word) > 1}
    grams: set[str] = set()
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", lowered):
        grams.update(chunk[index : index + 2] for index in range(len(chunk) - 1))
    return words | grams


def similarity(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens and not right_tokens:
        overlap = 1.0
    elif not left_tokens or not right_tokens:
        overlap = 0.0
    else:
        overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    raw = SequenceMatcher(None, left.lower(), right.lower()).ratio()
    return 0.55 * overlap + 0.45 * raw


def _near(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        return abs(int(left) - int(right)) <= 3
    except (TypeError, ValueError):
        return False


def _phrase(finding: dict) -> str:
    return f"{finding.get('title', '')} {finding.get('evidence', '')}"


class _Union:
    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, index: int) -> int:
        while self.parent[index] != index:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def union(self, left: int, right: int) -> None:
        self.parent[self.find(left)] = self.find(right)


def align_findings(cards: list[dict]) -> dict:
    items = []
    unaligned = []
    for card in cards:
        for finding in card.get("findings") or []:
            record = {
                "agent_id": card.get("agent_id"),
                "agent_name": card.get("agent_name"),
                "severity": finding.get("severity"),
                "title": finding.get("title"),
                "file": normalize_file(finding.get("file")),
                "line": finding.get("line"),
                "evidence": finding.get("evidence") or "",
                "recommendation": finding.get("recommendation") or "",
            }
            if not record["file"]:
                unaligned.append(record)
            else:
                items.append(record)
    groups = _Union(len(items))
    conflicts = []
    for left in range(len(items)):
        for right in range(left + 1, len(items)):
            if items[left]["file"] != items[right]["file"] or not _near(items[left]["line"], items[right]["line"]):
                continue
            score = similarity(_phrase(items[left]), _phrase(items[right]))
            if score >= 0.55:
                groups.union(left, right)
            elif score < 0.35:
                conflicts.append((left, right, round(score, 3)))
    clustered: dict[int, list[int]] = defaultdict(list)
    for index in range(len(items)):
        clustered[groups.find(index)].append(index)
    consensus = []
    consensus_indexes = set()
    for indexes in clustered.values():
        agents = {items[index]["agent_id"] for index in indexes}
        if len(indexes) < 2 or len(agents) < 2:
            continue
        sample = items[indexes[0]]
        consensus.append(
            {
                "file": sample["file"],
                "line": sample["line"],
                "agents": sorted(str(agent) for agent in agents if agent),
                "findings": [items[index] for index in indexes],
            }
        )
        consensus_indexes.update(indexes)
    conflict_rows = []
    conflict_indexes = set()
    seen = set()
    for left, right, score in conflicts:
        if groups.find(left) == groups.find(right):
            continue
        key = tuple(sorted((left, right)))
        if key in seen:
            continue
        seen.add(key)
        conflict_indexes.update((left, right))
        conflict_rows.append(
            {
                "file": items[left]["file"],
                "line": items[left]["line"],
                "similarity": score,
                "findings": [items[left], items[right]],
            }
        )
    single = [
        items[index]
        for index in range(len(items))
        if index not in consensus_indexes and index not in conflict_indexes
    ]
    return {
        "consensus": consensus,
        "single": single,
        "conflicts": conflict_rows,
        "unaligned": unaligned,
    }


def compare_cards(cards: list[dict]) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for card in cards:
        grouped[card.get("category") or "other"].append(
            {
                "agent_id": card.get("agent_id"),
                "agent_name": card.get("agent_name"),
                "status": card.get("status"),
                "summary": card.get("summary"),
                "findings": card.get("findings") or [],
                "notes": card.get("notes") or "",
                "version": card.get("version"),
                "execution_mode": card.get("execution_mode"),
                "review_profile": card.get("review_profile"),
            }
        )
    return {"by_category": dict(grouped), "alignment": align_findings(cards)}
