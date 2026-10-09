<h1 align="center">Daily Recap</h1>

<p align="center">
  Turn your AI conversations into a daily record of what you worked on, what changed, and what still needs attention.
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#a-day-at-a-glance">Example</a> ·
  <a href="SETUP.md">Setup guide</a> ·
  <a href="#privacy">Privacy</a>
</p>

<p align="center">Linux · Python 3.11+ · Codex desktop · MIT</p>

---

## Quick start

> Version 0.1.0 is a Linux manual-use beta. Start with one daily report. Scheduling is experimental.

Clone the project and install the skill:

```sh
git clone https://github.com/snikmas/day-recap.git
cd day-recap
python3 build_bundle.py
python3 release_check.py
python3 manage_skill.py install ~/.agents/skills/day-recap
```

Choose your apps, work folders, report storage, and writing model:

```sh
python3 ~/.agents/skills/day-recap/scripts/cli.py setup
```

In a supported Codex desktop chat, ask:

```text
$day-recap yesterday
```

The agent saves a Markdown report and shows the same text in chat. If the skill
is missing, refresh skill discovery or restart the desktop app.

Already installed? Follow the [update instructions](SETUP.md#update-or-uninstall).
For custom storage, exclusions, and terminal controls, see the [setup guide](SETUP.md).

## What it does

- **Daily recaps.** Group related conversations into activities, outcomes, and unfinished work.
- **Weekly reviews.** Connect saved daily reports and show which days are missing or incomplete.
- **Useful observations.** Point out supported learning or workflow difficulties, including agent and tool problems. Goals are optional.
- **Scope you choose.** Select apps and folders. ChatGPT requires a separate opt-in and supports excluded chat IDs.
- **Refresh with review.** Preview a new version before replacing a report. Keep the previous text in a backup.
- **Recoverable delivery.** Reuse a saved report after interruption and show it when delivery is still pending.

Python collects and prepares the evidence. Your current Codex desktop agent
writes the recap using its selected model. The Python code makes no model API
calls and requires no additional packages.

## A day at a glance

This is a fictional example:

> **October 8 · UTC**
>
> You fixed empty-row handling in an import parser and discussed duplicate records.
>
> **What you worked on**
> - The empty-row fix passed the recorded checks. The larger-file test is still unfinished. (codex)
> - You asked how duplicates should be handled. The assistant reply was unavailable, so the decision could not be confirmed. (chatgpt)
>
> **Problems and useful checks**
> - Test a larger file before calling the parser complete. Confirm the duplicate rule before implementing it. (codex, chatgpt)

Read the [full synthetic example](examples/daily-report.md). Report length follows
the day's activity, and you can ask for a different format.

## Conversation sources

| Source | Collection |
| --- | --- |
| Codex, Claude Code, Kimi Code, OpenCode, Hermes | Local history readers, filtered by selected work folders |
| ChatGPT | Desktop history tools, with separate opt-in and chat exclusions |
| Cursor | Metadata only; conversation text is unavailable |

ChatGPT needs `list_threads`, `read_thread`, and `list_archived_threads` in the
same desktop chat that runs the recap. Some histories or replies may be missing.
The report describes these gaps; it cannot account for activity outside the
selected conversations.

## Privacy

Selected conversation text goes to the current desktop agent. Local storage does
not mean offline model processing. Reports can contain personal information,
and redaction does not catch every sensitive detail.

Raw extracts use private temporary folders. Successful saving cleans the report's
own extraction folder. Interrupted attempts remain available for explicit recovery
or cleanup. Keep reports and preferences outside the installed skill and out of Git.

Review reports before sharing. See the [privacy and recovery details](SETUP.md#privacy-and-limits).

## Current limits

Linux is the initial supported platform. macOS is unverified; Windows is unsupported.
Scheduled generation, delivery after sleep, and app-reopen recovery have not been
verified end to end. Independent beta-user installation and usefulness are also
still unverified.

## Development

Run the local checks:

```sh
python3 -m unittest discover -s tests -q
python3 build_bundle.py
python3 release_check.py
```

Bug reports and small fixes are welcome. Use synthetic examples when reporting
an issue; do not attach personal histories, reports, or credentials.

## License

[MIT](LICENSE).
