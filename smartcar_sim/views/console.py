"""控制台：编译诊断（可点击跳转）+ 运行日志。"""
from __future__ import annotations

import html

from PySide6.QtCore import Signal, QUrl
from PySide6.QtWidgets import QTextBrowser


class Console(QTextBrowser):
    jump_requested = Signal(str, int, int)  # file, line, col

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setStyleSheet(
            "QTextBrowser { background:#1e1e1e; color:#d4d4d4;"
            " font-family:Consolas,monospace; font-size:12px; }"
        )
        self._jump_targets: list[tuple[str, int, int]] = []
        self.anchorClicked.connect(self._on_anchor)

    def _on_anchor(self, url: QUrl) -> None:
        s = url.toString()
        if s.startswith("jump:"):
            try:
                idx = int(s[len("jump:"):])
                file, line, col = self._jump_targets[idx]
                self.jump_requested.emit(file, line, col)
            except (ValueError, IndexError):
                pass

    def clear_all(self) -> None:
        self.clear()
        self._jump_targets.clear()

    def append_info(self, text: str) -> None:
        self.append(f'<span style="color:#569cd6">{html.escape(text)}</span>')

    def append_success(self, text: str) -> None:
        self.append(f'<span style="color:#4ec9b0">{html.escape(text)}</span>')

    def append_error(self, text: str) -> None:
        self.append(f'<span style="color:#f48771">{html.escape(text)}</span>')

    def append_diags(self, diags) -> None:
        for d in diags:
            color = "#f48771" if d.severity == "error" else "#dcdcaa"
            idx = len(self._jump_targets)
            self._jump_targets.append((d.file, d.line, d.col))
            fname = d.file.replace("\\", "/").split("/")[-1]
            loc = html.escape(f"{fname}:{d.line}:{d.col}")
            msg = html.escape(d.msg)
            self.append(
                f'<a href="jump:{idx}" style="color:{color};'
                f' text-decoration:none">[{d.severity}] {loc}</a>'
                f' <span style="color:#d4d4d4">{msg}</span>'
            )

    def append_logs(self, logs) -> None:
        for frame_idx, text in logs:
            prefix = f"[F{frame_idx}] " if frame_idx >= 0 else ""
            self.append(
                f'<span style="color:#808080">{prefix}</span>'
                f'<span style="color:#9cdcfe">{html.escape(text)}</span>'
            )
