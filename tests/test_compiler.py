import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smartcar_sim.build.compiler import compile_sources  # noqa: E402
from smartcar_sim.build.diagnostics import friendly_link_error, parse_gcc_output  # noqa: E402

W, H = 188, 120
GOOD = """
#include "sim_api.h"
void image_process(uint8_t img[IMG_H][IMG_W]) {
    sim_draw_point(10, 20, SIM_RED);
    (void)img;
}
"""
SYNTAX_ERR = """
#include "sim_api.h"
void image_process(uint8_t img[IMG_H][IMG_W]) {
    int x = ;
    (void)img;
}
"""
MISSING_ENTRY = """
#include "sim_api.h"
int helper(void) { return 1; }
"""


def test_compile_ok(tmp_path):
    src = tmp_path / "ok.c"
    src.write_text(GOOD, encoding="utf-8")
    r = compile_sources([src], W, H)
    assert r.ok, r.raw_output
    assert r.exe_path and r.exe_path.exists()


def test_compile_syntax_error_has_diag(tmp_path):
    src = tmp_path / "bad.c"
    src.write_text(SYNTAX_ERR, encoding="utf-8")
    r = compile_sources([src], W, H)
    assert not r.ok
    errs = [d for d in r.diags if d.severity == "error"]
    assert errs, f"应有 error 诊断: {r.raw_output}"
    # 诊断路径应回映射到用户原始文件
    assert errs[0].file == str(src)
    assert errs[0].line > 0


def test_compile_missing_entry_friendly(tmp_path):
    src = tmp_path / "noentry.c"
    src.write_text(MISSING_ENTRY, encoding="utf-8")
    r = compile_sources([src], W, H)
    assert not r.ok
    assert "image_process" in r.friendly_error


def test_diag_regex_col_optional():
    out = "u0.c:5:9: error: expected expression before ';' token\n"
    diags = parse_gcc_output(out, {"u0.c": "C:/工作区/图像.c"})
    assert len(diags) == 1
    assert diags[0].file == "C:/工作区/图像.c"
    assert diags[0].line == 5 and diags[0].col == 9


def test_friendly_link_error():
    assert "image_process" in friendly_link_error(
        "undefined reference to `image_process'"
    )
    assert friendly_link_error("some unrelated text") == ""
