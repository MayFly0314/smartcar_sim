"""健壮性验收：崩溃帧定位 + 死循环看门狗 + 链接错误 + 状态机跨帧存活。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402

from smartcar_sim.build.compiler import compile_sources  # noqa: E402
from smartcar_sim.imaging.loader import FrameSet  # noqa: E402
from smartcar_sim.paths import new_work_dir  # noqa: E402
from smartcar_sim.run.runner import run_sim  # noqa: E402

W, H = 188, 120


def _fs(n):
    return FrameSet(frames=np.full((n, H, W), 128, np.uint8), paths=[Path(f"{i}") for i in range(n)])


def _compile_run(code, n, tmp, timeout_base=5.0):
    src = tmp / "t.c"
    src.write_text(code, encoding="utf-8")
    cr = compile_sources([src], W, H)
    assert cr.ok, f"编译应成功:\n{cr.raw_output}"
    od = new_work_dir("rob")
    fs = _fs(n)
    fs.pack_input_bin(od / "input.bin")
    return run_sim(cr.exe_path, od / "input.bin", n, od, W, H, timeout_base_s=timeout_base)


CRASH = '''
#include "sim_api.h"
void image_process(uint8_t img[IMG_H][IMG_W]) {
    if (sim_frame_index() == 3) { int *p = 0; *p = 1; }
    (void)img;
}
'''

DEADLOOP = '''
#include "sim_api.h"
void image_process(uint8_t img[IMG_H][IMG_W]) {
    if (sim_frame_index() == 2) { volatile int x = 1; while (x) {} }
    (void)img;
}
'''

STATEFUL = '''
#include "sim_api.h"
static int counter = 0;
void image_process(uint8_t img[IMG_H][IMG_W]) {
    counter++;
    sim_plot("counter", (float)counter);
    (void)img;
}
'''

LINKERR = '''
#include "sim_api.h"
int helper(void) { return 1; }
'''


def main() -> int:
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="robust_"))
    ok = True

    # 1. 崩溃帧定位
    rr = _compile_run(CRASH, 6, tmp)
    if rr.crashed and rr.crash_frame == 3:
        print(f"[1] 崩溃帧定位 ✓ 第{rr.crash_frame}帧 ({rr.error_msg})")
    else:
        print(f"[1] 崩溃帧定位 ✗ crashed={rr.crashed} frame={rr.crash_frame}")
        ok = False

    # 2. 死循环看门狗（超时基数设小以加快测试）
    rr = _compile_run(DEADLOOP, 5, tmp, timeout_base=2.0)
    if rr.crashed and "超时" in rr.error_msg:
        print(f"[2] 死循环看门狗 ✓ ({rr.error_msg})")
    else:
        print(f"[2] 死循环看门狗 ✗ crashed={rr.crashed} msg={rr.error_msg}")
        ok = False

    # 3. 状态机跨帧存活：counter 应 1..5 递增
    rr = _compile_run(STATEFUL, 5, tmp)
    counters = [f.watches.get("counter") for f in rr.frames]
    if counters == [1, 2, 3, 4, 5]:
        print(f"[3] static 跨帧存活 ✓ counter={counters}")
    else:
        print(f"[3] static 跨帧存活 ✗ counter={counters}")
        ok = False

    # 4. 链接错误友好提示
    src = tmp / "le.c"
    src.write_text(LINKERR, encoding="utf-8")
    cr = compile_sources([src], W, H)
    if not cr.ok and "image_process" in cr.friendly_error:
        print("[4] 链接错误友好提示 ✓")
    else:
        print(f"[4] 链接错误友好提示 ✗ ok={cr.ok} friendly={cr.friendly_error!r}")
        ok = False

    print("\n健壮性验收：" + ("全部通过 ✓" if ok else "存在失败 ✗"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
