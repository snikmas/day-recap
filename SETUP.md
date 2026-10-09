# Set up and use Daily Recap

[Back to the project overview](README.md)

Turn selected AI conversations into a daily journal of your work, learning,
decisions, and unfinished tasks. Weekly reviews connect saved daily reports and
show missing days. This is a Linux manual-use beta under the [MIT license](LICENSE).

Python prepares evidence and saves reports. The current supported desktop agent
writes the report using its selected model and reasoning setting. The Python
code makes no model API calls. History sources and the writing model are separate
choices: OpenCode history can be read while the Codex desktop agent writes.

## Requirements

- Linux with Python 3.11 or newer. Runtime code uses the standard library.
- A supported Codex desktop chat for writing reports. Selected ChatGPT history
  requires `list_threads`, `read_thread`, and `list_archived_threads` in that
  execution context.
- Writable preferences and report storage. Setup detects the computer timezone;
  you can change it when needed.

Windows is unsupported. macOS has not been verified with an installation and
sample. A separate model CLI does not establish desktop model availability or
history access. The terminal cannot promise either capability.

## Install one version

If this is your first installation, run these commands from the repository directory:

```sh
python3 build_bundle.py
python3 release_check.py
python3 manage_skill.py install ~/.agents/skills/day-recap
```

If a skill already exists at that path, use the update or migration instructions below.

The generated `bundle/day-recap/` contains the skill and its scripts. The source
`skill/` directory alone is incomplete. Installation refuses to overwrite an
existing skill. Refresh desktop skill discovery or restart if the skill is absent.
The ZIP at `bundle/day-recap.zip` contains the same allowed files for distribution.

## Choose scope and storage

Run the terminal wizard:

```sh
python3 ~/.agents/skills/day-recap/scripts/cli.py setup
```

Use arrows to move, Space to toggle sources, and Enter to continue. Backspace
returns to the previous screen; Escape or Ctrl+C cancels. Paths are text fields.
Use `b` to go back, `q` to cancel, and `-` to clear an optional field. For a
numbered-input terminal, use `setup --numbered`. Empty input and EOF do not
confirm a source or save setup. Using no setup flags in a noninteractive session produces
an error rather than inferred consent.

The five screens cover sources, work folders, report storage, model policy, and
final review. Sources start unchecked. Detection stats known locations without
opening message bodies or provider configuration. Available local readers are
Codex, Claude Code, Kimi Code, OpenCode, and Hermes. Cursor is metadata-only;
missing or inaccessible sources appear in coverage. Only selected readers run.

ChatGPT is a separate opt-in across topics. You can enter excluded chat IDs;
check those IDs in desktop. The terminal does not scrape or enumerate chats.
Folder filters apply to local coding sessions; ChatGPT exclusions use chat IDs.
The recap workspace, preferences directory, and report storage are excluded from
local collection automatically. If your terminal is outside your recap chat's
workspace, pass `setup --workspace /path/to/recap-chat`.

Preferences default to `~/.local/share/day-recap/preferences.json`. To choose a
different preferences directory, pass `--data-dir DIRECTORY` **before** every
command. Reports may use a different folder selected in setup. Keep both preferences and
reports outside the installed skill directory. Rerunning setup
prefills choices and preserves reports and scheduling identity. Only final Save
replaces preferences atomically. Old preferences without confirmed source scope
require setup again before collection.

For repeatable scripted setup, explicitly select every source and accept the
notice. This example uses your own folders and starts no collection or schedule:

```sh
python3 ~/.agents/skills/day-recap/scripts/cli.py --data-dir ~/daily-recap-data setup \
  --source codex --root ~/projects --workspace ~/recap-chat \
  --report-dir ~/daily-reports --accept-data-notice
```

Optional scripted flags include `--exclude`, `--exclude-chat`, `--zone`,
`--start-date`, `--model`, and `--reasoning`. A requested specific model stays
pending until selected and verified in the same desktop host. Setup defaults to
the current desktop model. It does not configure arbitrary providers or read keys.

## Request your sample

In the supported desktop chat, request:

```text
$day-recap yesterday
Use my saved preferences directory. Start with a manual sample.
```

Before collection, the skill checks the requested model and required selected
history tools. A supported host model catalog is used only when actually exposed;
otherwise setup says "Check in desktop." A current selection reported by the host
can verify the requested model without a catalog. If the agent cannot switch it,
change the desktop model yourself and resume. There is no silent fallback.

The agent reviews every prepared input segment, writes the report, saves it,
displays the saved text, and then records delivery. For a date range, it saves
and displays a separate daily report for each requested date. Metadata separates requested
settings from desktop-reported observations. Unverifiable details are `unknown`;
those observations are supplied by the agent, not independently measured by Python.
Each scheduled or manual preparation records its own runtime evidence.
See the [complete workflow](skill/SKILL.md) and [synthetic daily example](examples/daily-report.md).

