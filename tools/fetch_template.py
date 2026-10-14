#!/usr/bin/env python3
"""
Fetch templates from English Wikipedia as a starting point for this repository.

For each template name the current wikitext is read through the MediaWiki API
(one request for up to 50 names, with an identifying User-Agent, a timeout and
retries on temporary errors only) and written to templates/<Name>.wiki under
the attribution header that tools/check_headers.py requires:

* Source, History and the exact Revision that was copied, from the API;
* "Changes: TODO", for the person adapting it to fill in, noting that
  Wikipedia's own <noinclude> part (its documentation call and categories)
  was removed, since the header takes its place;
* "Needs adapting:", when the text uses what the phpBB Modders wiki cannot run:
  Lua ({{#invoke:}}), TemplateStyles, or parser functions and magic words it
  does not have;
* the licence notice.

check_headers.py fails while "Changes: TODO" or "Needs adapting:" is left, so a
fetched template cannot be merged before a person has adapted it.

Input: template names, with or without "Template:". Output: one .wiki file per
template, and a report on stdout of what each one needs and which other
templates it calls. Exit status: 0 when every template was written, 1 when any
was missing or could not be written, 2 for bad arguments.
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_URL = "https://en.wikipedia.org/w/api.php"
WIKI_URL = "https://en.wikipedia.org"
USER_AGENT = ("phpbbmodders-wiki-templates/1.0 "
              "(https://github.com/phpbbmodders/wiki-templates; "
              "board@phpbbmodders.com)")
LICENCE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
PREFIX = "Template:"
BATCH_SIZE = 50
TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 4

# Parser functions and magic words the phpBB Modders wiki supports (its README
# lists them). Anything else written as {{#name: or {{name: is flagged.
SUPPORTED_FUNCTIONS = {
    "#if", "#ifeq", "#switch", "#ifexist", "#expr", "#ifexpr", "#iferror",
    "#time", "#len", "#pos", "#rpos", "#sub", "#replace", "#explode",
    "lc", "uc", "lcfirst", "ucfirst", "padleft", "padright", "urlencode",
    "anchorencode",
}
SUPPORTED_MAGIC_WORDS = {"PAGENAME", "FULLPAGENAME", "NAMESPACE", "SITENAME"}

# MediaWiki's functions written without "#", as {{name:...}}. Those not in
# SUPPORTED_FUNCTIONS are flagged.
CORE_FUNCTIONS = {
    "formatnum", "plural", "gender", "grammar", "int", "ns", "nse", "fullurl",
    "localurl", "canonicalurl", "filepath", "urlencode", "anchorencode", "lc",
    "uc", "lcfirst", "ucfirst", "padleft", "padright", "safesubst", "subst",
}

# Magic words, which look like templates but are not: {{PAGENAME}}, {{!}} ...
MAGIC_WORD = re.compile(
    r"^(?:!|=|(?:FULL|BASE|SUB|ROOT|TALK|SUBJECT)?PAGENAMEE?"
    r"|NAMESPACEE?|SITENAME|(?:CURRENT|LOCAL|REVISION|NUMBEROF)[A-Z]*"
    r"|SERVER(?:NAME)?|SCRIPTPATH|DISPLAYTITLE|DEFAULTSORT|PAGESIZE"
    r"|PROTECTIONLEVEL)$")

# Names that cannot be a file in templates/: subpages and path characters.
INVALID_NAME = re.compile(r'[/\\<>:"|?*\x00-\x1f]|^\.|^\s|\s$')


class FetchError(Exception):
    """The API could not be read."""


def template_name(raw: str) -> str:
    """
    Turn "Template:see also" or "see_also" into "See also", the name the file
    and the page on a board use. Raises ValueError for a name that cannot be
    a file, such as a subpage ("Foo/doc").
    """
    name = raw.strip()
    if name.lower().startswith(PREFIX.lower()):
        name = name[len(PREFIX):].strip()
    name = re.sub(r"[_\s]+", " ", name)
    if not name or INVALID_NAME.search(name):
        raise ValueError(
            f"not a template name this repository can hold: {raw!r}")
    return name[0].upper() + name[1:]


def page_url(title: str, **query: str) -> str:
    """The address of a Wikipedia page, with an optional query string."""
    path = urllib.parse.quote(title.replace(" ", "_"), safe=":()_,'!")
    if not query:
        return f"{WIKI_URL}/wiki/{path}"
    params = "&".join(f"{key}={value}" for key, value in query.items())
    return f"{WIKI_URL}/w/index.php?title={path}&{params}"


def api_get(params: dict) -> dict:
    """Call the API, retrying only on 429, 5xx and dropped connections."""
    url = API_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    delay = 5
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(
                    request, timeout=TIMEOUT_SECONDS) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            transient = error.code == 429 or error.code >= 500
            if not transient or attempt == MAX_ATTEMPTS:
                raise FetchError(
                    f"HTTP {error.code} from {API_URL}") from None
            retry_after = error.headers.get("Retry-After", "")
            wait = (min(int(retry_after), 300) if retry_after.isdigit()
                    else delay)
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == MAX_ATTEMPTS:
                raise FetchError(f"{API_URL}: {error}") from None
            wait = delay
        time.sleep(wait)
        delay *= 2
    raise FetchError(f"{API_URL}: retries exhausted")


def fetch(names: list) -> dict:
    """
    Read the current revision of each template.

    Returns {name: page} where page holds "title" (after redirects), "revid",
    "timestamp" and "text", or None when Wikipedia has no such template.
    """
    found = {}
    for start in range(0, len(names), BATCH_SIZE):
        batch = names[start:start + BATCH_SIZE]
        data = api_get({
            "action": "query", "format": "json", "formatversion": "2",
            "prop": "revisions", "rvprop": "ids|timestamp|content",
            "rvslots": "main", "redirects": "1",
            "titles": "|".join(PREFIX + name for name in batch),
        })
        query = data.get("query", {})
        # Where each requested title ended up after normalising and redirects
        moved = {}
        for step in query.get("normalized", []) + query.get("redirects", []):
            moved[step["from"]] = step["to"]
        pages = {page["title"]: page for page in query.get("pages", [])}
        for name in batch:
            title = PREFIX + name
            while title in moved:
                title = moved[title]
            page = pages.get(title)
            if not page or page.get("missing") or not page.get("revisions"):
                found[name] = None
                continue
            revision = page["revisions"][0]
            found[name] = {
                "title": page["title"],
                "revid": revision["revid"],
                "timestamp": revision["timestamp"],
                "text": revision["slots"]["main"]["content"],
            }
    return found


def without_noinclude(text: str) -> tuple:
    """
    Remove Wikipedia's own <noinclude> parts (its {{Documentation}} call and
    categories), which this repository's header replaces. Returns the text
    and whether anything was removed.
    """
    stripped = re.sub(r"<noinclude>.*?</noinclude>", "", text,
                      flags=re.IGNORECASE | re.DOTALL)
    return stripped.strip("\n"), stripped != text


def needs(text: str) -> list:
    """What in a template's text the phpBB Modders wiki cannot run."""
    problems = []
    if re.search(r"\{\{\s*#invoke\s*:", text, re.IGNORECASE):
        problems.append("Lua ({{#invoke:}})")
    if re.search(r"<templatestyles\b", text, re.IGNORECASE):
        problems.append("TemplateStyles")
    unsupported = set()
    for match in re.finditer(r"\{\{\s*(#?[A-Za-z][\w ]*?)\s*:", text):
        word = match.group(1).strip().lower()
        if word == "#invoke" or word in SUPPORTED_FUNCTIONS:
            continue
        if word.startswith("#") or word in CORE_FUNCTIONS:
            unsupported.add(word)
    for match in re.finditer(r"\{\{\s*([A-Z][A-Z0-9]*)\s*(?:\}\}|:)", text):
        word = match.group(1)
        if (MAGIC_WORD.match(word) and word not in SUPPORTED_MAGIC_WORDS
                and not word.startswith("CURRENT")):
            unsupported.add(word)
    if unsupported:
        problems.append("unsupported " + ", ".join(sorted(unsupported)))
    return problems


