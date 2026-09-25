"""格式化引擎：分词、状态机、规范形状渲染、行级 diff。

只依赖标准库。规范形状的唯一确定规则见 README 第 2 节。
"""

from __future__ import annotations

import difflib

MAX_WIDTH = 100
INDENT = "    "


class FormatError(Exception):
    """输入不符合 README 4.1 的约定时抛出。"""


# ---------------------------------------------------------------- 分词

_DELIMS = set(' \t"(),=')


def tokenize(code: str, lineno: int) -> list[str]:
    """把一行（已去掉注释）的代码部分切成 token 列表。"""
    tokens: list[str] = []
    i = 0
    n = len(code)
    while i < n:
        ch = code[i]
        if ch in " \t":
            i += 1
        elif ch in "(),=":
            tokens.append(ch)
            i += 1
        elif ch == '"':
            j = i + 1
            closed = False
            while j < n:
                cj = code[j]
                if cj == "\\":
                    j += 2
                    continue
                if cj == '"':
                    closed = True
                    j += 1
                    break
                j += 1
            if not closed:
                raise FormatError(f"第 {lineno} 行：字符串未闭合（字符串不跨行）")
            tokens.append(code[i:j])
            i = j
        else:
            j = i
            while j < n and code[j] not in _DELIMS:
                j += 1
            tokens.append(code[i:j])
            i = j
    return tokens


def split_comment(line: str) -> tuple[str, str | None]:
    """把一行拆成（代码, 注释）。注释含开头的 #，不含行尾空白。"""
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == '"':
            i += 1
            while i < n:
                ci = line[i]
                if ci == "\\":
                    i += 2
                    continue
                if ci == '"':
                    i += 1
                    break
                i += 1
            else:
                # 未闭合字符串：交给 tokenize 报错，这里先当没有注释
                return line, None
        elif ch == "#":
            return line[:i], line[i:]
        else:
            i += 1
    return line, None


# ---------------------------------------------------------------- 解析

# 数据单位：("stmt", tokens, comment) / ("comment", text) / ("blank",)


