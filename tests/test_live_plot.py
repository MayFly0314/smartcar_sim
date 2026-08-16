"""实时波形面板：通道适配、滚动上限、跟随窗口、手动缩放退出跟随。"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import smartcar_sim.views.live_plot as live_plot_mod  # noqa: E402
from smartcar_sim.views.live_plot import LiveWavePanel  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_append_adapts_channel_count(app):
    p = LiveWavePanel()
    p.append([1.0])
    p.append([2.0, 20.0])       # 通道变多：新线历史补 None
    p.append([3.0, 30.0])
    assert [s.name for s in p._series] == ["CH1", "CH2"]
    assert p._series[0].values == [1.0, 2.0, 3.0]
    assert p._series[1].values == [None, 20.0, 30.0]


def test_channel_shrink_pads_none(app):
    p = LiveWavePanel()
    p.append([1.0, 10.0])
    p.append([2.0])             # 少发一个通道：缺的补 None
    assert p._series[1].values == [10.0, None]


def test_rolling_cap_trims_batch(app, monkeypatch):
    monkeypatch.setattr(live_plot_mod, "_MAX_POINTS", 100)
    monkeypatch.setattr(live_plot_mod, "_TRIM_SLACK", 20)
    p = LiveWavePanel()
    for i in range(121):
        p.append([float(i)])
    assert len(p._series[0].values) == 100   # 超过 100+20 才裁一次，裁回 100
    assert p._series[0].values[0] == 21.0
    assert p._series[0].values[-1] == 120.0


def test_follow_window_tracks_latest(app):
    p = LiveWavePanel()
    for i in range(600):
        p.append([float(i)])
    p._spin_win.setValue(100)
    p._flush()
    x0, x1 = p._curve.x_view()
    assert x1 == pytest.approx(599.0)
    assert x1 - x0 == pytest.approx(100.0)
    assert p._curve._cur == 599              # 游标钉在最新点


def test_fit_visible_uses_window_only(app):
    p = LiveWavePanel()
    for i in range(600):
        p.append([float(i)])
    p._spin_win.setValue(100)
    p._flush()
    # 可见窗口是 499..599，自动量程不该被 0 拉低
    assert p._curve._lo >= 400.0


def test_manual_zoom_exits_follow(app):
    p = LiveWavePanel()
    for i in range(600):
        p.append([float(i)])
    p._flush()
    assert p._chk_follow.isChecked()
    p._curve._zoom_x(300.0, 0.5)             # 模拟滚轮缩放
    assert not p._chk_follow.isChecked()


def test_manual_y_zoom_disables_autorange(app):
    p = LiveWavePanel()
    p.append([1.0])
    p._flush()
    p._on_y_range(-5.0, 5.0)
    assert not p._chk_auto.isChecked()
    assert (p._curve._lo, p._curve._hi) == (-5.0, 5.0)


def test_clear_resets(app):
    p = LiveWavePanel()
    p.append([1.0, 2.0])
    p.clear()
    assert p._series == []
    assert p._curve.frame_count() == 0
