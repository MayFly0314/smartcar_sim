"""SD 卡直读对话框：插卡 → 自动找到录制 → 预览 → 载入，全程不经 HxD。

与「数据记录方案」设计器的分工：
  设计器 = 定义布局 + 生成车端 C 代码（写卡那一侧）
  本对话框 = 按当前方案把卡上的数据读回来（读卡那一侧）

只读：底层 sdcard 模块没有任何写设备的路径。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..imaging import sdcard
from ..record.scheme import CTYPES, RecordScheme, default_scheme
from ..settings import Settings

_MONO = "font-family:Consolas,monospace;"

# 找到一段后，继续往后找下一段的扫描预算。车端目前只写一段，
# 给小预算避免在大卡上空扫；将来支持多段录制时再放大。
_TAIL_SCAN_BYTES = 64 << 20

# 载入前的体积护栏：packed1 解压后约 8 倍，再加 numpy 帧数组，
# 超过这个原始字节数就先问一句，免得直接把内存吃爆。
_CONFIRM_RAW_BYTES = 256 << 20


class SdCardDialog(QDialog):
    """(FrameSet|None, 标签, [(参数名, 数组)], [(线名, 数组)])——与 RecordDialog 同一信号契约。"""

    record_loaded = Signal(object, str, object, object)

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("从 SD 卡直接读取录制")
        self.resize(720, 520)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self._found: list[tuple[int, int]] = []   # [(起始LBA, 帧数)]
        self._build_ui()
        self._refresh_drives()

    # ---- UI ----
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("SD 卡"))
        self._combo = QComboBox()
        self._combo.setMinimumWidth(280)
        row.addWidget(self._combo, 1)
        b_refresh = QPushButton("刷新")
        b_refresh.clicked.connect(self._refresh_drives)
        row.addWidget(b_refresh)
        b_scan = QPushButton("扫描录制")
        b_scan.setDefault(True)
        b_scan.clicked.connect(self._scan)
        row.addWidget(b_scan)
        root.addLayout(row)

        self._lbl_scheme = QLabel()
        self._lbl_scheme.setWordWrap(True)
        self._lbl_scheme.setStyleSheet(f"color:#4ec9b0; {_MONO}")
        root.addWidget(self._lbl_scheme)

        gb = QGroupBox("卡上找到的录制")
        gl = QVBoxLayout(gb)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["起始扇区(LBA)", "帧数", "大小", "扇区范围"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setStyleSheet(f"QTableWidget {{ {_MONO} }}")
        self._table.itemSelectionChanged.connect(self._preview)
        gl.addWidget(self._table)
        root.addWidget(gb, 1)

        prow = QHBoxLayout()
        self._preview_lbl = QLabel("（选中一行看首帧预览）")
        self._preview_lbl.setFixedSize(280, 120)
        self._preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_lbl.setStyleSheet("background:#111; color:#666; border:1px solid #333;")
        prow.addWidget(self._preview_lbl)
        pinfo = QVBoxLayout()
        self._lbl_preview_info = QLabel("")
        self._lbl_preview_info.setWordWrap(True)
        self._lbl_preview_info.setStyleSheet(f"color:#9cdcfe; {_MONO}")
        pinfo.addWidget(self._lbl_preview_info, 1)
        mrow = QHBoxLayout()
        mrow.addWidget(QLabel("手动起始 LBA"))
        self._spin_lba = QSpinBox()
        self._spin_lba.setRange(0, 2_000_000_000)
        self._spin_lba.setToolTip("扫描没找到时可手填；填完点「按此 LBA 读取」")
        mrow.addWidget(self._spin_lba, 1)
        b_manual = QPushButton("按此 LBA 读取")
        b_manual.clicked.connect(self._manual)
        mrow.addWidget(b_manual)
        pinfo.addLayout(mrow)
        prow.addLayout(pinfo, 1)
        root.addLayout(prow)

        warn = QLabel(
            "⚠ 只读访问，本功能不会向 SD 卡写入任何数据。\n"
            "　 若 Windows 弹出「需要格式化磁盘」，请点【取消】——点格式化会清空卡上的录制。"
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#e0a030;")
        root.addWidget(warn)

        bottom = QHBoxLayout()
        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet(f"color:#9cdcfe; {_MONO}")
        bottom.addWidget(self._lbl_status, 1)
        b_save = QPushButton("保存为文件...")
        b_save.setToolTip("把选中这一段存成 .bin，之后不插卡也能用【打开记录文件】查看")
        b_save.clicked.connect(self._save_selected)
        bottom.addWidget(b_save)
        b_load = QPushButton("载入选中的录制")
        b_load.clicked.connect(self._load_selected)
        bottom.addWidget(b_load)
        root.addLayout(bottom)

    # ---- 方案 ----
    def _scheme(self) -> RecordScheme:
        """当前记录方案。坏 JSON / 坏 hex / 坏类型一律回落默认，别让对话框开不出来。"""
        fallback = default_scheme(self.settings.img_w, self.settings.img_h)
        saved = self.settings.record_scheme
        if not saved:
            return fallback
        try:
            s = RecordScheme.from_json(saved)
            s.magic()               # from_json 不校验 hex，这里触发
            s.sectors_per_frame()   # 触发 CTYPES 查表，坏 ctype 在此暴露
            return s
        except Exception:  # noqa: BLE001
            return fallback

    @staticmethod
    def _segment_predicate(s: RecordScheme):
        """若方案里带 run_id/seq 两个参数，构造「同段」判据，用来截断陈旧帧。

        车端每次开始录制 run_id +1、段内 seq 从 0 递增。判据是
        run_id 等于本段第 0 帧 且 seq == 帧序号——只看 magic 的话，
        「今天 300 帧」会和「昨天残留的 700 帧」无缝拼成 1000 帧且不报错。

        方案里没有这两个参数（老数据）就返回 None，回落成只比 magic。
        字段必须整个落在帧的第 0 个扇区内，否则探测要多读几倍，直接放弃。
        """
        names = [p.name.strip().lower() for p in s.params]
        if "run_id" not in names or "seq" not in names:
            return None
        off = len(s.magic())
        pos: dict[str, tuple[int, int]] = {}
        for p in s.params:
            size = CTYPES[p.ctype][1]
            key = p.name.strip().lower()
            if key in ("run_id", "seq"):
                pos[key] = (off, size)
            off += size
        (ro, rs), (so, ss) = pos["run_id"], pos["seq"]
        if max(ro + rs, so + ss) > sdcard.SECTOR:
            return None          # 跨出第 0 扇区，探测代价太大，不启用

        def make():
            """每段一个新判据实例——run_id 基准不能跨段残留。"""
            base: list[int] = []

            def ok(sector0: bytes, idx: int) -> bool:
                run = int.from_bytes(sector0[ro:ro + rs], "little")
                seq = int.from_bytes(sector0[so:so + ss], "little")
                if idx == 0 or not base:
                    base[:] = [run]
                return run == base[0] and seq == idx

            return ok

        return make

    def _refresh_drives(self) -> None:
        self._combo.clear()
        drives = sdcard.list_removable_drives()
        for d in drives:
            self._combo.addItem(d.label, d)
        if not drives:
            self._combo.addItem("（没有检测到可移动盘——插上读卡器后点刷新）", None)
        s = self._scheme()
        tagged = self._segment_predicate(s) is not None
        mark = (
            "✓ 方案含 run_id/seq，可自动截断上次残留的陈旧帧"
            if tagged else
            "· 方案无 run_id/seq：只按帧头判断长度，可能把上次没被覆盖完的旧帧算进来"
        )
        self._lbl_scheme.setText(
            f"按当前方案读取： {s.img_w}×{s.img_h} · {len(s.params)} 参数 · "
            f"{len(s.line_fields)} 条线 · 每帧 {s.sectors_per_frame()} 扇区\n"
            f"{mark}\n"
            f"（方案在【文件 → 数据记录方案】里改；方案必须与车端录制时一致，否则解出来是花屏）"
        )

    # ---- 扫描 ----
    def _scan(self) -> None:
        d = self._combo.currentData()
        if d is None:
            QMessageBox.information(self, "没有可移动盘", "请插上读卡器后点「刷新」。")
            return
        s = self._scheme()
        magic, stride = s.magic(), s.stride()
        if not magic:
            QMessageBox.warning(
                self, "方案没有帧头",
                "当前方案的帧头为空，无法在卡上定位录制。\n请在记录方案里设置帧头（如 AA 55）。",
            )
            return
        self._table.setRowCount(0)
        self._found = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._lbl_status.setText("正在扫描……")
        QApplication.processEvents()
        err: str | None = None
        make_ok = self._segment_predicate(s)
        legacy_hit = 0          # 用判据一帧都找不到、但只比 magic 能找到时的帧数
        try:
            with sdcard.open_readonly(d.letter) as f:
                lba = sdcard.find_magic_lba(f, magic, stride, size_bytes=d.size_bytes)
                first_lba = lba
                while lba is not None:
                    n = sdcard.probe_frame_count(
                        f, lba, magic, stride,
                        frame_ok=make_ok() if make_ok else None,
                    )
                    if n <= 0:
                        break
                    self._found.append((lba, n))
                    self._append_row(lba, n, stride)   # 立刻上表，中途出错也不丢已找到的
                    if len(self._found) >= 64:
                        break
                    # 跳过这段继续找。车端目前只写一段，所以这里给个小预算即可，
                    # 免得在 60GB 卡上空扫半天；车端支持多段录制后再放大。
                    nxt = lba + n * stride // sdcard.SECTOR
                    lba = sdcard.find_magic_lba(
                        f, magic, stride, size_bytes=d.size_bytes,
                        scan_limit=_TAIL_SCAN_BYTES, start_lba=nxt,
                    )
                # 方案带 run_id 但卡上是加 run_id 之前录的老数据：判据只会认出第 0 帧
                # （老数据 run_id/seq 恒为 0，seq==idx 仅在 idx=0 成立），
                # 表现为「只有 1 帧」。退回只比 magic 看看实际有多少。
                if make_ok is not None and first_lba is not None and (
                    not self._found or (len(self._found) == 1 and self._found[0][1] <= 1)
                ):
                    plain = sdcard.probe_frame_count(f, first_lba, magic, stride)
                    if plain > 1:
                        legacy_hit = plain
                        self._found = [(first_lba, plain)]
                        self._table.setRowCount(0)
                        self._append_row(first_lba, plain, stride)
        except OSError as e:
            err = sdcard.explain_oserror(e, d.letter)
        finally:
            QApplication.restoreOverrideCursor()

        if err:
            QMessageBox.warning(self, "读取失败", err)
            if not self._found:
                self._lbl_status.setText("")
                return

        if self._found:
            self._table.selectRow(len(self._found) - 1)   # 默认选最后一段（最新）
            if legacy_hit:
                self._lbl_status.setText(f"找到 1 段（老格式，{legacy_hit} 帧）")
                QMessageBox.information(
                    self, "这是加 run_id 之前录的老数据",
                    f"当前方案带 run_id/seq，但卡上这段是加 run_id **之前**录的，"
                    f"所以按老规则（只比帧头）识别出 {legacy_hit} 帧。\n\n"
                    "⚠ 注意两点：\n"
                    "1. 老数据的参数偏移比新方案少 8 字节（没有 run_id/seq），"
                    "直接载入会导致参数错位、图像花屏。\n"
                    "   要看这段老数据，请临时把方案里的 run_id/seq 两行删掉。\n"
                    "2. 这段帧数可能包含更早的残留帧——正是 run_id 要解决的问题。\n\n"
                    "车端重新烧录后录的新数据不会有这个问题。",
                )
            else:
                self._lbl_status.setText(f"找到 {len(self._found)} 段录制")
        else:
            self._lbl_status.setText("没找到——方案的帧头/布局可能与卡上不符")
            QMessageBox.information(
                self, "没找到录制",
                "在卡上没有找到与当前方案匹配的帧头。可能原因：\n"
                "· 记录方案与车端录制时用的不一致（帧头/参数/分辨率）\n"
                "· 这张卡还没录过\n"
                "· 录制起点在扫描范围（前 512MB）之外——可在下方手填起始 LBA",
            )

    def _append_row(self, lba: int, n: int, stride: int) -> None:
        r = self._table.rowCount()
        self._table.insertRow(r)
        end = lba + n * stride // sdcard.SECTOR - 1
        for c, text in enumerate((
            f"{lba:,}", f"{n}", f"{n * stride / 1024 / 1024:.2f} MB", f"{lba:,} ~ {end:,}"
        )):
            self._table.setItem(r, c, QTableWidgetItem(text))

    # ---- 预览 ----
    def _current(self) -> tuple[int, int] | None:
        r = self._table.currentRow()
        if 0 <= r < len(self._found):
            return self._found[r]
        return None

    def _preview(self) -> None:
        cur = self._current()
        d = self._combo.currentData()
        if cur is None or d is None:
            return
        self._preview_lbl.clear()          # 先清掉上一段的图，免得解码失败时看着像成功了
        self._preview_lbl.setText("")
        lba, n = cur
        s = self._scheme()
        try:
            with sdcard.open_readonly(d.letter) as f:
                blob = sdcard.read_sectors(f, lba, s.stride() // sdcard.SECTOR)
            fs, cols, _cnt, _lines = s.decode_with_lines(np.frombuffer(blob, np.uint8))
        except Exception as e:  # noqa: BLE001
            self._preview_lbl.setText("预览失败")
            self._lbl_preview_info.setText(
                f"预览失败：{e}" if str(e) else f"预览失败：{type(e).__name__}"
            )
            return
        info = [f"起始 LBA {lba:,} · {n} 帧"]
        if fs is not None and fs.count:
            img = np.ascontiguousarray(fs.frames[0])
            qi = QImage(img.data, img.shape[1], img.shape[0], img.shape[1],
                        QImage.Format.Format_Grayscale8)
            self._preview_lbl.setPixmap(
                QPixmap.fromImage(qi).scaled(
                    self._preview_lbl.size(), Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation)
            )
            white = float((img > 127).mean() * 100)
            info.append(f"首帧 {img.shape[1]}×{img.shape[0]} 白像素 {white:.0f}%")
            if white < 2 or white > 98:
                info.append("⚠ 画面几乎全黑/全白，方案可能与卡上布局不符")
        for p, c in list(zip(s.params, cols))[:3]:
            info.append(f"{p.name}={c[0]}")
        self._lbl_preview_info.setText("\n".join(info))
        self._spin_lba.setValue(lba)

    # ---- 载入 ----
    def _manual(self) -> None:
        d = self._combo.currentData()
        if d is None:
            QMessageBox.information(self, "没有可移动盘", "请插上读卡器后点「刷新」。")
            return
        s = self._scheme()
        if not s.magic():
            QMessageBox.warning(
                self, "方案没有帧头",
                "当前方案的帧头为空，无法判断该位置有没有数据。\n"
                "请在记录方案里设置帧头（如 AA 55）。",
            )
            return
        lba = self._spin_lba.value()
        make_ok = self._segment_predicate(s)
        try:
            with sdcard.open_readonly(d.letter) as f:
                n = sdcard.probe_frame_count(
                    f, lba, s.magic(), s.stride(),
                    frame_ok=make_ok() if make_ok else None,
                )
        except OSError as e:
            QMessageBox.warning(self, "读取失败", sdcard.explain_oserror(e, d.letter))
            return
        if n <= 0:
            QMessageBox.warning(
                self, "该位置没有数据",
                f"LBA {lba:,} 处没有匹配当前方案帧头的数据。",
            )
            return
        self._found.append((lba, n))
        self._append_row(lba, n, s.stride())
        self._table.selectRow(self._table.rowCount() - 1)

    def _save_selected(self) -> None:
        """把选中那一段原样存成 .bin，另存一份同名 .scheme.json 记住当时的布局。

        存的是卡上的原始字节（不是解码后的图），所以将来用【打开记录文件】
        重新解一次，和插着卡读到的完全一致。
        """
        cur = self._current()
        d = self._combo.currentData()
        if d is None:
            QMessageBox.information(self, "没有可移动盘", "请插上读卡器后点「刷新」。")
            return
        if cur is None:
            QMessageBox.information(self, "先选一段", "请先扫描并在列表里选中一段录制。")
            return
        lba, n = cur
        s = self._scheme()
        start = self.settings.last_sd_raw or str(Path.home())
        default = str(Path(start).parent / f"record_lba{lba}_{n}frames.bin")
        fn, _ = QFileDialog.getSaveFileName(
            self, "保存这一段录制", default, "记录文件 (*.bin);;所有文件 (*)"
        )
        if not fn:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        err = None
        try:
            with sdcard.open_readonly(d.letter) as f:
                blob = sdcard.read_sectors(f, lba, n * s.stride() // sdcard.SECTOR)
            Path(fn).write_bytes(bytes(blob))
            # 布局随行：方案以后改了，这个文件也还能正确解开
            Path(fn).with_suffix(".scheme.json").write_text(
                s.to_json(), encoding="utf-8"
            )
        except OSError as e:
            err = sdcard.explain_oserror(e, d.letter) if not isinstance(
                e, PermissionError) or e.filename is None else str(e)
        except Exception as e:  # noqa: BLE001
            err = str(e) or type(e).__name__
        finally:
            QApplication.restoreOverrideCursor()
        if err:
            QMessageBox.warning(self, "保存失败", err)
            return
        self.settings.last_sd_raw = fn
        self._lbl_status.setText(
            f"已保存 {n} 帧 → {Path(fn).name}（另存了 .scheme.json 记住布局）"
        )
        QMessageBox.information(
            self, "保存成功",
            f"已保存 {n} 帧到：\n{fn}\n\n"
            f"同时生成了 {Path(fn).with_suffix('.scheme.json').name}，记录了当前布局。\n\n"
            "以后不用插卡：【文件 → 数据记录方案】→「按此方案打开记录文件」选这个 .bin 即可。",
        )

    def _load_selected(self) -> None:
        cur = self._current()
        d = self._combo.currentData()
        if d is None:
            QMessageBox.information(self, "没有可移动盘", "请插上读卡器后点「刷新」。")
            return
        if cur is None:
            QMessageBox.information(self, "先选一段", "请先扫描并在列表里选中一段录制。")
            return
        lba, n = cur
        s = self._scheme()
        raw = n * s.stride()
        if raw > _CONFIRM_RAW_BYTES:
            # packed1 解压后约 8 倍，提前告诉用户要吃多少内存
            est = raw * 9 if s.image_mode == "packed1" else raw * 2
            if QMessageBox.question(
                self, "这段很大",
                f"这段有 {n} 帧、原始 {raw / 1024 ** 2:.0f} MB，"
                f"解码后大约需要 {est / 1024 ** 3:.1f} GB 内存。\n继续载入吗？",
            ) != QMessageBox.StandardButton.Yes:
                return
        err: str | None = None
        fs = cols = line_cols = None
        cnt = 0
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            with sdcard.open_readonly(d.letter) as f:
                blob = sdcard.read_sectors(f, lba, n * s.stride() // sdcard.SECTOR)
            fs, cols, cnt, line_cols = s.decode_with_lines(np.frombuffer(blob, np.uint8))
        except MemoryError:
            err = "内存不足——这段录制太大，装不进内存。"
        except OSError as e:
            err = sdcard.explain_oserror(e, d.letter)
        except Exception as e:  # noqa: BLE001
            err = str(e) or f"解码失败：{type(e).__name__}"
        finally:
            QApplication.restoreOverrideCursor()
        if err:
            QMessageBox.warning(self, "载入失败", err)
            return

        # 与 RecordDialog 一致：把方案分辨率同步到全局，
        # 否则 image_mode='none' 时主窗口画三线会用到过期的宽高。
        self.settings.img_w = s.img_w
        self.settings.img_h = s.img_h
        label = f"SD卡 {d.letter}: LBA {lba:,} · {cnt} 帧"
        params = [(p.name, cols[i]) for i, p in enumerate(s.params) if i < len(cols)]
        lines = [
            (line.name, line_cols[i])
            for i, line in enumerate(s.line_fields)
            if i < len(line_cols)
        ]
        self.scheme_used = s          # 主窗口据此取分组
        self.record_loaded.emit(fs, label, params, lines)
        self._lbl_status.setText(f"已载入 {cnt} 帧——参数见主窗口「车端记录」面板")
