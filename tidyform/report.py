"""自包含 HTML 报告：左右对照，行号与改动标记取自引擎，报告层只排版。"""

from __future__ import annotations

import html

from .core import format_text, line_diff

_STYLE = """
body{margin:24px;font:14px/1.5 "PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;color:#1f2328}
h1{font-size:20px;margin:0 0 4px}
h2{font-size:15px;margin:28px 0 8px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
table{border-collapse:collapse}
.s td,.s th{border:1px solid #d0d7de;padding:4px 14px;text-align:left}
.s th{background:#f6f8fa}
.s td.num{text-align:right;font-variant-numeric:tabular-nums}
.ok{color:#1a7f37;font-weight:600}
.bad{color:#cf222e;font-weight:600}
.d{margin-top:4px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;line-height:1.45}
.d td{vertical-align:top;white-space:pre}
.d td.n{color:#6e7781;text-align:right;padding:0 8px;-webkit-user-select:none;user-select:none;border-right:1px solid #eaeef2;min-width:3em}
.d td.xl{background:#ffebe9}
.d td.xr{background:#dafbe1}
.legend{color:#57606a;font-size:12px;margin:4px 0 0}
.sw{display:inline-block;width:10px;height:10px;margin:0 4px 0 12px;vertical-align:middle}
""".strip()


def _number_cell(number):
    if number is None:
        return "<td class=n>"
    return "<td class=n>%d" % number


def _text_cell(text, changed, mark):
    if text is None:
        return "<td>"
    if changed:
        return '<td class="%s">%s' % (mark, html.escape(text))
    return "<td>%s" % html.escape(text)


def _file_section(name, before, after):
    changed, rows = line_diff(before, after)
    parts = ["<h2>", html.escape(name), "</h2><table class=d>"]
    for left_no, left_tx, left_ch, right_no, right_tx, right_ch in rows:
        parts.append("<tr>")
        parts.append(_number_cell(left_no))
        parts.append(_text_cell(left_tx, left_ch, "xl"))
        parts.append(_number_cell(right_no))
        parts.append(_text_cell(right_tx, right_ch, "xr"))
    parts.append("</table>")
    return changed, "".join(parts)


def write_report(path, files):
    """files 是 (显示名, 原文, 结果) 的列表；产出单个自包含 HTML 文件。"""
    summary = []
    sections = []
    total = 0
    for name, before, after in files:
        changed, section = _file_section(name, before, after)
        total += changed
        idempotent = format_text(after) == after
        summary.append(
            "<tr><td>%s<td class=num>%d<td class=%s>%s"
            % (html.escape(name), changed,
               "ok" if idempotent else "bad",
               "通过" if idempotent else "未通过")
        )
        sections.append(section)
    out = [
        "<!DOCTYPE html><html lang=zh-CN><head><meta charset=utf-8>",
        "<title>tidyform 格式化报告</title><style>", _STYLE, "</style></head><body>",
        "<h1>tidyform 格式化报告</h1>",
        '<p class=legend>改动行数 = 行级最长公共序列之外的行数（原文被替换或删除的行 + 结果新增的行）；'
        "幂等自检 = 对结果再跑一次格式化，零改动为通过。",
        '<span class=sw style="background:#ffebe9"></span>原文改动行',
        '<span class=sw style="background:#dafbe1"></span>结果改动行</p>',
        "<table class=s><tr><th>文件<th>改动行数<th>幂等自检",
        "".join(summary),
        '<tr><th>合计<td class=num>%d<td>' % total,
        "</table>",
        "".join(sections),
        "</body></html>",
    ]
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write("".join(out))
