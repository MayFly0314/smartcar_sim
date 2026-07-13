import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smartcar_sim.run.protocol import (  # noqa: E402
    parse_draw_file,
    parse_stdout_logs,
)


def test_parse_draw_basic(tmp_path):
    p = tmp_path / "draw.txt"
    p.write_text(
        "P 10 20 ff0000\n"
        "L 0 0 5 5 00cc44\n"
        "T 4 4 ffd500 F0%20th=200\n"
        "V threshold 200\n"
        "F 0 459.6\n"
        "P 11 21 ff0000\n"
        "F 1 175.2\n",
        encoding="utf-8",
    )
    frames = parse_draw_file(p)
    assert len(frames) == 2
    f0, f1 = frames
    assert f0.index == 0 and abs(f0.t_us - 459.6) < 0.01
    assert len(f0.cmds) == 3
    t = [c for c in f0.cmds if c.kind == "T"][0]
    assert t.text == "F0 th=200", f"转义解码错误: {t.text!r}"
    assert f0.watches == {"threshold": 200.0}
    assert len(f1.cmds) == 1


def test_parse_draw_bad_lines_tolerated(tmp_path):
    p = tmp_path / "draw.txt"
    p.write_text("GARBAGE\nP xx yy zz\nP 1 2 ff0000\nF 0 1.0\n", encoding="utf-8")
    frames = parse_draw_file(p)
    assert len(frames) == 1
    assert len(frames[0].cmds) == 1


def test_parse_draw_crash_tail_kept(tmp_path):
    # 崩溃时最后一帧没有 F 收尾，指令仍应保留
    p = tmp_path / "draw.txt"
    p.write_text("P 1 2 ff0000\nF 0 1.0\nP 3 4 00cc44\n", encoding="utf-8")
    frames = parse_draw_file(p)
    assert len(frames) == 2
    assert frames[1].cmds[0].args == (3, 4)


def test_parse_stdout_logs():
    logs, last = parse_stdout_logs(
        "G 0 otsu = 200\nF 0\nraw printf leak\nG 1 hello\nF 1\n"
    )
    assert last == 1
    assert (0, "otsu = 200") in logs
    assert (1, "hello") in logs
    assert (-1, "raw printf leak") in logs, "用户裸 printf 应作为无帧号日志保留"


def test_missing_draw_file(tmp_path):
    assert parse_draw_file(tmp_path / "nope.txt") == []
