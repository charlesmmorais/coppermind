from coppermind.backends.memory_backend import MemoryBackend
from coppermind.domain import operations as ops
from coppermind.transactions.manager import Document


def _doc():
    b = ops.create_board("d", 50, 40)
    be = MemoryBackend()
    be.apply(b)
    return Document(b, be)


def test_commit_records_timeline_entry():
    doc = _doc()
    ops.add_component(doc.working(), "R1", "R_0805", 10, 10)
    doc.commit(label="place R1")
    tl = doc.timeline()
    assert len(tl) == 1
    assert tl[0].step == 1 and tl[0].label == "place R1"
    assert tl[0].components == 1


def test_blocked_commit_does_not_record():
    doc = _doc()
    ops.add_component(doc.working(), "R1", "R_0805", 999, 999)  # outside board
    assert not doc.commit().committed
    assert doc.timeline() == []


def test_timeline_steps_increment():
    doc = _doc()
    ops.add_component(doc.working(), "R1", "R_0805", 10, 10)
    doc.commit(label="a")
    ops.add_component(doc.working(), "R2", "R_0805", 20, 10)
    doc.commit(label="b")
    steps = [e.step for e in doc.timeline()]
    labels = [e.label for e in doc.timeline()]
    assert steps == [1, 2] and labels == ["a", "b"]
