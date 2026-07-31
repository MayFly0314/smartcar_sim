"""数据记录方案：帧布局模型 + 车端 C 代码生成 + 记录文件解码。

一个"方案"= 一帧在 SD 卡里的字节布局：
    [帧头 magic][参数1][参数2]...[图像(1bpp压缩/8bit原始/无)][补零到整扇区]
上位机据此：
  1) 生成车端打包写卡的 C 函数（用户复制进 image_record.c）；
  2) 用同一方案把记录文件解回 (FrameSet, 每参数逐帧数组)。
两端字节序均为小端（RISC-V / x86 一致），float 为 4 字节 IEEE754。
"""
from __future__ import annotations

import json
import struct
from dataclasses import asdict, dataclass, field

import numpy as np

from ..imaging.loader import FrameSet
from ..link.serial_link import parse_hex

_SECTOR = 512

# ctype -> (struct fmt, 字节数, numpy dtype, C 类型名)
CTYPES: dict[str, tuple[str, int, str, str]] = {
    "uint8":  ("B", 1, "u1", "uint8"),
    "int8":   ("b", 1, "i1", "int8"),
    "uint16": ("H", 2, "u2", "uint16"),
    "int16":  ("h", 2, "i2", "int16"),
    "uint32": ("I", 4, "u4", "uint32"),
    "int32":  ("i", 4, "i4", "int32"),
    "float":  ("f", 4, "f4", "float"),
}

IMAGE_MODES = {  # key -> 显示名
    "packed1": "压缩二值 1bit/像素",
    "raw8":    "原始灰度 8bit/像素",
    "none":    "不存图像（仅参数）",
}


@dataclass
class ParamField:
    name: str            # 显示名（回放面板里可改，不影响布局）
    ctype: str           # CTYPES key
    expr: str            # 车端 C 变量/表达式（生成代码用）


