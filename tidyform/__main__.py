"""命令行入口：python -m tidyform [--write] [--report 报告.html] 输入文件..."""

from __future__ import annotations

import argparse
import sys

from .core import FormatError, format_text
from .report import write_report


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="tidyform",
        description="幂等格式化器：不带选项时把唯一输入的格式化结果写到 stdout；"
                    "--write 就地改写；--report 额外产出 HTML 对照报告。",
    )
    parser.add_argument("inputs", nargs="+", metavar="输入文件",
                        help="待格式化的文件；stdout 模式下只允许一个")
    parser.add_argument("--write", action="store_true",
                        help="就地改写输入文件（内容无变化时不触碰）")
    parser.add_argument("--report", metavar="报告.html",
                        help="把左右对照报告写到指定 HTML 文件，可与 --write 并用")
    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    to_stdout = not args.write and not args.report
    if to_stdout and len(args.inputs) != 1:
        parser.error("stdout 模式只允许一个输入文件；多文件请配合 --write 或 --report")

    files = []
    for path in args.inputs:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                before = handle.read()
        except (OSError, UnicodeDecodeError) as exc:
            print("tidyform: %s: 读取失败: %s" % (path, exc), file=sys.stderr)
            return 1
        try:
            after = format_text(before)
        except FormatError as exc:
            print("tidyform: %s: %s" % (path, exc), file=sys.stderr)
            return 1
        files.append((path, before, after))

    if args.write:
        for path, before, after in files:
            if after == before:
                continue
            try:
                with open(path, "w", encoding="utf-8", newline="") as handle:
                    handle.write(after)
            except OSError as exc:
                print("tidyform: %s: 写入失败: %s" % (path, exc), file=sys.stderr)
                return 1
    if args.report:
        try:
            write_report(args.report, [(name, before, after) for name, before, after in files])
        except OSError as exc:
            print("tidyform: %s: 报告写入失败: %s" % (args.report, exc), file=sys.stderr)
            return 1
    if to_stdout:
        sys.stdout.write(files[0][2])
    return 0


if __name__ == "__main__":
    sys.exit(main())
