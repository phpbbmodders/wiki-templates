#!/usr/bin/env python3
"""
Fetch templates from a Wikimedia wiki as a starting point for this repository.

--site picks the wiki: English Wikipedia (the default), MediaWiki.org,
Meta-Wiki or Wikimedia Commons, all CC BY-SA 4.0. The wiki's licence is read
from its API first, and nothing is fetched or recorded unless it is CC BY-SA.

For each template name the current wikitext is read through the MediaWiki API
(one request for up to 50 names, with an identifying User-Agent, a timeout and
retries on temporary errors only) and written to templates/<Name>.wiki under
the attribution header that tools/check_headers.py requires:

* Source, History and the exact Revision that was copied, from the API;
* "Changes: TODO", for the person adapting it to fill in, noting that the
  source's page-only part (its documentation call and categories: what is
  outside <onlyinclude>, or inside <noinclude>) was removed, since the header
  takes its place;
* "Needs adapting:", when the text uses what the phpBB Modders wiki cannot run:
  Lua ({{#invoke:}}), TemplateStyles, the Translate extension's markup, or
  parser functions and magic words it does not have;
* the licence notice.

Once adapted and passing check_headers.py, --mark-adapted records it as such.

Every template fetched, or rejected with --mark-unadaptable, is recorded in
data/templates.json by its wiki and page ID ("enwiki:1208356"; the page ID
stays the same when a page is renamed), with the revision looked at. A
template recorded at its latest revision is not downloaded again; only its
page info is read, which is cheap. --check-updates reports recorded templates
that were edited, renamed or deleted since, on every wiki, so rejected ones
can be looked at again and adapted ones can pick up fixes.

check_headers.py fails while "Changes: TODO" or "Needs adapting:" is left, so a
fetched template cannot be merged before a person has adapted it.

Input: template names, with or without "Template:". Output: one .wiki file per
template, and a report on stdout of what each one needs and which other
templates it calls. Exit status: 0 when every template was written, 1 when any
was missing or could not be written, 2 for bad arguments.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# The wikis templates can be fetched from: all Wikimedia wikis, under CC BY-SA
# 4.0, with the same API and the same rules for automated access. Each wiki's
# licence is still read from its API before fetching (see check_licence()).
SITES = {
    "enwiki": {"base": "https://en.wikipedia.org",
               "label": "English Wikipedia",
               "api": "https://en.wikipedia.org/w/api.php"},
    "mediawiki": {"base": "https://www.mediawiki.org",
                  "label": "MediaWiki.org",
                  "api": "https://www.mediawiki.org/w/api.php"},
    "meta": {"base": "https://meta.wikimedia.org", "label": "Meta-Wiki",
             "api": "https://meta.wikimedia.org/w/api.php"},
    "commons": {"base": "https://commons.wikimedia.org",
                "label": "Wikimedia Commons",
                "api": "https://commons.wikimedia.org/w/api.php"},
}
DEFAULT_SITE = "enwiki"
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


def page_url(site: dict, title: str, **query: str) -> str:
    """The address of a page on a wiki, with an optional query string."""
    path = urllib.parse.quote(title.replace(" ", "_"), safe=":()_,'!")
    if not query:
        return f"{site['base']}/wiki/{path}"
    params = "&".join(f"{key}={value}" for key, value in query.items())
    return f"{site['base']}/w/index.php?title={path}&{params}"


def api_get(site: dict, params: dict) -> dict:
    """Call a wiki's API, retrying only on 429, 5xx and dropped connections."""
    api_url = site["api"]
    url = api_url + "?" + urllib.parse.urlencode(params)
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
                    f"HTTP {error.code} from {api_url}") from None
            retry_after = error.headers.get("Retry-After", "")
            wait = (min(int(retry_after), 300) if retry_after.isdigit()
                    else delay)
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == MAX_ATTEMPTS:
                raise FetchError(f"{api_url}: {error}") from None
            wait = delay
        time.sleep(wait)
        delay *= 2
    raise FetchError(f"{api_url}: retries exhausted")


def check_licence(site: dict) -> str:
    """
    The wiki's licence as its API reports it. Raises FetchError unless it is
    a CC BY-SA licence, which this repository can take templates under.
    """
    data = api_get(site, {"action": "query", "meta": "siteinfo",
                          "siprop": "rightsinfo", "format": "json",
                          "formatversion": "2"})
    rights = data.get("query", {}).get("rightsinfo", {})
    text = f"{rights.get('text', '')} {rights.get('url', '')}".strip()
    if not re.search(r"by-sa|attribution-share ?alike", text, re.IGNORECASE):
        raise FetchError(f"{site['label']} reports its licence as "
                         f"{text or 'nothing'!r}, not CC BY-SA")
    return text


