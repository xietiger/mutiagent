import json

import pytest

from app.output.parse import parse_claude, parse_codex, parse_grok, parse_kimi
from app.output.validate import ContractError, validate_and_normalize


def test_valid_contract():
    result = validate_and_normalize(
        {
            "schema_version": 1,
            "summary": "发现一处重定向问题",
            "category": "review",
            "findings": [
                {
                    "severity": "high",
                    "title": "未校验重定向目标",
                    "file": "./src/auth.py",
                    "line": "42",
                    "evidence": "redirect_url 直接来自请求参数",
                    "recommendation": "使用允许列表",
                    "confidence": "high",
                }
            ],
            "notes": "",
            "follow_ups": [],
            "status": "succeeded",
        }
    )
    assert result["findings"][0]["file"] == "src/auth.py"
    assert result["findings"][0]["line"] == 42
    assert "status" not in result


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 1, "summary": "x", "category": "nope", "findings": [], "notes": "", "follow_ups": []},
        {"schema_version": 1, "summary": "x", "category": "review", "findings": [{"severity": "high", "title": "t", "file": "/etc/passwd"}], "notes": "", "follow_ups": []},
        {"schema_version": 1, "summary": "x", "category": "review", "findings": [{"severity": "high", "title": "t", "file": "../secret"}], "notes": "", "follow_ups": []},
        {"schema_version": 2, "summary": "x", "category": "review", "findings": [], "notes": "", "follow_ups": []},
    ],
)
def test_rejects_bad_contract(payload):
    with pytest.raises(ContractError):
        validate_and_normalize(payload)


def test_parse_structured_outputs():
    contract = {
        "schema_version": 1,
        "summary": "ok",
        "category": "review",
        "findings": [],
        "notes": "",
        "follow_ups": [],
    }
    parsed, _session, strict = parse_codex(json.dumps(contract), "")
    assert strict and parsed["summary"] == "ok"
    parsed, session, strict = parse_claude(json.dumps({"structured_output": contract, "session_id": "s1", "result": "ignored"}))
    assert strict and session == "s1"
    parsed, session, strict = parse_grok(json.dumps({"text": json.dumps(contract), "sessionId": "g1"}))
    assert strict and session == "g1"
    parsed, session, strict = parse_kimi(
        json.dumps({"role": "assistant", "content": json.dumps(contract)}) + "\n"
        + json.dumps({"role": "meta", "session_id": "k1"})
    )
    assert strict and session == "k1"
    parsed, _session, strict = parse_kimi("not json")
    assert not strict
    assert "非严格回退" in parsed["notes"]
