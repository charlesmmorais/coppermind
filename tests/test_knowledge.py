import pytest

from coppermind.intelligence import knowledge as kb


def test_version_is_set():
    assert kb.KNOWLEDGE_BASE_VERSION


def test_rule_ids_unique_and_complete():
    rules = kb.all_rules()
    ids = [r.id for r in rules]
    assert len(ids) == len(set(ids)), "duplicate rule ids"
    for r in rules:
        assert r.id and r.title and r.statement, f"{r.id} incomplete"
        assert r.citation, f"{r.id} must cite a source"
        assert r.rationale, f"{r.id} must explain why"


def test_get_rule_and_unknown():
    assert kb.get_rule("EE.POWER.TRACE_WIDTH").citation == "IPC-2221"
    with pytest.raises(KeyError):
        kb.get_rule("EE.NOPE")
