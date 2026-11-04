from app.compare import compare_cards


def card(agent, title, file, line, evidence=""):
    return {
        "agent_id": agent,
        "agent_name": agent,
        "status": "succeeded",
        "category": "review",
        "summary": title,
        "findings": [
            {
                "severity": "high",
                "title": title,
                "file": file,
                "line": line,
                "evidence": evidence,
                "recommendation": "",
            }
        ],
    }


def test_alignment_keeps_unique_findings_and_conflicts():
    cards = [
        card("codex", "Missing auth check", "src/a.py", 10, "no check"),
        card("claude", "Missing authentication check", "src/a.py", 12, "no check"),
        card("grok", "Use prepared statements for SQL", "src/a.py", 11, "string concat"),
        card("vscode", "Unique issue", "other.py", 3, "only here"),
        card("codex", "General note", None, None, "no file"),
    ]
    result = compare_cards(cards)
    alignment = result["alignment"]
    assert len(alignment["consensus"]) == 1
    assert set(alignment["consensus"][0]["agents"]) == {"claude", "codex"}
    assert any(item["title"] == "Unique issue" for item in alignment["single"])
    assert alignment["conflicts"]
    assert any(item["title"] == "General note" for item in alignment["unaligned"])
    assert "review" in result["by_category"]
