"""gcc 诊断信息解析。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_DIAG_RE = re.compile(
    r"^(.+?):(\d+):(?:(\d+):)?\s*(fatal error|error|warning|note):\s*(.*)$"
)
_UNDEF_RE = re.compile(r"undefined reference to [`'](\w+)'")


@dataclass
class Diagnostic:
    file: str          # 用户工作区内的原始文件路径（已回映射）
    line: int
    col: int
    severity: str      # error / warning / note
    msg: str


@dataclass
class CompileResult:
    ok: bool
    exe_path: Path | None
    diags: list[Diagnostic] = field(default_factory=list)
    raw_output: str = ""
    friendly_error: str = ""   # 链接错误等的中文友好提示


def parse_gcc_output(text: str, file_map: dict[str, str]) -> list[Diagnostic]:
    """解析 gcc stderr；file_map 把临时区文件名映射回用户原始路径。"""
    diags: list[Diagnostic] = []
    for line in text.splitlines():
        m = _DIAG_RE.match(line.strip())
        if not m:
            continue
        raw_file, lineno, col, sev, msg = m.groups()
        name = Path(raw_file).name
        orig = file_map.get(name, raw_file)
        diags.append(
            Diagnostic(
                file=orig,
                line=int(lineno),
                col=int(col) if col else 1,
                severity="error" if "error" in sev else sev,
                msg=msg.strip(),
            )
        )
    return diags


def friendly_link_error(text: str) -> str:
    """把常见 ld 错误翻译成中文提示；无匹配返回空串。"""
    names = _UNDEF_RE.findall(text)
    if not names:
        return ""
    uniq = sorted(set(names))
    if "image_process" in uniq:
        return (
            "链接失败：找不到 image_process 函数。\n"
            "请确认代码里定义了  void image_process(uint8_t img[IMG_H][IMG_W])  "
            "（检查函数名拼写和参数）。"
        )
    return "链接失败：以下函数被调用但没有定义：" + ", ".join(uniq)
