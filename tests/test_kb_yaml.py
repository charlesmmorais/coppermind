import pytest

from coppermind.intelligence import knowledge as kb


def test_loads_from_yaml_with_version_and_rules():
    assert kb.KNOWLEDGE_BASE_VERSION
    rules = kb.all_rules()
    assert len(rules) >= 7  # data-driven KB expanded beyond the original 3


def test_rules_complete_and_unique():
    rules = kb.all_rules()
    ids = [r.id for r in rules]
    assert len(ids) == len(set(ids))
    for r in rules:
        assert r.id and r.title and r.statement and r.citation and r.rationale


def test_get_rule_and_unknown():
    assert kb.get_rule("EE.POWER.TRACE_WIDTH").citation == "IPC-2221"
    with pytest.raises(KeyError):
        kb.get_rule("EE.NOPE")


def test_override_rules_file_via_env(tmp_path, monkeypatch):
    custom = tmp_path / "rules.yaml"
    custom.write_text(
        'version: "9.9"\n'
        "rules:\n"
        "  - id: X.ONE\n"
        "    title: One\n"
        "    category: test\n"
        "    statement: do a thing\n"
        "    citation: nowhere\n"
        "    rationale: because\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("COPPERMIND_RULES", str(custom))
    kb.reload_rules()
    try:
        rules = kb.all_rules()
        assert [r.id for r in rules] == ["X.ONE"]
        assert kb.get_rule("X.ONE").category == "test"
    finally:
        monkeypatch.delenv("COPPERMIND_RULES", raising=False)
        kb.reload_rules()  # restore default KB for other tests
