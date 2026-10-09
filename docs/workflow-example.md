# Setup and daily-use example

This is a synthetic walkthrough. The guided setup below is the **target after
TODO 2 and 3**, not a transcript or a claim that those choices already work.
Today, setup supports work roots, exclusions, storage, and timezone; the skill
requires a fixed model and does not offer per-app selection.

## First setup

**User:** `$day-recap setup`

**Assistant:** I found Codex and OpenCode history locations. ChatGPT history
tools are available in this chat. I have not read message bodies. Which sources
should the recap include?

**User:** Codex and ChatGPT. Leave OpenCode out.

**Assistant:** Which project folders should I include for Codex? ChatGPT can
include the accessible chats across all topics; you can exclude individual chats.

**User:** Use `~/projects`. Exclude `~/projects/private-client`. Leave out my
ChatGPT chat called "Personal journal".

**Assistant:** I will exclude that chat, the private-client folder, and this
recap workspace. Where should reports go? A separate `~/daily-recaps` folder
would keep them outside your projects.

**User:** Use that folder.

**Assistant:** Use this chat's current model for writing, or choose another
model available in this same app? Using the current model needs no extra API key.

**User:** Use the current model.

**Assistant:** Your timezone was detected from the computer. Selected conversation
text will be processed by this chat's model. Reports stay in your chosen folder
and may contain personal information. ChatGPT access can be incomplete. Shall I
generate yesterday's sample with these choices?

**User:** Yes.

If the user asks for a different model, show only options supplied by a supported
runtime capability. If no list is available, ask them to choose in the host app
and verify the execution context afterward. Do not invent options from installed
apps, read credential files, or promise arbitrary provider support.

## What happens during the sample

1. Check for an existing completed report before collecting histories.
2. Read only selected, eligible sources and collect accessible ChatGPT pages.
3. Select the local day, apply exclusions, remove duplicates, and split evidence.
4. Review every segment and write a draft grounded in the messages.
5. Save the report and compact source metadata, then show the saved report.
6. Checkpoint delivery and remove task-owned temporary extraction files.

**Assistant:** Yesterday's report is saved. Codex coverage was readable. Some
ChatGPT replies were unavailable, so that part is incomplete. Does this length
and level of detail work for you?

**User:** Make it shorter next time.

**Assistant:** I will use a shorter recap. Keep reports manual, or choose a
daily time? Scheduling remains experimental until this installation passes
the runtime and recovery checks.

**User:** Manual for now.

Length preferences can remain in the existing recap chat for v1. Persistent
style presets across new chats are outside the required setup changes.

## A short fictional report

> October 8, 2026. You moved the import parser closer to completion and clarified
> how duplicate records should behave. The larger-file check remains unfinished.
>
> Coverage: selected Codex conversations were readable. Some ChatGPT assistant
> replies were unavailable, so those discussions may be incomplete.
>
> **What you worked on**
>
> You fixed the parser's handling of empty rows. The recorded boundary checks
> passed after the fix. A larger-file test was planned but has no recorded
> result. (codex)
>
> You asked how duplicate records should be handled. The available discussion
> establishes the question, but the missing assistant reply prevents a reliable
> account of the proposed solution. (chatgpt)
>
> **Good**
>
> - The parser fix has a recorded test result. (codex)
>
> **Needs work**
>
> - Run the larger-file check before calling the parser complete. (codex)
> - Confirm the duplicate-record rule before implementing it. (chatgpt)

Real reports should scale with the amount of supported activity. This example
is deliberately short and contains no personal history.

## Later use

**User:** `$day-recap yesterday`

The agent generates yesterday's report or shows the existing report requested
by the user. A scheduled check stays quiet for an already delivered report.
A saved report with pending delivery is displayed without regenerating it.

**User:** `$day-recap refresh yesterday`

The agent prepares a candidate and preserves the current report. After the
user asks to accept it, promotion keeps a backup. Repeating this cycle is the
behavior required by TODO 1; the current implementation blocks a second refresh.

**User:** `$day-recap review the previous completed week`

The agent uses saved daily reports and names missing dates. With no daily
evidence, it explains why it cannot write a factual weekly review.

**User:** `Change setup: also include OpenCode.`

After TODO 2, the agent updates the selected source list for future collections.
Existing reports remain unchanged unless the user requests a refresh.
