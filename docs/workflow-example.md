# Setup and daily-use example

**Design preview, not implemented.** These screens show the planned terminal
wizard. Today, the CLI requires explicit setup flags, the skill requires a fixed
model, and per-app selection is unavailable. All paths and selections below are
illustrative. No personal histories are included.

## Interaction references

[Hermes setup](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/setup.py)
uses single-select menus, checklists, defaults, and back/cancel navigation.
[Matt Pocock's setup skill](https://github.com/mattpocock/skills/blob/main/skills/engineering/setup-matt-pocock-skills/SKILL.md)
is prompt-driven: it inspects existing state, recommends answers, and skips
irrelevant questions. Its skills installer also offers selection of skills and
agents. Daily Recap adopts terminal controls and short, conditional steps.

## Start setup

The planned entry point is:

```sh
python3 cli.py setup
```

A small wizard appears in the terminal. Existing settings are prefilled on rerun.
Use arrows to move, Space to toggle, and Enter to continue. Back revisits a step;
Escape or Ctrl+C cancels without saving. A numbered-input fallback provides the
same choices when interactive controls are unavailable.

## 1. Choose conversation sources

The wizard checks known history locations without reading message bodies.
Sources begin unchecked on first setup. This example shows the user's choices
just before continuing:

```text
Daily Recap setup                              1 / 5

Include conversations from:

  [x] Codex              History location found
  [ ] OpenCode           History location found
  [x] ChatGPT            Access checked later in desktop
  [-] Cursor             Message bodies unavailable

  Other supported sources: not detected

Space toggle   Enter continue   Esc cancel
```

The checked ChatGPT option is a request to include it, not proof of access.
Do not scan for more providers or read their configuration files. Keep the
existing reader set for v1.

## 2. Choose folders

```text
Project folders to include                     2 / 5

  ~/projects

Excluded folders:
  ~/projects/private-client

  [+ Add folder]  [+ Add exclusion]

The recap workspace and report storage are excluded automatically.

[Back]  [Continue]
```

Only show coding-folder selection if a local coding source was selected.
ChatGPT exclusions are separate from folder filters. Offer an optional chat-ID
field, or a selectable chat list when the desktop host actually provides one.
Do not pretend the standalone terminal can enumerate desktop conversations.

## 3. Choose report storage

```text
Save reports                                  3 / 5

Folder:    ~/daily-recaps
Timezone:  Detected from this computer    [Change]

[Back]  [Continue]
```

Validate paths and report directory access. Do not ask about timezone unless
it cannot be detected or the user selects Change. Show the actual detected
zone in the real wizard; the text above is an illustrative label.

## 4. Choose the writing model

```text
Writing model                                 4 / 5

> Use the model selected in Codex desktop  (recommended)
  Choose a specific model in Codex desktop

Runtime/model availability: check in desktop before the sample.
No additional API key is needed for the existing runtime.

[Back]  [Continue]
```

When a supported host integration returns an available model list, the second
option opens a searchable selection menu populated from that list. Otherwise
it records a pending choice and gives a short instruction to choose in the host.
It must not invent model names or treat installed apps as working providers.
Actual model and history-tool availability must be checked before generation.

Arbitrary API providers and local model endpoints remain outside v1. The model
choice does not change which apps supply conversation histories.

## 5. Review and save

```text
Review setup                                  5 / 5

Sources       Codex, ChatGPT (desktop check pending)
Work folders  ~/projects
Excluded      ~/projects/private-client + recap workspace/storage
Reports       ~/daily-recaps
Model         Use the selection in Codex desktop
Schedule      Manual

Selected conversation text will be processed by the desktop model.
Reports can contain private information. ChatGPT coverage may be incomplete.

[Back]  [Save setup]  [Cancel]
```

Save one private preferences file only when Save setup is selected. Do not
start history collection, a model call, or a schedule merely by saving setup.
After a successful save:

```text
Setup saved.

Next: open your Codex desktop recap chat and run:
  $day-recap yesterday

Before writing, the skill will verify the requested model and history access.
To change these settings later: python3 cli.py setup
```

The terminal prepares settings. Report generation still runs through the
supported desktop agent. This handoff keeps the existing runtime without adding
a separate summarization client or falsely promising a standalone terminal app.

## Generate the sample

The user requests `$day-recap yesterday` in the desktop chat. The agent checks
runtime access and explains unresolved choices before reading selected histories.
It then collects evidence, applies date and scope filters, reviews each segment,
writes and saves a report, displays it, records delivery, and cleans temporary
extraction files. An existing completed report is reused.

After sample acceptance, scheduling can be offered as a separate explicit step.
A selected time alone never activates automation. Keep manual use available
while scheduled execution and recovery remain experimental.

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

- Daily report: `$day-recap yesterday` in the desktop agent.
- Refresh: `$day-recap refresh yesterday`, then explicitly accept the candidate.
  The current second-refresh defect remains tracked in TODO 1.
- Weekly review: `$day-recap review the previous completed week`. Missing daily
  reports remain visible; no evidence means no factual review.
- Settings: rerun the terminal wizard and change the saved selections. Existing
  reports stay unchanged unless the user requests a refresh.

Scheduled runs reuse saved reports, retry pending delivery, and stay quiet for
already delivered reports. TODO 4 makes this rule consistent across instructions.

The wizard changes setup interaction only. It adds no dashboard, accounts,
provider credentials, or new conversation integrations.
