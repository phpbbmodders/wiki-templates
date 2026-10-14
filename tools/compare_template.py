#!/usr/bin/env python3
"""
Check an adapted template against the original: render its examples on a
test board and on the wiki it came from, and compare what a reader sees.

A template's examples are the "Example:" lines in its header, one call each:

    Example: {{Main|History of phpBB}}

They also show as documentation on the template's own page on a board.

For each example:

* the source wiki renders the call with the original template, through its
  API (action=parse); that is the template's current version there, which
  may be newer than the one copied (see fetch_template.py --check-updates);
* a phpBB test board with the phpBB Modders wiki extension renders it with
  this repository's templates, through tools/render_on_board.php, which
  loads the board with seed-forum's bin/seed-bootstrap.php and leaves the
  board unchanged;
* the visible text of both is compared, with runs of white space made one.

Templates copied from Fandom have no automatic reference, since Fandom's
terms forbid automated access; their examples are rendered on the board only.

Input: template names, or --all. Output: one line per example (MATCH, DIFFER
or BOARD ONLY) with a word diff for those that differ. Exit status: 0 when
every example matches, 1 when any differs, a template has no example, or a
render fails, 2 for bad arguments.
"""

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_template  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RENDERER = Path(__file__).resolve().parent / "render_on_board.php"
EXAMPLE = re.compile(r"^Example: (.+)$", re.M)
SOURCE = re.compile(r"^Source: (https://[^/\s]+)", re.M)
RENDER_TIMEOUT_SECONDS = 300
# Between two parse requests to the source wiki, to stay polite
PARSE_PAUSE_SECONDS = 0.5


class TextOnly(HTMLParser):
    """Collects the text a reader sees, leaving out styles and scripts."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self.hidden += 1
        elif tag in ("br", "p", "div", "li", "tr", "td", "th"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("style", "script") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def visible_text(html: str) -> str:
    """The text of some HTML as a reader sees it, on one line."""
    parser = TextOnly()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts).replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def word_diff(old: str, new: str) -> str:
    """The words that differ, as [-removed-] and {+added+}."""
    out = []
    old_words, new_words = old.split(), new.split()
    matcher = difflib.SequenceMatcher(a=old_words, b=new_words)
    for op, a1, a2, b1, b2 in matcher.get_opcodes():
        if op == "equal":
            out.append(" ".join(old_words[a1:a2]))
            continue
        if a2 > a1:
            out.append("[-" + " ".join(old_words[a1:a2]) + "-]")
        if b2 > b1:
            out.append("{+" + " ".join(new_words[b1:b2]) + "+}")
    return " ".join(out)


def site_of(text: str):
    """
    The fetch_template.py site a template came from, None for a Fandom
    source, or raise ValueError when its Source line names no known wiki.
    """
    match = SOURCE.search(text)
    if not match:
        raise ValueError("no Source line")
    base = match.group(1)
    for site in fetch_template.SITES.values():
        if site["base"] == base:
            return site
    if base.endswith(".fandom.com"):
        return None
    raise ValueError(f"the source {base} is not a known wiki")


def reference(site: dict, call: str) -> str:
    """The source wiki's rendering of a call, as HTML."""
    data = fetch_template.api_get(site, {
        "action": "parse", "format": "json", "formatversion": "2",
        "text": call, "title": "Template comparison",
        "contentmodel": "wikitext", "prop": "text",
        "disablelimitreport": "1", "disableeditsection": "1",
    })
    if "parse" not in data:
        raise fetch_template.FetchError(
            f"{site['label']} could not render {call}: "
            f"{data.get('error', {}).get('info', 'no reason given')}")
    return data["parse"]["text"]


def render_on_board(board: Path, bootstrap: Path, templates: dict,
                    calls: list) -> dict:
    """Render calls on the board with the given templates; see the module."""
    job = json.dumps({"templates": templates, "calls": calls})
    result = subprocess.run(
        ["php", str(RENDERER), str(board), str(bootstrap)], input=job,
        capture_output=True, text=True, timeout=RENDER_TIMEOUT_SECONDS,
        check=False)
    if result.returncode != 0:
        raise RuntimeError("render_on_board.php failed: "
                           + (result.stderr or result.stdout).strip()[-500:])
    # PHP may print notices before the JSON; it is the last line
    return json.loads(result.stdout.strip().splitlines()[-1])


