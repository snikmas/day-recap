# Public-beta TODO

These tasks describe work still to do. Publishing the current source does not
mean that these fixes or the proposed setup already exist.

## Scope and order

Keep v1 a small desktop skill with standard-library Python. Retain the current
conversation sources. Do not add more providers, a backend, accounts, a database,
or a settings dashboard for this release.

History sources and the writing model are separate choices: a user can read
OpenCode conversations while the current Codex agent writes the recap.

Implement 1 and 4 first, then 2 and 3 together with setup. Complete 5 and 6
before inviting the testers in 7. Scheduling can stay experimental while the
manual workflow is tested.

## 1. Allow repeated refreshes

- [ ] After successful promotion, archive or remove only that consumed candidate
  and its metadata. Preserve the previous canonical report backup.
- [ ] Make interrupted promotion recoverable before clearing a candidate.
- [ ] Test two complete refresh/promotion cycles, edited originals, and failure
  between report saving and candidate cleanup.

Done when a user can revise the same date repeatedly without manually deleting
files, losing edits, or losing the previous report backup.

## 2. Let users choose what is collected

- [ ] Discover known history locations without reading message bodies, credentials,
  environment files, or provider configuration values.
- [ ] Ask users to select detected apps before the first collection. Record
  inaccessible or metadata-only sources honestly. Do not add new readers for v1.
- [ ] Ask for coding work roots and exclusions; exclude recap storage and the
  recap chat workspace automatically.
- [ ] Offer ChatGPT as a separate opt-in with a concise scope notice. Support
  excluding specific chats without requiring a complex rule language.
- [ ] Before the first sample, explain that selected text goes to the current
  agent, reports can contain personal information, and redaction is limited.
- [ ] Add cleanup for task-owned temporary files after success and a safe recovery
  path for interrupted runs. Never sweep unrelated temporary directories.
- [ ] Test that disabled apps and excluded chats contribute no message bodies.

Done when the user can see and change collection scope through the setup wizard,
without editing JSON or sharing histories with an unselected runtime.

## 3. Choose a runtime model and record what actually ran

- [ ] Default to the model and reasoning setting already selected in the current
  supported desktop chat. Remove the fixed model requirement from the skill.
- [ ] If the runtime offers a supported model-listing capability, show its reported
  options. Installed apps or cached model names do not establish availability.
- [ ] Let the user choose another model available in that same host. If the agent
  cannot switch it safely, explain how the user changes it and resume afterward.
- [ ] Check that the execution context still has the required history tools.
  A model being callable through a separate CLI is insufficient.
- [ ] Store only a small model preference. Record requested and observed runtime
  details separately in each report. Use `unknown` when execution is unverifiable.
- [ ] Leave an unavailable requested model pending; never silently substitute.
- [ ] Test inherited selection, unavailable selection, missing runtime evidence,
  and a scheduled run that has different settings from the manual chat.

Done when users can choose among supported host models and saved metadata does
not claim unverified execution details.

Arbitrary provider/model API entry and local-model execution are deferred. They
would require a new execution adapter, credential handling, and separate history
tool access. Do not scan the computer for keys or add a provider-config matrix.

## 4. Make delivery recovery consistent

- [ ] Align skill instructions and runtime handling: reuse a saved report, display
  it if delivery is pending, and stay quiet if already delivered.
- [ ] Keep refresh candidates separate from ordinary scheduled delivery.
- [ ] Mark delivery only after confirmed display; document the possible duplicate
  if execution stops after display and before checkpointing.
- [ ] Test saving without display, retrying pending delivery, and rerunning after
  successful delivery. Keep one start notice for each report attempt sequence.

Done when retries do not regenerate saved reports or silently abandon pending
delivery. Exactly-once delivery is not a v1 promise.

## 5. Make the release understandable and safe to copy

