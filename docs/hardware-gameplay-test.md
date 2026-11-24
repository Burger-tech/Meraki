# Hardware readiness and gameplay acceptance test

Research draft, 2026-11-23. Inputs: pinned VIctory at
`C:\Meraki\baseline` (`d2a4bae1f49533ef5cb512fd1b1ba1513f2e1989`) and local
traces under `C:\Meraki\.local`. Meraki `HEAD` during research:
`1046c0364f09ff2105833dfce3bc5ce070fc2a0d`.

Labels: **VERIFIED** = executed or inspected here; **SOURCE** = read from the
pin; **UNVERIFIED** = proposed test/design; **UPSTREAM** = VIctory README claim.
This research did not launch the title, take focus, change system settings, or
use exploit techniques. T1-T4 are future supervised tests. No memory editing,
debugger injection, DLL hooking, driver changes, or title-file changes.

A diagnostics run was already active when research began
(`.local/live-gameplay/session-20261123-232934-diag`). It was not started,
controlled, or stopped here. Its frozen trace is
`.local/hardware/snapshot-232934.log`.

## Bottom line

| Question | Finding | State |
|---|---|---|
| SM 6.6 and mesh shaders? | RX 7800 XT and WARP both pass VIctory's exact gate. | VERIFIED |
| World rendering? | No local gameplay trace. Upstream reports a dark scene at 0.5-1.8 s/frame. | UNVERIFIED |
| Lower presentation resolution with fixed title settings? | Not in pinned VIctory: the swap chain is title-texture sized and has no scaling path. A host-side scale patch is design-only. | VERIFIED / UNVERIFIED |
| Is 30 FPS a renderer cap? | No host cap found. Every local interval request was 33.333 ms and was passed through. | VERIFIED |
| Is 60 FPS proven? | No 16.667 ms request and no player-controlled measurement. | UNVERIFIED |
| TDR triage? | Feasible with event log, dumps, and DRED in a supervised hardware run. No local TDR history. | VERIFIED / UNVERIFIED |

## T0: D3D12 capability probe (no title)

VIctory's gate (`baseline/crates/victory-gpu/src/host.rs:417-447`) lazily queries
`D3D12_FEATURE_SHADER_MODEL` with `D3D_SHADER_MODEL_6_6` and
`D3D12_FEATURE_D3D12_OPTIONS7.MeshShaderTier`. It passes only if both queries
succeed, the tier is not `NOT_SUPPORTED`, and the highest shader model is at
least 6.6. The one-time log is `host mesh shader support mesh=...`. The gate is
reached only when a translated pipeline has a mesh stage, not at startup; menus
never log it.

The safe probe creates only a D3D12 device: no title process, window, swap
chain, focus, or input. Source and binary are scratch files at
`.local/hardware/probe_d3d12_tiers.cpp` and `.exe`.

```powershell
cmd /c '"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul && cl /nologo /EHsc /std:c++17 /Fe:C:\Meraki\.local\hardware\probe_d3d12_tiers.exe /Fo:C:\Meraki\.local\hardware\probe_d3d12_tiers.obj C:\Meraki\.local\hardware\probe_d3d12_tiers.cpp d3d12.lib dxgi.lib ole32.lib'
& 'C:\Meraki\.local\hardware\probe_d3d12_tiers.exe'
```

The harmless `vswhere.exe` warning from `vcvars64.bat` does not affect the
build. A Python `ctypes` vtable attempt caused access violations and was not used
as evidence.

| Adapter | SM 6.6 query | Highest query | Mesh tier | VIctory gate |
|---|---|---|---|---|
| RX 7800 XT (`0x1002:0x747e`, 16176 MiB) | `S_OK`, 6.6 | 6.8 | Tier 1 (`10`) | **PASS** |
| Microsoft WARP | `S_OK`, 6.6 | 6.8 | Tier 1 (`10`) | **PASS** |

This proves API capability only. World pipeline compilation, binding,
execution, and pixels remain T2/T3 items.

## Local evidence

Source behavior:

- `host.rs:179-184`: diagnostics plus `VICTORY_D3D12_WARP` selects WARP;
  otherwise the default hardware adapter.
- `host.rs:52-110`, `558-573`: failures report the device-removed reason and
  debug-layer message; submissions over 250 ms log `slow host submission`.
- `host.rs:1580-1610`: `present()` takes its size from the title texture;
  `ResizeBuffers` runs only when that texture size/format changes.
- `host.rs:1653`: `Present(0, DXGI_PRESENT(0))`, sync interval 0.
- `host.rs:1662-1693`: swap chain is title-texture sized; log is
  `presenting to a window width=... height=... format=...`.
