# Daily Recap

Turn accessible AI conversations into a daily journal of what you worked on,
learned, decided, and left unfinished. Weekly reviews connect the saved daily
reports and show missing days.

**Status: early manual-use version.** The current implementation works inside
Codex desktop. Python prepares dated evidence and saves files; the current
agent writes the report. The public-beta work is tracked in [TODO.md](TODO.md).
The [setup and usage example](docs/workflow-example.md) separates today's
workflow from the proposed terminal setup wizard. The planned wizard uses menus,
checkboxes, and a final review screen; it is not implemented yet.

## What works today

- Local readers for Codex, Claude Code, Kimi Code, OpenCode, and Hermes.
- ChatGPT collection through supported desktop history tools.
- Workspace exclusions, local-date filtering, duplicate removal, and bounded
  input segments.
- Daily Markdown reports with compact source references in companion metadata.
- Weekly input from saved daily reports, with missing and partial days shown.
- Existing-report reuse, refresh candidates, backups on promotion, and separate
  saved/delivered state.

The current skill requires GPT-6.1 Sol High. Configurable runtime model choice
is planned, not implemented. The Python code makes no model API calls itself.

## Install for a manual trial

The tested environment is Linux with Python 3.11+ and the required Codex desktop
history tools. Runtime Python code uses only the standard library. Windows is
not supported by the current Unix file-locking code. macOS has not been verified.

From this repository directory, run:

```sh
python3 -m unittest discover -s tests -q
python3 build_bundle.py
```

The build creates `bundle/day-recap/` and `bundle/day-recap.zip`. Copy the
**generated** `bundle/day-recap` folder into your user skill directory, normally
`~/.agents/skills/day-recap`. Do not overwrite an existing skill. The source
`skill/` folder alone does not include the Python scripts.

In a Codex desktop chat, request:

```text
$day-recap setup
Use my chosen project folder and save reports outside it.
Start with a manual sample. Do not enable a schedule.
```

Choose your own paths when asked. Keep the recap chat workspace excluded from
collection so earlier reports do not feed back into new ones. Setup creates a
local preferences file; it does not require editing a configuration template.

For the next report, request `$day-recap yesterday`. For a weekly review,
request `$day-recap review the previous completed week` after saving daily
reports. See the [skill instructions](skill/SKILL.md) for the complete procedure.

## Coverage and privacy

The reader currently tries every supported local source and filters coding
sessions by the chosen work folders. Per-app selection is planned. ChatGPT
currently covers accessible chats across all topics and needs the desktop
agent to retrieve them. A CLI-only run cannot establish ChatGPT coverage.

The implemented ChatGPT workflow uses a bounded active-chat listing. Some
assistant replies and attachment contents may be unavailable. Cursor is
metadata-only. Missing access appears in coverage; a recap does not represent
everything you did outside the available conversations.

Selected conversation text is processed by the Codex agent. Local collection
and storage do **not** mean offline model processing. Reports and metadata can
contain private topics, titles, and paths. Review them before sharing.

Raw extracted text is written to private temporary directories. The skill
instructs the agent to remove those files after saving; crash-safe cleanup is
still planned. Readers apply limited redaction, which is not a guarantee that
all sensitive text will be removed. No credentials are included in this project.

## Current limitations

- Refreshing again after accepting a candidate is blocked by the leftover
  candidate. This known defect is tracked as TODO 1.
- Metadata hardcodes the expected model instead of proving which model ran.
- Some collection, review, cleanup, and delivery steps depend on agent behavior.
- Scheduled generation, sleep recovery, and app-closed behavior need release
  validation. Start with manual use. Saving a schedule preference does not
  activate a desktop automation.
- Model processing uses the user's existing runtime and its usage limits.
  No unlimited or zero-cost execution is promised.

## Development

`reader.py` parses evidence, `core.py` handles storage and due dates, and
`cli.py` connects those operations. `skill/SKILL.md` tells the desktop agent how
to collect ChatGPT pages and write reports. Tests use synthetic temporary data.

Run `python3 -m unittest discover -s tests -q` after changes. Run
`python3 build_bundle.py` to regenerate the installable skill. Generated bundles,
personal reports, preferences, state, and local setup files are excluded from Git.

The v1 plan retains the existing sources and avoids a provider SDK, server,
database, or dashboard. No license has been selected yet; choosing one remains
an explicit release task.
