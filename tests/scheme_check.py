"""最小复现：只测 app:// scheme 能否加载一个简单页面。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from smartcar_sim.editor.scheme_handler import SCHEME, SchemeHandler, register_scheme  # noqa: E402
register_scheme()

from PySide6.QtCore import QTimer, QUrl  # noqa: E402
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from smartcar_sim.paths import ASSETS_DIR  # noqa: E402

# 临时在 handler 上加诊断
_orig = SchemeHandler.requestStarted
def _traced(self, job):
    print(f"[handler] requestStarted: {job.requestUrl().toString()}", flush=True)
    r = self._resolve(job.requestUrl())
    print(f"[handler]   resolved -> {r}", flush=True)
    _orig(self, job)
SchemeHandler.requestStarted = _traced


def main() -> int:
    app = QApplication(sys.argv)
    profile = QWebEngineProfile("test")
    handler = SchemeHandler(ASSETS_DIR)
    profile.installUrlSchemeHandler(SCHEME, handler)

    view = QWebEngineView()
    page = QWebEnginePage(profile, view)
    page.javaScriptConsoleMessage = lambda l, m, ln, s: print(f"[JS] {m} ({s}:{ln})", flush=True)
    view.setPage(page)
    view.loadStarted.connect(lambda: print("[load] started", flush=True))
    view.loadFinished.connect(lambda ok: print(f"[load] finished ok={ok}", flush=True))
    page.renderProcessTerminated.connect(
        lambda status, code: print(f"[RENDER TERMINATED] status={status} code={code}", flush=True)
    )
    view.resize(400, 300)
    view.show()

    print(f"[main] assets dir = {ASSETS_DIR}", flush=True)
    print(f"[main] editor.html exists = {(ASSETS_DIR / 'editor.html').is_file()}", flush=True)
    print(f"[main] loader.js exists = {(ASSETS_DIR / 'monaco' / 'vs' / 'loader.js').is_file()}", flush=True)

    # 阶段1：setHtml（完全不走 scheme，验证 WebEngine 本身可用）
    def stage_html():
        print("[stage] setHtml", flush=True)
        page.setHtml("<html><body><h1 id=x>hello</h1></body></html>")
        QTimer.singleShot(1500, stage_scheme)

    # 阶段2：走 app:// scheme
    def stage_scheme():
        print("[stage] load app://app/editor.html", flush=True)
        view.load(QUrl("app://app/editor.html"))
        QTimer.singleShot(2500, probe_dom)

    def probe_dom():
        page.runJavaScript("document.title + '|' + document.body.innerHTML.length",
                           lambda r: print(f"[dom] {r}", flush=True))

    QTimer.singleShot(300, stage_html)
    QTimer.singleShot(6000, app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
