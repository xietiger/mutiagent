from __future__ import annotations

import json
import urllib.request

from app.compare import compare_cards


def rule_summary(cards: list[dict], alignment: dict) -> str:
    lines = []
    for card in cards:
        summary = (card.get("summary") or "").strip()
        if summary:
            lines.append(f"{card.get('agent_name') or card.get('agent_id')}：{summary}")
    lines.append(
        "对齐结果：共识 {consensus} 项，单独发现 {single} 项，冲突 {conflicts} 项。共识只表示多个 Agent 提出了相近问题，不是正确性投票。".format(
            consensus=len(alignment.get("consensus") or []),
            single=len(alignment.get("single") or []),
            conflicts=len(alignment.get("conflicts") or []),
        )
    )
    return "\n".join(lines)[:4000]


def _safe_payload(cards: list[dict], alignment: dict) -> dict:
    return {
        "summaries": [
            {
                "agent": card.get("agent_name"),
                "summary": (card.get("summary") or "")[:1000],
                "notes": (card.get("notes") or "")[:500],
                "findings": [
                    {
                        "severity": item.get("severity"),
                        "title": item.get("title"),
                        "file": item.get("file"),
                        "line": item.get("line"),
                        "recommendation": (item.get("recommendation") or "")[:300],
                    }
                    for item in (card.get("findings") or [])[:30]
                ],
            }
            for card in cards
        ],
        "alignment": {
            "consensus": len(alignment.get("consensus") or []),
            "single": len(alignment.get("single") or []),
            "conflicts": len(alignment.get("conflicts") or []),
        },
    }


def summarize(cards: list[dict], *, summary_url: str | None) -> tuple[str, str]:
    compared = compare_cards(cards)
    alignment = compared["alignment"]
    ruled = rule_summary(cards, alignment)
    if not summary_url:
        return ruled, "rule"
    try:
        request = urllib.request.Request(
            summary_url,
            data=json.dumps(_safe_payload(cards, alignment), ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(8000).decode("utf-8", errors="replace").strip()
        if not body:
            return ruled, "rule"
        return body[:4000], "llm"
    except Exception:
        return ruled, "rule"
