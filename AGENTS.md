\# Workspace Rules



\## Primary workspace

C:\\Meraki



\## Reference workspace

C:\\Leonida

D:\\  ## This drive has the GTA 6 files from an xbox build that you will be getting running on win 11







\## Requirements

\- All development must occur within C:\\Meraki.

\- Treat C:\\Leonida as read-only reference material.

\- Never modify, delete, or build files inside C:\\Leonida.

\- All new source files, scripts, dependencies, build

&#x20; artifacts, caches, and logs must reside in C:\\Meraki.

\- Use C:\\Meraki as the working directory for all builds.

\- Do not introduce runtime dependencies on C:\\Leonida.

\- Meraki must remain independently buildable.

\- All subagents must follow these same restrictions.

\- The lead agent may perform all project work directly, including architecture, debugging, implementation, builds, testing, review, and integration. Delegation is optional.

\- When delegating through T3 Code, use up to six concurrent DeepSeek workers on DeepInfra with `deepseek-ai/DeepSeek-V4.1-Flash-1017`. Assign distinct ownership and use isolated Git worktrees when edits overlap.

\- Maintain PROGRESS.md within C:\\Meraki.

- Use `python` explicitly for Python commands in Windows shells and in delegated worker briefs.
- Include the menu controls in every live-test brief. Enter activates the focused button, and W/A/S/D move selection like Tab. Verify the game has keyboard focus before sending input.
- Use hardware rendering for live tests by default. Use WARP for software-specific diagnostics.
- On each worker completion, review the evidence, record the result in PROGRESS.md, and start the next useful implementation or verification task. A ready visual-test candidate gets the next free desktop slot. Keep one live game instance and use offline work when there is no meaningful live retry.
- Notify the user of major verified milestones and blockers through ntfy with `tools\notify.ps1` (PowerShell, no dependencies). Title is always `Meraki` and priority is `4`; the topic comes only from `$env:NTFY_TOPIC` and must never appear in tracked files, arguments, or logs. Send only for a verified milestone or a real blocker, and check formatting offline first with `-DryRun` (it sends nothing).
- ntfy body: one short plain-language outcome line, a blank line, then up to three short labelled lines for the headline measurement, the blocker, and the next action when relevant. Say whether the context is gameplay, loading, or offline work, mark numbers as measured or estimated, and leave out hashes, paths, and jargon.

