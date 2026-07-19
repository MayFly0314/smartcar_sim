import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smartcar_sim.run.protocol import FrameResult  # noqa: E402
from smartcar_sim.views.watch_panel import aggregate_watches  # noqa: E402


def _frame(idx: int, watches: dict[str, float]) -> FrameResult:
    fr = FrameResult(index=idx)
    fr.watches = watches
    return fr


def test_aggregate_basic_order_and_values():
    frames = [
        _frame(0, {"error": -3.0, "state": 1.0}),
        _frame(1, {"error": 5.0, "state": 1.0}),
        _frame(2, {"error": 0.0, "state": 2.0}),
    ]
    data = aggregate_watches(frames)
    assert not data.empty
    assert data.frame_count == 3
    assert [t.name for t in data.tracks] == ["error", "state"], "变量应按首次出现顺序"
    err = data.tracks[0]
    assert err.values == [-3.0, 5.0, 0.0]
    assert err.vmin == -3.0 and err.vmax == 5.0


def test_aggregate_missing_frames():
    # 条件调用：某些帧没写 -> None；迟到变量之前的帧预填 None
    frames = [
        _frame(0, {"a": 1.0}),
        _frame(1, {}),
        _frame(2, {"a": 3.0, "late": 9.0}),
    ]
    data = aggregate_watches(frames)
    a = data.tracks[0]
    late = data.tracks[1]
    assert a.values == [1.0, None, 3.0]
    assert late.values == [None, None, 9.0]
    assert late.vmin == late.vmax == 9.0


def test_aggregate_constant_series():
    frames = [_frame(i, {"c": 7.0}) for i in range(4)]
    data = aggregate_watches(frames)
    t = data.tracks[0]
    assert t.vmin == t.vmax == 7.0  # 面板据此走居中横线分支，不除零


def test_aggregate_nonfinite_isolated():
    frames = [
        _frame(0, {"x": 1.0}),
        _frame(1, {"x": math.inf}),
        _frame(2, {"x": math.nan}),
        _frame(3, {"x": 2.0}),
    ]
    data = aggregate_watches(frames)
    t = data.tracks[0]
    assert t.vmin == 1.0 and t.vmax == 2.0, "inf/nan 不应污染 min/max"


def test_aggregate_single_frame_and_empty():
    single = aggregate_watches([_frame(0, {"v": 4.5})])
    assert single.frame_count == 1
    assert single.tracks[0].values == [4.5]

    empty = aggregate_watches([_frame(0, {}), _frame(1, {})])
    assert empty.empty

    assert aggregate_watches([]).empty
