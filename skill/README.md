# Install Daily Recap 0.1.0

Linux, Python 3.11+, and a supported Codex desktop chat are required. Runtime
code uses the Python standard library. macOS is unverified. Windows is unsupported.
The MIT license is included in this folder.

Copy this generated folder to `~/.agents/skills/day-recap` without overwriting
an existing skill. Keep preferences and reports outside the skill folder so updates
preserve them. The source repository links to a setup guide with install, update, migration,
and uninstall commands. Refresh skill discovery or restart the desktop if needed.

Run the terminal wizard:

```sh
python3 ~/.agents/skills/day-recap/scripts/cli.py setup
```

Setup starts with sources unchecked. Use arrows, Space, Enter, Backspace, and
Escape. Use `setup --numbered` for a numbered-input terminal. Paths are text fields;
enter `b` to go back or `q` to cancel. Use `-` to clear optional exclusions.
Save only after reviewing scope, storage, model policy, and data handling.
The default preferences directory is `~/.local/share/day-recap`. Specify
`--data-dir DIRECTORY` before `setup` or any other command to use another location.

Then request `$day-recap yesterday` in the supported desktop chat, naming your
preferences directory. The current agent writes the report using the selected
host model. Python prepares evidence and saves files; it makes no model API calls.
A requested different model remains pending until verified in the same desktop
host. Selected ChatGPT access needs the required desktop history tools.

Reports can contain private information. Selected text goes to the desktop model.
Local storage does not imply offline processing. Redaction is limited. ChatGPT
coverage and unavailable replies remain visible. Do not share raw histories with
testers or put preferences and reports in a public repository.

Scheduling is experimental. Accept a manual sample first. A saved time does not
activate automation. Live scheduled delivery, sleep recovery, and closed/reopened
app behavior remain unverified. Scheduled execution depends on an awake, online,
signed-in computer with the required desktop tools available.

The daily report uses topic bullets by default; ask for a different format if you
prefer. Keep preferences and reports outside the skill directory. Setup rejects
storage nested inside the skill.

For an old symlink installation, run the migration helper from the source
checkout after building and checking the bundle:

```sh
python3 manage_skill.py migrate ~/.agents/skills/day-recap
```

The helper is not included in the installed bundle. It archives the old symlink
outside skill discovery and leaves its target untouched. Migration does not read
or move preferences or reports. Then re-run setup with your previous preferences
directory explicitly selected through `--data-dir`. Setup reads that file to
prefill choices; review source consent and report storage before saving.

See `SKILL.md` for daily, refresh, weekly, temporary-file recovery, and delivery
instructions. No personal preferences, histories, or reports are included.
