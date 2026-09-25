"""自包含 HTML 报告：顶部汇总 + 每份文件左右逐行对照。

不依赖 JavaScript 与外部资源。行号与改动标记全部来自引擎
（engine.diff_rows / engine.count_changed_lines），本模块只排版。
"""

from __future__ import annotations

import html

from .engine import diff_rows, format_text

_CSS = """
body{font:14px/1.45 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;margin:24px;color:#1f2328;background:#fff}
h1{font-size:20px}h2{font-size:16px;margin:28px 0 8px}
table{border-collapse:collapse}
.summary td,.summary th{border:1px solid #d0d7de;padding:4px 12px;text-align:left}
.summary th{background:#f6f8fa}
.pass{color:#1a7f37}.fail{color:#cf222e}
.diff{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12.5px;width:100%}
.diff td{padding:0 8px;white-space:pre;vertical-align:top}
.diff td.n{text-align:right;color:#8c959f;border-right:1px solid #eaeef2;min-width:3em}
.diff td.sep{width:12px}
tr.c td{background:#fff8c5}
tr.c td.m{background:#ffebe9}
.legend{color:#57606a;font-size:12.5px;margin:4px 0 16px}
.sw{display:inline-block;width:12px;height:12px;vertical-align:-2px;background:#fff8c5;border:1px solid #d4a72c}
"""


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def _render_rows(name: str, rows: list[tuple]) -> str:
    parts = [f"<h2>{_esc(name)}</h2>\n<table class=diff>"]
    for left_no, left, right_no, right, changed in rows:
        cls = " class=c" if changed else ""
        lno = str(left_no) if left_no is not None else ""
        rno = str(right_no) if right_no is not None else ""
        ltxt = _esc(left) if left is not None else ""
        rtxt = _esc(right) if right is not None else ""
        lm = " class=m" if changed and left is None else ""
        rm = " class=m" if changed and right is None else ""
        parts.append(
            f"<tr{cls}><td class=n>{lno}</td><td{lm}>{ltxt}</td>"
            f"<td class=sep></td>"
            f"<td class=n>{rno}</td><td{rm}>{rtxt}</td></tr>"
        )
    parts.append("</table>")
    return "\n".join(parts)


def _changed_of(rows: list[tuple]) -> int:
    """从对照行推出改动行数，与 engine.count_changed_lines 同口径。"""
    total = 0
    for left_no, _l, right_no, _r, changed in rows:
        if changed:
            total += (left_no is not None) + (right_no is not None)
    return total


def build_report(files: list[tuple[str, str, str]]) -> str:
    """files 是 (显示名, 原文, 结果) 的列表，返回完整 HTML。"""
    summary_rows = []
    bodies = []
    for name, before, after in files:
        rows = diff_rows(before, after)
        changed = _changed_of(rows)
        idem_ok = format_text(after) == after
        idem = '<span class=pass>通过（0 行改动）</span>' if idem_ok else '<span class=fail>未通过</span>'
        summary_rows.append(
            f"<tr><td>{_esc(name)}</td><td>{changed}</td><td>{idem}</td></tr>"
        )
        bodies.append(_render_rows(name, rows))
    return (
        "<!DOCTYPE html>\n<html lang=zh><head><meta charset=utf-8>"
        "<title>tidyform 格式差异报告</title>"
        f"<style>{_CSS}</style></head><body>\n"
        "<h1>tidyform 格式差异报告</h1>\n"
        "<table class=summary><tr><th>文件</th><th>改动行数</th><th>幂等自检</th></tr>"
        + "\n".join(summary_rows)
        + "</table>\n"
        '<p class=legend><span class=sw></span> 高亮行为改动行；行号与改动标记由格式化引擎给出。</p>\n'
        + "\n".join(bodies)
        + "\n</body></html>\n"
    )


def write_report(path: str, files: list[tuple[str, str, str]]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(build_report(files))
