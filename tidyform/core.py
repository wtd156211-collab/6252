"""幂等格式化引擎：解析、规范形状重排、行级差异统计。"""

from __future__ import annotations

import difflib
from bisect import bisect_left
from collections import Counter

MAX_WIDTH = 100
INDENT = "    "
COMMENT_GAP = "  "

_NO_SPACE_BEFORE = frozenset("(),")
_WORD_END = frozenset(' \t"(),=')


class FormatError(Exception):
    """输入不符合 README 4.1 的约定。"""


def _split_comment(line):
    """把一行拆成 (代码, 注释)。注释从字符串外第一个 # 起，只删行尾空白。"""
    in_string = False
    index = 0
    length = len(line)
    while index < length:
        char = line[index]
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "#":
            return line[:index], line[index:].rstrip(" \t")
        index += 1
    if in_string:
        raise FormatError("字符串没有在一行内闭合")
    return line, None


def _paren_balance(code, balance):
    """在既有括号深度上累计一行的括号收支，字符串内的括号不计。"""
    in_string = False
    index = 0
    length = len(code)
    while index < length:
        char = code[index]
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "(":
            balance += 1
        elif char == ")":
            balance -= 1
            if balance < 0:
                raise FormatError("括号不配平")
        index += 1
    return balance


def _tokenize(code):
    """切出字符串与词；空白只作分隔符。"""
    tokens = []
    index = 0
    length = len(code)
    while index < length:
        char = code[index]
        if char in " \t":
            index += 1
        elif char == '"':
            end = index + 1
            while end < length:
                if code[end] == "\\":
                    end += 2
                    continue
                if code[end] == '"':
                    break
                end += 1
            tokens.append(code[index:end + 1])
            index = end + 1
        elif char in "(),=":
            tokens.append(char)
            index += 1
        else:
            end = index
            while end < length and code[end] not in _WORD_END:
                end += 1
            tokens.append(code[index:end])
            index = end
    return tokens


