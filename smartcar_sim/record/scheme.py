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
from dataclasses import asdict, dataclass, field, fields

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
    group: str = ""      # 分组名（仅影响面板显示与设计器排序，不影响字节布局）


@dataclass
class LineField:
    """一条边界线：按图像行保存 x 坐标，负数表示该行无效。"""

    name: str
    ctype: str = "int16"
    expr: str = ""


@dataclass
class RecordScheme:
    magic_hex: str = "AA 55"
    params: list[ParamField] = field(default_factory=list)
    image_mode: str = "packed1"
    image_expr: str = "binary_image"   # 车端图像数组名
    img_w: int = 186
    img_h: int = 70
    func_name: str = "sd_record_frame_c"
    line_fields: list[LineField] = field(default_factory=list)

    # ---- 布局 ----
    def magic(self) -> bytes:
        return parse_hex(self.magic_hex)

    def params_bytes(self) -> int:
        return sum(CTYPES[p.ctype][1] for p in self.params)

    def line_bytes(self) -> int:
        return sum(CTYPES[p.ctype][1] * self.img_h for p in self.line_fields)

    def image_bytes(self) -> int:
        per = self.img_w * self.img_h
        if self.image_mode == "packed1":
            return (per + 7) // 8
        if self.image_mode == "raw8":
            return per
        return 0

    def payload_bytes(self) -> int:
        return len(self.magic()) + self.params_bytes() + self.line_bytes() + self.image_bytes()

    def sectors_per_frame(self) -> int:
        return max(1, (self.payload_bytes() + _SECTOR - 1) // _SECTOR)

    def stride(self) -> int:
        return self.sectors_per_frame() * _SECTOR

    def padding_bytes(self) -> int:
        """每帧补零的余量。参数加到吃光余量就会多占一个扇区、写卡变慢。"""
        return self.stride() - self.payload_bytes()

    def headroom_hint(self) -> str:
        """余量提示：还能再加多少参数才会跨扇区。"""
        pad = self.padding_bytes()
        if pad == 0:
            return "⚠ 余量 0B —— 再加任何参数都会多占一个扇区"
        nxt = self.sectors_per_frame() + 1
        pct = round(100 / self.sectors_per_frame())
        return (
            f"余量 {pad}B（约 {pad // 4} 个 int32/float 参数）"
            f"——超出后每帧变 {nxt} 扇区，写卡量 +{pct}%"
        )

    def layout_summary(self) -> str:
        m, pb, lb, ib = (
            len(self.magic()), self.params_bytes(), self.line_bytes(), self.image_bytes()
        )
        return (
            f"帧头 {m}B + 参数 {pb}B + 三线 {lb}B + 图像 {ib}B = {self.payload_bytes()}B "
            f"→ 每帧 {self.sectors_per_frame()} 扇区（{self.stride()}B，含补零）\n"
            f"{self.headroom_hint()}"
        )

    # ---- 持久化 ----
    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "RecordScheme":
        d = json.loads(text)
        # 只取认识的键：老方案没有 group（取默认值），将来多出的键也不会炸
        d["params"] = [
            ParamField(**{k: v for k, v in p.items()
                          if k in ("name", "ctype", "expr", "group")})
            for p in d.get("params", [])
        ]
        if "line_fields" in d:
            d["line_fields"] = [
                LineField(**{k: v for k, v in p.items()
                             if k in ("name", "ctype", "expr")})
                for p in d.get("line_fields", [])
            ]
        else:
            d["line_fields"] = default_line_fields(int(d.get("img_h", 70)))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})

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
        """兼容接口：返回 (帧集|None, 参数数组, 帧数)。"""
        fs, cols, n, _lines = self.decode_with_lines(data, skip)
        return fs, cols, n

    def decode_with_lines(
        self, data: np.ndarray, skip: int = 0
    ) -> tuple[FrameSet | None, list[np.ndarray], int, list[np.ndarray]]:
        """按方案切帧，并额外返回与 line_fields 对齐的三线数组。"""
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

        line_cols: list[np.ndarray] = []
        for line in self.line_fields:
            _fmt, size, npdt, _c = CTYPES[line.ctype]
            total = size * self.img_h
            seg = np.ascontiguousarray(blob[:, off:off + total]).reshape(n, self.img_h, size)
            line_cols.append(
                np.frombuffer(seg.tobytes(), dtype="<" + npdt).copy().reshape(n, self.img_h)
            )
            off += total

        per = self.img_w * self.img_h
        ib = self.image_bytes()
        if self.image_mode == "none":
            return None, cols, n, line_cols
        img_seg = np.ascontiguousarray(blob[:, off:off + ib])
        if self.image_mode == "packed1":
            bits = np.unpackbits(img_seg, axis=1)[:, :per]  # MSB 在前，与 C 端一致
            frames = (bits.reshape(n, self.img_h, self.img_w) * 255).astype(np.uint8)
        else:  # raw8
            frames = img_seg.reshape(n, self.img_h, self.img_w).copy()
        return FrameSet(frames=np.ascontiguousarray(frames), paths=[]), cols, n, line_cols

    # ---- C 代码生成 ----
    def generate_c(self) -> str:
        magic = self.magic()
        sec = self.sectors_per_frame()
        lines: list[str] = []
        a = lines.append
        a("/* ================================================================")
        a(" * 由上位机「数据记录方案」自动生成 —— 整段粘贴到 image_record.c 末尾")
        for i, ln in enumerate(self.layout_summary().splitlines()):
            a(f" * 布局: {ln}" if i == 0 else f" *       {ln}")
        a(" * 依赖同文件已有的 IMG_START_SECTOR / MAX_RECORD_FRAMES / record_idx，")
        a(" * 与原始版 sd_record_frame 共用帧计数与起始扇区——一次只用其中一种，")
        a(" * 回放时在上位机选同一方案打开。")
        a(" * ================================================================ */")
        a(f"#define REC_C_SECTORS   {sec}u")
        a(f"#define REC_IMG_W       {self.img_w}   /* 方案里填的分辨率，非工程宏 */")
        a(f"#define REC_IMG_H       {self.img_h}")
        a("/* 缓冲区按方案算，循环也必须按方案走——两者同源才不会写越界。")
        a(" * 若与工程的 IMG_W/IMG_H 不一致，下面这行编译期就会报错（而不是到车上踩内存）。")
        a(" * 如果你的工程没有 IMG_W/IMG_H 宏，删掉这一行即可。 */")
        a("_Static_assert(IMG_W == REC_IMG_W && IMG_H == REC_IMG_H,")
        a('               "scheme resolution != project IMG_W/IMG_H");')
        a("static uint8 rec_c_buf[REC_C_SECTORS * 512];")
        a("")
        a("/* 多段录制的挂钩：定义了 sd_log_* 那套就用它的基址和帧序号，")
        a(" * 没定义就退回原来的固定起点行为。这样这段生成代码在两种工程里都能直接编译。 */")
        a("#ifndef SDLOG_BASE")
        a("  #ifdef SDLOG_HIST_START            /* 有多段录制模块 */")
        a("    #define SDLOG_BASE     sdlog_base_lba")
        a("    #define SDLOG_SEQ_INC  (sdlog_seq++)")
        a("  #else                              /* 没有：老的固定起点 */")
        a("    #define SDLOG_BASE     IMG_START_SECTOR")
        a("    #define SDLOG_SEQ_INC  ((void)0)")
        a("  #endif")
        a("#endif")
        a("")
        if self.image_mode == "packed1":
            a("/* 二值图压缩：8 像素/字节，MSB 在前，逐行扫描（上位机按同序解压） */")
            a("static void rec_pack_1bpp(uint8 img[REC_IMG_H][REC_IMG_W], uint8 *dst)")
            a("{")
            a("    int x, y; uint32 di = 0; uint8 acc = 0, nb = 0;")
            a("    for (y = 0; y < REC_IMG_H; y++)")
            a("        for (x = 0; x < REC_IMG_W; x++) {")
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
        a("#ifdef SDLOG_HIST_END      /* 多段录制：满 = 写到历史区尽头 */")
        a("    if (SDLOG_BASE + (record_idx + 1) * REC_C_SECTORS > SDLOG_HIST_END) return 1;")
        a("#else")
        a("    if (record_idx >= MAX_RECORD_FRAMES) return 1;")
        a("#endif")
        a("    memset(rec_c_buf, 0, sizeof(rec_c_buf));")
        if magic:
            hexs = " ".join(f"*p++ = 0x{b:02X};" for b in magic)
            a(f"    {hexs}                     /* 帧头 */")
        cur_group = None
        for p in self.params:
            _fmt, size, _np, cname = CTYPES[p.ctype]
            g = (p.group or "").strip()
            if g != cur_group:
                cur_group = g
                if g:
                    a(f"    /* ---- {g} ---- */")
            a(f"    {{ {cname} v = ({cname})({p.expr}); "
              f"memcpy(p, &v, {size}); p += {size}; }}  /* {p.name} */")
        for line in self.line_fields:
            _fmt, size, _np, cname = CTYPES[line.ctype]
            a(f"    /* {line.name}: 每行一个 x 坐标，负数表示无效 */")
            a(f"    for (int i = 0; i < REC_IMG_H; ++i) {{ {cname} v = ({cname})({line.expr}[i]); "
              f"memcpy(p, &v, {size}); p += {size}; }}")
        if self.image_mode == "packed1":
            a(f"    rec_pack_1bpp({self.image_expr}, p);            "
              f"/* 图像压缩 {self.image_bytes()}B */")
        elif self.image_mode == "raw8":
            a(f"    memcpy(p, {self.image_expr}, {self.image_bytes()}u);  "
              f"/* 图像原始 {self.image_bytes()}B */")
        # 多段录制：基址、帧序号、满判据都由生成器写出来，
        # 免得用户重新粘贴时把手工加的那几行覆盖掉（踩过一次：
        # sdlog_seq++ 被覆盖 → seq 恒为 0 → 上位机每段只认出 1 帧）。
        a("    if (SD_write_sector_data(rec_c_buf,")
        a("            SDLOG_BASE + record_idx * REC_C_SECTORS,")
        a("            REC_C_SECTORS)) return 2;")
        a("    record_idx++;")
        a("    SDLOG_SEQ_INC;")
        a("    return 0;")
        a("}")
        return "\n".join(lines) + "\n"


def default_line_fields(img_h: int) -> list[LineField]:
    """默认三线：左边界 / 中线 / 右边界，数组长度为 IMG_H。"""
    _ = img_h
    return [
        LineField("左边界", "int16", "left_boundary"),
        LineField("中线", "int16", "center_line"),
        LineField("右边界", "int16", "right_boundary"),
    ]


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
        line_fields=default_line_fields(img_h),
    )
