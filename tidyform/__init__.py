"""tidyform：幂等式格式化器。规则见 README 第 2 节。"""

from .engine import FormatError, count_changed_lines, diff_rows, format_text
from .report import write_report

__all__ = [
    "FormatError",
    "count_changed_lines",
    "diff_rows",
    "format_text",
    "write_report",
]
