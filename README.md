# Meraki

Meraki launches a locally installed Xbox Series title on Windows 11 using a pinned VIctory runtime. The launcher detects the executable from MicrosoftGame.Config and uses Leonida's RPF9 format findings to check common.rpf, levels.rpf and audio.rpf.

## Build and launch

Use Windows x64, Visual Studio C++ Build Tools with the Windows SDK, Rustup on PATH and Python 3 with Tk. From the Meraki checkout, run these commands in PowerShell.

```powershell
git submodule update --init
powershell -NoProfile -ExecutionPolicy Bypass -File .\Build.ps1
python Meraki.pyw
```

The build installs the pinned Rust toolchain under .local and produces baseline/target/diag/victory.exe. To build the release executable as well, pass `-Profile both`.

The launcher searches D:\ and its immediate subfolders for the package manifest. Use **Browse** to select a title elsewhere. **Inspect** checks the archive headers and shows executable information. **Launch with WARP** runs the diagnostic build on Microsoft's CPU-based Direct3D adapter. This can be slow. Upstream reports that world rendering on a hardware GPU can reset the display driver.

With the game window focused and no controller connected, Enter acts as A, Backspace as B, the arrow keys as the D-pad and WASD as the left stick. **Stop** ends the running process. **Open full log** opens the selected session's output. Session logs, caches and saves live under .local.

See [PROGRESS.md](PROGRESS.md) for local test results and the current gameplay milestone.
