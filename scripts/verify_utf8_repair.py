"""校验 UTF-8 损坏文档的修复结果是否只在合法候选内取值。

背景：docs/ 下有 3 个文件存在 UTF-8 损坏。损坏形态已查明——每个 3 字节
中文字符的**第 3 字节被替换成 '?'（0x3F）**，前 2 字节完好。实测：
403 处第 3 字节为 '?'、1 处为 '.'，共 1116 处（三文件合计）。

因此修复是"从 64 个候选里挑一个"的问题，而不是自由重写。本脚本提供机械校验：
修复后每个位置的字符，其 UTF-8 前 2 字节必须与损坏文件中原有的 2 字节一致。
这条约束能挡住"顺手改写句子""凭印象重写段落"这类不可接受的修复方式——
修复只允许恢复被吃掉的那 1 个字节。

用法：
    python scripts/verify_utf8_repair.py <损坏文件> <修复后文件>

退出码 0 = 修复合法；非 0 = 有位置越出候选集，附具体差异。
"""

from __future__ import annotations

import sys
from pathlib import Path


def corruption_sites(data: bytes) -> list[tuple[int, bytes]]:
    """返回 [(offset, 完好的前2字节), ...]。"""
    sites: list[tuple[int, bytes]] = []
    i = 0
    while i < len(data):
        try:
            data[i:].decode("utf-8")
            break
        except UnicodeDecodeError as e:
            start = i + e.start
            sites.append((start, data[start : start + 2]))
            i = start + max(1, e.end - e.start)
    return sites


def _segments(data: bytes, sites: list[tuple[int, bytes]]) -> list[bytes]:
    """按损坏点把原文件切成完好片段（每处损坏消耗 3 字节：2 前缀 + 1 个 '?'）。"""
    segs: list[bytes] = []
    prev = 0
    for off, _prefix in sites:
        segs.append(data[prev:off])
        prev = off + 3
    segs.append(data[prev:])
    return segs


def verify(broken_path: Path, fixed_path: Path) -> int:
    broken = broken_path.read_bytes()
    sites = corruption_sites(broken)
    if not sites:
        print(f"[skip] {broken_path} 没有损坏点，无需校验")
        return 0

    fixed_bytes = fixed_path.read_bytes()
    try:
        fixed_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        print(f"[FAIL] 修复后文件仍非合法 UTF-8：offset {e.start} {e.object[e.start : e.end]!r}")
        return 2

    segs = _segments(broken, sites)

    # 修复后文件应形如: seg0 + ch0 + seg1 + ch1 + ... + segN
    # 逐段对齐，把段之间的字节取出来当作"被修复的字符"。
    pos = 0
    problems: list[str] = []
    for idx, seg in enumerate(segs):
        # 段内容必须逐字节一致（修复不得改动未损坏的正文）
        if fixed_bytes[pos : pos + len(seg)] != seg:
            problems.append(f"  第 {idx} 段正文被改动（offset≈{pos}）：修复只允许补齐损坏字符，不得重写正文")
            return _report(problems)
        pos += len(seg)
        if idx == len(segs) - 1:
            break

        # 段之间应恰好是 1 个 3 字节字符，且前 2 字节与损坏前一致
        prefix = sites[idx][1]
        got = fixed_bytes[pos : pos + 3]
        if len(got) < 3:
            problems.append(f"  损坏点 #{idx} 位置修复后内容不足 3 字节")
        elif got[:2] != prefix:
            problems.append(
                f"  损坏点 #{idx}（原 offset {sites[idx][0]}）前缀不符："
                f"应为 {prefix!r}，实为 {got[:2]!r} —— 换了个不相关的字，超出候选集"
            )
        pos += 3

    if pos != len(fixed_bytes):
        problems.append(f"  尾部长度不符：对齐消耗 {pos} 字节，文件共 {len(fixed_bytes)} 字节")

    return _report(problems, total=len(sites), path=fixed_path)


def _report(problems: list[str], total: int = 0, path: Path | None = None) -> int:
    if problems:
        print(f"[FAIL] {path}：{len(problems)} 处不合法")
        for p in problems[:20]:
            print(p)
        return 1
    print(f"[OK] {path}：{total} 处损坏全部在合法候选集内修复，未损坏正文逐字节一致")
    return 0


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 64
    return verify(Path(sys.argv[1]), Path(sys.argv[2]))


if __name__ == "__main__":
    raise SystemExit(main())
