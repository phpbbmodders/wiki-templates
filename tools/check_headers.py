#!/usr/bin/env python3
"""
Check that every template carries the attribution header CC BY-SA 4.0 needs.

Each templates/*.wiki file must start with a <noinclude> block holding:

* "Source:" followed by the Template:... page the template was adapted from,
  either on one of the wikis tools/fetch_template.py fetches from (English
  Wikipedia, MediaWiki.org, Meta-Wiki, Wikimedia Commons), or on a Fandom
  wiki (*.fandom.com), copied by hand, since Fandom's terms forbid automated
  access;
* "History:" followed by that page's history URL, on the same wiki;
* for a Fandom template, "Original licence:" naming the wiki's CC BY-SA 3.0
  or 4.0 licence with its link (Fandom wikis default to 3.0, and some use
  NonCommercial or NoDerivs licences, which cannot be taken);
* "Changes:" saying what was removed or changed (not "TODO");
* the licence notice, a link to
  https://creativecommons.org/licenses/by-sa/4.0/;

and no "Needs adapting:" line, which tools/fetch_template.py writes while a
template still uses what the wiki cannot run. Only "Example:" and "Expect:"
lines may hold {{ or }}: the header is the template page's documentation on
a board, so a call anywhere else in it would be run there.

Input: the templates directory (default: templates/ next to this script's
parent). Output: one line per problem on stderr. Exit status: 0 when every
file passes (or there are none yet), 1 when any file fails, 2 for a missing
directory.
"""

import argparse
import re
import sys
from pathlib import Path

LICENCE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
# Wikimedia wikis, which tools/fetch_template.py fetches from (its SITES)
WIKIMEDIA = r"(?P<host>en\.wikipedia\.org|www\.mediawiki\.org" \
            r"|meta\.wikimedia\.org|commons\.wikimedia\.org)"
# Fandom wikis, whose templates are only ever copied by hand: Fandom's terms
# forbid automated access. An optional language path, as in /de/wiki/.
FANDOM = r"(?P<host>[a-z0-9-]+\.fandom\.com(?:/[a-z]{2,3}(?:-[a-z]+)?)?)"
TITLE = r"(?P<title>Template:\S+?)"
SOURCES = {
    "wikimedia": (
        re.compile(r"^Source: https://" + WIKIMEDIA + r"/wiki/" + TITLE + "$",
                   re.M),
        re.compile(r"^History: https://" + WIKIMEDIA + r"/w/index\.php\?"
                   r"title=" + TITLE + r"&action=history$", re.M)),
    "fandom": (
        re.compile(r"^Source: https://" + FANDOM + r"/wiki/" + TITLE + "$",
                   re.M),
        re.compile(r"^History: https://" + FANDOM + r"/wiki/" + TITLE
                   + r"\?action=history$", re.M)),
}
# A Fandom wiki's own licence: CC BY-SA 3.0 by default, which lets an
# adaptation be shared under a later BY-SA version, so under 4.0 here
ORIGINAL_LICENCE = re.compile(
    r"^Original licence: CC BY-SA (?P<version>3\.0|4\.0), "
    r"https://creativecommons\.org/licenses/by-sa/(?P=version)/$", re.M)
REQUIRED = {
    "list of changes": re.compile(r"^Changes: \S", re.M),
    "licence notice": re.compile(re.escape(LICENCE_URL)),
}
HEADER = re.compile(r"\A<noinclude>(.*?)</noinclude>", re.S)


def source_problems(text: str) -> list:
    """What is wrong with the header's Source and History lines."""
    for kind, (source_line, history_line) in SOURCES.items():
        source = source_line.search(text)
        if source:
            break
    else:
        found = ["header has no source URL"]
        if not any(history.search(text) for _, history in SOURCES.values()):
            found.append("header has no history URL")
        return found

    history = history_line.search(text)
    if not history:
        if any(other.search(text) for _, other in SOURCES.values()):
            return ["the source and its history are on different wikis"]
        return ["header has no history URL"]
    found = []
    if history["host"] != source["host"]:
        found.append("the source and its history are on different wikis")
    elif history["title"] != source["title"]:
        found.append("the history link is for another page")
    if kind == "fandom" and not ORIGINAL_LICENCE.search(text):
        found.append("a Fandom template needs an Original licence line "
                     "naming CC BY-SA 3.0 or 4.0")
    return found


def problems(path: Path) -> list:
    """Return what is missing from one template file's header."""
    text = path.read_text(encoding="utf-8")
    header = HEADER.match(text)
    if not header:
        return ["does not start with a <noinclude> header"]
    found = source_problems(header.group(1))
    found += [f"header has no {name}" for name, pattern in REQUIRED.items()
              if not pattern.search(header.group(1))]
    if re.search(r"^Changes: TODO\b", header.group(1), re.M):
        found.append("the list of changes still says TODO")
    # The header is the template page's documentation on a board, so a call
    # written in it would be run there; only examples are meant to be
    for line in header.group(1).splitlines():
        if ("{{" in line or "}}" in line) and not line.startswith(
                ("Example: ", "Expect: ")):
            found.append("a header line other than Example and Expect holds "
                         "{{ or }}, which the board would run: "
                         + line.split(":")[0])
    if re.search(r"^Needs adapting:", header.group(1), re.M):
        found.append("still needs adapting (see its Needs adapting line)")
    return found


def main() -> int:
    """Check every template file and report the ones that fail."""
    parser = argparse.ArgumentParser(
        description="Check that every template has its attribution header.")
    parser.add_argument(
        "-d", "--dir", type=Path,
        default=Path(__file__).resolve().parent.parent / "templates",
        help="Directory of .wiki template files (default: %(default)s).")
    args = parser.parse_args()
    if not args.dir.is_dir():
        print(f"error: {args.dir} is not a directory", file=sys.stderr)
        return 2

    files = sorted(args.dir.glob("*.wiki"))
    failed = 0
    for path in files:
        for problem in problems(path):
            print(f"{path.name}: {problem}", file=sys.stderr)
            failed += 1
    print(f"{len(files)} templates checked, {failed} problems")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
