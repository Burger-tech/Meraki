# Meraki

Meraki launches a locally installed Xbox Series title on Windows 11 using a pinned VIctory runtime. The launcher detects the executable from MicrosoftGame.Config and uses Leonida's RPF9 format findings to check common.rpf, levels.rpf and audio.rpf.

## Progress tracker

**Current milestone:** Reach the first mission and verify player-controlled camera and character movement. In the latest visible WARP run, the account picker averaged **14.86 FPS** and first-run setup averaged **10.28 FPS**. The run ended at Navigation Experience and the game closed.

| Milestone | Status | Evidence or completion criteria |
| --- | --- | --- |
| Windows launcher and runtime builds | Verified | Diagnostic and release builds pass. The launcher detects the package, checks imports and launches with WARP. |
| Title startup and menu input | Verified | The title rendered the opening and reached first-run setup. Focused keyboard input advanced the account picker. |
| First-mission gameplay | Pending | Complete onboarding, reach a rendered mission and verify camera rotation and movement against a fixed landmark. |
| Frame-pacing measurement | In review | Calculate FPS and frame times from logged host presentation events. Validate on a live trace. |
| XCL, VIctory and Leonida comparison | In progress | Identify a compatibility change and compare it on the same package and scene. |
| Sustained 60 FPS on hardware | Unverified | Measure player-controlled gameplay on hardware with a 16.67 ms frame budget. Record resolution, run length and frame times. |

[Detailed progress and test criteria](PROGRESS.md)

## Build and launch

Meraki uses [VIctory](https://github.com/Marvisak/VIctory) as its runnable Windows baseline. Compatibility work also compares [XCL](https://github.com/ivall/xcl) for Direct3D 12 and shader translation behavior, and [Leonida](https://github.com/ItsNotRexed/Leonida) for package analysis and its independent graphics implementation. Compare changes against the same package and test scene before integrating them.

Use Windows x64, Visual Studio C++ Build Tools with the Windows SDK, Rustup on PATH and Python 3 with Tk. From the Meraki checkout, run these commands in PowerShell.

```powershell
git submodule update --init
powershell -NoProfile -ExecutionPolicy Bypass -File .\Build.ps1
python Meraki.pyw
```

The build installs the pinned Rust toolchain under .local and produces baseline/target/diag/victory.exe. To build the release executable as well, pass `-Profile both`.

The launcher searches D:\ and its immediate subfolders for the package manifest. Use **Browse** to select a title elsewhere. **Inspect** checks the archive headers and shows executable information. **Check imports** prepares the executable and lists resolved and missing imports for each module without starting the title. **Launch with WARP** runs the diagnostic build on Microsoft's CPU-based Direct3D adapter. This can be slow. Upstream reports that world rendering on a hardware GPU can reset the display driver.

With the game window focused and no controller connected, Enter acts as A, Backspace as B, the arrow keys as the D-pad and WASD as the left stick. **Stop** ends the running process. **Open full log** opens the selected session's output. Session logs, caches and saves live under .local.

## Diagnose a dark scene

Select **Save diagnostic frames on launch**, then **Launch with WARP**. Each captured run gets a folder beside its log under `.local/logs`. The folder and log share the same session name. VIctory saves presented frames 1, 2, 4, 8 and subsequent powers of two.

To investigate a transition, find the last visible scene and first dark scene in that sequence. Look up the corresponding `frame presented` lines in the session log. Each line counts draws and dispatches since the previous logged frame. The separate `victory_gpu::host` lines periodically sample FPS, draws per frame and draws dropped for lack of a pipeline. A displayed zero is rounded. Capture timing and software-rendering performance can differ from a normal run.

Run `python tools/render_log.py .local/smoke/boot.log` to summarize a capture log. Substitute the path to your session log for another run.