- `dxgi.rs:222-257`: the title sees exactly one mode, 3840x2160 at `60/1`.
- `frame.rs:26,45-56`: 16.667 ms is used only when the title passes length 0;
  otherwise the title's exact value is used and logged as `frame interval`.

Local traces:

- All observed interval records were `33.333ms`; none were `16.667ms`. The
  prior audit counted 28 records across seven logs.
- Every presentation line was `width=3840 height=2160 format=28`.
- No `host mesh shader support` line: menus did not reach the world gate.
- No device-removed/device-lost line.
- Frozen pre-existing snapshot: 4,146 present events, 13.21 observed FPS,
  p50 66.82 ms, p95 133.46 ms, p99 135.23 ms, max 1,132.80 ms; all five
  configured intervals were 33.333 ms.

Hardware: Ryzen 7 5700X3D, 32 GB RAM, Windows 11 Pro build 26200, RX 7800 XT
driver `32.0.32015.7029`, desktop 1920x1080 @165 Hz. The title still sees 4K60.

## Acceptance matrix

| ID | Run | Purpose | Pass condition | State |
|---|---|---|---|---|
| T0 | Capability probe | Confirm SM 6.6 + mesh tier | Both adapters pass | VERIFIED |
| T1 | Menu smoke | Validate logging/pacing | Menu presents; interval/window lines captured; no removal | UNVERIFIED |
| T2 | WARP world reach | Prove visible scene + input | Geometry visible; opposite yaw and landmark movement; no sustained black | UNVERIFIED |
| T3 | Hardware gameplay | Evaluate sustained 60 FPS | T3 criteria below; no TDR | UNVERIFIED |
| T4 | Failure capture | Classify TDR/crash/hang | Log, event, dump, DRED preserved | UNVERIFIED |

### T1: menu-only smoke

Use the diagnostics executable directly so `VICTORY_LOG` is not stripped by the
GUI launcher. Announce the visible run before starting.

```powershell
$root = 'C:\Meraki'
$env:VICTORY_GAME_DIR = '<package-dir>'
$env:VICTORY_DATA_DIR = "$root\.local\data"
$env:VICTORY_CACHE_DIR = "$root\.local\cache"
$env:VICTORY_D3D12_WARP = '1'
$env:VICTORY_LOG = 'info,victory_gpu::frame=debug'
& "$root\baseline\target\diag\victory.exe" run "$env:VICTORY_GAME_DIR\game_scarlett_master.exe" --execute *> "$root\.local\hardware\t1.log"
```

This is a trace smoke test, not a performance verdict. Expect 33.333 ms requests,
3840x2160 presentation, and dense `present token` lines. Close with the Windows
system-close path in `.local/research/first-mission-protocol.md`.

### T2: visible world and player control on WARP

Use the first-mission protocol. Capture the title card and first world frame; do
not infer arrival from elapsed time. On WARP the world may advance only every
0.5-1.8 s, so its timing is diagnostic, not a 60 FPS result.

Pass only if the scene is visibly rendered, a fixed landmark moves
forward/backward, opposite yaw inputs produce opposite world displacement while
the HUD stays fixed, draws/dispatches are nonzero, and a black warning does not
remain at frame +6. A black frame with all draws executed is scene-content or
presentation failure, not a frame-rate result; use the protocol's target-dump
triage.

### T3: hardware gameplay and 60 FPS

Run only after T2 has a visible, controllable scene. Announce and supervise the
hardware run: upstream says world entry can hang the machine and reset the
display. Keep the window visible and a human present; do not run unattended.

Use a diagnostics build with `VICTORY_D3D12_DRED=1` and
`VICTORY_D3D12_DEBUG=1`. Add `VICTORY_GPU_TIMING=1` only for slow-submission
triage; it adds overhead. Keep package, data, cache, title settings, scene, and
input script identical across comparisons.

Measure one contiguous 60 s player-controlled window containing idle, both yaw
directions, and forward/backward movement. Derive pacing from every present
event, not the periodic host sample:

```powershell
python .\tools\frame_pacing.py <runtime.log> --start-time <ISO> --end-time <ISO> --budget-ms 16.67
```

60 FPS acceptance:

- `frame interval interval=16.667ms` exists before and during the window;
- observed FPS >= 59.5;
- p95 <= 17.0 ms and p99 <= 25.0 ms;
- at most 1% of frames exceed 16.67 ms;
- no hitch over 250 ms and no device removal.

Report FPS, p50/p95/p99/max, miss count/rate, resolution, duration, and title
interval. A 30-FPS-capped menu or WARP result is not a hardware 60 pass. If only
33.333 ms is requested, report "title-selected 30 FPS", not "renderer cannot do
60".

## Lower presentation resolution

Pinned VIctory cannot test this under fixed title settings:

