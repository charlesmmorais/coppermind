"""Stable ids make the diff correct under reordering — the core robustness win.

Before stable ids, tracks/vias were diffed by list position, so any reorder or
mid-list insert produced a wrong plan (phantom modify/remove). With ids, only
real changes show up.
"""

from coppermind.backends.ipc_mapping import plan_apply
from coppermind.domain import operations as ops
from coppermind.domain.diff import diff_boards


def _board_with_two_tracks():
    b = ops.create_board("b", 50, 40)
    ops.create_net(b, "N")
    ops.route_track(b, "N", (0, 0), (10, 0))
    ops.route_track(b, "N", (0, 5), (10, 5))
    return b


def test_reorder_is_a_noop_in_plan():
    before = _board_with_two_tracks()
    after = before.copy_deep()
    after.tracks.reverse()  # same items, different order
    plan = plan_apply(before, after)
    assert plan.is_empty, "reordering identical tracks must not produce changes"
    assert diff_boards(before, after).is_empty


def test_midlist_insert_only_adds_one():
    before = _board_with_two_tracks()
    after = before.copy_deep()
    new = ops.route_track(after, "N", (0, 2), (10, 2))  # appended
    after.tracks.insert(1, after.tracks.pop())          # move it to the middle
    plan = plan_apply(before, after)
    assert [t.id for t in plan.tracks_to_add] == [new.id]
    assert plan.tracks_to_modify == [] and plan.track_ids_to_remove == []


def test_ids_are_unique_and_preserved_across_copy():
    b = _board_with_two_tracks()
    ids = [t.id for t in b.tracks]
    assert len(set(ids)) == 2
    assert [t.id for t in b.copy_deep().tracks] == ids  # copy preserves ids


def test_modify_keeps_id():
    b = _board_with_two_tracks()
    original = b.tracks[0].id
    b.tracks[0] = b.tracks[0].model_copy(update={"width": 0.4})
    assert b.tracks[0].id == original