def parse(text: str) -> list[tuple]:
    """按行读入，返回单位序列（空行尚未折叠）。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    units: list[tuple] = []
    stmt_tokens: list[str] | None = None
    stmt_comment: str | None = None
    stmt_start = 0
    depth = 0

    for lineno, raw in enumerate(text.split("\n"), 1):
        line = raw.rstrip(" \t")
        code, comment = split_comment(line)
        if stmt_tokens is None and not code.strip():
            if comment is not None:
                units.append(("comment", comment))
            else:
                units.append(("blank",))
            continue
        if stmt_tokens is None:
            stmt_tokens = []
            stmt_comment = None
            stmt_start = lineno
            depth = 0
        elif not code.strip():
            raise FormatError(f"第 {lineno} 行：语句内部不允许空行或独立注释行")
        if comment is not None:
            if stmt_comment is not None:
                raise FormatError(f"第 {lineno} 行：一条语句最多一个行尾注释")
            stmt_comment = comment
        for tok in tokenize(code, lineno):
            if tok == "(":
                depth += 1
            elif tok == ")":
                depth -= 1
                if depth < 0:
                    raise FormatError(f"第 {lineno} 行：括号不配平（多余的右括号）")
            stmt_tokens.append(tok)
        if depth == 0:
            units.append(("stmt", stmt_tokens, stmt_comment))
            stmt_tokens = None
    if stmt_tokens is not None:
        raise FormatError(f"第 {stmt_start} 行：语句到文件末尾括号仍未配平")
    return units


# ---------------------------------------------------------------- 渲染


def _need_space(left: str, right: str) -> bool:
    if left == "(" or right == "(" or right == ")" or right == ",":
        return False
    return True


def join_tokens(tokens: list[str]) -> str:
    """规范间距拼接；`)` 前的 `,`（空尾参数）不写出。"""
    out: list[str] = []
    prev: str | None = None
    for idx, tok in enumerate(tokens):
        if tok == "," and idx + 1 < len(tokens) and tokens[idx + 1] == ")":
            continue
        if prev is not None and _need_space(prev, tok):
            out.append(" ")
        out.append(tok)
        prev = tok
    return "".join(out)


def _match_parens(tokens: list[str]) -> list[int]:
    match = [-1] * len(tokens)
    stack: list[int] = []
    for i, tok in enumerate(tokens):
        if tok == "(":
            stack.append(i)
        elif tok == ")":
            match[stack.pop()] = i
    return match


def _top_level_args(tokens: list[str], open_idx: int, close_idx: int) -> list[list[str]]:
    """按顶层逗号切参数；末尾空参数（尾随逗号）不算。"""
    args: list[list[str]] = []
    depth = 0
    start = open_idx + 1
    for i in range(open_idx + 1, close_idx):
        tok = tokens[i]
        if tok == "(":
            depth += 1
        elif tok == ")":
            depth -= 1
        elif tok == "," and depth == 0:
            args.append(tokens[start:i])
            start = i + 1
    tail = tokens[start:close_idx]
    if tail or args:
        args.append(tail)
    if args and not args[-1]:
        args.pop()
    return args


def _find_split_group(tokens: list[str], match: list[int]):
    """按 ( 出现顺序找第一个顶层参数 ≥ 2 的括号组。"""
    for i, tok in enumerate(tokens):
        if tok != "(":
            continue
        args = _top_level_args(tokens, i, match[i])
        if len(args) >= 2:
            return i, match[i], args
    return None


def render_tokens(
    tokens: list[str],
    indent: int,
    match: list[int] | None = None,
    extra_width: int = 0,
) -> list[str]:
    """把一条语句的 token 渲染成规范形状的行（不含行尾注释）。

    extra_width 是行尾注释占的列数（两个空格 + 注释文本），只影响
    语句整体的单行/拆行判断；递归进参数后注释不再参与。
    """
    if match is None:
        match = _match_parens(tokens)
    single = join_tokens(tokens)
    pad = INDENT * indent
    if indent * 4 + len(single) + extra_width <= MAX_WIDTH:
        return [pad + single]
    group = _find_split_group(tokens, match)
    if group is None:
        return [pad + single]
    open_idx, close_idx, args = group
    lines = [pad + join_tokens(tokens[: open_idx + 1])]
    for arg in args:
        sub = render_tokens(arg, indent + 1)
        sub[-1] += ","
        lines.extend(sub)
    lines.append(pad + join_tokens(tokens[close_idx:]))
    return lines


# ---------------------------------------------------------------- 格式化


def format_text(text: str) -> str:
    """把输入文本格式化为规范形状。幂等：format_text(format_text(x)) == format_text(x)。"""
    units = parse(text)
    # 折叠空行：连续折成 1 行，首尾丢弃
    collapsed: list[tuple] = []
    for unit in units:
        if unit[0] == "blank":
            if collapsed and collapsed[-1][0] != "blank":
                collapsed.append(unit)
        else:
            collapsed.append(unit)
    while collapsed and collapsed[-1][0] == "blank":
        collapsed.pop()
    if not collapsed:
        return ""
    lines: list[str] = []
    for unit in collapsed:
        kind = unit[0]
        if kind == "blank":
            lines.append("")
        elif kind == "comment":
            lines.append(unit[1])
        else:
            comment = unit[2]
            extra = len(comment) + 2 if comment is not None else 0
            stmt_lines = render_tokens(unit[1], 0, extra_width=extra)
            if comment is not None:
                stmt_lines[-1] += "  " + comment
            lines.extend(stmt_lines)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- diff


def _lines_of(text: str) -> list[str]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _lcs_size(a: list[str], b: list[str]) -> int:
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(block.size for block in matcher.get_matching_blocks())


def count_changed_lines(before: str, after: str) -> int:
    """行级 LCS 之外的行数：原文被替换/删除的行 + 结果新增的行。"""
    a = _lines_of(before)
    b = _lines_of(after)
    return len(a) + len(b) - 2 * _lcs_size(a, b)


def diff_rows(before: str, after: str) -> list[tuple]:
    """逐行对照行：(左行号, 左文本, 右行号, 右文本, 是否改动)。

    行号从 1 开始；不存在的一侧行号为 None。报告层只排版，不重算。
    """
    a = _lines_of(before)
    b = _lines_of(after)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    rows: list[tuple] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                rows.append((i1 + k + 1, a[i1 + k], j1 + k + 1, b[j1 + k], False))
        elif tag == "replace":
            pairs = max(i2 - i1, j2 - j1)
            for k in range(pairs):
                left = (i1 + k + 1, a[i1 + k]) if i1 + k < i2 else (None, None)
                right = (j1 + k + 1, b[j1 + k]) if j1 + k < j2 else (None, None)
                rows.append((left[0], left[1], right[0], right[1], True))
        elif tag == "delete":
            for k in range(i1, i2):
                rows.append((k + 1, a[k], None, None, True))
        else:  # insert
            for k in range(j1, j2):
                rows.append((None, None, k + 1, b[k], True))
    return rows