def query_pages(site: dict, key: str, values: list, content: bool) -> dict:
    """
    Look pages up by title ("titles") or page ID ("pageids"), 50 at a time.

    Returns {value: page} where page holds "pageid", "title" (after
    normalising and redirects), "revid" and "timestamp" of the latest
    revision, and "text" when content is asked for; or None when there is no
    such page. Without content only the page info is read, which is cheap.
    """
    found = {}
    for start in range(0, len(values), BATCH_SIZE):
        batch = values[start:start + BATCH_SIZE]
        params = {"action": "query", "format": "json", "formatversion": "2",
                  "redirects": "1", key: "|".join(str(v) for v in batch)}
        if content:
            params.update(prop="revisions", rvprop="ids|timestamp|content",
                          rvslots="main")
        else:
            params.update(prop="info")
        query = api_get(site, params).get("query", {})
        # Where each requested title ended up after normalising and redirects
        moved = {}
        for step in query.get("normalized", []) + query.get("redirects", []):
            moved[step["from"]] = step["to"]
        pages = query.get("pages", [])
        by_title = {page.get("title"): page for page in pages}
        by_id = {page.get("pageid"): page for page in pages}
        for value in batch:
            if key == "pageids":
                page = by_id.get(value)
            else:
                title = value
                while title in moved:
                    title = moved[title]
                page = by_title.get(title)
            if not page or page.get("missing") or page.get("invalid"):
                found[value] = None
                continue
            entry = {"pageid": page["pageid"], "title": page["title"]}
            if content:
                revision = page["revisions"][0]
                entry.update(revid=revision["revid"],
                             timestamp=revision["timestamp"],
                             text=revision["slots"]["main"]["content"])
            else:
                entry.update(revid=page["lastrevid"],
                             timestamp=page.get("touched", ""))
            found[value] = entry
    return found


def fetch(site: dict, names: list, content: bool = True) -> dict:
    """Look templates up by name; see query_pages()."""
    titles = [PREFIX + name for name in names]
    pages = query_pages(site, "titles", titles, content)
    return {name: pages[PREFIX + name] for name in names}


def record_key(site_id: str, pageid) -> str:
    """A record key: page IDs are unique only within one wiki."""
    return f"{site_id}:{pageid}"


def split_key(key: str) -> tuple:
    """The site and page ID of a record key."""
    site_id, _, pageid = key.rpartition(":")
    return site_id, int(pageid)


def load_record(path: Path) -> dict:
    """
    The record of templates already fetched or rejected, keyed by page ID
    (as a string, since it is JSON). A missing file is an empty record.
    """
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        record = json.load(handle)
    if not isinstance(record, dict):
        raise ValueError(f"{path} is not a JSON object keyed by page ID")
    # Keys without a site are from before other wikis were supported
    return {(key if ":" in key else record_key(DEFAULT_SITE, key)): entry
            for key, entry in record.items()}


def save_record(path: Path, record: dict) -> None:
    """Write the record sorted by page ID, atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # By site, then page ID in numeric order; json.dumps(sort_keys=True)
    # would sort the IDs as text, so only each entry's fields are sorted here
    ordered = {key: dict(sorted(record[key].items()))
               for key in sorted(record, key=split_key)}
    text = json.dumps(ordered, indent=2, ensure_ascii=False)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=path.name, delete=False) as tmp:
        tmp.write(text + "\n")
    os.replace(tmp.name, path)


def record_entry(page: dict, name: str, status: str, reason: str) -> dict:
    """One template's record: what was looked at, and what was decided."""
    return {"name": name, "title": page["title"], "revid": page["revid"],
            "status": status, "reason": reason}


def without_noinclude(text: str) -> tuple:
    """
    Remove the source's page-only parts (its documentation call and
    categories), which this repository's header replaces: everything outside
    <onlyinclude> when the template uses it (the phpBB Modders wiki does not
    know that tag), otherwise the <noinclude> parts. Returns the text and
    whether anything was removed.
    """
    only = re.findall(r"<onlyinclude>(.*?)</onlyinclude>", text,
                      flags=re.IGNORECASE | re.DOTALL)
    if only:
        return "".join(only).strip("\n"), True
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
    if re.search(r"<(?:translate|languages)\b|<!--T:\d+-->", text,
                 re.IGNORECASE):
        problems.append("Translate markup (<translate>, <languages/>)")
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


