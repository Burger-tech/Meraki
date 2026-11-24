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

\- Delegate most implementation, compilation, testing, and research to up to four concurrent DeepSeek workers through T3 Code. Use DeepInfra with `deepseek-ai/DeepSeek-V4.1-Flash-1017`.

\- When the lead is a ChatGPT model, it coordinates only and must delegate all project work to DeepSeek workers, including architecture, debugging, implementation, builds, testing, review, and integration. Assign distinct ownership and use isolated Git worktrees when edits overlap.

\- Maintain PROGRESS.md within C:\\Meraki.

- Use `python` explicitly for Python commands in Windows shells and in delegated worker briefs.
- Include the menu controls in every live-test brief. Enter activates the focused button, and W/A/S/D move selection like Tab. Verify the game has keyboard focus before sending input.
- Use hardware rendering for live tests by default. Use WARP for software-specific diagnostics.
- On each worker completion, review the evidence, record the result in PROGRESS.md, and start the next useful implementation or verification task. A ready visual-test candidate gets the next free desktop slot. Keep one live game instance and use offline work when there is no meaningful live retry.
- Notify the user of major verified milestones and blockers through ntfy. Use PowerShell to POST a short message to `https://ntfy.sh/$env:NTFY_TOPIC` with title `Meraki` and priority `4`. Keep the topic value out of tracked files and logs.