- [x] Publish only selected source files, synthetic tests, and portable documentation.
- [x] Provide one root README and keep the older implementation out of this repo.
- [x] Add a clearly labelled target setup example and a synthetic report example.
- [ ] Choose a license and initial release version explicitly.
- [ ] Verify installation, setup, update, and uninstall instructions in a clean
  environment. Uninstall must preserve reports unless the user requests deletion.
- [ ] Update docs and the installable bundle as tasks land. Keep current behavior
  separate from planned behavior.
- [ ] Add a lightweight release check that allows only intended bundle files and
  fails if personal settings, reports, absolute author paths, or credentials enter it.
- [ ] Add a small Linux test job using the existing unittest suite.

Done when a new user can identify requirements, install one version, generate a
sample, and find known limitations without the author's machine or private data.

## 6. State platform and automation limits accurately

- [ ] Verify the clean-install workflow on Linux and declare it the initial platform.
- [ ] Return a readable unsupported-platform error where file locking or path
  discovery is unavailable. Do not claim Windows support with `fcntl` unchanged.
- [ ] Keep macOS unverified until a real installation and sample succeed.
- [ ] Check Python, timezone handling, required desktop tools, and writable report
  storage during setup. Offer a timezone override only if detection fails or the
  user requests one.
- [ ] Before marking automation supported, verify a fresh scheduled report and
  delivery, recovery after actual sleep, and app-closed/reopened behavior.
- [ ] Document awake, online, signed-in, and desktop availability requirements.
  Do not suspend a user's computer without permission.

Done when supported platforms and automation claims match observed behavior.
Manual-only beta release remains possible before automation validation completes.

## 7. Run a small manual-first beta

- [ ] Invite three to five consenting users after the release blockers above.
  Each user keeps their own histories and reports on their own installation.
- [ ] Observe installation, scope selection, one daily report, and one refresh.
- [ ] Ask whether important activity is missing, any claims are wrong, and the
  length and tone are useful. Collect feedback without requesting raw histories.
- [ ] Review a completed week after sufficient daily use. Keep missing days visible.
- [ ] Fix repeated problems before expanding distribution or adding sources.

Done when testers can complete the manual workflow without the author operating
their machine, understand its limits, and find the recap worth using again.

## Keep setup small

Build an interactive terminal wizard, invoked with `python3 cli.py setup`.
Use one screen per decision, arrow-key selection, Space for checkboxes, Enter
to continue, Back to revisit choices, and Escape or Ctrl+C to cancel. Keep a
numbered-input fallback for terminals that cannot render interactive controls.
Paths are short text fields. No free-form setup conversation or settings dashboard.

- [ ] Add interactive setup when no setup flags are supplied. Keep explicit flags
  for repeatable scripted setup; reject missing input in noninteractive sessions.
- [ ] Show detected sources with availability labels; only user-selected sources
  become enabled. Never interpret a default highlight or EOF as consent.
- [ ] Use screens for sources, folders, report storage, model, and final review.
  Show advanced exclusions and timezone overrides only when requested or needed.
- [ ] Prefill saved choices on rerun. Save all changes atomically only after the
  final confirmation; cancellation leaves existing settings and reports untouched.
- [ ] Test menu state, Back, cancellation, invalid paths, and numbered fallback.
- [ ] Keep one private preferences file. Prefer a small standard-library terminal
  implementation; do not add Node or a full TUI framework for setup alone.

A standalone terminal cannot assume access to desktop ChatGPT tools or a model
catalog. Let it save a pending choice, then verify it in the supported desktop
runtime before the sample. If a supported bridge provides actual runtime data,
show it; otherwise say "Check in desktop" rather than inventing detected access.
Desktop-only chat exclusions can use a selectable list there when supported,
or an optional ID field. Do not scrape the browser to populate a terminal menu.

The final screen summarizes scope, output folder, model policy, and data handling.
After saving, show the command to request the first sample in the desktop agent.
Offer scheduling only after that sample is accepted and runtime checks pass.
Keep the existing history sources and defer arbitrary provider/API configuration.

Use [the target example](docs/workflow-example.md) as the acceptance walkthrough.
The wizard is planned work; the current CLI still requires setup flags.