def default_bootstrap() -> str:
    """seed-forum's bootstrap, when it is checked out next to this repo."""
    sibling = REPO.parent / "seed-forum" / "bin" / "seed-bootstrap.php"
    return os.environ.get("SEED_FORUM_BOOTSTRAP",
                          str(sibling) if sibling.is_file() else "")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Render each template's Example lines on a test board "
                    "and on the wiki it came from, and compare what a reader "
                    "sees.")
    parser.add_argument(
        "names", nargs="*", metavar="NAME",
        help='Templates to compare, as named in templates/ (without ".wiki").')
    parser.add_argument(
        "-a", "--all", action="store_true",
        help="Compare every template in the directory.")
    parser.add_argument(
        "-b", "--board", type=Path,
        default=os.environ.get("WIKI_TEMPLATES_BOARD"),
        help="Root of an installed phpBB board with the phpBB Modders wiki "
             "extension enabled (default: $WIKI_TEMPLATES_BOARD).")
    parser.add_argument(
        "-B", "--bootstrap", type=Path, default=default_bootstrap() or None,
        help="seed-forum's bin/seed-bootstrap.php (default: "
             "$SEED_FORUM_BOOTSTRAP, else ../seed-forum next to this "
             "repository).")
    parser.add_argument(
        "-d", "--dir", type=Path, default=REPO / "templates",
        help="Directory of .wiki template files (default: %(default)s).")
    parser.add_argument(
        "--html", action="store_true",
        help="Also print both renderings as HTML.")
    return parser


def main() -> int:
    """Compare the chosen templates; see the module docstring."""
    parser = build_parser()
    args = parser.parse_args()
    if not args.names and not args.all:
        parser.print_help()
        return 0
    if args.names and args.all:
        parser.error("give template names or --all, not both")
    if not args.board or not (args.board / "config.php").is_file():
        parser.error("--board must be an installed phpBB board")
    if not args.bootstrap or not args.bootstrap.is_file():
        parser.error("--bootstrap must be seed-forum's bin/seed-bootstrap.php")
    if not args.dir.is_dir():
        parser.error(f"{args.dir} is not a directory")

    # Every template is loaded on the board, so they can call each other
    templates = {path.stem: path.read_text(encoding="utf-8")
                 for path in sorted(args.dir.glob("*.wiki"))}
    names = sorted(templates) if args.all else args.names
    missing = [name for name in names if name not in templates]
    if missing:
        parser.error("not in the directory: " + ", ".join(missing))

    failed = 0
    plan = []
    for name in names:
        calls = EXAMPLE.findall(templates[name])
        try:
            site = site_of(templates[name])
        except ValueError as error:
            print(f"FAILED   {name}: {error}")
            failed += 1
            continue
        if not calls:
            print(f"FAILED   {name}: no Example lines in its header")
            failed += 1
            continue
        plan.extend((name, site, call) for call in calls)

    if plan:
        try:
            ours = render_on_board(args.board, args.bootstrap, templates,
                                   [call for _, _, call in plan])
        except (RuntimeError, subprocess.TimeoutExpired,
                json.JSONDecodeError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1

    for index, (name, site, call) in enumerate(plan):
        board_html = ours.get(call, "")
        board_text = visible_text(board_html)
        if site is None:
            print(f"BOARD ONLY {name}: {call}\n    board: {board_text}")
            continue
        if index:
            time.sleep(PARSE_PAUSE_SECONDS)
        try:
            source_html = reference(site, call)
        except fetch_template.FetchError as error:
            print(f"FAILED   {name}: {call}: {error}")
            failed += 1
            continue
        source_text = visible_text(source_html)
        if source_text == board_text:
            print(f"MATCH    {name}: {call}")
        else:
            failed += 1
            print(f"DIFFER   {name}: {call}\n"
                  f"    {site['label']}: {source_text}\n"
                  f"    board: {board_text}\n"
                  f"    diff: {word_diff(source_text, board_text)}")
        if args.html:
            print(f"    {site['label']} HTML: {source_html.strip()}\n"
                  f"    board HTML: {board_html.strip()}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
