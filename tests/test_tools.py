#!/usr/bin/env python3
"""
Offline tests for tools/fetch_template.py and tools/check_headers.py: name
handling, what is flagged, the header written, and that the header check
holds back a fetched template until it is adapted. Nothing is fetched.

Run: python3 -m unittest discover -s tests
"""

import importlib.util
import json
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
ENWIKI = fetch_template.SITES["enwiki"]


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
        self.assertEqual(
            fetch_template.page_url(ENWIKI, "Template:See also"),
            "https://en.wikipedia.org/wiki/Template:See_also")
        self.assertEqual(
            fetch_template.page_url(fetch_template.SITES["mediawiki"],
                                    "Template:Note"),
            "https://www.mediawiki.org/wiki/Template:Note")
        self.assertEqual(
            fetch_template.page_url(ENWIKI, "Template:See also",
                                    action="history"),
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

    def test_only_the_onlyinclude_part_is_kept(self):
        text = ("<languages/>\nDocs {{Documentation}}\n<onlyinclude>{{#if:"
                "{{{1|}}}|<b>{{{1}}}</b>}}</onlyinclude>\nMore docs "
                "<onlyinclude>!</onlyinclude>[[Category:X]]")
        self.assertEqual(fetch_template.without_noinclude(text),
                         ("{{#if:{{{1|}}}|<b>{{{1}}}</b>}}!", True))

    def test_lua_templatestyles_and_unsupported_functions_are_flagged(self):
        text = ('{{#invoke:Hatnote|x}}<templatestyles src="a.css" />'
                "{{#if:a|b}}{{#tag:ref|x}}{{formatnum:5}}{{lc:A}}"
                "{{PAGENAME}}{{BASEPAGENAME}}{{CURRENTYEAR}}")
        self.assertEqual(fetch_template.needs(text), [
            "Lua ({{#invoke:}})", "TemplateStyles",
            "unsupported #tag, BASEPAGENAME, formatnum"])

    def test_translate_markup_is_flagged(self):
        self.assertEqual(
            fetch_template.needs(
                "'''<translate><!--T:2--> Note:</translate>'''"),
            ["Translate markup (<translate>, <languages/>)"])

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
        header = fetch_template.header(ENWIKI, PAGE, ["Lua ({{#invoke:}})"],
                                       True)
        self.assertIn("&oldid=1292725734 (07/09/2026 5:15 AM UTC)", header)
        self.assertNotIn("{{Documentation}}", header)
        with tempfile.TemporaryDirectory() as directory:
            found = check_headers.problems(self.write(directory, header))
        self.assertEqual(found, [
            "the list of changes still says TODO",
            "still needs adapting (see its Needs adapting line)"])

    def test_adapted_header_passes(self):
        header = fetch_template.header(ENWIKI, PAGE, [], True).replace(
            "Changes: TODO.", "Changes: rewritten without Lua.")
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                check_headers.problems(self.write(directory, header)), [])


