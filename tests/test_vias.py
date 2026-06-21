from coppermind.backends.ipc_mapping import plan_apply
from coppermind.domain import operations as ops
from coppermind.domain.diff import diff_boards


def test_add_via_and_diff_counts():
    b = ops.create_board("b", 50, 40)
    after = b.copy_deep()
    ops.add_via(after, 10, 10, net="GND")
    d = diff_boards(b, after)
    assert d.vias_added == 1 and not d.is_empty
    assert "vias" in d.summary()


def test_plan_includes_via_additions_and_removals():
    before = ops.create_board("b", 50, 40)
    after = before.copy_deep()
    ops.add_via(after, 1, 1, net="N")
    ops.add_via(after, 2, 2, net="N")
    plan = plan_apply(before, after)
    assert len(plan.vias_to_add) == 2

    after2 = before.copy_deep()
    ops.add_via(before, 5, 5)  # before now has 1 via, after2 has 0
    removed_id = before.vias[0].id
    assert plan_apply(before, after2).via_ids_to_remove == [removed_id]
