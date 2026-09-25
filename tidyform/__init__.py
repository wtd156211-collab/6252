"""tidyform：规则写死、幂等、最小改动的 .task 格式化器。"""

from .core import FormatError, count_changed_lines, format_text, line_diff
from .report import write_report

__all__ = [
    "FormatError",
    "count_changed_lines",
    "format_text",
    "line_diff",
    "write_report",
]
