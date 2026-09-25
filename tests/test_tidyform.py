import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tidyform import FormatError, count_changed_lines, format_text, write_report

SAMPLES = ROOT / "samples"


def read_bounds():
    bounds = {}
    for line in (SAMPLES / "expected-changes.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, bound = line.split()
            bounds[name] = int(bound)
    return bounds


class SampleTests(unittest.TestCase):
    def test_samples_match_expected_byte_for_byte(self):
        for inp in sorted((SAMPLES / "input").glob("*.task")):
            with self.subTest(file=inp.name):
                expected = (SAMPLES / "expected" / inp.name).read_bytes()
                got = format_text(inp.read_text(encoding="utf-8")).encode("utf-8")
                self.assertEqual(got, expected)

    def test_expected_files_are_idempotent(self):
        for exp in sorted((SAMPLES / "expected").glob("*.task")):
            with self.subTest(file=exp.name):
                text = exp.read_text(encoding="utf-8")
                self.assertEqual(format_text(text), text)

    def test_changed_lines_within_bounds(self):
        for name, bound in read_bounds().items():
            with self.subTest(file=name):
                before = (SAMPLES / "input" / name).read_text(encoding="utf-8")
                after = (SAMPLES / "expected" / name).read_text(encoding="utf-8")
                self.assertLessEqual(count_changed_lines(before, after), bound)


class RuleTests(unittest.TestCase):
    def test_empty_and_whitespace_only_input(self):
        self.assertEqual(format_text(""), "")
        self.assertEqual(format_text("   \n\t\n \t \n"), "")

    def test_exactly_one_trailing_newline(self):
        self.assertEqual(format_text("a = 1"), "a = 1\n")
        self.assertEqual(format_text("a = 1\n\n\n"), "a = 1\n")

    def test_crlf_and_cr_normalized(self):
        self.assertEqual(format_text("a = 1\r\nb = 2\rc = 3\n"), "a = 1\nb = 2\nc = 3\n")

    def test_trailing_whitespace_removed(self):
        self.assertEqual(format_text("a = 1  \t\n# c  \n"), "a = 1\n# c\n")

    def test_inner_spacing_and_tabs(self):
        self.assertEqual(
            format_text("\tfetch(  source = \"s3://x\" ,retry = 3 )"),
            'fetch(source = "s3://x", retry = 3)\n',
        )

    def test_blank_lines_collapse_and_do_not_cross_comments(self):
        got = format_text("a = 1\n\n\n\n# c\n\n\nb = 2\n")
        self.assertEqual(got, "a = 1\n\n# c\n\nb = 2\n")

    def test_standalone_comment_indent_reset(self):
        self.assertEqual(format_text("      # note\n"), "# note\n")

    def test_comment_keeps_inner_spacing(self):
        self.assertEqual(format_text("a = 1   #  keep  me\n"), "a = 1  #  keep  me\n")

    def test_string_protects_structural_chars(self):
        self.assertEqual(
            format_text('notify(channel = "#a,(=", note = "x \\"# y")'),
            'notify(channel = "#a,(=", note = "x \\"# y")\n',
        )

    def test_trailing_comma_empty_arg_dropped(self):
        self.assertEqual(format_text("f(a, b,)\n"), "f(a, b)\n")

    def test_split_shape(self):
        got = format_text("f(" + "a = 1, " * 30 + "b = 2)\n")
        lines = got.splitlines()
        self.assertEqual(lines[0], "f(")
        self.assertTrue(all(line.startswith("    ") and line.endswith(",") for line in lines[1:-1]))
        self.assertEqual(lines[-1], ")")

    def test_split_comment_lands_on_last_line(self):
        got = format_text("f(" + "a = 1, " * 30 + "b = 2)  # tail\n")
        self.assertTrue(got.splitlines()[-1].endswith(")  # tail"))

    def test_single_arg_group_not_split(self):
        line = "note(message = \"" + "长" * 120 + "\")"
        self.assertEqual(format_text(line + "\n"), line + "\n")

    def test_nested_single_arg_group_splits_inner(self):
        inner = "fetch(" + ", ".join(f"a{i} = {i}" for i in range(20)) + ")"
        got = format_text(f"wrap({inner})\n")
        self.assertTrue(got.startswith("wrap(fetch(\n"))
        self.assertTrue(got.endswith("))\n"))

    def test_idempotent_on_own_output(self):
        src = (SAMPLES / "input" / "large.task").read_text(encoding="utf-8")
        once = format_text(src)
        self.assertEqual(format_text(once), once)


class CountTests(unittest.TestCase):
    def test_count_changed_lines(self):
        self.assertEqual(count_changed_lines("", ""), 0)
        self.assertEqual(count_changed_lines("a\n", "a\n"), 0)
        self.assertEqual(count_changed_lines("a\nb\n", "a\nc\n"), 2)
        self.assertEqual(count_changed_lines("a\nb\nc\n", "a\nc\n"), 1)
        self.assertEqual(count_changed_lines("a\n", "a\nb\nc\n"), 2)
        self.assertEqual(count_changed_lines("a\nb\n", "x\ny\nz\n"), 5)


class ErrorTests(unittest.TestCase):
    def test_unbalanced_parens(self):
        with self.assertRaises(FormatError):
            format_text("f(a\n")
        with self.assertRaises(FormatError):
            format_text("f(a))\n")

    def test_unterminated_string(self):
        with self.assertRaises(FormatError):
            format_text('f(a = "x\n')

    def test_blank_line_inside_statement(self):
        with self.assertRaises(FormatError):
            format_text("f(a,\n\nb)\n")

    def test_two_trailing_comments(self):
        with self.assertRaises(FormatError):
            format_text("f(a,  # one\nb)  # two\n")


class CliTests(unittest.TestCase):
    def run_cli(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, "-m", "tidyform", *args],
            cwd=cwd or ROOT, capture_output=True, text=True,
        )

    def test_stdout_single_file(self):
        proc = self.run_cli("samples/input/messy.task")
        self.assertEqual(proc.returncode, 0)
        expected = (SAMPLES / "expected" / "messy.task").read_text(encoding="utf-8")
        self.assertEqual(proc.stdout, expected)

    def test_stdout_rejects_multiple_files(self):
        proc = self.run_cli("samples/input/messy.task", "samples/input/tidy.task")
        self.assertNotEqual(proc.returncode, 0)

    def test_write_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "x.task"
            target.write_text("f(  a = 1 ,b = 2 )  \n", encoding="utf-8")
            report = pathlib.Path(tmp) / "r.html"
            proc = self.run_cli("--write", "--report", str(report), str(target))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(target.read_text(encoding="utf-8"), "f(a = 1, b = 2)\n")
            html = report.read_text(encoding="utf-8")
            self.assertIn("<td>2</td>", html)  # 红 1 行 + 绿 1 行
            self.assertIn("通过", html)
            self.assertNotIn("<script", html)

    def test_missing_file_fails(self):
        proc = self.run_cli("no-such-file.task")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no-such-file.task", proc.stderr)

    def test_invalid_input_fails_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "bad.task"
            target.write_text("f(a\n", encoding="utf-8")
            proc = self.run_cli("--write", str(target))
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "f(a\n")


class ReportTests(unittest.TestCase):
    def test_report_marks_come_from_engine(self):
        before = "a = 1\nf(  x = 1 )\n"
        after = format_text(before)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "r.html"
            write_report(str(path), [("demo.task", before, after)])
            html = path.read_text(encoding="utf-8")
        self.assertIn("<td>demo.task</td><td>2</td>", html)
        self.assertIn("通过（0 行改动）", html)
        self.assertIn("class=c", html)  # 改动行有标记
        self.assertNotIn("http", html)


if __name__ == "__main__":
    unittest.main()
