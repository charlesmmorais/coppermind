from coppermind.backends.ipc_mapping import plan_apply
from coppermind.domain import operations as ops


def _base():
    b = ops.create_board("b", 50, 40)
    ops.add_component(b, "R1", "R_0805", 10, 10)
    ops.create_net(b, "N")
    ops.route_track(b, "N", (1, 1), (2, 2))
    return b


def test_move_is_modify_not_add_remove():
    before = _base()
    after = before.copy_deep()
    ops.move_component(after, "R1", 30, 30)
    plan = plan_apply(before, after)
    assert [c.reference for c in plan.components_to_modify] == ["R1"]
    assert plan.footprints_to_add == []
    assert plan.component_refs_to_remove == []


def test_edit_value_is_modify():
    before = _base()
    after = before.copy_deep()
    ops.edit_component(after, "R1", value="330")
    plan = plan_apply(before, after)
    assert [c.value for c in plan.components_to_modify] == ["330"]


def test_delete_is_removal():
    before = _base()
    after = before.copy_deep()
    ops.delete_component(after, "R1")
    plan = plan_apply(before, after)
    assert plan.component_refs_to_remove == ["R1"]
    assert not plan.components_to_modify


def test_track_modify_detected_by_id():
    before = _base()
    after = before.copy_deep()
    tid = after.tracks[0].id
    after.tracks[0] = after.tracks[0].model_copy(update={"width": 0.5})
    plan = plan_apply(before, after)
    assert [t.id for t in plan.tracks_to_modify] == [tid]   # same id, modified
    assert plan.tracks_to_add == [] and plan.track_ids_to_remove == []


def test_track_add_and_remove_by_id():
    before = _base()
    after = before.copy_deep()
    ops.route_track(after, "N", (3, 3), (4, 4))
    assert len(plan_apply(before, after).tracks_to_add) == 1

    after2 = before.copy_deep()
    removed_id = after2.tracks[0].id
    after2.tracks.clear()
    assert plan_apply(before, after2).track_ids_to_remove == [removed_id]