def header(site: dict, page: dict, problems: list, stripped: bool) -> str:
    """The attribution header that tools/check_headers.py requires."""
    lines = [
        "<noinclude>",
        "Source: " + page_url(site, page["title"]),
        "History: " + page_url(site, page["title"], action="history"),
        "Revision: " + page_url(site, page["title"], oldid=str(page["revid"]))
        + f" ({human_time(page['timestamp'])})",
        "Adapted by phpBB Modders.",
        "Changes: TODO" + (". Done by fetch_template.py: removed the source's"
                           " page-only part (its documentation and"
                           " categories)." if stripped else ""),
    ]
    if problems:
        lines.append("Needs adapting: " + "; ".join(problems))
    lines += [f"Licence: CC BY-SA 4.0, {LICENCE_URL}", "</noinclude>"]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Fetch templates from a Wikimedia wiki (English Wikipedia "
                    "by default) into templates/, "
                    "under the attribution header the repository requires, "
                    "as a starting point for adapting them. Every template "
                    "fetched or rejected is recorded by its wiki and page ID "
                    "in data/templates.json, so it is not fetched again "
                    "until it changes.")
    parser.add_argument(
        "names", nargs="*", metavar="NAME",
        help='Template names, with or without "Template:", for example Main '
             'or "See also".')
    parser.add_argument(
        "-s", "--site", choices=sorted(SITES), default=DEFAULT_SITE,
        help="The wiki to fetch from or mark templates of: "
             + ", ".join(f"{key} ({value['label']})"
                         for key, value in sorted(SITES.items()))
             + " (default: %(default)s).")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "-m", "--mark-unadaptable", action="store_true",
        help="Record the named templates as not adaptable instead of "
             "fetching them; needs --reason.")
    modes.add_argument(
        "-a", "--mark-adapted", action="store_true",
        help="Record the named templates as adapted, once their files in "
             "the directory pass tools/check_headers.py. Fetches nothing.")
    modes.add_argument(
        "-c", "--check-updates", action="store_true",
        help="Report recorded templates, from every wiki, that were edited, "
             "renamed or deleted since they were recorded. Writes nothing.")
    parser.add_argument(
        "-r", "--reason", metavar="TEXT",
        help="Why the templates cannot be adapted (with --mark-unadaptable).")
    parser.add_argument(
        "-d", "--dir", type=Path,
        default=Path(__file__).resolve().parent.parent / "templates",
        help="Directory to write the .wiki files in (default: %(default)s).")
    parser.add_argument(
        "-R", "--record", type=Path,
        default=Path(__file__).resolve().parent.parent / "data"
        / "templates.json",
        help="The record of fetched and rejected templates "
             "(default: %(default)s).")
    parser.add_argument(
        "-f", "--force", action="store_true",
        help="Fetch even when the template is recorded at its latest "
             "revision, and replace a file that is already in the directory.")
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help="Fetch and report, but write no files and change no record.")
    return parser


def check_updates(record: dict) -> int:
    """Report recorded templates that changed on their wiki; return 0."""
    if not record:
        print("The record is empty.")
        return 0
    by_site = {}
    for key in record:
        site_id, pageid = split_key(key)
        by_site.setdefault(site_id, []).append(pageid)
    latest = {}
    for site_id, pageids in by_site.items():
        if site_id not in SITES:
            raise FetchError(f"the record names an unknown wiki: {site_id}")
        for pageid, page in query_pages(SITES[site_id], "pageids", pageids,
                                        False).items():
            latest[record_key(site_id, pageid)] = page
    changed = 0
    for key in sorted(record, key=lambda k: (record[k]["name"].lower(), k)):
        entry = record[key]
        page = latest[key]
        site_id, pageid = split_key(key)
        where = "" if site_id == DEFAULT_SITE else f", {site_id}"
        label = f"{entry['name']} ({entry['status']}{where})"
        if page is None:
            print(f"DELETED  {label}: page {pageid} no longer exists")
            changed += 1
            continue
        notes = []
        if page["revid"] != entry["revid"]:
            notes.append(f"edited: revision {entry['revid']} -> "
                         f"{page['revid']}")
        if page["title"] != entry["title"]:
            notes.append(f"renamed to {page['title']}")
        if notes:
            print(f"CHANGED  {label}: {'; '.join(notes)}")
            changed += 1
    print(f"{len(record)} recorded, {changed} changed since")
    return 0


