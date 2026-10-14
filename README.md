# wiki-templates

Ready-made templates for the [phpBB Modders wiki extension](https://github.com/phpbbmodders/phpbb-ext-wiki), adapted from Wikipedia's for what the wiki can do, so a board can start with a useful set instead of writing every template from nothing.

No templates have been added yet. The plan for this repository is in the wiki extension's [`docs/TODO/todo-wiki-templates-repo.md`](https://github.com/phpbbmodders/phpbb-ext-wiki/blob/main/docs/TODO/todo-wiki-templates-repo.md).

## Why a separate repository

Wikipedia's templates are licensed under CC BY-SA 4.0. The wiki extension is GPL-2.0, and CC BY-SA 4.0 is not compatible with GPL-2.0, so the copies live here under their own licence. The extension only reads them when an admin installs them.

## What goes in

Only templates that work as plain wiki text with parameters:

- hatnotes (`{{Main}}`, `{{See also}}`, `{{Further}}`, `{{About}}`);
- message boxes ("needs references", "out of date", "under construction", stub);
- small inline helpers (`{{nowrap}}`, `{{small}}`, `{{center}}`);
- simplified infobox, citation and navbox templates that take the same parameter names as Wikipedia's.

Left out: Lua modules (`{{#invoke:}}`) and the templates that need them, TemplateStyles (CSS inside a template), and anything whose source page says it is not plain CC BY-SA.

## Adding a template

Start with [`tools/fetch_template.py`](tools/fetch_template.py), which fetches a template's current text from English Wikipedia through the MediaWiki API and writes it with the header below filled in:

```bash
python3 tools/fetch_template.py Nowrap "See also"
```

It records the exact revision copied, and removes Wikipedia's own `<noinclude>` part (its documentation and categories), since the header takes its place. It leaves `Changes: TODO` for you to fill in, and adds a `Needs adapting:` line when the text uses something the wiki can't run: Lua (`{{#invoke:}}`), TemplateStyles, or a parser function or magic word the wiki doesn't have. It also lists the other templates each one calls. It never replaces a file that's already here unless given `--force`, and `--dry-run` only reports. Then adapt the template by hand: rewrite any Lua part in plain wiki text, and write down what you changed.

One file per template in [`templates/`](templates/), named after the Wikipedia template (`Main.wiki`, `See also.wiki`, ...), so text pasted from Wikipedia finds the same names and parameters. Every file starts with this header:

```text
<noinclude>
Source: https://en.wikipedia.org/wiki/Template:Main
History: https://en.wikipedia.org/w/index.php?title=Template:Main&action=history
Adapted by phpBB Modders.
Changes: rewritten without Lua; the "selfref" option removed.
Licence: CC BY-SA 4.0, https://creativecommons.org/licenses/by-sa/4.0/
</noinclude>
```

The header meets what Wikipedia asks of a reuser: it links the page copied and its history (which lists the authors), says the copy was changed, and states the licence. It sits inside `<noinclude>`, so it shows on the template's own page on the board but not in the articles that use it.

The [Check](.github/workflows/check.yml) workflow runs [`tools/check_headers.py`](tools/check_headers.py) on every push and pull request. It fails when a template is missing any of these lines, still says `Changes: TODO`, or still has a `Needs adapting:` line:

```bash
python3 tools/check_headers.py
```

This is not legal advice. Wikipedia's [Reusing Wikipedia content](https://en.wikipedia.org/wiki/Wikipedia:Reusing_Wikipedia_content) page and the Wikimedia [Terms of Use](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use) say each reuser must work out how the licences apply to them.

## Installing on a board

Planned in the wiki extension, not built yet. The admin uploads this repository's zip in the ACP, or copies the files into a folder in the board's `store/`, then an **Install starter templates** button creates one `Template:` page per file. An existing template page is not overwritten without asking.

## Contributing

Contributions are welcome!

- **Bug reports**: [Open an issue](https://github.com/phpbbmodders/wiki-templates/issues).
- **Everything else** (questions, ideas, which templates to add): [use Discussions](https://github.com/orgs/phpbbmodders/discussions) or the [phpBB Modders forum](https://www.phpbbmodders.com/).
- Pull requests are welcome for new templates that pass the header check.

## Acknowledgments

- The templates are adapted from [Wikipedia](https://en.wikipedia.org/)'s, by their authors listed in each source page's history.
- Code review, bug fixes, and documentation assisted by [Claude](https://www.anthropic.com/claude).

## License

The templates are licensed under **Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)**, like the Wikipedia pages they come from.

See [LICENSE](LICENSE) for more information.
