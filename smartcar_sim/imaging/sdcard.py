r"""Windows 下只读直读 SD 卡扇区。

为什么走卷路径 `\\.\D:` 而不是 `\\.\PhysicalDriveN`：
实测（Win11，非管理员）——
  - `\\.\PhysicalDriveN` / 系统盘卷 `\\.\C:` → CreateFileW 直接 ACCESS_DENIED(5)
  - 可移动盘卷 `\\.\D:`                      → 普通权限即可打开并读扇区
所以只列可移动盘、只开卷，就能做到**免管理员 + 天然挡住系统盘**。

两条硬约束（实测，违反即 OSError errno 22）：
  - seek 偏移与 read 长度都必须是 512 的整数倍
  - seek(0, SEEK_END) 不可用，容量要靠二分探测

本模块全程只读：没有任何以写模式打开设备的代码路径。
"""
from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass

SECTOR = 512

_DRIVE_REMOVABLE = 2
_MAX_SECTORS_PER_READ = 2048  # 每次 syscall 最多 1 MiB（不是总内存上限，见 read_sectors）
_K32 = None


@dataclass
class DriveInfo:
    letter: str          # "D"
    label: str           # 下拉框显示用
    size_bytes: int      # 0 表示未探测


def _kernel32():
    global _K32
    if _K32 is None:
        _K32 = ctypes.WinDLL("kernel32", use_last_error=True)
    return _K32


def list_removable_drives() -> list[DriveInfo]:
    """枚举可移动盘。只返回 DRIVE_REMOVABLE——固定盘/系统盘一律不出现在列表里。"""
    if sys.platform != "win32":
        return []
    k32 = _kernel32()
    mask = k32.GetLogicalDrives()
    out: list[DriveInfo] = []
    for i in range(26):
        if not (mask >> i & 1):
            continue
        letter = chr(65 + i)
        if k32.GetDriveTypeW(f"{letter}:\\") != _DRIVE_REMOVABLE:
            continue
        size = 0
        try:
            with open_readonly(letter) as f:
                size = probe_size(f)
        except OSError:
            pass  # 插槽为空/被占用，仍然列出，让用户看得到
        label = f"{letter}:  可移动" + (f"  {size / 1024 ** 3:.1f} GB" if size else "  （未插卡？）")
        out.append(DriveInfo(letter=letter, label=label, size_bytes=size))
    return out


def open_readonly(letter: str):
    """只读打开可移动卷。buffering=0 直通设备，避免 Python 缓冲层做非对齐读。

    这里再挡一道 DRIVE_REMOVABLE：列表已经过滤过，但本函数是「只读打开」这个
    保证的唯一入口，不能依赖调用方先过滤（尤其将来若以管理员身份启动，
    系统盘就不再有 ACCESS_DENIED 兜底了）。
    """
    letter = letter.strip().rstrip(":")
    if len(letter) != 1 or not letter.isalpha():
        raise ValueError(f"盘符不合法：{letter!r}")
    letter = letter.upper()
    if sys.platform == "win32":
        if _kernel32().GetDriveTypeW(f"{letter}:\\") != _DRIVE_REMOVABLE:
            raise PermissionError(f"{letter}: 不是可移动盘——本功能只读取可移动盘")
    return open(rf"\\.\{letter}:", "rb", buffering=0)


def read_sectors(f, lba: int, count: int) -> bytearray:
    """读 count 个扇区。偏移与长度都天然 512 对齐。

    预分配 + readinto，避免「bytearray 累加再 bytes() 复制一次」导致峰值翻倍
    （整段录制可达数百 MB）。返回 bytearray，np.frombuffer 可直接吃。
    """
    if lba < 0 or count <= 0:
        raise ValueError("lba/count 必须为正")
    buf = bytearray(count * SECTOR)
    done = 0
    with memoryview(buf) as view:
        while done < count:
            chunk = min(count - done, _MAX_SECTORS_PER_READ)
            f.seek((lba + done) * SECTOR)
            with view[done * SECTOR:(done + chunk) * SECTOR] as dst:
                got = f.readinto(dst)
            if not got:
                break                       # 读到设备末尾
            done += got // SECTOR
            if got % SECTOR:                # 罕见的部分读，截回扇区边界
                break
    return buf if done == count else buf[:done * SECTOR]


