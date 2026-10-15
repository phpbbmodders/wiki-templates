# wiki-templates

Ready-made templates for the [phpBB Modders wiki extension](https://github.com/phpbbmodders/phpbb-ext-wiki), adapted from Wikipedia's and other Wikimedia wikis' for what the wiki can do, so a board can start with a useful set instead of writing every template from nothing.

So far [`templates/`](templates/) holds the hatnotes `{{Main}}`, `{{See also}}`, `{{Further}}`, `{{About}}`, `{{Distinguish}}`, `{{For}}`, `{{Other uses}}` and `{{Redirect}}`; the message boxes `{{Ambox}}`, `{{Update}}`, `{{Unreferenced}}`, `{{More citations needed}}`, `{{Primary sources}}`, `{{Cleanup}}`, `{{Confusing}}`, `{{Technical}}`, `{{Expand section}}` and `{{Under construction}}`; the stub boxes `{{Asbox}}` and `{{Stub}}`; the inline helpers `{{Nowrap}}`, `{{Small}}`, `{{Large}}` and `{{Center}}`; `{{Blockquote}}` (phpBB's quote box) and `{{Template link}}`, which shows a template's name in braces as a link; `{{Infobox}}`, a table of labelled facts that other infoboxes can be built on; `{{Cite web}}`, a citation of a web page in Wikipedia's style; and `{{Navbox}}`, a box of links to related articles that the reader opens and closes (wiki extension 1.1.0-a2 and later). The plan this repository was built to, now completed, is archived in the wiki extension's [`docs/TODO/archive/archive1.md`](https://github.com/phpbbmodders/phpbb-ext-wiki/blob/main/docs/TODO/archive/archive1.md#starter-templates-repository-completed-10142026).

## Why a separate repository

Wikipedia's templates, like those of the other Wikimedia wikis, are licensed under CC BY-SA 4.0. The wiki extension is GPL-2.0, and CC BY-SA 4.0 is not compatible with GPL-2.0, so the copies live here under their own licence. The extension only reads them when an admin installs them.

## What goes in

Only templates that work as plain wiki text with parameters:

- hatnotes (`{{Main}}`, `{{See also}}`, `{{Further}}`, `{{About}}`);
- message boxes ("needs references", "out of date", "under construction", stub);
- small inline helpers (`{{Nowrap}}`, `{{Small}}`, `{{Large}}`, `{{Center}}`, which needs the wiki extension 1.1.0-a2 or later for `<center>`);
- simplified infobox, citation and navbox templates that take the same parameter names as Wikipedia's.

Left out: Lua modules (`{{#invoke:}}`) and the templates that need them, TemplateStyles (CSS inside a template), and anything whose source page says it is not plain CC BY-SA.

## Adding a template

Each template is one file in [`templates/`](templates/), named after the original (`Main.wiki`, `See also.wiki`). It starts with a header inside `<noinclude>` that links the page it was copied from and that page's history, says what was changed, and states the licence, as Wikipedia asks of a reuser; the [Check](.github/workflows/check.yml) workflow refuses a template without it.

1. **Fetch** the original, with its header filled in ([Fetching templates](https://github.com/phpbbmodders/wiki-templates/wiki/Fetching-templates)):

   ```bash
   python3 tools/fetch_template.py "See also"
   ```

2. **Adapt** it by hand: rewrite what the wiki can't run in plain wiki text, and say what you changed in its header ([The header](https://github.com/phpbbmodders/wiki-templates/wiki/The-header)).
3. **Compare** its examples with the original on a test board ([Checking a template](https://github.com/phpbbmodders/wiki-templates/wiki/Checking-a-template)):

   ```bash
   python3 tools/compare_template.py --board ~/boards/wiki "See also"
   ```

4. **Record** it as adapted in `data/templates.json` ([The record](https://github.com/phpbbmodders/wiki-templates/wiki/The-record)):

   ```bash
   python3 tools/fetch_template.py --mark-adapted "See also"
   ```

Templates from Fandom wikis are copied by hand instead: [Templates from Fandom](https://github.com/phpbbmodders/wiki-templates/wiki/Templates-from-Fandom). The [wiki](https://github.com/phpbbmodders/wiki-templates/wiki) covers each step in full.

## Installing on a board

In the wiki extension (1.1.0-a2 and later), **ACP → Extensions → Wiki → Starter templates**. The admin uploads this repository's zip, presses **Download latest**, or copies the files from `templates/` by FTP into the board's `store/phpbbmodders_wiki/templates/`, then ticks which templates to install. Each becomes a new version of its `Template:` page. A page edited on the board since it was installed is not ticked, so the board's changes are only replaced if the admin chooses to. A file without its source and licence header, or still marked as not adapted, cannot be installed.

The page can also check this repository every few days, as often as the admin chooses, and tell the board's admins when templates are new or have changed. It never downloads or installs on its own.

## Contributing

Contributions are welcome!

- **Bug reports**: [Open an issue](https://github.com/phpbbmodders/wiki-templates/issues).
- **Everything else** (questions, ideas, which templates to add): [use Discussions](https://github.com/orgs/phpbbmodders/discussions) or the [phpBB Modders forum](https://www.phpbbmodders.com/).
- Pull requests are welcome for new templates that pass the header check.

## Acknowledgments

- The templates are adapted from those of [Wikipedia](https://en.wikipedia.org/) and other Wikimedia wikis, by their authors listed in each source page's history.
- Code review, bug fixes, and documentation assisted by [Claude](https://www.anthropic.com/claude).

## License

The templates are licensed under **Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)**, like the Wikimedia pages they come from.

See [LICENSE](LICENSE) for more information.
