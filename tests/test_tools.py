#!/usr/bin/env python3
"""
Offline tests for tools/fetch_template.py and tools/check_headers.py: name
handling, what is flagged, the header written, and that the header check
holds back a fetched template until it is adapted. Nothing is fetched.

Run: python3 -m unittest discover -s tests
"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def load(name):
    """Import a script from tools/ as a module."""
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch_template = load("fetch_template")
check_headers = load("check_headers")

PAGE = {"title": "Template:See also", "revid": 1292725734,
        "timestamp": "2026-07-09T05:15:34Z"}


class NameTests(unittest.TestCase):
    """Turning what is typed into a template and file name."""

    def test_prefix_underscores_and_first_letter(self):
        self.assertEqual(fetch_template.template_name("Template:see_also"),
                         "See also")
        self.assertEqual(fetch_template.template_name("  nowrap "), "Nowrap")

    def test_subpages_and_path_characters_are_refused(self):
        for raw in ("Foo/doc", "..", "a\\b", "Template:", "a:b", ""):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    fetch_template.template_name(raw)

    def test_page_urls(self):
        self.assertEqual(fetch_template.page_url("Template:See also"),
                         "https://en.wikipedia.org/wiki/Template:See_also")
        self.assertEqual(
            fetch_template.page_url("Template:See also", action="history"),
            "https://en.wikipedia.org/w/index.php?title=Template:See_also"
            "&action=history")


class TextTests(unittest.TestCase):
    """What is removed, flagged and listed in a template's text."""

    def test_wikipedias_noinclude_part_is_removed(self):
        text = ("<span>{{{1}}}</span><noinclude>\n{{Documentation}}\n"
                "[[Category:X]]</noinclude>\n")
        self.assertEqual(fetch_template.without_noinclude(text),
                         ("<span>{{{1}}}</span>", True))
        self.assertEqual(fetch_template.without_noinclude("plain"),
                         ("plain", False))

    def test_lua_templatestyles_and_unsupported_functions_are_flagged(self):
        text = ('{{#invoke:Hatnote|x}}<templatestyles src="a.css" />'
                "{{#if:a|b}}{{#tag:ref|x}}{{formatnum:5}}{{lc:A}}"
                "{{PAGENAME}}{{BASEPAGENAME}}{{CURRENTYEAR}}")
        self.assertEqual(fetch_template.needs(text), [
            "Lua ({{#invoke:}})", "TemplateStyles",
            "unsupported #tag, BASEPAGENAME, formatnum"])

    def test_plain_template_needs_nothing(self):
        self.assertEqual(fetch_template.needs(
            '<span class="nowrap">{{{1}}}</span>'), [])

    def test_called_templates_skip_magic_words_and_parameters(self):
        text = ("{{Hatnote|x}} {{ ambox }} {{{1|{{Main}}}}} {{PAGENAME}} "
                "{{!}} {{#if:a|{{Nowrap|b}}}} {{lc:X}} {{NPOV}}")
        self.assertEqual(fetch_template.called_templates(text),
                         ["Ambox", "Hatnote", "Main", "NPOV", "Nowrap"])

    def test_time_is_us_format_utc(self):
        self.assertEqual(fetch_template.human_time("2026-07-09T05:15:34Z"),
                         "07/09/2026 5:15 AM UTC")
        self.assertEqual(fetch_template.human_time("2015-11-28T22:13:53Z"),
                         "11/28/2015 10:13 PM UTC")


class HeaderTests(unittest.TestCase):
    """The header written, and the header check's verdict on it."""

    def write(self, directory, header, body="{{{1}}}"):
        path = Path(directory) / "See also.wiki"
        path.write_text(header + body + "\n", encoding="utf-8")
        return path

    def test_fetched_header_is_held_back_until_adapted(self):
        header = fetch_template.header(PAGE, ["Lua ({{#invoke:}})"], True)
        self.assertIn("&oldid=1292725734 (07/09/2026 5:15 AM UTC)", header)
        self.assertNotIn("{{Documentation}}", header)
        with tempfile.TemporaryDirectory() as directory:
            found = check_headers.problems(self.write(directory, header))
        self.assertEqual(found, [
            "the list of changes still says TODO",
            "still needs adapting (see its Needs adapting line)"])

    def test_adapted_header_passes(self):
        header = fetch_template.header(PAGE, [], True).replace(
            "Changes: TODO.", "Changes: rewritten without Lua.")
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                check_headers.problems(self.write(directory, header)), [])


class CommandTests(unittest.TestCase):
    """The command line, with the API replaced by a stub."""

    def run_main(self, *args):
        with mock.patch.object(sys, "argv", ["fetch_template.py", *args]):
            return fetch_template.main()

    def test_existing_file_is_not_replaced_without_force(self):
        page = dict(PAGE, text="<span>{{{1}}}</span>")
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(fetch_template, "fetch",
                                  return_value={"See also": page}), \
                mock.patch("builtins.print"):
            target = Path(directory) / "See also.wiki"
            self.assertEqual(self.run_main("-d", directory, "See also"), 0)
            target.write_text("edited", encoding="utf-8")
            self.assertEqual(self.run_main("-d", directory, "See also"), 1)
            self.assertEqual(target.read_text(encoding="utf-8"), "edited")
            self.assertEqual(
                self.run_main("-d", directory, "--force", "See also"), 0)
            self.assertIn("<span>{{{1}}}</span>",
                          target.read_text(encoding="utf-8"))

    def test_missing_template_fails_and_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(fetch_template, "fetch",
                                  return_value={"Nope": None}), \
                mock.patch("builtins.print"):
            self.assertEqual(self.run_main("-d", directory, "-n", "Nope"), 1)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
