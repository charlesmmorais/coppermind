from coppermind.intelligence.placement import hpwl, neighbors, suggest_placement


def test_hpwl_single_net():
    pos = {"A": (0, 0), "B": (10, 0), "C": (10, 5)}
    assert hpwl(pos, {"N": ["A", "B", "C"]}) == 15.0  # 10 wide + 5 tall


def test_hpwl_ignores_singleton_nets():
    assert hpwl({"A": (0, 0)}, {"N": ["A"]}) == 0.0


def test_neighbors_from_shared_nets():
    adj = neighbors({"N1": ["A", "B"], "N2": ["B", "C"]})
    assert adj["B"] == {"A", "C"}


def test_barycenter_reduces_wirelength():
    pos = {"A": (0, 0), "B": (10, 0), "C": (5, 20)}
    nl = {"N": ["A", "B", "C"]}
    moved = suggest_placement(pos, nl, fixed={"A", "B"})
    assert hpwl(moved, nl) < hpwl(pos, nl)


def test_fixed_components_do_not_move():
    pos = {"A": (0, 0), "B": (10, 0)}
    moved = suggest_placement(pos, {"N": ["A", "B"]}, fixed={"A", "B"})
    assert moved == pos
