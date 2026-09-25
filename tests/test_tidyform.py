import pathlib
import subprocess
import sys
import tempfile
import unittest

import tidyform
from tidyform import FormatError, count_changed_lines, format_text, write_report

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"


def _sample_names():
    return sorted(p.name for p in (SAMPLES / "input").iterdir())


def _bounds():
    bounds = {}
    for line in (SAMPLES / "expected-changes.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, limit = line.split()
        bounds[name] = int(limit)
    return bounds


class SampleTests(unittest.TestCase):
    def test_expected_byte_exact(self):
        for name in _sample_names():
            with self.subTest(name=name):
                before = (SAMPLES / "input" / name).read_text(encoding="utf-8")
                expected = (SAMPLES / "expected" / name).read_bytes()
                self.assertEqual(format_text(before).encode("utf-8"), expected)

    def test_idempotent_on_expected(self):
        for name in _sample_names():
            with self.subTest(name=name):
                expected = (SAMPLES / "expected" / name).read_text(encoding="utf-8")
                self.assertEqual(format_text(expected), expected)

    def test_idempotent_on_input(self):
        for name in _sample_names():
            with self.subTest(name=name):
                before = (SAMPLES / "input" / name).read_text(encoding="utf-8")
                once = format_text(before)
                self.assertEqual(format_text(once), once)

    def test_changed_lines_within_bounds(self):
        bounds = _bounds()
        for name in _sample_names():
            with self.subTest(name=name):
                before = (SAMPLES / "input" / name).read_text(encoding="utf-8")
                after = (SAMPLES / "expected" / name).read_text(encoding="utf-8")
                self.assertLessEqual(count_changed_lines(before, after), bounds[name])

    def test_tidy_untouched(self):
        before = (SAMPLES / "input" / "tidy.task").read_text(encoding="utf-8")
        self.assertEqual(format_text(before), before)
        self.assertEqual(count_changed_lines(before, format_text(before)), 0)


class RuleTests(unittest.TestCase):
    def test_empty_and_blank_only_inputs(self):
        self.assertEqual(format_text(""), "")
        self.assertEqual(format_text("\n\n  \n\t\n"), "")
        self.assertEqual(count_changed_lines("", ""), 0)

    def test_trailing_whitespace_and_tabs(self):
        self.assertEqual(format_text("fetch(x = 1)  \t\n"), "fetch(x = 1)\n")

    def test_inner_spacing(self):
        self.assertEqual(
            format_text("fetch(  source = \"s3://a\" ,retry = 3 )\n"),
            'fetch(source = "s3://a", retry = 3)\n',
        )

    def test_indent_recomputed(self):
        self.assertEqual(format_text("\tfetch(x = 1)\n"), "fetch(x = 1)\n")
        self.assertEqual(format_text("    fetch(x = 1)\n"), "fetch(x = 1)\n")

    def test_standalone_comment_dedented_and_kept(self):
        self.assertEqual(
            format_text("fetch(x = 1)\n   # 注释  \nnotify(y = 2)\n"),
            "fetch(x = 1)\n# 注释\nnotify(y = 2)\n",
        )

    def test_comment_not_detached_from_statement(self):
        long_args = ", ".join("arg%02d = %d" % (i, i) for i in range(10))
        text = "f(%s)  # 跟着语句走\n" % long_args
        out = format_text(text)
        self.assertTrue(out.endswith(")  # 跟着语句走\n"))
        self.assertEqual(format_text(out), out)

    def test_comment_hash_inside_string(self):
        self.assertEqual(
            format_text('notify(channel = "#ops")  # 真注释\n'),
            'notify(channel = "#ops")  # 真注释\n',
        )

    def test_blank_lines_collapsed_and_trimmed(self):
        self.assertEqual(
            format_text("\n\nfetch(x = 1)\n\n\n\nnotify(y = 2)\n\n"),
            "fetch(x = 1)\n\nnotify(y = 2)\n",
        )

    def test_blank_lines_not_merged_across_comment(self):
        self.assertEqual(
            format_text("fetch(x = 1)\n\n\n# 注释\n\n\nnotify(y = 2)\n"),
            "fetch(x = 1)\n\n# 注释\n\nnotify(y = 2)\n",
        )

    def test_missing_final_newline_added(self):
        self.assertEqual(format_text("fetch(x = 1)"), "fetch(x = 1)\n")

    def test_crlf_normalized(self):
        self.assertEqual(format_text("fetch(x = 1)\r\nnotify(y = 2)\r\n"),
                         "fetch(x = 1)\nnotify(y = 2)\n")

    def test_multiline_statement_merged(self):
        self.assertEqual(
            format_text('aggregate(keys = "day,region",\n    window = "1d")\n'),
            'aggregate(keys = "day,region", window = "1d")\n',
        )

    def test_overwide_single_arg_not_split(self):
        text = 'note(message = "%s")\n' % ("长" * 120)
        self.assertEqual(format_text(text), text)

    def test_split_shape(self):
        text = "f(%s)\n" % ", ".join("arg%02d = %d" % (i, i) for i in range(12))
        out = format_text(text)
        lines = out.splitlines()
        self.assertEqual(lines[0], "f(")
        self.assertEqual(lines[-1], ")")
        for line in lines[1:-1]:
            self.assertTrue(line.startswith("    "))
            self.assertTrue(line.endswith(","))
        self.assertEqual(format_text(out), out)

    def test_nested_single_arg_group_split(self):
        inner = ", ".join("arg%02d = %d" % (i, i) for i in range(12))
        out = format_text("wrap(fetch(%s))\n" % inner)
        lines = out.splitlines()
        self.assertEqual(lines[0], "wrap(fetch(")
        self.assertEqual(lines[-1], "))")
        self.assertEqual(format_text(out), out)

    def test_trailing_comma_not_written(self):
        self.assertEqual(format_text("fetch(x = 1,)\n"), "fetch(x = 1)\n")

    def test_string_with_escaped_quote(self):
        text = 'note(message = "a\\"b, (x)")\n'
        self.assertEqual(format_text(text), text)

    def test_width_counts_codepoints(self):
        text = 'note(message = "%s")\n' % ("界" * 82)
        self.assertEqual(len(text.rstrip("\n")), 100)
        self.assertEqual(format_text(text), text)


class ErrorTests(unittest.TestCase):
    def test_unbalanced_paren(self):
        with self.assertRaises(FormatError):
            format_text("fetch(x = 1\n")
        with self.assertRaises(FormatError):
            format_text("fetch(x = 1))\n")

    def test_unterminated_string(self):
        with self.assertRaises(FormatError):
            format_text('note(message = "abc\n')

    def test_blank_line_inside_statement(self):
        with self.assertRaises(FormatError):
            format_text("fetch(\n\n)\n")

    def test_standalone_comment_inside_statement(self):
        with self.assertRaises(FormatError):
            format_text("fetch(\n# 注释\n)\n")

    def test_multiple_trailing_comments(self):
        with self.assertRaises(FormatError):
            format_text("fetch(\n    x = 1,  # 一\n)  # 二\n")


class DiffTests(unittest.TestCase):
    def test_count_changed_lines(self):
        self.assertEqual(count_changed_lines("a\nb\nc\n", "a\nb\nc\n"), 0)
        self.assertEqual(count_changed_lines("a\nb\nc\n", "a\nx\nc\n"), 2)
        self.assertEqual(count_changed_lines("a\nc\n", "a\nb\nc\n"), 1)
        self.assertEqual(count_changed_lines("a\nb\nc\n", "a\nc\n"), 1)
        self.assertEqual(count_changed_lines("a\nb\n", ""), 2)
        self.assertEqual(count_changed_lines("", "a\n"), 1)

    def test_line_diff_rows_carry_engine_line_numbers(self):
        changed, rows = tidyform.line_diff("a\nb\nc\n", "a\nx\nc\n")
        self.assertEqual(changed, 2)
        marked = [row for row in rows if row[2] or row[5]]
        self.assertEqual(len(marked), 1)
        _, left_text, left_changed, _, right_text, right_changed = marked[0]
        self.assertEqual((left_text, left_changed), ("b", True))
        self.assertEqual((right_text, right_changed), ("x", True))


class ReportTests(unittest.TestCase):
    def test_report_contains_summary_and_marks(self):
        before = "fetch(  x = 1 )\n"
        after = format_text(before)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "r.html"
            write_report(str(path), [("demo.task", before, after)])
            html_text = path.read_text(encoding="utf-8")
        self.assertIn("demo.task", html_text)
        self.assertIn("通过", html_text)
        self.assertIn("改动行数", html_text)
        self.assertIn("xl", html_text)  # 原文改动行标记
        self.assertIn("xr", html_text)  # 结果改动行标记
        self.assertNotIn("<script", html_text)
        self.assertNotIn("http://", html_text)
        self.assertNotIn("https://", html_text)

    def test_report_html_escapes_content(self):
        before = "note(message = \"<tag>\")\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "r.html"
            write_report(str(path), [("esc.task", before, before)])
            html_text = path.read_text(encoding="utf-8")
        self.assertIn("&lt;tag&gt;", html_text)


class CliTests(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "tidyform", *args],
            cwd=ROOT, capture_output=True, text=True,
        )

    def test_stdout_single_input(self):
        result = self._run("samples/input/messy.task")
        self.assertEqual(result.returncode, 0)
        expected = (SAMPLES / "expected" / "messy.task").read_text(encoding="utf-8")
        self.assertEqual(result.stdout, expected)

    def test_stdout_rejects_multiple_inputs(self):
        result = self._run("samples/input/messy.task", "samples/input/tidy.task")
        self.assertNotEqual(result.returncode, 0)

    def test_write_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "a.task"
            target.write_text("fetch(  x = 1 )\n", encoding="utf-8")
            result = self._run("--write", str(target))
            self.assertEqual(result.returncode, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "fetch(x = 1)\n")

    def test_report_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = pathlib.Path(tmp) / "r.html"
            result = self._run("--report", str(report), "samples/input/messy.task")
            self.assertEqual(result.returncode, 0)
            self.assertIn("messy.task", report.read_text(encoding="utf-8"))

    def test_missing_file_fails(self):
        result = self._run("samples/input/nope.task")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nope.task", result.stderr)

    def test_invalid_input_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "bad.task"
            target.write_text("fetch(\n", encoding="utf-8")
            result = self._run("--write", str(target))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "fetch(\n")


if __name__ == "__main__":
    unittest.main()