@dataclass
class RecordScheme:
    magic_hex: str = "AA 55"
    params: list[ParamField] = field(default_factory=list)
    image_mode: str = "packed1"
    image_expr: str = "binary_image"   # 车端图像数组名
    img_w: int = 186
    img_h: int = 70
    func_name: str = "sd_record_frame_c"

    # ---- 布局 ----
    def magic(self) -> bytes:
        return parse_hex(self.magic_hex)

    def params_bytes(self) -> int:
        return sum(CTYPES[p.ctype][1] for p in self.params)

    def image_bytes(self) -> int:
        per = self.img_w * self.img_h
        if self.image_mode == "packed1":
            return (per + 7) // 8
        if self.image_mode == "raw8":
            return per
        return 0

    def payload_bytes(self) -> int:
        return len(self.magic()) + self.params_bytes() + self.image_bytes()

    def sectors_per_frame(self) -> int:
        return max(1, (self.payload_bytes() + _SECTOR - 1) // _SECTOR)

    def stride(self) -> int:
        return self.sectors_per_frame() * _SECTOR

    def layout_summary(self) -> str:
        m, pb, ib = len(self.magic()), self.params_bytes(), self.image_bytes()
        return (
            f"帧头 {m}B + 参数 {pb}B + 图像 {ib}B = {self.payload_bytes()}B "
            f"→ 每帧 {self.sectors_per_frame()} 扇区（{self.stride()}B，含补零）"
        )

    # ---- 持久化 ----
    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "RecordScheme":
        d = json.loads(text)
        d["params"] = [ParamField(**p) for p in d.get("params", [])]
        return cls(**d)

    # ---- 解码 ----
    def find_frame0_offset(self, data: np.ndarray, search: int = 1 << 16) -> int | None:
        """在文件头部搜索第一个有效帧起点（magic 处且下一帧位置也是 magic）。

        用于 HxD 导出起点没对齐时的自救。无 magic 的方案返回 None。
        """
        magic = self.magic()
        if not magic:
            return None
        head = bytes(data[: min(data.size, search + self.stride() + len(magic))])
        k = head.find(magic)
        while k >= 0 and k <= search:
            nxt = k + self.stride()
            if data.size < nxt + len(magic) or bytes(data[nxt:nxt + len(magic)]) == magic:
                return k
            k = head.find(magic, k + 1)
        return None

    def decode(
        self, data: np.ndarray, skip: int = 0
    ) -> tuple[FrameSet | None, list[np.ndarray], int]:
        """按方案切帧。返回 (帧集|None, 与 params 对齐的逐帧值数组列表, 帧数)。"""
        if skip > 0:
            data = data[skip:]
        stride = self.stride()
        n = int(data.size // stride)
        if n == 0:
            raise ValueError(
                f"字节数 {data.size} 不足一帧（每帧 {stride}B）——检查导出长度/方案是否匹配"
            )
        blob = np.ascontiguousarray(data[: n * stride]).reshape(n, stride)

        magic = self.magic()
        if magic and bytes(blob[0, : len(magic)]) != magic:
            raise ValueError(
                f"帧头不匹配：期望 {magic.hex(' ')}，实际 {bytes(blob[0, :len(magic)]).hex(' ')}"
            )

        off = len(magic)
        cols: list[np.ndarray] = []
        for p in self.params:
            _fmt, size, npdt, _c = CTYPES[p.ctype]
            seg = np.ascontiguousarray(blob[:, off:off + size])
            cols.append(np.frombuffer(seg.tobytes(), dtype="<" + npdt).copy())
            off += size

        per = self.img_w * self.img_h
        ib = self.image_bytes()
        if self.image_mode == "none":
            return None, cols, n
        img_seg = np.ascontiguousarray(blob[:, off:off + ib])
        if self.image_mode == "packed1":
            bits = np.unpackbits(img_seg, axis=1)[:, :per]  # MSB 在前，与 C 端一致
            frames = (bits.reshape(n, self.img_h, self.img_w) * 255).astype(np.uint8)
        else:  # raw8
            frames = img_seg.reshape(n, self.img_h, self.img_w).copy()
        return FrameSet(frames=np.ascontiguousarray(frames), paths=[]), cols, n

    # ---- C 代码生成 ----
    def generate_c(self) -> str:
        magic = self.magic()
        sec = self.sectors_per_frame()
        lines: list[str] = []
        a = lines.append
        a("/* ================================================================")
        a(" * 由上位机「数据记录方案」自动生成 —— 整段粘贴到 image_record.c 末尾")
        a(f" * 布局: {self.layout_summary()}")
        a(" * 依赖同文件已有的 IMG_START_SECTOR / MAX_RECORD_FRAMES / record_idx，")
        a(" * 与原始版 sd_record_frame 共用帧计数与起始扇区——一次只用其中一种，")
        a(" * 回放时在上位机选同一方案打开。")
        a(" * ================================================================ */")
        a(f"#define REC_C_SECTORS   {sec}u")
        a(f"static uint8 rec_c_buf[REC_C_SECTORS * 512];")
        a("")
        if self.image_mode == "packed1":
            a("/* 二值图压缩：8 像素/字节，MSB 在前，逐行扫描（上位机按同序解压） */")
            a("static void rec_pack_1bpp(const uint8 img[IMG_H][IMG_W], uint8 *dst)")
            a("{")
            a("    int x, y; uint32 di = 0; uint8 acc = 0, nb = 0;")
            a("    for (y = 0; y < IMG_H; y++)")
            a("        for (x = 0; x < IMG_W; x++) {")
            a("            acc = (uint8)((acc << 1) | (img[y][x] ? 1u : 0u));")
            a("            if (++nb == 8) { dst[di++] = acc; nb = 0; acc = 0; }")
            a("        }")
            a("    if (nb) dst[di++] = (uint8)(acc << (8 - nb));")
            a("}")
            a("")
        a("/* 每帧调用一次。返回 0=成功 1=已满 2=写失败 */")
        a(f"uint8 {self.func_name}(void)")
        a("{")
        a("    uint8 *p = rec_c_buf;")
        a("    if (record_idx >= MAX_RECORD_FRAMES) return 1;")
        a("    memset(rec_c_buf, 0, sizeof(rec_c_buf));")
        if magic:
            hexs = " ".join(f"*p++ = 0x{b:02X};" for b in magic)
            a(f"    {hexs}                     /* 帧头 */")
        for p in self.params:
            _fmt, size, _np, cname = CTYPES[p.ctype]
            a(f"    {{ {cname} v = ({cname})({p.expr}); "
              f"memcpy(p, &v, {size}); p += {size}; }}  /* {p.name} */")
        if self.image_mode == "packed1":
            a(f"    rec_pack_1bpp({self.image_expr}, p);            "
              f"/* 图像压缩 {self.image_bytes()}B */")
        elif self.image_mode == "raw8":
            a(f"    memcpy(p, {self.image_expr}, {self.image_bytes()}u);  "
              f"/* 图像原始 {self.image_bytes()}B */")
        a("    if (SD_write_sector_data(rec_c_buf,")
        a("            IMG_START_SECTOR + record_idx * REC_C_SECTORS,")
        a("            REC_C_SECTORS)) return 2;")
        a("    record_idx++;")
        a("    return 0;")
        a("}")
        return "\n".join(lines) + "\n"


def default_scheme(img_w: int, img_h: int) -> RecordScheme:
    """默认方案：贴合本项目车端现状（binary_image + servo/error 两参数示例）。"""
    return RecordScheme(
        magic_hex="AA 55",
        params=[
            ParamField("servo_angle", "int32", "servo_angle"),
            ParamField("error", "float", "error"),
        ],
        image_mode="packed1",
        image_expr="binary_image",
        img_w=img_w,
        img_h=img_h,
    )
