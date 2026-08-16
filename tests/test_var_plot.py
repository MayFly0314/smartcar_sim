"""多变量曲线窗口：叠加、勾选隐藏、只看一条、归一化。

调 PI 速度环时必须能把目标速度和当前转速叠在同一张图上，
所以这些行为都要有回归保护。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from smartcar_sim.views.var_plot import VarPlotDialog, color_for  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _catalog():
    n = 60
    return {
        "目标速度": [0.0] * 10 + [4500.0] * (n - 10),
        "当前转速": [float(i) * 75 for i in range(n)],
        "PWM": [float((i % 20) - 10) * 50 for i in range(n)],
        "常量": [3.0] * n,
    }


def _dlg(app, first="当前转速"):
    cat = _catalog()
    return VarPlotDialog(first, cat[first], provider=lambda: dict(cat)), cat


def test_starts_with_single_series(app):
    dlg, cat = _dlg(app)
    assert dlg.names() == ["当前转速"]
    # 下拉里应该列出其余变量
    items = [dlg._combo_add.itemText(i) for i in range(dlg._combo_add.count())]
    assert set(items) == set(cat) - {"当前转速"}


def test_overlay_additional_series(app):
    dlg, _ = _dlg(app)
    dlg._combo_add.setCurrentIndex(dlg._combo_add.findText("目标速度"))
    dlg._add_from_combo()
    assert dlg.names() == ["当前转速", "目标速度"]
    # 叠加后下拉里不该再出现已在图上的变量
    items = [dlg._combo_add.itemText(i) for i in range(dlg._combo_add.count())]
    assert "目标速度" not in items


def test_colors_are_stable_when_hiding(app):
    """颜色跟变量走，不跟可见序号走——否则隐藏一条会让其余线全换色。"""
    dlg, _ = _dlg(app)
    for name in ("目标速度", "PWM"):
        dlg._combo_add.setCurrentIndex(dlg._combo_add.findText(name))
        dlg._add_from_combo()
    before = {s.name: s.color.name() for s in dlg._series}
    assert len(set(before.values())) == 3        # 三条线三种颜色

    dlg._on_row_toggled("目标速度", False)
    after = {s.name: s.color.name() for s in dlg._series}
    assert after == before


def test_solo_shows_only_one(app):
    dlg, _ = _dlg(app)
    for name in ("目标速度", "PWM"):
        dlg._combo_add.setCurrentIndex(dlg._combo_add.findText(name))
        dlg._add_from_combo()
    dlg._on_solo("PWM")
    assert [s.name for s in dlg._series if s.visible] == ["PWM"]
    assert {n: r._chk.isChecked() for n, r in dlg._rows.items()} == {
        "当前转速": False, "目标速度": False, "PWM": True}


def test_set_all_and_empty_is_safe(app):
    dlg, _ = _dlg(app)
    dlg._set_all(False)
    assert dlg._curve.visible_series() == []
    dlg._curve.repaint()                          # 全不选也不能崩
    dlg._set_all(True)
    assert len(dlg._curve.visible_series()) == 1


def test_shared_range_spans_all_visible(app):
    """共享量程要覆盖所有可见曲线，否则叠加没有意义。"""
    dlg, cat = _dlg(app)
    dlg._combo_add.setCurrentIndex(dlg._combo_add.findText("PWM"))
    dlg._add_from_combo()
    dlg._fit(silent=True)
    lo, hi = dlg._curve._lo, dlg._curve._hi
    assert lo <= min(cat["PWM"]) and hi >= max(cat["当前转速"])


def test_normalized_each_series_fills_plot(app):
    """归一化：每条线各自铺满绘图区，用来比较量纲不同的量的形状。"""
    dlg, _ = _dlg(app)
    dlg._combo_add.setCurrentIndex(dlg._combo_add.findText("PWM"))
    dlg._add_from_combo()
    dlg.resize(800, 400)
    dlg._chk_norm.setChecked(True)
    r = dlg._curve._plot_rect()
    for s in dlg._series:
        f = s.finite()
        assert dlg._curve._y_at(min(f), r, s) == pytest.approx(r.bottom(), abs=0.5)
        assert dlg._curve._y_at(max(f), r, s) == pytest.approx(r.top(), abs=0.5)


def test_normalized_disables_shared_range_controls(app):
    """归一化时 Y 轴不是绝对值，共享量程控件必须禁用，免得误读。"""
    dlg, _ = _dlg(app)
    dlg._chk_norm.setChecked(True)
    assert not dlg._spin_lo.isEnabled()
    assert not dlg._chk_auto.isEnabled()
    dlg._chk_norm.setChecked(False)
    assert dlg._chk_auto.isEnabled()


def test_constant_series_does_not_divide_by_zero(app):
    dlg, _ = _dlg(app, first="常量")
    dlg.resize(800, 400)
    dlg._chk_norm.setChecked(True)
    r = dlg._curve._plot_rect()
    y = dlg._curve._y_at(3.0, r, dlg._series[0])
    assert r.top() <= y <= r.bottom()
    dlg._curve.repaint()


def test_refresh_updates_every_series(app):
    """重跑后所有曲线都要刷新，不能只刷主变量。"""
    dlg, cat = _dlg(app)
    dlg._combo_add.setCurrentIndex(dlg._combo_add.findText("目标速度"))
    dlg._add_from_combo()
    cat2 = {k: [v * 2 for v in vals] for k, vals in cat.items()}
    dlg.set_all_values(cat2)
    for s in dlg._series:
        assert s.values == cat2[s.name]


def test_drop_unchecked_keeps_at_least_one(app):
    dlg, _ = _dlg(app)
    dlg._combo_add.setCurrentIndex(dlg._combo_add.findText("PWM"))
    dlg._add_from_combo()
    dlg._on_row_toggled("PWM", False)
    dlg._drop_unchecked()
    assert dlg.names() == ["当前转速"]
    # 全部取消勾选时不该把图清空
    dlg._set_all(False)
    dlg._drop_unchecked()
    assert dlg.names() == ["当前转速"]


def test_palette_slots_distinct():
    assert len({color_for(i).name() for i in range(8)}) == 8


# ---- 缩放 / 平移 ----

def test_x_zoom_keeps_anchor_and_resets_on_zoom_out(app):
    """锚定缩放：缩放后鼠标指的还是那一帧；缩回全程时复位为跟随模式。"""
    dlg, _ = _dlg(app)
    c = dlg._curve
    n = c.frame_count()                       # 60
    c._zoom_x(30.0, 0.5)
    x0, x1 = c._x_view()
    assert x1 - x0 == pytest.approx((n - 1) * 0.5)
    assert x0 + (x1 - x0) * (30 / (n - 1)) == pytest.approx(30.0)
    c._zoom_x(30.0, 10.0)                     # 大幅缩小 → 回完整视野
    assert c._x_full
    assert c._x_view() == (0.0, float(n - 1))


def test_x_pan_clamps_to_data(app):
    dlg, _ = _dlg(app)
    c = dlg._curve
    c._zoom_x(30.0, 0.5)
    span = c._x_view()[1] - c._x_view()[0]
    c._pan_x(1e9)
    assert c._x_view()[1] == pytest.approx(59.0)
    c._pan_x(-1e9)
    assert c._x_view()[0] == pytest.approx(0.0)
    assert c._x_view()[1] - c._x_view()[0] == pytest.approx(span)   # 平移不改跨度


def test_frame_at_x_roundtrips_when_zoomed(app):
    """缩放后左键选帧/悬停读数要落在可见窗口里，不能还按全程算。"""
    dlg, _ = _dlg(app)
    dlg.resize(800, 400)
    c = dlg._curve
    c._zoom_x(30.0, 0.5)
    r = c._plot_rect()
    x0, x1 = c._x_view()
    assert c._frame_at_x(r.left(), r) == round(x0)
    assert c._frame_at_x(r.right(), r) == round(x1)


def test_wheel_y_zoom_takes_over_toolbar(app):
    """Ctrl+滚轮缩放 Y：取消自动量程并同步上下限输入框。"""
    dlg, _ = _dlg(app)
    dlg._on_y_range_requested(10.0, 20.0)
    assert not dlg._chk_auto.isChecked()
    assert dlg._spin_lo.value() == pytest.approx(10.0)
    assert dlg._spin_hi.value() == pytest.approx(20.0)
    assert (dlg._curve._lo, dlg._curve._hi) == (10.0, 20.0)


def test_reset_zoom_restores_full_view_and_autorange(app):
    dlg, _ = _dlg(app)
    dlg._curve._zoom_x(30.0, 0.5)
    dlg._on_y_range_requested(10.0, 20.0)
    dlg._reset_zoom()
    assert dlg._curve._x_full
    assert dlg._chk_auto.isChecked()
    assert dlg._curve._hi > 20.0              # 量程确实重新适配了数据


def test_y_pan_shifts_range_via_toolbar(app):
    """右键竖直拖拽：量程整体平移，跨度不变，走工具条接管通道。"""
    dlg, _ = _dlg(app)
    dlg.resize(800, 400)
    dlg._on_y_range_requested(0.0, 100.0)
    r = dlg._curve._plot_rect()
    dlg._curve._pan_y(r.height() / 10)        # 往下拖 1/10 高度 → 看更高的值段
    assert dlg._spin_lo.value() == pytest.approx(10.0)
    assert dlg._spin_hi.value() == pytest.approx(110.0)
    assert not dlg._chk_auto.isChecked()
    dlg._chk_norm.setChecked(True)            # 归一化下无共享量程，竖直平移应无动作
    dlg._curve._pan_y(50.0)
    assert dlg._spin_lo.value() == pytest.approx(10.0)


def test_zoomed_render_smoke(app):
    """缩放状态下渲染不崩：裁剪、部分范围、游标在视野外。"""
    dlg, _ = _dlg(app)
    dlg.resize(800, 400)
    c = dlg._curve
    c._zoom_x(45.0, 0.2)
    dlg.set_current_frame(2)                  # 游标落在视野外
    img = QImage(max(1, c.width()), max(1, c.height()),
                 QImage.Format.Format_RGB32)
    c.render(img)
