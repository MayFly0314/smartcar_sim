"""运行 sim.exe：看门狗超时、崩溃帧定位、结果解析。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .protocol import (
    RunResult,
    load_processed_frames,
    parse_draw_file,
    parse_stdout_logs,
)

_CREATE_NO_WINDOW = 0x08000000


def _crash_message(code: int) -> str:
    mapping = {
        0xC0000005: "非法内存访问（空指针/数组越界）",
        0xC00000FD: "栈溢出（递归过深或超大局部数组）",
        0xC0000094: "整数除以零",
        0xC000008C: "数组下标越界",
    }
    u = code & 0xFFFFFFFF
    return mapping.get(u, f"异常退出码 0x{u:08X}")


def run_sim(
    exe: Path,
    input_bin: Path,
    frame_count: int,
    out_dir: Path,
    img_w: int,
    img_h: int,
    timeout_base_s: float = 5.0,
    timeout_per_frame_s: float = 0.05,
) -> RunResult:
    """同步运行 sim.exe 并解析结果。"""
    timeout = timeout_base_s + timeout_per_frame_s * frame_count
    cmd = [str(exe), str(input_bin), str(frame_count), str(out_dir)]

    crashed = False
    crash_frame = -1
    exit_code = 0
    error_msg = ""
    stdout = ""

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL,  # noconsole 打包下 stdin 句柄无效，必须显式重定向
            timeout=timeout, creationflags=_CREATE_NO_WINDOW,
        )
        stdout = proc.stdout or ""
        exit_code = proc.returncode
        if exit_code != 0:
            crashed = True
            error_msg = _crash_message(exit_code)
    except subprocess.TimeoutExpired as e:
        crashed = True
        error_msg = f"运行超时（>{timeout:.1f}s），可能存在死循环。"
        stdout = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")

    logs, last_done = parse_stdout_logs(stdout)
    if crashed:
        # 崩溃发生在最后完成帧的下一帧
        crash_frame = last_done + 1

    frames = parse_draw_file(out_dir / "draw.txt")
    processed = load_processed_frames(out_dir / "frames_out.bin", img_w, img_h)

    # 把日志按帧号并入（-1 归到崩溃帧或全局）
    return RunResult(
        frames=frames,
        processed=processed,
        logs=logs,
        crashed=crashed,
        crash_frame=crash_frame,
        exit_code=exit_code,
        error_msg=error_msg,
    )
