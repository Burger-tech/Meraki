# Meraki

Meraki is a Windows launcher and diagnostics harness for a locally installed Xbox Series X|S title. It uses the pinned [VIctory](https://github.com/Marvisak/VIctory) runtime (`ffe310e`), detects the title from `MicrosoftGame.Config`, checks `common.rpf`, `levels.rpf` and `audio.rpf`, and launches the diagnostic build on the hardware GPU by default.

Meraki contains no game data. The pinned `ffe310e` build is not playable through the first mission. An isolated fxceless `4e17478` comparison runtime rendered the lit intro world on the RX 7800 XT, but the native hardware world path measured a median **1.8 FPS / 556.1 ms per frame**, and no HUD or confirmed input handoff was reached. Earlier menu runs met the title's 30 FPS request at 33.3 ms median; the latest pause menu was observed at 20 FPS / 49.9 ms. The intro arm had no device removal, but minimum free commit fell to **338 MiB**, so memory headroom remains tight. Host-side performance work is underway.

## Availability and access

As of 2026-11-24, the Meraki repository is **private**. The only downloads are source-only snapshot ZIPs attached to `src-*` releases; there are no binaries and no game data in any package. You need access to `https://github.com/Burger-tech/Meraki` and must build from source.

## Get the source

With GitHub authentication configured, clone Meraki and its VIctory submodule into the documented workspace:

```powershell
git clone --recurse-submodules https://github.com/Burger-tech/Meraki.git C:\Meraki
Set-Location C:\Meraki
```

If `C:\Meraki` already exists, update the submodule instead:

```powershell
Set-Location C:\Meraki
git submodule update --init --recursive
```

`baseline` is the VIctory submodule. `Build.ps1` stops with `Run git submodule update --init first.` when it is missing.

Source snapshots are published as versioned ZIPs on the `src-*` releases. Each ZIP contains Meraki's launcher, tools, tests and documentation plus `BUILDING.md`, `NOTICE.md`, `manifest.json` and `SHA256SUMS.txt`; it never contains the `baseline` submodule, game data, build outputs, captures or logs.

## Prerequisites

- Windows 11 x64. The tested host is Windows 11 25H2 (build 26200); the pinned runtime declares Windows 10/11 x64.
- Git for Windows.
- Python 3 with Tcl/Tk. Tested with Python 3.13.14 and Tk 8.6. Use `python` in Windows commands.
- Rustup on `PATH`. `Build.ps1` installs the pinned Rust 1.98.1 MSVC toolchain under `.local`, but it does not install Rustup itself.
- Visual Studio 2022 C++ Build Tools and the Windows SDK (x64). The MSVC linker is required by the Rust target.
- A Direct3D 12 GPU. The runtime's world gate requires shader model 6.6 and mesh shaders; WARP passed that capability check on the tested host. Hardware world entry is unverified.
- Several GiB of available Windows commit for the title. If the runtime reports Windows error 1455, close other applications or increase the paging file.

## Build

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Build.ps1
```

The default build is the diagnostics profile and writes `baseline\target\diag\victory.exe`. This is the runtime used by **Launch**.

Other profiles:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Build.ps1 -Profile release
powershell -NoProfile -ExecutionPolicy Bypass -File .\Build.ps1 -Profile both
```

The release executable is `baseline\target\release\victory.exe`. The launcher requires the diagnostics profile to launch the title.

The launcher and tools need no third-party Python packages. Run the regression suite without game data:

```powershell
python -B -m unittest discover -s tests -v
```

The current suite has 114 tests, including tests that construct the Tk launcher in withdrawn windows.

## Local title requirements

Meraki does not include, download or link to game data. Supply a legally obtained Xbox Series X|S title package that is already on local disk.

The package folder must contain:

- `MicrosoftGame.Config`.
- The executable named under `ExecutableList/Executable` in that manifest.
- `common.rpf`, `levels.rpf` and `audio.rpf` beside the executable.

The launcher auto-detects `D:\MicrosoftGame.Config` and one level below `D:\`. Use **Browse** for any other path. **Inspect** checks the RPF9 header of each archive; it does not validate archive contents or game integrity.

The first-run legal terms and onboarding belong to the title. Complete them yourself; Meraki does not accept terms or automate consent.

The launcher uses hardware rendering by default. Select **Use WARP** for software-rendering diagnostics. Upstream reports that entering the world on a hardware GPU can hang the display and trigger a Windows display-driver reset.

## Launch

From `C:\Meraki`:

```powershell
python Meraki.pyw
```

Select the title executable, then use:

- **Inspect** to read the package and archive headers.
- **Check imports** to prepare the executable and list host, HLE and missing imports without starting the title.
- **Launch** to start the diagnostics executable on the GPU. **Use WARP** switches that run to the software adapter.
- **Capture frames and timing on launch** to save diagnostic frames and per-present log lines. Capture is off by default.
- **Stop** to request the title window's normal close, then force termination after five seconds.

Session logs and captures are under `.local\logs`; cache and data are under `.local\cache` and `.local\data`. These paths are git-ignored.

### Menu controls

With the game window focused and no controller connected:

| Key | Action |
| --- | --- |
| Enter | A / activate the focused button |
| Backspace | B / back |
| W A S D | Left stick; moves menu selection like Tab |
| Arrow keys | D-pad |
| I J K L | Right stick |
| Q / E | Shoulders |
| Z / C | Triggers |
| F / H | Stick clicks |
| Esc / Tab | Menu / View |

Confirm the game window has keyboard focus before sending input.

## Progress tracker

**Current milestone:** Render the first mission on hardware with responsive camera and character movement at **15-30 FPS**. The isolated `4e17478` fxceless runtime rendered the lit intro world with native pacing and no device removal, but the world view measured a median **1.8 FPS** (556.1 ms/frame); no HUD or confirmed player-controlled camera/movement was reached. Minimum free commit was **338 MiB**. Host-side performance work is underway.

| Milestone | Status | Evidence or completion criteria |
| --- | --- | --- |
| Windows launcher and runtime builds | Verified | Diagnostic and release builds pass, and the 114-test Python suite passes. The launcher detects the package, checks imports and offers GPU and WARP rendering. |
| Title startup and menu input | Verified | Hardware runs rendered the lit opening video, logos and Jason/Lucia loading cards. Earlier menus measured a 33.3 ms median present interval (30.0 FPS); the latest pause menu was observed at 20 FPS / 49.9 ms. Focused keyboard input was accepted. |
| Lit intro world rendering | Verified (visual only) | The isolated `4e17478` runtime rendered Lucia, the prison yard, NPCs and lighting on the RX 7800 XT at a median 1.8 FPS, with zero device removals. No HUD or confirmed input handoff was reached. |
| First-mission gameplay | Pending | The `4e17478` arm reached the lit intro but not a confirmed player-controlled mission segment. Complete onboarding, reach a rendered mission and verify camera rotation and movement against a fixed landmark. |
| Frame-pacing measurement | Tool verified | Menu-only present-call pacing works; the latest world-view cadence comes from the runtime meter. No player-controlled gameplay trace yet. |
| XCL, VIctory and Leonida comparison | Research complete | First controlled experiment compares cold and warm shader and pipeline caches on the same package and scene. See [upstream comparison](docs/upstream-comparison.md). |
| Hardware graphics capability | Verified | The RX 7800 XT and WARP pass the shader model 6.6 and mesh shader capability check. The lit intro world rendered on hardware; this is not a playable-world or FPS pass. See [hardware gameplay test plan](docs/hardware-gameplay-test.md). |
| Timed-capture candidate | Unit-tested; startup smoke | 67 GPU tests pass with one ignored. A startup run saved five timed frames; render-thread overhead is unmeasured. |
| RenderDoc descriptor replay | Tool verified (synthetic) | A 65-check D3D12 probe resolved four per-draw descriptors and matched render-target exports to snapshots. It does not use the title or clear a live descriptor fault. See [RenderDoc descriptor test](docs/renderdoc-descriptor-test.md). |
| Replay-safe descriptor retirement candidate | Unit-tested; live pending | Replay regressions and 59 default / 62 diagnostics `victory-gpu` tests pass with one ignored. No live title run has used this candidate; the `4e17478` intro arm was a different fork build. |
| First mission at 15-30 FPS on hardware | Unverified | The latest world-view median was 1.8 FPS. Measure a player-controlled segment using the title's native pacing, including resolution, run length and frame times. |

### Latest runtime evidence

These results come from isolated comparison candidates, not from the pinned `ffe310e` runtime that `Build.ps1` produces.

**Lit intro world (fxceless `4e17478`, latest).** The isolated `4e17478` diagnostics binary (SHA-256 `305C6F6428D112CAC2A3C6472C1D7CEBA0BDE9906BBFD33BCB0A71309AA599B9`) ran on the RX 7800 XT with native pacing, DRED, default flags and the prior fork cache. After a focused `Enter` on the account picker, the intro rendered lit Lucia and prison-yard geometry, NPCs, windows, sunlight and reflections. World-view meter samples (150; draws > 1,000) had a median **1.8 FPS / 556.1 ms per frame**, p10 1.2 FPS, range 0.6-2.8 FPS and median 5,840 draws per frame. A focused 2 s `W` press was delivered with all 19 focus samples true, but cinematic camera motion prevented a confirmed input handoff; no HUD appeared. There was no device removal, root-signature or host-pipeline refusal, replay warning, panic or out-of-memory marker. Twelve shader translation warnings remain. Peak private memory was 24,623 MiB with a minimum 338.3 MiB free commit. Evidence: `.local/fxceless-refresh-hardware/session-20261124-144046-hw/evidence/REPORT.md`. Host-side performance work is underway.

**Prior hardware mission attempt (fxceless `578d459`).** The `fxceless/victory-gta6` comparison fork produced substantially more complete pre-mission visuals than earlier runs but did not reach a playable mission. On the RX 7800 XT, the opening video, logos and Jason/Lucia loading cards rendered lit and detailed, and menus met the 30 FPS request at a 33.3 ms median interval. Credits then appeared over black, with overlapping rows, and froze; mission entry presented audio-only black frames at about **0.95 FPS**, and the host removed the device (`0x887A0006`) after an eight-list submission. DRED reported a fault address far beyond the view and sampler heap ranges, consistent with an out-of-range descriptor index; it does not identify the triggering instruction. The process exited and the run was not repeated. Evidence: `.local/fxceless-live/session-20261124-113816/REPORT-20261124-live.md`.

**Rapid timed capture (Rust candidate).** The isolated capture candidate copies each timed readback into owned memory and encodes it on a bounded worker queue, so encoding does not run on the render thread. The diagnostics build succeeded, and 67 GPU tests passed with one ignored. A short RX 7800 XT startup run saved five timed frames with a 2.533 s median gap and a 4.300 s maximum gap, then exited with code 0. This is screenshot cadence, not an FPS result: a matched run is still needed to measure render-thread overhead, and frames still queued at process exit can be lost. Evidence: `.local/async-smoke-20261124-125938`.

**Replay-safe descriptor retirement (candidate).** A game-free review showed that a completed submission does not end a command list's recording: a closed list can be executed again without `Reset`. A candidate that disarmed lists after every completed submission could therefore free a descriptor slot that a replay still names. The corrected candidate keeps a recorded list armed until `Reset` or drop, skips retirement after a failed fence wait, and still lets never-recorded idle lists release. Targeted replay regressions pass, as do 59 default and 62 diagnostics `victory-gpu` tests (one ignored), with no clippy warnings from the crate. A diagnostics counter now logs replayed lists. The cost is that a recorded list retains displaced slots until reset; retention is bounded by list lifetime. No live title run has used this candidate, so its hardware effect is pending. Evidence: `.local/retirement-live/REPORT.md`.

[Detailed progress and test criteria](PROGRESS.md)

## Troubleshooting

| Problem | Action |
| --- | --- |
| `git clone` returns 404 or authentication fails | The repository is private. Request access and configure Git credentials for GitHub. |
| Build says `Run git submodule update --init first.` | Run `git submodule update --init --recursive` from `C:\Meraki`. |
| `rustup` is not recognized | Install Rustup, reopen PowerShell, and confirm `%USERPROFILE%\.cargo\bin` is on `PATH`. |
| Build fails looking for `link.exe`, MSVC or the Windows SDK | Install Visual Studio 2022 C++ Build Tools and the Windows SDK (x64), then reopen PowerShell. |
| Launcher says `Runtime not built` | Run `.\Build.ps1` and confirm `baseline\target\diag\victory.exe` exists. |
| Launcher says `Release build only` | Rebuild with the default diagnostics profile. |
| No package is detected or the executable is wrong | Use a package under `D:\` or one folder below it, or select the executable with **Browse**. It must be the manifest's executable. |
| An RPF badge is missing or unrecognized | Put `common.rpf`, `levels.rpf` and `audio.rpf` beside the executable. The badge checks only the RPF9 header. |
| `python Meraki.pyw` fails with `No module named tkinter` | Repair or reinstall Python with Tcl/Tk support. |
| Windows error 1455 or out-of-commit errors | Close other applications or increase the Windows paging file, then retry. |
| A mission entry is black or the D3D12 device is removed | Current compatibility blocker, not a setup failure. The `578d459` run lost the device (`0x887A0006`) at a black mission entry with descriptor addresses past the heap ranges. The newer `4e17478` intro arm rendered lit world geometry at a median 1.8 FPS with no removal, but still showed no HUD or confirmed control. Stop after the first failure, keep the session log and capture, and do not use the frames as a player-controlled FPS result. |
| WARP is slow | Expected for software rendering. The menu/setup FPS numbers are not mission FPS. |

## Diagnostics

The launcher's capture option sets `VICTORY_LOG=info,victory_gpu::frame=debug` and saves presented frames beside the session log. Summarize a session with:

```powershell
python tools\render_log.py .local\logs\<session>.log
python tools\frame_pacing.py .local\logs\<session>.log
```

`frame_pacing.py` measures logged host present-call cadence. It does not establish mission performance unless the log covers a visibly rendered, player-controlled mission.

## References

- [Pinned VIctory runtime](https://github.com/Marvisak/VIctory) (the `baseline` submodule).
- [Detailed progress and test criteria](PROGRESS.md).
- [Upstream comparison](docs/upstream-comparison.md) and [hardware gameplay test plan](docs/hardware-gameplay-test.md).
- [RenderDoc descriptor test](docs/renderdoc-descriptor-test.md) (synthetic D3D12 tooling check).