def _parse_units(text):
    """把全文解析成单位序列：空行 / 独立注释行 / 语句（token 列表 + 行尾注释）。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    units = []
    index = 0
    total = len(lines)
    while index < total:
        code, comment = _split_comment(lines[index])
        index += 1
        if not code.strip(" \t"):
            if comment is None:
                units.append(("blank", None, None))
            else:
                units.append(("comment", comment, None))
            continue
        parts = [code]
        balance = _paren_balance(code, 0)
        while balance > 0:
            if index >= total:
                raise FormatError("语句结束括号不配平")
            more, more_comment = _split_comment(lines[index])
            index += 1
            if not more.strip(" \t"):
                raise FormatError("语句内部出现空行或独立注释行")
            if more_comment is not None:
                if comment is not None:
                    raise FormatError("一条语句最多一个行尾注释")
                comment = more_comment
            parts.append(more)
            balance = _paren_balance(more, balance)
        units.append(("stmt", _tokenize(" ".join(parts)), comment))
    return units


def _join(tokens):
    """规范间距拼接 token；右括号前的尾随逗号（空参数）不写出。"""
    out = []
    previous = ""
    for position, token in enumerate(tokens):
        if token == "," and position + 1 < len(tokens) and tokens[position + 1] == ")":
            continue
        if out and previous != "(" and token not in _NO_SPACE_BEFORE:
            out.append(" ")
        out.append(token)
        previous = token
    return "".join(out)


def _split_args(tokens):
    """按顶层逗号切参数；末尾的空参数（尾随逗号）不算。"""
    args = []
    depth = 0
    start = 0
    for position, token in enumerate(tokens):
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
        elif token == "," and depth == 0:
            args.append(tokens[start:position])
            start = position + 1
    args.append(tokens[start:])
    if args and not args[-1]:
        args.pop()
    return args


def _find_split_span(tokens):
    """找可拆的括号组：最左组参数 >= 2 即可拆；单参数且内部还有组就继续往里找。"""
    for position, token in enumerate(tokens):
        if token != "(":
            continue
        depth = 0
        close = position
        while True:
            current = tokens[close]
            if current == "(":
                depth += 1
            elif current == ")":
                depth -= 1
                if depth == 0:
                    break
            close += 1
        args = _split_args(tokens[position + 1:close])
        if len(args) >= 2:
            return position, close
        if len(args) == 1:
            sub = _find_split_span(args[0])
            if sub is not None:
                return position + 1 + sub[0], position + 1 + sub[1]
        return None
    return None


def _render(tokens, level, comment, suffix):
    """把一条语句（或一个参数）渲染成若干行，suffix 是行尾补的逗号。"""
    single = INDENT * level + _join(tokens) + suffix
    if comment is not None:
        single += COMMENT_GAP + comment
    if len(single) <= MAX_WIDTH:
        return [single]
    span = _find_split_span(tokens)
    if span is None:
        return [single]
    open_at, close_at = span
    pad = INDENT * level
    lines = [pad + _join(tokens[:open_at + 1])]
    for arg in _split_args(tokens[open_at + 1:close_at]):
        lines.extend(_render(arg, level + 1, None, ","))
    last = pad + _join(tokens[close_at:]) + suffix
    if comment is not None:
        last += COMMENT_GAP + comment
    lines.append(last)
    return lines


def format_text(text):
    """把输入文本整理成规范形状；同一份输入永远得到同一份输出。"""
    units = _parse_units(text)
    out = []
    blank_pending = False
    for kind, payload, comment in units:
        if kind == "blank":
            if out:
                blank_pending = True
            continue
        if blank_pending:
            out.append("")
            blank_pending = False
        if kind == "comment":
            out.append(payload)
        else:
            out.extend(_render(payload, 0, comment, ""))
    if not out:
        return ""
    return "\n".join(out) + "\n"


def _to_lines(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if lines and not lines[-1]:
        lines.pop()
    return lines


_ANCHOR_LIMIT = 64


def _anchor_opcodes(old, new):
    """行级对齐：出现次数相同且不太频繁的行按次序配对成锚，锚间递归切分。

    锚把大问题切成小段，段内找不到锚时退回 difflib 精确比对；
    输出与「行级最长公共序列之外」同口径的一组 (tag, i1, i2, j1, j2)。
    """
    out = []
    stack = [(0, len(old), 0, len(new))]
    while stack:
        alo, ahi, blo, bhi = stack.pop()
        while alo < ahi and blo < bhi and old[alo] == new[blo]:
            out.append(("equal", alo, alo + 1, blo, blo + 1))
            alo += 1
            blo += 1
        tail = []
        while ahi > alo and bhi > blo and old[ahi - 1] == new[bhi - 1]:
            ahi -= 1
            bhi -= 1
            tail.append(("equal", ahi, ahi + 1, bhi, bhi + 1))
        if alo >= ahi or blo >= bhi:
            if alo < ahi:
                out.append(("delete", alo, ahi, blo, blo))
            if blo < bhi:
                out.append(("insert", alo, alo, blo, bhi))
            out.extend(tail)
            continue
        old_counts = Counter(old[alo:ahi])
        new_counts = Counter(new[blo:bhi])
        anchor_words = {
            word for word, count in old_counts.items()
            if count == new_counts.get(word, 0) and count <= _ANCHOR_LIMIT
        }
        if not anchor_words:
            matcher = difflib.SequenceMatcher(
                None, old[alo:ahi], new[blo:bhi], autojunk=False)
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                out.append((tag, alo + i1, alo + i2, blo + j1, blo + j2))
            out.extend(tail)
            continue
        seen = {}
        anchors = {}
        for i in range(alo, ahi):
            word = old[i]
            if word in anchor_words:
                order = seen.get(word, 0)
                seen[word] = order + 1
                anchors[(word, order)] = i
        seen = {}
        pairs = []
        for j in range(blo, bhi):
            word = new[j]
            if word in anchor_words:
                order = seen.get(word, 0)
                seen[word] = order + 1
                pairs.append((anchors[(word, order)], j))
        pairs.sort()
        tails = []
        sequence = []
        for a_pos, b_pos in pairs:
            slot = bisect_left(tails, b_pos)
            if slot == len(tails):
                tails.append(b_pos)
            else:
                tails[slot] = b_pos
            sequence.append((slot, a_pos, b_pos))
        lis = []
        want = len(tails) - 1
        for slot, a_pos, b_pos in reversed(sequence):
            if slot == want:
                lis.append((a_pos, b_pos))
                want -= 1
        lis.reverse()
        pa, pb = alo, blo
        for a_pos, b_pos in lis:
            stack.append((pa, a_pos, pb, b_pos))
            out.append(("equal", a_pos, a_pos + 1, b_pos, b_pos + 1))
            pa, pb = a_pos + 1, b_pos + 1
        stack.append((pa, ahi, pb, bhi))
        out.extend(tail)
    out.sort(key=lambda op: (op[1], op[3]))
    return out


def line_diff(before, after):
    """行级 LCS 对齐。

    返回 (改动行数, 对齐行)。改动行数 = 原文被替换或删除的行 + 结果新增的行。
    对齐行元素为 (左行号, 左文本, 左改动, 右行号, 右文本, 右改动)，
    行号从 1 起，占位侧的行号与文本为 None。报告层只排版，不重新比对。
    """
    old = _to_lines(before)
    new = _to_lines(after)
    rows = []
    changed = 0
    for tag, i1, i2, j1, j2 in _anchor_opcodes(old, new):
        if tag == "equal":
            for k in range(i2 - i1):
                rows.append((i1 + k + 1, old[i1 + k], False,
                             j1 + k + 1, new[j1 + k], False))
            continue
        changed += (i2 - i1) + (j2 - j1)
        height = max(i2 - i1, j2 - j1)
        for k in range(height):
            left_at = i1 + k
            right_at = j1 + k
            rows.append((
                left_at + 1 if left_at < i2 else None,
                old[left_at] if left_at < i2 else None,
                left_at < i2,
                right_at + 1 if right_at < j2 else None,
                new[right_at] if right_at < j2 else None,
                right_at < j2,
            ))
    return changed, rows


def count_changed_lines(before, after):
    """原文与结果的行级最长公共序列之外的行数。"""
    changed, _ = line_diff(before, after)
    return changed
