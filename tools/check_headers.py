#!/usr/bin/env python3
"""
Check that every template carries the attribution header CC BY-SA 4.0 needs.

Each templates/*.wiki file must start with a <noinclude> block holding:

* "Source:" followed by the https://en.wikipedia.org/wiki/Template:... page
  the template was adapted from;
* "History:" followed by that page's history URL;
* "Changes:" saying what was removed or changed;
* the licence notice, a link to https://creativecommons.org/licenses/by-sa/4.0/.

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
REQUIRED = {
    "source URL": re.compile(
        r"^Source: https://en\.wikipedia\.org/wiki/Template:\S+", re.M),
    "history URL": re.compile(
        r"^History: https://en\.wikipedia\.org/w/index\.php\?title="
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
    return [f"header has no {name}" for name, pattern in REQUIRED.items()
            if not pattern.search(header.group(1))]


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