def called_templates(text: str) -> list:
    """The other templates a template's text calls, A to Z."""
    names = set()
    call = re.compile(r"(?<!\{)\{\{(?!\{)\s*([^{}|#:\n]+?)\s*(?:\||\}\})")
    for match in call.finditer(text):
        name = match.group(1).strip()
        if (name and not MAGIC_WORD.match(name)
                and name.lower() not in CORE_FUNCTIONS):
            names.add(name[0].upper() + name[1:])
    return sorted(names)


def human_time(timestamp: str) -> str:
    """An API timestamp as MM/DD/YYYY h:mm AM/PM UTC."""
    moment = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
    moment = moment.replace(tzinfo=timezone.utc)
    return moment.strftime("%m/%d/%Y %I:%M %p UTC").replace(" 0", " ", 1)


def header(page: dict, problems: list, stripped: bool) -> str:
    """The attribution header that tools/check_headers.py requires."""
    lines = [
        "<noinclude>",
        "Source: " + page_url(page["title"]),
        "History: " + page_url(page["title"], action="history"),
        "Revision: " + page_url(page["title"], oldid=str(page["revid"]))
        + f" ({human_time(page['timestamp'])})",
        "Adapted by phpBB Modders.",
        "Changes: TODO" + (". Done by fetch_template.py: removed Wikipedia's"
                           " <noinclude> part (its documentation and"
                           " categories)." if stripped else ""),
    ]
    if problems:
        lines.append("Needs adapting: " + "; ".join(problems))
    lines += [f"Licence: CC BY-SA 4.0, {LICENCE_URL}", "</noinclude>"]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Fetch templates from English Wikipedia into templates/, "
                    "under the attribution header the repository requires, "
                    "as a starting point for adapting them.")
    parser.add_argument(
        "names", nargs="*", metavar="NAME",
        help='Template names, with or without "Template:", for example Main '
             'or "See also".')
    parser.add_argument(
        "-d", "--dir", type=Path,
        default=Path(__file__).resolve().parent.parent / "templates",
        help="Directory to write the .wiki files in (default: %(default)s).")
    parser.add_argument(
        "-f", "--force", action="store_true",
        help="Replace a template that is already in the directory.")
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help="Fetch and report, but write no files.")
    return parser


