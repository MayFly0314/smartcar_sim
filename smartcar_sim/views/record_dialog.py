"""数据记录方案设计器：左边"填空"拼帧布局，右边实时生成车端 C 代码。

流程：设计布局（帧头/参数/图像压缩）→ 复制生成的函数到 image_record.c →
车上录卡 → 回来用同一方案打开记录文件 → 图像进时间轴、参数进监视面板。
方案自动保存（QSettings），下次打开就是上次的布局。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..record.scheme import CTYPES, IMAGE_MODES, ParamField, RecordScheme, default_scheme
from ..settings import Settings

_MONO = "font-family:Consolas,monospace;"


class RecordDialog(QDialog):
    # (FrameSet|None, 标签, [(参数名, 逐帧值数组)])
    record_loaded = Signal(object, str, object)

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("数据记录方案 — 压缩存图 / 参数回放")
        self.resize(980, 620)
        self.setWindowFlag(Qt.WindowType.Window, True)

        saved = self.settings.record_scheme
        try:
            self._scheme = RecordScheme.from_json(saved) if saved else default_scheme(
                settings.img_w, settings.img_h
            )
        except Exception:  # noqa: BLE001 — 坏 JSON 回落默认
            self._scheme = default_scheme(settings.img_w, settings.img_h)

        self._build_ui()
        self._load_scheme_to_ui()
        self._refresh()

    # ---- UI ----
    def _build_ui(self) -> None:
        split = QSplitter(Qt.Orientation.Horizontal, self)

        # == 左：布局设计 ==
        left = QWidget()
        llay = QVBoxLayout(left)

        gb_head = QGroupBox("帧结构")
        hl = QVBoxLayout(gb_head)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("帧头 hex"))
        self._edit_magic = QLineEdit()
        self._edit_magic.setPlaceholderText("如 AA 55（空=无帧头，不建议）")
        row1.addWidget(self._edit_magic, 1)
        hl.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("图像"))
        self._combo_img = QComboBox()
        for key, text in IMAGE_MODES.items():
            self._combo_img.addItem(text, key)
        row2.addWidget(self._combo_img, 1)
        hl.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("图像数组"))
        self._edit_imgexpr = QLineEdit()
        row3.addWidget(self._edit_imgexpr, 1)
        row3.addWidget(QLabel("宽"))
        self._spin_w = QSpinBox()
        self._spin_w.setRange(1, 4096)
        row3.addWidget(self._spin_w)
        row3.addWidget(QLabel("高"))
        self._spin_h = QSpinBox()
        self._spin_h.setRange(1, 4096)
        row3.addWidget(self._spin_h)
        hl.addLayout(row3)
        llay.addWidget(gb_head)

        gb_par = QGroupBox("参数（每帧随图像一起记录；名称在回放面板显示，可随时改）")
        pl = QVBoxLayout(gb_par)
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["名称", "类型", "车端变量/表达式"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet(f"QTableWidget {{ {_MONO} }}")
        pl.addWidget(self._table)
        btns = QHBoxLayout()
        b_add = QPushButton("+ 添加参数")
        b_del = QPushButton("− 删除选中")
        b_add.clicked.connect(self._add_param)
        b_del.clicked.connect(self._del_param)
        btns.addWidget(b_add)
        btns.addWidget(b_del)
        btns.addStretch(1)
        pl.addLayout(btns)
        llay.addWidget(gb_par, 1)

        self._lbl_layout = QLabel()
        self._lbl_layout.setStyleSheet(f"color:#4ec9b0; {_MONO}")
        self._lbl_layout.setWordWrap(True)
        llay.addWidget(self._lbl_layout)

        row_fn = QHBoxLayout()
        row_fn.addWidget(QLabel("函数名"))
        self._edit_fn = QLineEdit()
        row_fn.addWidget(self._edit_fn, 1)
        llay.addLayout(row_fn)

        # == 右：生成代码 ==
        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.addWidget(QLabel("车端代码（整段粘贴到 image_record.c 末尾，主循环里改调此函数）"))
        self._code = QPlainTextEdit()
        self._code.setReadOnly(True)
        self._code.setStyleSheet(f"{_MONO} font-size:12px; background:#1e1e1e; color:#d4d4d4;")
        rlay.addWidget(self._code, 1)
        b_copy = QPushButton("复制代码到剪贴板")
        b_copy.clicked.connect(self._copy_code)
        rlay.addWidget(b_copy)

        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([460, 520])

        root = QVBoxLayout(self)
        root.addWidget(split, 1)

        bottom = QHBoxLayout()
        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet(f"color:#9cdcfe; {_MONO}")
        bottom.addWidget(self._lbl_status, 1)
        b_open = QPushButton("按此方案打开记录文件...")
        b_open.setDefault(True)
        b_open.clicked.connect(self._open_record)
        bottom.addWidget(b_open)
        root.addLayout(bottom)

        # 任何编辑 → 重建方案 + 刷新
        self._edit_magic.textChanged.connect(self._refresh)
        self._combo_img.currentIndexChanged.connect(self._refresh)
        self._edit_imgexpr.textChanged.connect(self._refresh)
        self._spin_w.valueChanged.connect(self._refresh)
        self._spin_h.valueChanged.connect(self._refresh)
        self._edit_fn.textChanged.connect(self._refresh)
        self._table.cellChanged.connect(lambda *_: self._refresh())

    def _load_scheme_to_ui(self) -> None:
        s = self._scheme
        self._edit_magic.setText(s.magic_hex)
        i = self._combo_img.findData(s.image_mode)
        if i >= 0:
            self._combo_img.setCurrentIndex(i)
        self._edit_imgexpr.setText(s.image_expr)
        self._spin_w.setValue(s.img_w)
        self._spin_h.setValue(s.img_h)
        self._edit_fn.setText(s.func_name)
        for p in s.params:
            self._append_row(p)

    def _append_row(self, p: ParamField) -> None:
        r = self._table.rowCount()
        self._table.insertRow(r)
        self._table.setItem(r, 0, QTableWidgetItem(p.name))
        combo = QComboBox()
        combo.addItems(list(CTYPES.keys()))
        combo.setCurrentText(p.ctype)
        combo.currentIndexChanged.connect(lambda *_: self._refresh())
        self._table.setCellWidget(r, 1, combo)
        self._table.setItem(r, 2, QTableWidgetItem(p.expr))

    def _add_param(self) -> None:
        self._append_row(ParamField(f"param{self._table.rowCount()}", "int32", ""))
        self._refresh()

    def _del_param(self) -> None:
        r = self._table.currentRow()
        if r >= 0:
            self._table.removeRow(r)
            self._refresh()

    # ---- 方案同步 ----
    def _collect(self) -> RecordScheme | None:
        params: list[ParamField] = []
        for r in range(self._table.rowCount()):
            name_it = self._table.item(r, 0)
            expr_it = self._table.item(r, 2)
            combo = self._table.cellWidget(r, 1)
            name = (name_it.text().strip() if name_it else "") or f"param{r}"
            ctype = combo.currentText() if isinstance(combo, QComboBox) else "int32"
            expr = expr_it.text().strip() if expr_it else ""
            params.append(ParamField(name, ctype, expr or name))
        try:
            s = RecordScheme(
                magic_hex=self._edit_magic.text().strip(),
                params=params,
                image_mode=self._combo_img.currentData() or "packed1",
                image_expr=self._edit_imgexpr.text().strip() or "binary_image",
                img_w=self._spin_w.value(),
                img_h=self._spin_h.value(),
                func_name=self._edit_fn.text().strip() or "sd_record_frame_c",
            )
            s.magic()  # 触发 hex 校验
            return s
        except Exception as e:  # noqa: BLE001
            self._lbl_layout.setText(f"⚠ 方案无效：{e}")
            return None

    def _refresh(self) -> None:
        s = self._collect()
        if s is None:
            return
        self._scheme = s
        self._lbl_layout.setText(s.layout_summary())
        self._code.setPlainText(s.generate_c())
        self.settings.record_scheme = s.to_json()

    def _copy_code(self) -> None:
        QApplication.clipboard().setText(self._code.toPlainText())
        self._lbl_status.setText("代码已复制——粘贴到 image_record.c 末尾，主循环改调新函数")

    # ---- 回放 ----
    def _open_record(self) -> None:
        s = self._scheme
        start = self.settings.last_sd_raw or str(Path.home())
        fn, _ = QFileDialog.getOpenFileName(
            self, "按当前方案打开记录文件", start,
            "记录文件 (*.bin *.raw *.dat);;所有文件 (*)",
        )
        if not fn:
            return
        try:
            data = np.fromfile(fn, dtype=np.uint8)
            skip = 0
            magic = s.magic()
            if magic and bytes(data[: len(magic)]) != magic:
                found = s.find_frame0_offset(data)
                if found is None:
                    raise ValueError(
                        "找不到帧头——检查方案的帧头/布局是否与录制时一致，或导出起点是否正确"
                    )
                skip = found
            fs, cols, n = s.decode(data, skip=skip)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "解析失败", str(e))
            return
        self.settings.last_sd_raw = fn
        note = f"（自动对齐：跳过前 {skip} 字节）" if skip else ""
        label = f"记录 {Path(fn).name} · {n} 帧{note}"
        params = [(p.name, cols[i]) for i, p in enumerate(s.params)]
        self.record_loaded.emit(fs, label, params)
        self._lbl_status.setText(f"已加载 {n} 帧{note}——参数见主窗口监视面板")