class HostTests(unittest.TestCase):
    """Which wikis the header check accepts as a source."""

    def problems_for(self, header_text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Note.wiki"
            path.write_text(header_text + "x\n", encoding="utf-8")
            return check_headers.problems(path)

    def header_for(self, site, page=None):
        page = page or dict(PAGE, title="Template:Note")
        return fetch_template.header(site, page, [], False).replace(
            "Changes: TODO", "Changes: none")

    def test_every_fetchable_wiki_is_accepted(self):
        for site_id, site in fetch_template.SITES.items():
            with self.subTest(site=site_id):
                self.assertEqual(self.problems_for(self.header_for(site)), [])

    def test_another_wiki_and_mixed_wikis_are_refused(self):
        other = {"base": "https://example.fandom.com"}
        self.assertEqual(self.problems_for(self.header_for(other)),
                         ["header has no source URL",
                          "header has no history URL"])
        mixed = self.header_for(ENWIKI).replace(
            "History: https://en.wikipedia.org",
            "History: https://meta.wikimedia.org")
        self.assertEqual(self.problems_for(mixed), [
            "the source and its history are on different wikis"])


class LicenceTests(unittest.TestCase):
    """Only a wiki that reports a CC BY-SA licence is fetched from."""

    def licence(self, text, url=""):
        reply = {"query": {"rightsinfo": {"text": text, "url": url}}}
        with mock.patch.object(fetch_template, "api_get", return_value=reply):
            return fetch_template.check_licence(ENWIKI)

    def test_a_wiki_that_is_not_cc_by_sa_is_refused(self):
        for text in ("All rights reserved", "CC BY-NC 4.0", "CC BY-NC-SA 3.0",
                     "Creative Commons Attribution-NonCommercial-ShareAlike",
                     "CC BY-ND 4.0", ""):
            with self.subTest(text=text):
                with self.assertRaises(fetch_template.FetchError):
                    self.licence(text)

    def test_cc_by_sa_is_accepted(self):
        self.assertIn("4.0", self.licence(
            "Creative Commons Attribution-Share Alike 4.0",
            "https://creativecommons.org/licenses/by-sa/4.0/"))
        self.assertEqual(self.licence("CC-BY-SA"), "CC-BY-SA")


class CommandTests(unittest.TestCase):
    """The command line, with the API replaced by stubs."""

    INFO = {"pageid": 1721254, "title": "Template:See also",
            "revid": 1292725734, "timestamp": ""}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.record = self.dir / "data" / "templates.json"
        self.fetched = []

        def fake_fetch(site, names, content=True):
            if content:
                self.fetched.extend(names)
            return {name: (dict(self.INFO, text="<span>{{{1}}}</span>",
                                timestamp="2025-05-30T12:00:00Z")
                           if name == "See also" else None)
                    for name in names}
        patcher = mock.patch.object(fetch_template, "fetch", fake_fetch)
        patcher.start()
        self.addCleanup(patcher.stop)
        licence = mock.patch.object(fetch_template, "check_licence",
                                    return_value="CC BY-SA 4.0")
        licence.start()
        self.addCleanup(licence.stop)
        printer = mock.patch("builtins.print")
        self.printed = printer.start()
        self.addCleanup(printer.stop)

    def run_main(self, *args):
        argv = ["fetch_template.py", "-d", str(self.dir),
                "-R", str(self.record), *args]
        with mock.patch.object(sys, "argv", argv):
            return fetch_template.main()

    def saved(self):
        return json.loads(self.record.read_text(encoding="utf-8"))

    def test_fetch_records_the_page_id_and_skips_a_known_revision(self):
        self.assertEqual(self.run_main("See also"), 0)
        self.assertEqual(self.saved(), {"enwiki:1721254": {
            "name": "See also", "reason": "", "revid": 1292725734,
            "status": "fetched", "title": "Template:See also"}})
        (self.dir / "See also.wiki").unlink()
        self.assertEqual(self.run_main("See also"), 0)
        self.assertEqual(self.fetched, ["See also"])
        self.assertFalse((self.dir / "See also.wiki").exists())

    def test_existing_file_is_not_replaced_without_force(self):
        target = self.dir / "See also.wiki"
        target.write_text("edited", encoding="utf-8")
        self.assertEqual(self.run_main("See also"), 1)
        self.assertEqual(target.read_text(encoding="utf-8"), "edited")
        self.assertEqual(self.run_main("--force", "See also"), 0)
        self.assertIn("<span>{{{1}}}</span>",
                      target.read_text(encoding="utf-8"))

    def test_missing_template_fails_and_dry_run_writes_nothing(self):
        self.assertEqual(self.run_main("-n", "Nope", "See also"), 1)
        self.assertFalse(self.record.exists())
        self.assertFalse((self.dir / "See also.wiki").exists())

    def test_mark_unadaptable_records_without_downloading(self):
        self.assertEqual(self.run_main("-m", "-r", "Lua, too large",
                                       "See also"), 0)
        entry = self.saved()["enwiki:1721254"]
        self.assertEqual(entry["status"], "not adaptable")
        self.assertEqual(entry["reason"], "Lua, too large")
        self.assertEqual(self.fetched, [])
        self.assertFalse((self.dir / "See also.wiki").exists())
        # A rejected template is not fetched again at the same revision
        self.assertEqual(self.run_main("See also"), 0)
        self.assertEqual(self.fetched, [])

    def test_mark_unadaptable_needs_a_reason(self):
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit) as end:
            self.run_main("-m", "See also")
        self.assertEqual(end.exception.code, 2)

    def test_check_updates_reports_edits_renames_and_deletions(self):
        record = {
            "enwiki:1": {"name": "A", "title": "Template:A", "revid": 10,
                         "status": "not adaptable", "reason": "Lua"},
            "enwiki:2": {"name": "B", "title": "Template:B", "revid": 20,
                         "status": "fetched", "reason": ""},
            "enwiki:3": {"name": "C", "title": "Template:C", "revid": 30,
                         "status": "fetched", "reason": ""},
            "commons:4": {"name": "D", "title": "Template:D", "revid": 40,
                          "status": "fetched", "reason": ""},
            "commons:1": {"name": "E", "title": "Template:E", "revid": 50,
                          "status": "fetched", "reason": ""},
        }
        fetch_template.save_record(self.record, record)
        latest = {
            "English Wikipedia": {
                1: {"pageid": 1, "title": "Template:A", "revid": 11},
                2: {"pageid": 2, "title": "Template:B2", "revid": 20},
                3: None},
            "Wikimedia Commons": {
                4: {"pageid": 4, "title": "Template:D", "revid": 40},
                1: {"pageid": 1, "title": "Template:E", "revid": 51}},
        }

        def fake_query(site, key, values, content):
            self.assertEqual((key, content), ("pageids", False))
            return {value: latest[site["label"]][value] for value in values}
        with mock.patch.object(fetch_template, "query_pages", fake_query):
            self.assertEqual(self.run_main("--check-updates"), 0)
        lines = [call.args[0] for call in self.printed.call_args_list]
        self.assertEqual(lines, [
            "CHANGED  A (not adaptable): edited: revision 10 -> 11",
            "CHANGED  B (fetched): renamed to Template:B2",
            "DELETED  C (fetched): page 3 no longer exists",
            "CHANGED  E (fetched, commons): edited: revision 50 -> 51",
            "5 recorded, 4 changed since",
        ])
        self.assertEqual(self.saved(), record)

    def test_old_keys_without_a_wiki_are_read_as_english_wikipedia(self):
        self.record.parent.mkdir(parents=True)
        self.record.write_text('{"1721254": {"name": "See also"}}',
                               encoding="utf-8")
        self.assertEqual(fetch_template.load_record(self.record),
                         {"enwiki:1721254": {"name": "See also"}})

    def test_record_is_sorted_by_page_id(self):
        fetch_template.save_record(self.record, {
            "enwiki:100": {"name": "X"}, "enwiki:20": {"name": "Y"},
            "enwiki:3": {"name": "Z"}, "commons:5": {"name": "W"}})
        keys = list(json.loads(self.record.read_text(encoding="utf-8")))
        self.assertEqual(keys, ["commons:5", "enwiki:3", "enwiki:20",
                                "enwiki:100"])


if __name__ == "__main__":
    unittest.main()