def mark_unadaptable(site_id: str, names: list, reason: str,
                     record: dict) -> int:
    """Record templates as not adaptable; return the exit status."""
    site = SITES[site_id]
    pages = fetch(site, names, content=False)
    failed = 0
    for name in names:
        page = pages[name]
        if page is None:
            print(f"MISSING  {name}: no such template on {site['label']}")
            failed += 1
            continue
        record[record_key(site_id, page["pageid"])] = record_entry(
            page, name, "not adaptable", reason)
        print(f"RECORDED {name} (page {page['pageid']}, revision "
              f"{page['revid']}): not adaptable: {reason}")
    return 1 if failed else 0


def mark_adapted(names: list, args: argparse.Namespace, record: dict) -> int:
    """
    Record templates as adapted, once their files pass the header check;
    return the exit status. The revision recorded stays the one that was
    fetched, so --check-updates still reports later edits to the original.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import check_headers
    by_name = {(key.split(":")[0], entry["name"]): key
               for key, entry in record.items()}
    failed = 0
    for name in names:
        key = by_name.get((args.site, name))
        path = args.dir / f"{name}.wiki"
        if key is None:
            print(f"UNKNOWN  {name}: not in the record for {args.site}; "
                  "fetch it first")
            failed += 1
        elif not path.is_file():
            print(f"MISSING  {name}: no {path.name} in {args.dir}")
            failed += 1
        elif check_headers.problems(path):
            print(f"NOT YET  {name}: "
                  + "; ".join(check_headers.problems(path)))
            failed += 1
        else:
            record[key].update(status="adapted", reason="")
            print(f"ADAPTED  {name}")
    return 1 if failed else 0


def fetch_templates(names: list, args: argparse.Namespace,
                    record: dict) -> int:
    """Fetch, write and record templates; return the exit status."""
    site_id = args.site
    site = SITES[site_id]
    failed = 0
    # Page info first, which is cheap: anything recorded at its latest
    # revision is not downloaded again
    info = fetch(site, names, content=False)
    wanted = []
    for name in names:
        page = info[name]
        if page is None:
            print(f"MISSING  {name}: no such template on {site['label']}")
            failed += 1
            continue
        entry = record.get(record_key(site_id, page["pageid"]))
        if entry and entry["revid"] == page["revid"] and not args.force:
            print(f"KNOWN    {name}: recorded at revision {page['revid']} "
                  f"({entry['status']}); use --force to fetch it again")
            continue
        wanted.append(name)

    pages = fetch(site, wanted) if wanted else {}
    for name in wanted:
        page = pages[name]
        if page is None:
            print(f"MISSING  {name}: no such template on {site['label']}")
            failed += 1
            continue
        target = args.dir / f"{name}.wiki"
        if target.exists() and not args.force:
            print(f"SKIPPED  {name}: {target.name} exists;"
                  " use --force to replace it")
            failed += 1
            continue
        body, stripped = without_noinclude(page["text"])
        problems = needs(body)
        if not args.dry_run:
            text = header(site, page, problems, stripped) + body + "\n"
            target.write_text(text, encoding="utf-8")
        record[record_key(site_id, page["pageid"])] = record_entry(
            page, name, "needs adapting" if problems else "fetched",
            "; ".join(problems))
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


def main() -> int:
    """Run the chosen mode; see the module docstring."""
    parser = build_parser()
    args = parser.parse_args()
    if not args.names and not args.check_updates:
        parser.print_help()
        return 0
    if args.check_updates and args.names:
        parser.error("--check-updates takes no template names")
    if args.mark_adapted and not args.dir.is_dir():
        parser.error(f"{args.dir} is not a directory")
    if args.mark_unadaptable and not (args.reason and args.reason.strip()):
        parser.error("--mark-unadaptable needs --reason")
    if args.reason and not args.mark_unadaptable:
        parser.error("--reason is only used with --mark-unadaptable")
    try:
        names = list(dict.fromkeys(template_name(raw) for raw in args.names))
    except ValueError as error:
        parser.error(str(error))
    if not args.check_updates and not args.mark_unadaptable \
            and not args.dir.is_dir():
        parser.error(f"{args.dir} is not a directory")
    try:
        record = load_record(args.record)
    except (ValueError, json.JSONDecodeError) as error:
        parser.error(f"cannot read the record: {error}")

    try:
        if args.check_updates:
            return check_updates(record)
        if args.mark_adapted:
            status = mark_adapted(names, args, record)
            if not args.dry_run:
                save_record(args.record, record)
            return status
        # Only a wiki whose licence the repository can take templates under
        check_licence(SITES[args.site])
        if args.mark_unadaptable:
            status = mark_unadaptable(args.site, names, args.reason.strip(),
                                      record)
        else:
            status = fetch_templates(names, args, record)
    except FetchError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if not args.dry_run:
        save_record(args.record, record)
    return status


if __name__ == "__main__":
    sys.exit(main())