def main() -> int:
    """Fetch the named templates and write them; see the module docstring."""
    parser = build_parser()
    args = parser.parse_args()
    if not args.names:
        parser.print_help()
        return 0
    try:
        names = list(dict.fromkeys(template_name(raw) for raw in args.names))
    except ValueError as error:
        parser.error(str(error))
    if not args.dir.is_dir():
        parser.error(f"{args.dir} is not a directory")

    try:
        pages = fetch(names)
    except FetchError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    failed = 0
    for name in names:
        page = pages[name]
        target = args.dir / f"{name}.wiki"
        if page is None:
            print(f"MISSING  {name}: no such template on English Wikipedia")
            failed += 1
            continue
        if target.exists() and not args.force:
            print(f"SKIPPED  {name}: {target.name} exists;"
                  " use --force to replace it")
            failed += 1
            continue
        body, stripped = without_noinclude(page["text"])
        problems = needs(body)
        if not args.dry_run:
            text = header(page, problems, stripped) + body + "\n"
            target.write_text(text, encoding="utf-8")
        state = "NEEDS ADAPTING" if problems else "fetched"
        print(f"{state:15}{name} (revision {page['revid']})"
              + (f": {'; '.join(problems)}" if problems else ""))
        calls = called_templates(body)
        if calls:
            missing = [call for call in calls
                       if not (args.dir / f"{call}.wiki").exists()]
            note = (f" (not in the repository: {', '.join(missing)})"
                    if missing else "")
            print(f"{'':15}calls {', '.join(calls)}{note}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
