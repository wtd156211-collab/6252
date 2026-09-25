"""命令行：python -m tidyform [--write] [--report 报告.html] 输入文件..."""

from __future__ import annotations

import argparse
import sys

from .engine import FormatError, format_text
from .report import write_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tidyform",
        description="幂等式格式化器：规则写死、稳定优先。",
    )
    parser.add_argument("files", nargs="+", metavar="输入文件")
    parser.add_argument("--write", action="store_true", help="就地改写输入文件")
    parser.add_argument("--report", metavar="报告.html", help="输出左右对照的 HTML 报告")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.write and not args.report and len(args.files) != 1:
        print("错误：不带 --write/--report 时只允许一个输入文件", file=sys.stderr)
        return 2

    results: list[tuple[str, str, str]] = []
    failed = False
    for path in args.files:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                before = fh.read()
        except OSError as exc:
            print(f"错误：读不到 {path}：{exc}", file=sys.stderr)
            failed = True
            continue
        try:
            after = format_text(before)
        except FormatError as exc:
            print(f"错误：{path} 不符合输入约定：{exc}", file=sys.stderr)
            failed = True
            continue
        results.append((path, before, after))
    if failed:
        return 1

    if args.report:
        try:
            write_report(args.report, results)
        except OSError as exc:
            print(f"错误：写报告失败：{exc}", file=sys.stderr)
            return 1
    if args.write:
        for path, before, after in results:
            if after != before:
                try:
                    with open(path, "w", encoding="utf-8", newline="\n") as fh:
                        fh.write(after)
                except OSError as exc:
                    print(f"错误：写不回 {path}：{exc}", file=sys.stderr)
                    return 1
    if not args.write and not args.report:
        sys.stdout.write(results[0][2])
    return 0


if __name__ == "__main__":
    sys.exit(main())
