from coppermind.backends.ipc_mapping import plan_apply
from coppermind.backends.units import mm_to_nm, nm_to_mm
from coppermind.domain import operations as ops


def test_mm_nm_round_trip():
    assert mm_to_nm(1.0) == 1_000_000
    assert mm_to_nm(0.25) == 250_000
    assert nm_to_mm(1_000_000) == 1.0
    assert abs(nm_to_mm(mm_to_nm(3.3)) - 3.3) < 1e-9


def test_plan_additions():
    before = ops.create_board("b", 50, 40)
    after = before.copy_deep()
    ops.add_component(after, "R1", "R_0805", 10, 10)
    ops.create_net(after, "LED1")
    ops.route_track(after, "LED1", (10, 10), (20, 10))

    plan = plan_apply(before, after)
    assert plan.nets_to_create == ["LED1"]
    assert [c.reference for c in plan.footprints_to_add] == ["R1"]
    assert len(plan.tracks_to_add) == 1
    assert plan.tracks_to_add[0].net == "LED1"
    assert not plan.is_empty


def test_plan_removals():
    before = ops.create_board("b", 50, 40)
    ops.add_component(before, "R1", "R_0805", 10, 10)
    ops.create_net(before, "N")
    ops.route_track(before, "N", (1, 1), (2, 2))
    after = before.copy_deep()
    del after.components["R1"]
    after.tracks.clear()

    removed_track_id = before.tracks[0].id
    plan = plan_apply(before, after)
    assert plan.component_refs_to_remove == ["R1"]
    assert plan.track_ids_to_remove == [removed_track_id]


def test_empty_plan_for_identical():
    b = ops.create_board("b", 50, 40)
    assert plan_apply(b, b.copy_deep()).is_empty