## Refresh, review, and recover

- Request `$day-recap refresh yesterday` to prepare a separate candidate. The
  agent shows the candidate as a preview. Review it and explicitly accept promotion.
  Only then does the agent display and record delivery of the promoted report. Each promotion preserves the previous
  canonical text, including edits, in a backup. Repeated refreshes are supported.
- If canonical edits occurred after candidate creation, promotion preserves them
  and stops. On explicit rejection, `archive-candidate DATE` archives the candidate
  so a new refresh can be prepared. Interrupted promotions resume from a journal.
- Request `$day-recap review the previous completed week` after daily use. Missing
  and partial days stay visible; no activity is invented for missing days.
- Ordinary retries reuse saved reports. Pending delivery displays the saved text;
  already delivered scheduled reports stay quiet. A stop after display but before
  the delivery checkpoint may cause a duplicate. Exactly-once delivery is not promised.
- `temporary-list` lists owned interrupted extraction attempts. Resume one or use
  `cleanup DIRECTORY` for that explicitly owned attempt. Successful commit cleans
  its extraction directory; separate desktop capture attempts need their own
  cleanup. Unrelated temporary directories are never swept.

All CLI commands use the installed `scripts/cli.py` with the same `--data-dir`.
Reports are Markdown with compact provenance in companion metadata. Report text
and edits are preserved on reuse; refresh candidates are separate from scheduled
canonical delivery.

## Update or uninstall

Build and check the new checkout, then update:

```sh
python3 build_bundle.py
python3 release_check.py
python3 manage_skill.py update ~/.agents/skills/day-recap
```

Update archives the prior skill outside the skill discovery directory, normally
under `~/.agents/day-recap-archives`. Preferences and
reports live outside it and remain unchanged. If installation fails after the
old skill is archived, the helper restores it.

### Migrate an older symlink installation

If the installer reports a legacy symlink, run these commands from this source
checkout, not from the installed skill folder:

```sh
python3 build_bundle.py
python3 release_check.py
python3 manage_skill.py migrate ~/.agents/skills/day-recap
```

Migration installs the current bundle while preserving the original link and
leaving its target untouched. The old link is archived outside skill discovery.
It does not find, read, or move your preferences or reports. Keep the migration
receipt printed by the command. An archived relative link retains its original
text and must be restored to its original location to resolve the same way.

After migration, run setup with the preferences directory you used before:

```sh
python3 ~/.agents/skills/day-recap/scripts/cli.py --data-dir /path/to/your/data setup
```

Replace the example path with your own. Setup reads that chosen preferences file
to prefill existing choices. Review the selected sources, exclusions, and report
folder before saving. Older preferences need explicit source consent before
collection can run. Refresh skill discovery or restart the desktop app afterward.

If update or uninstall refuses a folder containing extra data, leave it in place.
Choose external storage and relocate your data deliberately before retrying;
these commands do not move it for you.

### Uninstall

To remove the active skill:

```sh
python3 manage_skill.py uninstall ~/.agents/skills/day-recap
```

Uninstall archives the skill rather than deleting it. It preserves preferences,
reports, and backups. Any separately enabled native automation must also be
paused through the desktop's automation tools. Report deletion is a separate
explicit decision.

## Privacy and limits

Selected conversation text goes to the current desktop agent. Local collection
and storage do not imply offline model processing. Reports and metadata can
contain personal topics, titles, chat IDs, and paths. Redaction is limited, not a
guarantee that all sensitive text is removed. Review reports before sharing.
No credentials or personal settings belong in the bundle.

Raw extraction stays in private task-owned temporary directories. A successful
commit cleans its own directory; interruption can leave owned evidence available
for recovery. Unverified attempt directories are listed with a warning and preserved for
inspection; automatic cleanup is refused.
ChatGPT active enumeration is bounded, and some replies or attachment contents
may be unavailable. Coverage describes those gaps. A recap does not represent
activity outside the selected, accessible conversations.

Scheduling is **experimental**. A saved time alone activates nothing. Accept a
manual sample and verify runtime access before enabling a native heartbeat.
Live scheduled generation and delivery, recovery after actual sleep, and
closed/reopened app behavior remain unverified. Scheduled execution requires an
awake, online, signed-in computer and an available desktop runtime with its
history tools. No unlimited or zero-cost model usage is promised. No automatic
computer suspension is part of setup or testing.

## Verify the source

```sh
python3 -m unittest discover -s tests -q
python3 build_bundle.py
python3 release_check.py
```

The suite covers synthetic readers, scope enforcement, setup navigation and
cancellation, real pseudo-terminal keyboard controls, promotion interruption
boundaries, delivery retry, and an isolated Linux install/setup/synthetic
sample/refresh/update/uninstall workflow. The Linux CI job runs the suite on
Python 3.11 and 3.13 when pushed. Local tests do not prove live desktop generation,
report usefulness, real sleep recovery, or tester acceptance.
