"""app:// 自定义 scheme：进程内提供 Monaco 静态文件。

用自定义安全 scheme 而非 file://，让 Monaco 的 web worker 能在标准相对
路径下启动（file:// 下 worker 会因跨源被拒）。

注意：register_scheme() 必须在 QApplication 构造之前调用！
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QUrl
from PySide6.QtWebEngineCore import (
    QWebEngineUrlScheme,
    QWebEngineUrlSchemeHandler,
    QWebEngineUrlRequestJob,
)

SCHEME = b"app"
_HOST_MONACO = "monaco"   # app://monaco/vs/...  -> assets/monaco/
_HOST_APP = "app"         # app://app/editor.html -> assets/

_MIME = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".json": "application/json",
    ".ttf": "font/ttf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".svg": "image/svg+xml",
    ".map": "application/json",
}


def register_scheme() -> None:
    """注册 app:// 为安全本地 scheme。必须在 QApplication 之前调用。

    关键：不能加 LocalScheme——它会让每个响应变成唯一的不透明源
    （与 file:// 同样的行为），从而破坏 web worker 与同源。
    """
    scheme = QWebEngineUrlScheme(SCHEME)
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme
        | QWebEngineUrlScheme.Flag.LocalAccessAllowed
        | QWebEngineUrlScheme.Flag.CorsEnabled
    )
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    QWebEngineUrlScheme.registerScheme(scheme)


class SchemeHandler(QWebEngineUrlSchemeHandler):
    def __init__(self, assets_dir: Path, parent=None):
        super().__init__(parent)
        self._assets = assets_dir
        self._monaco = assets_dir / "monaco"

    def _resolve(self, url: QUrl) -> Path | None:
        host = url.host()
        rel = url.path().lstrip("/")
        if host == _HOST_MONACO:
            base = self._monaco
        elif host == _HOST_APP:
            base = self._assets
        else:
            return None
        target = (base / rel).resolve()
        # 防目录穿越
        if base.resolve() not in target.parents and target != base.resolve():
            return None
        return target if target.is_file() else None

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:  # noqa: N802
        try:
            path = self._resolve(job.requestUrl())
            if path is None:
                job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
                return
            ext = path.suffix.lower()
            mime = _MIME.get(ext) or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            data = QByteArray(path.read_bytes())
            buf = QBuffer(job)
            buf.setData(data)
            buf.open(QIODevice.OpenModeFlag.ReadOnly)
            job.reply(mime.encode("ascii"), buf)
        except Exception as e:  # noqa: BLE001
            import sys
            print(f"[SchemeHandler ERROR] {e}", file=sys.stderr, flush=True)
            job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