- The title texture, not the window client size, sets the swap chain; resizing
  the window does not lower the backbuffer (`host.rs:1587-1607`).
- The only title-visible mode is 3840x2160 @60 (`dxgi.rs:222-257`).
- `Present(0, ...)` uses sync interval 0 and there is no scaling blit.
- No resolution/render-scale/presentation-scale environment variable exists.
- Changing desktop resolution does not change the 4K swap chain; changing
  in-title settings changes title settings and is not a controlled hold.

A Meraki-only host experiment could keep the 4K title texture and title settings,
allocate a smaller swap chain, and downscale during presentation. It would test
display/present/compositor cost only, not lower internal rendering resolution.
It requires a source change and is design-only here. Advertising another mode
(e.g. 120 Hz) to influence the requested interval is a separate title-visible
change, not a settings-constant resolution test.

## 30 versus 60 FPS triage

| Observation | Meaning | Next step |
|---|---|---|
| `33.333ms`, present p50 ~33.3 ms | Title requests 30 Hz; host keeps up | Record title-capped 30 FPS; do not claim 60. |
| `33.333ms`, p50 ~66.7 ms | Two ticks per frame (15 FPS) | Look for GPU wait, copy, or submission cost. |
| `33.333ms`, p50 ~100 ms | Three ticks (10 FPS), commonly a missed tick | Not a 30 pass; inspect slow submissions/WARP/pipelines. |
| `16.667ms`, p50 ~16.7 ms | Real 60 attempt | Apply T3 metrics. |
| `16.667ms`, p95 over budget | Renderer/presenter misses 60 budget | Profile GPU wait, copies, pipeline creation, CPU prep. |
| No interval line | Logging/window wrong | Fix `VICTORY_LOG`; do not infer from host samples. |

`dxgi.rs` advertises only 4K60 and its comment mentions a missing 120 Hz mode, so
the title's mode choice is a leading hypothesis for 30 Hz. It is not confirmed;
test it as a separate mode-list experiment.

## TDR and failure triage

Do not change `TdrLevel`, `TdrDelay`, `TdrDdiDelay`, driver, or power settings.
Record existing values and leave them alone. TDR is a Windows display-driver
reset, not just an application error.

Before a hardware run:

```powershell
$start = Get-Date
Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers' |
  Select-Object TdrLevel, TdrDelay, TdrDdiDelay
Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Display'; Id=4101,4102; StartTime=(Get-Date).AddDays(-30)} -ErrorAction SilentlyContinue
Get-ChildItem 'C:\Windows\LiveKernelReports','C:\Windows\Minidump' -Recurse -File -ErrorAction SilentlyContinue |
  Select-Object FullName, LastWriteTime
```

Empty registry values mean no overrides. Local preflight found no Display
4101/4102 events in the prior 30 days and no LiveKernelReports/Minidump files.
Save pre-run counts and filenames.

On failure, search the runtime log for:

```text
host GPU device removed after a submission
device removed:
page fault at
breadcrumbs
slow host submission
slow host list
```

`VICTORY_D3D12_DRED=1` adds faulting addresses, allocation names, and the command
where an unfinished list stopped. `VICTORY_D3D12_DEBUG=1` names the first bad
command. A 250 ms warning alone is not a TDR.

| Classification | Evidence | Meaning |
|---|---|---|
| TDR | New Display 4101/4102, often a LiveKernelReport, plus VIctory device-removed failure and long/last submission | Windows reset the driver. Record time, reason, last frame/token, crash report. Stop; do not relaunch immediately. |
| App crash | Crash report/access violation, no new 4101/4102 | Process fault. On WARP, a shader wild access becomes an access violation, not a driver reset. |
| Hang | No new presents, possibly alive, no removal/event | Deadlock or stalled submission. Capture last present/frame; bounded human decision. |
| Slow frame | `slow host submission` or long interval, process continues | Hitch/performance evidence, not TDR. |

After the run, repeat the event/dump queries with `$start` and preserve the log,
`crashes.log`, captures, and environment. A display reset is a recorded TDR, not
a reason to retry immediately.

## Known gaps and artifacts

No hardware world run or player-controlled gameplay evidence; no local mesh-gate
line; no 16.667 ms request; no resolution override; no local TDR/dump history.
The pre-existing diagnostics session was not part of this design.

- `.local/hardware/probe_d3d12_tiers.cpp`, `.exe` - safe capability probe.
- `.local/hardware/snapshot-232934.log` - frozen pre-existing run.
- `.local/research/PERFORMANCE-RESEARCH-20261123.md` - pacing/hardware evidence.
- `.local/research/first-mission-protocol.md` - input, capture, black-frame, shutdown.
- `.local/live-gameplay/REPORT-20261123.md` - last supervised live run.
