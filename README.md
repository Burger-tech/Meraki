# Meraki

Meraki is a Windows launcher and diagnostics harness for a locally installed Xbox Series X|S title. It uses the pinned [VIctory](https://github.com/Marvisak/VIctory) runtime, detects the title from `MicrosoftGame.Config`, checks `common.rpf`, `levels.rpf` and `audio.rpf`, and launches the diagnostic build on Microsoft's WARP software adapter.

Meraki contains no game data. The current build is not playable through the first mission. Menus and onboarding work, but recent WARP mission attempts reached the mission loading card, then went black and lost the D3D12 device. Mission rendering, player control and mission FPS are unverified.

## Availability and access

As of 2026-11-24, the Meraki repository is **private** and has **no GitHub Releases or tags**. There are no downloadable binaries. You need access to `https://github.com/Burger-tech/Meraki` and must build from source.

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

## Prerequisites

- Windows 11 x64. The tested host is Windows 11 25H2 (build 26200); the pinned runtime declares Windows 10/11 x64.
- Git for Windows.
- Python 3 with Tcl/Tk. Tested with Python 3.13.14 and Tk 8.6. Use `python` in Windows commands.
- Rustup on `PATH`. `Build.ps1` installs the pinned Rust 1.98.1 MSVC toolchain under `.local`, but it does not install Rustup itself.
- Visual Studio 2022 C++ Build Tools and the Windows SDK (x64). The MSVC linker is required by the Rust target.
- D3D12 with WARP available. The runtime's world gate requires shader model 6.6 and mesh shaders; WARP passed that capability check on the tested host. Hardware world entry is unverified.
- Several GiB of available Windows commit for the title. If the runtime reports Windows error 1455, close other applications or increase the paging file.

## Build

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Build.ps1
```

The default build is the diagnostics profile and writes `baseline\target\diag\victory.exe`. This is the runtime used by **Launch with WARP**.

Other profiles:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Build.ps1 -Profile release
powershell -NoProfile -ExecutionPolicy Bypass -File .\Build.ps1 -Profile both
```

The release executable is `baseline\target\release\victory.exe`. A release-only build cannot be launched with WARP from the launcher; build the diagnostics profile for that action.

The launcher and tools need no third-party Python packages. Run the regression suite without game data:

```powershell
python -B -m unittest discover -s tests -v
```

The current suite has 113 tests, including tests that construct the Tk launcher in withdrawn windows.

## Local title requirements

Meraki does not include, download or link to game data. Supply a legally obtained Xbox Series X|S title package that is already on local disk.

The package folder must contain:

- `MicrosoftGame.Config`.
- The executable named under `ExecutableList/Executable` in that manifest.
- `common.rpf`, `levels.rpf` and `audio.rpf` beside the executable.

The launcher auto-detects `D:\MicrosoftGame.Config` and one level below `D:\`. Use **Browse** for any other path. **Inspect** checks the RPF9 header of each archive; it does not validate archive contents or game integrity.

The first-run legal terms and onboarding belong to the title. Complete them yourself; Meraki does not accept terms or automate consent.

The supported setup path is the WARP diagnostic. Upstream reports that entering the world on a hardware GPU can hang the display and trigger a Windows display-driver reset.

## Launch

From `C:\Meraki`:

```powershell
python Meraki.pyw
```

Select the title executable, then use:

- **Inspect** to read the package and archive headers.
- **Check imports** to prepare the executable and list host, HLE and missing imports without starting the title.
- **Launch with WARP** to run `baseline\target\diag\victory.exe run <exe> --execute` on the software adapter.
- **Capture frames and timing on launch** to save diagnostic frames and per-present log lines. Capture is off by default.
- **Stop** to request the title window's normal close, then force termination after five seconds.

Session logs and captures are under `.local\logs`; cache and data are under `.local\cache` and `.local\data`. These paths are git-ignored.

Meraki's launcher always uses WARP for launching. It is a diagnostic path, not evidence of hardware performance.

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

**Current milestone:** Reach the first mission and verify player-controlled camera and character movement. On the RX 7800 XT, VIctory `ffe310e` averaged **28.94 presents per second** in the first minute of startup and menus. The run reached the opening credits, then lost the D3D12 device. Mission geometry, player control, and 30 FPS gameplay remain unverified.

| Milestone | Status | Evidence or completion criteria |
| --- | --- | --- |
| Windows launcher and runtime builds | Verified | Diagnostic and release builds pass. The launcher detects the package, checks imports and launches with WARP. |
| Title startup and menu input | Verified | The title rendered the opening and reached first-run setup. Focused keyboard input advanced the account picker. |
| First-mission gameplay | Pending | Complete onboarding, reach a rendered mission and verify camera rotation and movement against a fixed landmark. |
| Frame-pacing measurement | Tool verified | Menu-only present-call pacing works. Live gameplay trace pending. |
| XCL, VIctory and Leonida comparison | Research complete | First controlled experiment compares cold and warm shader and pipeline caches on the same package and scene. See [upstream comparison](docs/upstream-comparison.md). |
| Hardware graphics capability | Verified | The RX 7800 XT and WARP pass the shader model 6.6 and mesh shader capability check. This is not a world-rendering result. See [hardware test plan](docs/hardware-gameplay-test.md). |
| Sustained 60 FPS on hardware | Unverified | Measure player-controlled gameplay on hardware with a 16.67 ms frame budget. Record resolution, run length and frame times. |

[Detailed progress and test criteria](PROGRESS.md)

## Troubleshooting

| Problem | Action |
| --- | --- |
| `git clone` returns 404 or authentication fails | The repository is private. Request access and configure Git credentials for GitHub. |
| Build says `Run git submodule update --init first.` | Run `git submodule update --init --recursive` from `C:\Meraki`. |
| `rustup` is not recognized | Install Rustup, reopen PowerShell, and confirm `%USERPROFILE%\.cargo\bin` is on `PATH`. |
| Build fails looking for `link.exe`, MSVC or the Windows SDK | Install Visual Studio 2022 C++ Build Tools and the Windows SDK (x64), then reopen PowerShell. |
| Launcher says `Runtime not built` | Run `.\Build.ps1` and confirm `baseline\target\diag\victory.exe` exists. |
| Launcher says `Release build only` | Rebuild with the default diagnostics profile. A release-only build cannot launch with WARP. |
| No package is detected or the executable is wrong | Use a package under `D:\` or one folder below it, or select the executable with **Browse**. It must be the manifest's executable. |
| An RPF badge is missing or unrecognized | Put `common.rpf`, `levels.rpf` and `audio.rpf` beside the executable. The badge checks only the RPF9 header. |
| `python Meraki.pyw` fails with `No module named tkinter` | Repair or reinstall Python with Tcl/Tk support. |
| Windows error 1455 or out-of-commit errors | Close other applications or increase the Windows paging file, then retry. |
| A mission entry is black or the D3D12 device is removed | This is the current compatibility blocker, not a setup failure. Stop the run, keep the session log and capture, and do not use that run as an FPS result. |
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