def probe_size(f) -> int:
    """二分探测容量——seek(0, END) 在裸设备上不可用（errno 22）。"""
    lo, hi = 0, 1 << 47
    while lo + SECTOR < hi:
        mid = ((lo + hi) // 2) // SECTOR * SECTOR
        try:
            f.seek(mid)
            ok = len(f.read(SECTOR)) == SECTOR
        except OSError:
            ok = False
        if ok:
            lo = mid
        else:
            hi = mid
    return lo + SECTOR if lo else 0


def find_magic_lba(
    f,
    magic: bytes,
    stride: int,
    size_bytes: int = 0,
    scan_limit: int = 512 << 20,
    start_lba: int = 0,
) -> int | None:
    """从 start_lba 起扫描，找第一个「本扇区起点是 magic 且下一帧起点也是 magic」的 LBA。

    只看扇区起点（车端总是扇区对齐写），因此每 512B 只比对一次，
    再要求 +stride 处也对得上，避免图像数据里偶然出现的 magic。
    scan_limit 是从 start_lba 起往后扫的字节预算。
    """
    if not magic:
        return None
    if stride % SECTOR:
        raise ValueError(f"stride {stride} 不是 512 的整数倍")
    start = start_lba * SECTOR
    end = start + scan_limit
    if size_bytes:
        end = min(end, size_bytes)
    chunk = 1 << 20
    pos = start
    while pos < end:
        try:
            f.seek(pos)
            buf = f.read(min(chunk, end - pos))
        except OSError:
            return None
        if not buf:
            return None
        for off in range(0, len(buf) - len(magic) + 1, SECTOR):
            if buf[off:off + len(magic)] != magic:
                continue
            lba = (pos + off) // SECTOR
            nxt = read_sectors(f, lba + stride // SECTOR, 1)
            if len(nxt) >= len(magic) and nxt[:len(magic)] == magic:
                return lba
        pos += len(buf) // SECTOR * SECTOR       # 部分读也要保持扇区对齐
        if len(buf) < SECTOR:
            return None
    return None


def probe_frame_count(
    f,
    lba: int,
    magic: bytes,
    stride: int,
    hard_cap: int = 1 << 20,
    *,
    frame_ok=None,
) -> int:
    """倍增 + 二分，找从 lba 起属于同一段录制的帧数。

    实测 62.5GB 卡上约 12ms。这就是「读多少」的答案——不用人算。

    frame_ok(sector0: bytes, idx: int) -> bool 可覆盖判定逻辑：
    默认只比 magic（老数据没有段标记，只能这么判）。车端加了 run_id/seq 之后
    传一个校验它们的谓词，就能把「上次没跑完留在卡上的陈旧帧」截断掉——
    只看 magic 的话，今天 300 帧会和昨天残留的 700 帧无缝拼成 1000 帧且不报错。

    注意：每次探测只读**帧的第 0 个扇区**，所以谓词只能用到帧内偏移 < 512 的字段。
    这也是 run_id/seq 该放帧头而非帧尾补零区的原因（放帧尾要多读 5 倍）。

    二分要求判定是「前缀为真、之后为假」，即同一段的帧在卡上必须物理连续。
    """
    if not magic and frame_ok is None:
        return 0
    step = stride // SECTOR

    def ok(idx: int) -> bool:
        d = read_sectors(f, lba + idx * step, 1)
        if len(d) < len(magic) or bytes(d[:len(magic)]) != magic:
            return False
        return frame_ok(bytes(d), idx) if frame_ok is not None else True

    if not ok(0):
        return 0
    lo, hi = 0, 1
    while hi < hard_cap and ok(hi):
        lo = hi
        hi = min(hi * 2, hard_cap)
        if hi == lo:            # 已顶到上限，别再倍增
            break
    # hi 此时是「已知不属于本段」或上限，二分收敛到真实边界
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return min(lo + 1, hard_cap)


def explain_oserror(e: OSError, letter: str) -> str:
    """把 CPython 的错误映射翻译回人话。

    坑：ERROR_NOT_READY(21，插槽没卡) 会被映射成 errno 13 PermissionError，
    看起来像权限不足，其实只是没插卡。filename 为 None 是判据（错误来自 read 而非 open）。
    """
    if isinstance(e, PermissionError):
        if e.filename is None:
            return f"{letter}: 读不到数据——多半是读卡器里没插卡，或卡接触不良。"
        return (
            f"无法打开 {letter}:——该盘不是可移动盘，或已被其他程序独占。\n"
            "（本功能只支持可移动盘，不会也不能访问系统盘。）"
        )
    if getattr(e, "errno", None) == 22:
        return "读取偏移未按 512 字节对齐——这是内部错误，请反馈。"
    return f"读取 {letter}: 失败：{e}"
