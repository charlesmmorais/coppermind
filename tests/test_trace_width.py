from coppermind.intelligence.trace_width import min_trace_width_mm


def test_known_value_1a_external():
    # IPC-2221: ~0.30 mm for 1A, 1oz, 10C rise, external layer.
    assert abs(min_trace_width_mm(1.0) - 0.30) < 0.02


def test_internal_needs_more_copper_than_external():
    assert min_trace_width_mm(1.0, external=False) > min_trace_width_mm(1.0, external=True)


def test_more_current_needs_more_width():
    assert min_trace_width_mm(2.0) > min_trace_width_mm(1.0)


def test_more_copper_weight_needs_less_width():
    assert min_trace_width_mm(1.0, copper_oz=2.0) < min_trace_width_mm(1.0, copper_oz=1.0)


def test_zero_current_is_zero():
    assert min_trace_width_mm(0.0) == 0.0
