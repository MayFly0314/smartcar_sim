import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smartcar_sim.build.compiler import compile_sources  # noqa: E402
from smartcar_sim.build.diagnostics import friendly_link_error, parse_gcc_output  # noqa: E402
from smartcar_sim.build.scan import scan_includes  # noqa: E402

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


# ---- workspace 多文件 ----

def _write_multi_ws(tmp_path):
    """utils.h/utils.c 配对 + 引用它们的 main.c + 一个不相关的独立算法。"""
    (tmp_path / "utils.h").write_text(
        "#ifndef UTILS_H\n#define UTILS_H\n#include \"utils.h\"\nint add1(int x);\n#endif\n",
        encoding="utf-8",
    )  # 自包含 include 顺带测环路
    (tmp_path / "utils.c").write_text(
        '#include "utils.h"\nint add1(int x) { return x + 1; }\n', encoding="utf-8"
    )
    main = tmp_path / "main.c"
    main.write_text(
        '#include "sim_api.h"\n#include "utils.h"\n'
        "void image_process(uint8_t img[IMG_H][IMG_W]) {\n"
        "    sim_draw_point(add1(9), 20, SIM_RED);\n    (void)img;\n}\n",
        encoding="utf-8",
    )
    other = tmp_path / "other_algo.c"
    other.write_text(GOOD, encoding="utf-8")  # 同目录独立算法，不得被误链接
    return main


def test_include_scan(tmp_path):
    main = _write_multi_ws(tmp_path)
    c_files, h_files = scan_includes(main)
    assert c_files[0] == main.resolve()
    assert (tmp_path / "utils.c").resolve() in c_files
    assert (tmp_path / "utils.h").resolve() in h_files
    # 独立算法不被误带；sim_api.h 由 harness 提供不收集
    assert (tmp_path / "other_algo.c").resolve() not in c_files
    assert all(p.name != "sim_api.h" for p in h_files)


def test_multi_file_link(tmp_path):
    main = _write_multi_ws(tmp_path)
    c_files, h_files = scan_includes(main)
    r = compile_sources(c_files, W, H, header_files=h_files)
    assert r.ok, r.raw_output
    assert r.exe_path and r.exe_path.exists()


def test_obj_cache_hit(tmp_path):
    from smartcar_sim.build import compiler as comp

    src = tmp_path / "ok.c"
    src.write_text(GOOD, encoding="utf-8")
    gcc = comp.find_gcc()
    assert gcc
    key = comp._harness_cache_key(gcc, W, H)
    cache_dir = comp.ensure_ascii_dir() / "obj_cache" / key

    r1 = comp.compile_sources([src], W, H)
    assert r1.ok, r1.raw_output
    assert cache_dir.is_dir()
    mtimes = {o.name: o.stat().st_mtime_ns for o in cache_dir.glob("*.o")}
    assert mtimes

    r2 = comp.compile_sources([src], W, H)
    assert r2.ok, r2.raw_output
    # 第二次命中缓存：.o 未被重写
    assert {o.name: o.stat().st_mtime_ns for o in cache_dir.glob("*.o")} == mtimes


# ---- 换行归一化 ----

def test_newline_normalize(tmp_path):
    from smartcar_sim.main_window import _read_c_text, _write_c_text

    p = tmp_path / "damaged.c"
    # 模拟历史损坏：\r\r\n 混合正常 \r\n 与真空行（\r\n\r\n）
    p.write_bytes(b"line1\r\r\nline2\r\n\r\nline3\r\r\n")
    text = _read_c_text(p)
    assert text == "line1\nline2\n\nline3\n"  # 损坏修复，真空行保留

    _write_c_text(p, text)
    assert b"\r" not in p.read_bytes()  # 统一 LF 落盘

    _write_c_text(p, "a\r\nb\rc\n")  # 保存混合换行也被归一
    assert p.read_bytes() == b"a\nb\nc\n"
