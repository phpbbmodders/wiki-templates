#!/usr/bin/env python3
"""
Check that every template carries the attribution header CC BY-SA 4.0 needs.

Each templates/*.wiki file must start with a <noinclude> block holding:

* "Source:" followed by the Template:... page the template was adapted from,
  on one of the wikis tools/fetch_template.py fetches from (English
  Wikipedia, MediaWiki.org, Meta-Wiki, Wikimedia Commons);
* "History:" followed by that page's history URL, on the same wiki;
* "Changes:" saying what was removed or changed (not "TODO");
* the licence notice, a link to
  https://creativecommons.org/licenses/by-sa/4.0/;

and no "Needs adapting:" line, which tools/fetch_template.py writes while a
template still uses what the wiki cannot run.

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
# The wikis templates are taken from (tools/fetch_template.py's SITES)
HOSTS = (r"(?P<host>en\.wikipedia\.org|www\.mediawiki\.org"
         r"|meta\.wikimedia\.org|commons\.wikimedia\.org)")
REQUIRED = {
    "source URL": re.compile(
        r"^Source: https://" + HOSTS + r"/wiki/Template:\S+", re.M),
    "history URL": re.compile(
        r"^History: https://" + HOSTS + r"/w/index\.php\?title="
        r"Template:\S+&action=history", re.M),
    "list of changes": re.compile(r"^Changes: \S", re.M),
    "licence notice": re.compile(re.escape(LICENCE_URL)),
}
HEADER = re.compile(r"\A<noinclude>(.*?)</noinclude>", re.S)


def problems(path: Path) -> list:
    """Return what is missing from one template file's header."""
    text = path.read_text(encoding="utf-8")
    header = HEADER.match(text)
    if not header:
        return ["does not start with a <noinclude> header"]
    found = [f"header has no {name}" for name, pattern in REQUIRED.items()
             if not pattern.search(header.group(1))]
    source = REQUIRED["source URL"].search(header.group(1))
    history = REQUIRED["history URL"].search(header.group(1))
    if source and history and source["host"] != history["host"]:
        found.append("the source and its history are on different wikis")
    if re.search(r"^Changes: TODO\b", header.group(1), re.M):
        found.append("the list of changes still says TODO")
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
