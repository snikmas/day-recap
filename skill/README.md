# Install Daily Recap

Requires Python 3.11+ and Codex desktop history tools. Copy this folder to
`~/.agents/skills/day-recap` without overwriting an existing skill. Codex normally
discovers user skills automatically; refresh skill discovery or restart if needed.

Invoke `$day-recap setup` in the desktop chat. Choose your own work roots and
report storage. Setup saves non-secret preferences, detects the computer
timezone, excludes recap storage and generates a real sample. Keep the recap
chat workspace excluded. No goals file or summarization API key is required.

Reports are written by the current GPT-6.1 Sol High agent. The Python scripts
only prepare evidence and save reports. ChatGPT requires the desktop's history
tools; CLI-only runs cannot establish full coverage. Missing replies and bounded
chat enumeration must remain visible.

Once the manual sample is useful, choose a daily time and configure a native
current-chat heartbeat through Codex's automation tool. Verify live triggered
history access and sleep recovery. Do not silently replace it with a CLI timer.

Detailed workflow, refresh, weekly review and recovery instructions are in
`SKILL.md`. No personal reports or preferences are included in this bundle.
