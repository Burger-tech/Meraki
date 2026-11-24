# Upstream comparison: XCL, VIctory and Leonida

Status: research note, 2026-11-23. This compares the two upstream compatibility layers
Meraki can learn from, plus the Leonida reference work, against the pinned VIctory
baseline. It is a reading and measurement exercise: no game was launched for it, no
upstream code was copied, and this sub-agent's only repository change is this file. The optional XCL
checkout lives under `.local/xcl` (git-ignored); it is not a submodule, a build input, or
a runtime dependency of Meraki. `C:\Leonida` and `D:\` were read-only.

Meraki HEAD moved several times during this work (`ae76bc6` -> `03d0663` -> `e181373`
-> `2a35fe8`; last observed 2026-11-23). Those commits touched `README.md`,
`PROGRESS.md`, and the new frame-pacing tool/tests; no source under `baseline/` or
`.local/xcl` changed, so the citations remain valid. Meraki has no top-level license
file in this checkout, which matters for the licensing note below.

Labels used throughout:

- **OBSERVED** - read in the pinned source at the cited file:line, or measured from
  Meraki's own logs and captures.
- **CLAIM** - prose in an upstream README or document. It may be accurate, but it was not
  reproduced here.
- **INFERRED** - a conclusion that follows from the two above, with the reasoning shown.

## 1. Revisions and licenses

| Project | Checkout | Commit | Commit date | License |
|---|---|---|---|---|
| Meraki | `C:\Meraki` | `2a35fe84dc4d28b8205e7e267640c22344bce977` | 2026-11-23 | none declared in the checkout |
| XCL | `C:\Meraki\.local\xcl` (scratch clone) | `e50836bdf6f5c026f281d545ed86fb2f07ba6e6a` | 2026-11-24 | GPL-2.0-only (`Cargo.toml:8`, `LICENSE` GPLv2) |
| VIctory | `C:\Meraki\baseline` (submodule) | `d2a4bae1f49533ef5cb512fd1b1ba1513f2e1989` | 2026-11-24 | GPL-3.0-or-later (`Cargo.toml:11`, `LICENSE` GPLv3) |
| Leonida | `C:\Leonida` (read-only) | `aa2988cc555bad7ecd508b48a702adbb32fe7c95` | 2026-11-22 | GPLv3 (`README.md`: "GPLv3 or any later version"; `LICENSE` GPLv3) |

The three revisions match the list in `PROGRESS.md` at the time of writing
(`XCL e50836b`, `VIctory d2a4bae`, `Leonida aa2988c`). The commit dates are the upstream
committer dates in each repository's own timezone, not clone times.

**Source reuse.** XCL declares GPL-2.0-only and VIctory declares GPL-3.0-or-later.
Meraki has no declared license in this checkout. The proposed work uses observed
behavior and test ideas from XCL and Leonida. Review licensing before any source reuse.

## 2. What was actually done

- XCL was cloned into `.local/xcl` and checked out at `e50836b`. Its workspace was built
  in debug with the local Rust 1.98.1 toolchain (`CARGO_HOME` and `RUSTUP_HOME` under
  `.local`, `CARGO_TARGET_DIR=.local/xcl/target`). `target/debug/xcl.exe` and the test
  binaries were produced. `cargo test --workspace -- --list` then listed **745 test
  entries** (doc-tests: 0). **No test was executed**, and `xcl run` was never used with a
  title. `xcl --version` prints `xcl 0.1.0`.
- `xcl --help` was checked against the README: it lists `run`, `inspect`, `disasm`,
  `shaders`, `rpf`, and `--version` (custom usage text, not a clap-generated screen;
  `xcl shaders --help` is not a supported sub-help and exits with an error).
- VIctory was read at the pinned submodule. It was **not rebuilt** for this note; the
  prebuilt `baseline/target/diag/victory.exe` and `baseline/target/release/victory.exe`
  are from 2026-11-23 and were not produced by this research.
- Leonida was read only. Its build was not attempted: its README requires Windows x64,
  Python 3.12+, .NET 8, the Vulkan SDK, LLVM 21+ with the AMDGPU target, Visual Studio
  2022 C++ tools with Windows SDK 26100+, and about 350 GB of free space for the full
  build (`C:\Leonida\README.md:105-122`).
- Meraki's existing session artifacts were measured: `.local/gameplay-20261123-212748`
  (12 captured PNGs plus `runtime.log`) and
  `.local/live-gameplay/REPORT-20261123.md`. A throwaway PNG sampler was written at
  `.local/research/non_dark_probe.py` to apply XCL's sampling rule to VIctory's captures;
  it is not integrated. `tools/render_log.py --json` and `tools/frame_pacing.py` were run
  on the log; their numbers are in section 4.4.
- No game, no hardware run, no commit, no subagent. No writes outside `.local` and this
  file.

## 3. Build and test entry points

### 3.1 XCL

**OBSERVED** from the checkout:

- Edition 2021, version 0.1.0, `license = "GPL-2.0-only"` (`Cargo.toml:6-8`). No
  `rust-version` pin was found; the README asks for stable MSVC.
- Prerequisites in the README (`README.md:94-101`): Windows 10/11 x64, Rust
  `stable-x86_64-pc-windows-msvc`, the Windows SDK's DXC (`dxcompiler.dll` + `dxil.dll`,
  from `Windows Kits\10\bin\<version>\x64`, next to `xcl.exe`, or `XCL_DXC_DIR`), a
  D3D12 GPU with Shader Model 6.6 and mesh shaders, and the system
  `System32\xgameruntime.dll`. Windows 10 may need the Agility SDK `D3D12Core.dll` in a
  local `D3D12\` folder or `XCL_D3D12_DIR`.
- Build: `cargo build --release --workspace` -> `target\release\xcl.exe`
  (`README.md:117-119`).
- Tests: `.\scripts\test.ps1`, which is `cargo build --workspace` then
  `cargo test --workspace -- --test-threads=4` (`scripts/test.ps1:11,16`). Arguments
  after the script name go to the test binaries.
- CI (`.github/workflows/ci.yml`) runs on `windows-2025` with
  `./scripts/test.ps1 --skip test_title_runs_and_game_folder_is_untouched`. It has no GPU
  and no game data, so GPU tests print `SKIPPED <test>: <reason>` and pass; the script
  counts the skips at the end. `XCL_REQUIRE_GPU=wave64` or `=mesh` turns those skips into
  failures.
- Game-data tests are opt-in and skip when the variables are unset: `XCL_SAMPLE_RPF`,
  `XCL_SAMPLE_DLLS`, `XCL_SAMPLE_TTPF`, `XCL_SAMPLE_BK2`, `XCL_SAMPLE_BVH4`,
  `XCL_SAMPLE_AWC`, `XCL_SAMPLE_XG`, `XCL_SAMPLE_DXC` (`scripts/test.ps1:6`).
- CLI (from `xcl --help`): `xcl inspect <exe|dll> [--json]` analyzes imports without
  running; `xcl run <folder|exe> [-- args]` runs; `xcl disasm <file>` disassembles RDNA2
  and console containers; `xcl shaders <file|folder|rpf> [--top N] [--json] [--recomp]
  [--compile N]` reports corpus statistics and can translate/compile; `xcl rpf` lists or
  extracts inline records. The `shaders` parser also accepts `--precompile`,
  `--only <stage>`, and `--pipelines` (`shaders.rs:682-717`).
- Useful runtime variables verified in source: `XCL_RUN_SECONDS` (`host.rs:96`),
  `XCL_ACTIVITY` (`host.rs:33`), `XCL_FRAME_DUMP` / `XCL_FRAME_DUMP_FULL`
  (`present.rs:780,930`), `XCL_LAZY_PSO` (`pso_async.rs:117`), `XCL_ASYNC_PSO`
  (`pso_async.rs:69`), `XCL_PSO_PRELOAD` (`pso_async.rs:241`),
  `XCL_PSO_DISK_CACHE` (`real.rs:3455`), `XCL_DXIL_CACHE` (`dxc.rs:556`),
  `XCL_TRANSLATED_CACHE` (`pso.rs:157`), `XCL_PRESS_AT` / `XCL_PRESS_A_AT`
  (`gameinput.rs:258`), `XCL_TRACE_FRAME_EVENTS` (`frame.rs:317`), `XCL_DUMP_SHADERS`
  (`shader.rs:325`), `XCL_THREAD_DUMP_AT` (`host.rs:81`).

**Not verified here:** whether the local machine has DXC, a SM 6.6 mesh-capable adapter,
`xgameruntime.dll`, and the Agility SDK pieces XCL wants; whether the test suite passes;
whether `xcl run` boots this title.

### 3.2 VIctory

**OBSERVED** from the submodule:

- Toolchain pin: `rust-toolchain.toml` channel `1.98.1`, target
  `x86_64-pc-windows-msvc`, components rustfmt/clippy. Edition 2024, `rust-version 1.88`,
  `license = "GPL-3.0-or-later"` (`Cargo.toml:9-11`).
- Build: `cargo build --release -p victory`; diagnostics:
  `cargo build --profile diag -p victory --features diagnostics` (README). Meraki's
  `Build.ps1 [-Profile diag|release|both]` wraps this with `--locked`, pinned toolchain,
  and `CARGO_HOME` / `RUSTUP_HOME` / `TARGET_DIR` under `.local`.
- Tests: `cargo test --workspace` (no game data). `cargo xtask install-hooks` exists via
  the workspace alias (`.cargo/config.toml`); `cargo run -p victory -- config` inspects
  configuration.
- Config and data live outside the repository (`ensure_outside_repo`, `.victory-root`);
  the asset policy forbids shipping game files.
- Diagnostics variables verified in source (a subset relevant to comparison):
  `VICTORY_LOG`, `VICTORY_CAPTURE`, `VICTORY_CAPTURE_FRAMES`, `VICTORY_DUMP_TARGETS`,
  `VICTORY_KEYS`, `VICTORY_SKIP_PIPELINES`, `VICTORY_SHADER_LOOP_LIMIT`,
  `VICTORY_D3D12_WARP`, `VICTORY_D3D12_DEBUG`, `VICTORY_D3D12_GBV`,
  `VICTORY_D3D12_DRED`, `VICTORY_GPU_TIMING`, `VICTORY_AUDIO_CAPTURE`,
  `VICTORY_XMA_DUMP`, `VICTORY_CONFIG`, `VICTORY_GAME_DIR`, `VICTORY_DATA_DIR`,
  `VICTORY_CACHE_DIR` (`victory-core/src/config.rs:88-97`).

**Not verified here:** a local rebuild, the test suite, or any runtime behavior of the
prebuilt binaries in this task.

### 3.3 Leonida

**OBSERVED** from the read-only checkout:

- Build entry: `Build.bat` runs `python -I make_game.py`; `python -I make_game.py --check`
  validates prerequisites. Requirements as above (`README.md:105-122`).
- Tests: `python -I scripts/run_gpu_tests.py --build runtime/build/linux [--filter ...]
  [--require-pass]`; the shader shard build/check scripts; CTest for the Windows runtime
  under Wine/Proton (`docs/testing.md`). `--require-pass` makes an all-skipped run exit 1
  instead of 0 (`docs/testing.md:114`). `LEONIDA_VK_VALIDATION=1`,
  `LEONIDA_W64_EMULATE=1`, and `LEONIDA_MESH_COMPUTE=1` gate parts of the suite.
- Status: `README.md:42` says "**Early. The game does not boot yet.**"; the status table
  at `README.md:47` marks "Booting, story mode, anything playable" as "No". It is not a
  runnable fallback for Meraki.

## 4. Observed code against upstream claims

### 4.1 XCL

| Claim (upstream text) | What the pinned source shows | Reading |
|---|---|---|
| "retail games run - Minecraft Preview and Unicorn Overlord are fully playable; Fortnite and XDefiant work as far as each game goes" (`README.md:11-13`, `:20-25`) | No per-title evidence is in the repository; the mechanisms are in the source. | CLAIM. Unrelated to this package. |
| "A newer retail game ... starts in ~4 s, runs at a steady 30 fps ..., shows its menus and settings ... gameplay not reached; its minimap mesh pipelines are refused" (`README.md:26`) | The row does not name the title. The mechanisms below exist; no per-title numbers are in the code. | CLAIM. Do not assume it is this package. |
| "100% of a retail game's shaders translate - all 26 698 RDNA2 programs (26 503 records)" (`README.md:30-31`) | `ShaderStats` has unique/submitted/by-kind/by-stage/RDNA2/recomp/DXC counters (`gpu/shader.rs:150-190`); `xcl shaders --recomp` exists. No shader corpus is in the repo. | Mechanism OBSERVED; the result is a CLAIM. |
| "370+ automated tests" (`README.md:37`) | `cargo test --list` locally listed 745 entries, 0 doc-tests; none were executed. | Counts disagree; either may count differently. Neither is evidence of coverage. |
| "non-blocking creation ... a stand-in at once and built in the background" (`README.md:66`) | `pso_async.rs:1-8` describes the stand-in; `:106-124` submits real work; `:153-161` documents lazy + preload. | OBSERVED. |
| "The game folder is never modified - writes go to the overlay" (`README.md:132`) | `Report.vfs` carries unmapped paths and redirected writes (`report.rs:60`); the launcher prints both (`launcher.rs:507-515`). | OBSERVED mechanism; not exercised on this title. |
| "Every run writes report.json ..." (`README.md:135-143`) | `Report` (`report.rs:44-83`), `D3d12Stats` (`hle/d3d12x/real.rs:96-133`), frame-dump sample (`hle/d3d12x/present.rs:792-805`). | OBSERVED. |
| "Keyboard and mouse work too, as a gamepad" (`README.md:84-90`) | `kbm.rs:1-20`: WASD left stick, raw-input mouse right stick, mouse buttons triggers, wheel bumpers, focus-gated. | OBSERVED. |
| "any controller Windows sees through XInput" (`README.md:84-85`) | `gameinput.rs:1-12`: one always-connected pad from XInput slot 0-3, searched at most once per second when absent; reading callbacks polled at 250 Hz. Rumble is claimed by the README, not verified here. | Enumeration OBSERVED; rumble CLAIM. |

Concrete mechanisms worth reading (all **OBSERVED**):

- **Structured report.** `report.json` carries `xcl_version`, `title`, `exe`, `crash`,
  `exit_code`, `environment`, `imports_by_source`, `stubbed_imports`, `called_stubs`
  (DLL, function, calls, first caller), `modules`, `vfs`
  (unmapped paths, redirected writes, whiteouts), `shaders`, `dxc`, `d3d12`, `audio`,
  `xgameruntime`, `dstorage`, and `notes` (`report.rs:44-83`). `d3d12` includes backend,
  adapter, classes, unknown IIDs, fallback/failed pipelines, fallback root signatures,
  presents, frame boundaries, `last_frame_dump`, unified-memory fields, translated
  pipelines, translation errors, `background_pipelines: (built, failed, building)`, and
  DXIL cache statistics (`real.rs:96-133`).
- **Frame-content sample.** With `XCL_FRAME_DUMP=n` (`n > 1`), every n-th presented frame
  is dumped as a BMP at a quarter of each side (`XCL_FRAME_DUMP_FULL=1`: full size)
  (`present.rs:775-785`). The sampler takes every fourth texel of every fourth row and
  counts a sample as non-dark when decoded 8-bit R+G+B is greater than 30
  (`present.rs:929-957`). `FrameDumpSample` records frame, dimensions, format, step,
  sampled pixels, and `non_dark_samples`; the latter is `None` if the format cannot be
  decoded (`present.rs:792-805`). The code says explicitly that this is "not proof of
  gameplay" (`present.rs:792`) and its log says "N of M samples not black"
  (`present.rs:982-986`). Decoded formats are R10G10B10A2, RGBA8, BGRA8, and
  R11G11B10_FLOAT (tone-mapped); other formats are undecoded (`present.rs:847-860`).
- **Pipeline pressure.** The lazy path is on unless `XCL_LAZY_PSO=0`
  (`pso_async.rs:115-118`). The author's comment records a retail title creating about
  51,000 pipelines in its first 30 s, using few, each staying in the driver at about
  400 KB, until the process ran out of commit (`pso_async.rs:110-114`). A later comment
  records 2,170 skipped dispatches in the first world frames without preloading earlier
  runs' pipelines, and 94-150 with it (`pso_async.rs:153-161`). These are the author's
  measurements (CLAIM with context), not reproduced here.
- **Used-pipeline list.** `used-pipelines.txt` beside the DXIL cache holds one 16-digit
  hexadecimal key per shader set; earlier-run keys are preloaded at startup
  (`pso_async.rs:153-213`).
- **Frame clock.** A dedicated thread with a high-resolution waitable timer, spinning the
  last ~0.6 ms. It honors `ScheduleFrameEventX` offsets, releases a per-type semaphore
  (origin) or event, signals ancillary handles, keeps per-token origins, and answers
  `GetFrameStatisticsX`; it is not locked to the monitor's vblank (`frame.rs:1-14`).
  Accepted intervals include 60/30/20/15 Hz, with the 120 Hz pair only on a display that
  runs at 119 Hz or more (`frame.rs:46-55`).
- **Scripted input.** `XCL_PRESS_AT=s:BUTTON,...` and `XCL_PRESS_A_AT=s,...` press for
  200 ms at the given seconds after start (`gameinput.rs:14`, `:258`).

### 4.2 VIctory

| Claim or field (upstream text) | What the pinned source shows | Reading |
|---|---|---|
| "Not playable yet. The title boots, runs its menus at its own 30 fps and loads the world, where rendering fails" (`README.md:13-14`) | No local reproduction in this task. The WARP session reached onboarding only. | CLAIM for hardware; menu behavior is consistent with local WARP at a lower rate. |
| "The world ... title card renders, the scene after it is still dark; 0.5-1.8 s per frame" (`README.md:22`) | Not reproduced locally; the first mission was never reached. | CLAIM. |
| "Entering the world on a real GPU can currently hang it ... use `VICTORY_D3D12_WARP=1`" (`README.md:26-29`) | None; this is a safety warning. | CLAIM; treat as a real risk. |
| "Frame pacing drifts on one screen in release builds" (`README.md:41`) | `frame.rs:9-10`: event offsets are ignored; every event happens at the tick. `frame.rs:162-175`: `statistics` returns no data. | OBSERVED shortcut; a plausible cause of drift, not a confirmed one. |
| World shader coverage: mesh 8,191 of 8,506, VS/PS 10,617 of 12,346, compute 1,643 of 2,539 (`README.md:43`) | Meraki's offline pass reports mesh 8,191 of 8,506 (exact match), VS/PS 12,272 of 14,001, compute 1,693 of 2,581 (`PROGRESS.md`). | OBSERVED numbers with different scopes (world pipelines vs whole-pack emission). Do not reconcile them. |
| `VICTORY_KEYS=30:Enter,35:X` presses at those seconds, "focus or not" (`README.md:117`) | `gameinput.rs:1194`; the first-mission protocol records 0.2 s holds. | OBSERVED. |
| Capture saves powers-of-two frames at half size (`README.md`, protocol) | `capture.rs:1-4`, `:33-35`; only 8-bit RGBA/BGRA, other formats warn (`:37-40`, `:173-186`). | OBSERVED. |
| Black-frame detection | `queue.rs:303-334`: logs a black frame after a non-black one, with the 12-frame level ring and the levels six frames later. `capture.rs:484-516`: a probe read is "black" when the brightest probed channel is below 8. | OBSERVED; a different definition from XCL's. |
| Pipeline cache | `pipeline/library.rs:1-14`: every host pipeline goes into a host pipeline library keyed by description; the pipelines a run used are listed and started at creation next run. `host-pipelines.bin`, `early-pipelines.txt`, at most 8,192 early entries (`:51-54`); counters MADE/LOADED/EARLY are logged when the library is saved (`:179-182`). | OBSERVED; the same idea as XCL's used list, implemented independently. |
| Translated-shader disk cache | `shader_cache.rs:1-10`, `:39-45`: content-addressed by container content plus the BLAKE3 of the executable and the loop limit; a rebuilt translator never serves an old entry. | OBSERVED. |
| "`indirect`" in the host line | `list.rs:1177` increments `INDIRECT` only after indirect execution fails; `:1194` swaps it as "indirect executions dropped". The host line prints it as a neutral count (`host.rs:1524-1525`). | OBSERVED mislabel: treat `indirect` as a dropped count. |

Also OBSERVED: `VICTORY_SKIP_PIPELINES` (`pipeline.rs:240`) can suppress pipeline
creation for an experiment, and `VICTORY_SHADER_LOOP_LIMIT` (`victory-shader/src/emit/mod.rs:116`)
can test whether loop-bound shader work explains frame time.

### 4.3 Leonida

- **Status.** `README.md:42` - "**Early. The game does not boot yet.**"; `README.md:47` -
  "Booting, story mode, anything playable | No". It is not a runnable fallback.
- **Shader corpus.** The README claims 26,503 records (2,236 VS, 12,101 PS, 2,689 CS,
  9,282 mesh, 195 geometry) translated and all 26,503 passing `spirv-val` in a Linux
  rerun; the Windows rerun translated all and validated 26,501 before `dcd8ecf` fixed
  two ID-bound failures (`README.md:49-52`). These are CLAIMS; nothing was built here.
- **Internal inconsistency.** The README has two consecutive rows for the same metric
  (`README.md:50-51`); one says 23,841 shaders are wave64, the other 21,545.
  `docs/design.md:277` says 23,841 of 26,503, and `:512` breaks it down by stage. Treat
  21,545 as a stale duplicate; use 23,841 with the design document as the source.
- **What the validation means.** `README.md:53` states the GPU tests are small
  hand-written shaders; the game's own shaders are checked by `spirv-val` and by driver
  pipeline creation (`vk_pipeline_check`), "not by their output". `docs/pipeline_check.md`
  documents driver acceptance per hardware/driver, a ten-shard run covering 22,092 of
  26,503 entries, a full-corpus run on an RTX 4060 Ti, and a driver compiler running out
  of memory after about 21,000 pipelines (`:218-240`). This is an honest validation
  oracle, not a rendering check.
- **Input checklist.** `docs/gameinput.md` documents an SDL3-backed GameInput shim:
  DualSense/DS4/Switch Pro support, adaptive-trigger effects from impulse-trigger rumble,
  motion with normalized ranges, force feedback, and every pad reported as
  `GameInputFamilyXboxOne` (`:4-16`, `:61`, `:131-145`, `:220-238`, `:447`). It also lists
  approximations and unknowns (`:442-447`). Useful as a coverage checklist for VIctory's
  input layer; not code to reuse.
- **Test design.** `docs/testing.md` documents `--require-pass` (an all-skipped run exits
  1), a 120 s test timeout, and known driver-specific crashes (`:114`, `:411`). Good
  precedent for making skips explicit in Meraki's own harness.

### 4.4 Meraki's own measurements

Live WARP onboarding (OBSERVED, from `.local/live-gameplay/REPORT-20261123.md` and
`PROGRESS.md`):

- One session reached the account picker and then the Navigation Experience wizard; the
  privacy/terms gate was never cleared, so gameplay was never reached and no camera or
  movement test was run.
- Account picker: 39 host samples, mean 14.64 fps in the live report; the committed
  summary records 14.86 fps. Steady state was 15.0 fps at 66.6-66.7 ms/frame,
  21 draws/frame, 0 dropped. The two figures use different estimators over different
  spans; neither is wrong, and neither should be quoted as "the" frame rate without the
  window and method.
- A second run took 7 min 12 s, exceeding the five-minute cap; setup averaged 10.28 fps.
- Every `frame interval` line in this session requests 33.333 ms (five lines, one value).
  The committed summary records 28 requests across seven local logs, all 33.333 ms
  (`PROGRESS.md`). The title asks for 30 Hz during onboarding; the committed summary
  reports that VIctory honors the requested interval and presents with sync interval
  zero, so the menu cadence is not host vsync.
- GPU wait was 80.9% of frame time on average in this session's 47 host samples (median
  83.5%, range 59.7-94.2%); the committed summary reports 72-87% across WARP sessions.
  This points at GPU work in the menus, not host submission overhead.
- Frames 1-128 were uniform black; frame 2048 was the Rockstar legal-terms page.

Capture sample (OBSERVED, `.local/research/non_dark_probe.py`, XCL's every-4th-pixel
rule applied to VIctory's 1920x1080 half-size RGB8 PNGs):

| Frame | Sampled | Non-dark | Fraction | Mean R+G+B | Max R+G+B |
|---|---|---|---|---|---|
| 1, 2, 4, 8, 16, 32, 64, 128 | 129,600 | 0 | 0.0 | 0.0 | 0 |
| 256 | 129,600 | 129,582 | 0.9999 | 247.8 | 764 |
| 512 | 129,600 | 129,600 | 1.0 | 352.3 | 574 |
| 1024 | 129,600 | 129,550 | 0.9996 | 275.0 | 765 |
| 2048 | 129,600 | 129,504 | 0.9993 | 275.8 | 753 |

Two conclusions follow directly:

1. The black start is uniform, not a fade: every sample in frames 1-128 is exactly zero.
   A transition-based detector (VIctory's blink test) cannot fire there; a per-frame
   fraction can still describe it.
2. A non-dark frame is not gameplay. Frame 2048 is the legal-terms screen and is 99.93%
   non-dark. The sample proves the present path carries pixels; it proves nothing about
   the scene or interaction.

Log side (OBSERVED, `tools/render_log.py --json` on
`.local/gameplay-20261123-212748/runtime.log`):

- 849 lines, UTF-8, no replacement characters, 12 complete queue intervals covering
  frames 1-2048 contiguously with no gaps or duplicates.
- Totals: 40,018 draws recorded and 40,018 drawn; 1,978 dispatches recorded and 1,978
  dispatched.
- 47 host samples: mean 8.19 fps, median 7.5, min 4.5, max 14.5; mean 132.2 ms/frame,
  median 133.3; mean 21.36 draws/frame; `dropped` zero in all 47 samples.
- The picker-only ~14.6-14.9 fps and the whole-run 8.19 fps are not a contradiction: they
  cover different windows. This is exactly why a comparison harness must pin a frame
  window and record it.
- `tools/frame_pacing.py` on the same log found no `victory_gpu::frame` present-token
  lines, because the session did not enable `victory_gpu::frame=debug`. It therefore
  falls back to the 47 host aggregate samples (median 7.5 fps, mean 8.2) and labels them
  as interval averages, not frame times. Per-frame percentiles require the debug flag.

## 5. Complementary techniques

The useful question is not which project is better. It is which observed mechanism
answers a question Meraki cannot currently answer. Each subsection separates what is
observed from what it buys and what could go wrong.

### 5.1 Pipeline creation and reuse: convergent, not a gap

XCL gives a title a stand-in pipeline immediately and builds the real one on a worker;
graphics draws using the stand-in draw nothing until it is ready, while a compute
pipeline is waited for at its first bind because a skipped dispatch would corrupt state
(`pso_async.rs:1-8`). It also records the pipeline keys a run used and preloads them on
the next run (`pso_async.rs:153-213`). VIctory independently does the same class of
thing: every host pipeline goes into a D3D12 pipeline library keyed by its description,
and the title pipelines a run drew or dispatched with are started at creation on the next
run (`pipeline/library.rs:1-14`), capped at 8,192 early entries (`:51-54`), with
MADE/LOADED/EARLY counters logged when the library is saved (`:179-182`). Translated
shaders are separately content-addressed by container and executable hash
(`shader_cache.rs:1-10`, `:39-45`).

This is convergence, not a missing feature. The complementary part is measurement, not
code: log what the cache did (`loaded`, `started_early`, `made`) and what the title still
dropped, at a fixed frame window, so a cache change can be judged.

The trap is semantic. XCL's stand-in draw is not counted as "dropped"; VIctory's missing
pipeline drops the draw and counts it (`pipeline.rs:210`, `draw.rs:498-507`). A
cross-project "dropped draws" comparison is therefore invalid without a derived
definition: "GPU work that produced no pixels or updates because its pipeline was not
ready". Even then, XCL does not expose the stand-in draws as a counter; only
`background_pipelines.building` approximates it. Compare within a source, not across.

### 5.2 Frame-content evidence: two different detectors

XCL: one presented frame at the dump cadence, every fourth texel in each direction,
non-dark when 8-bit R+G+B > 30, decoded only for four formats, `None` otherwise, with an
explicit "not proof of gameplay" comment (`present.rs:775-805`, `:929-957`).
VIctory: a probe read of the presented resource, black when the brightest probed channel
is below 8, plus a 12-frame ring of levels and a log when a black frame follows a
non-black one (`capture.rs:484-516`, `queue.rs:303-334`); captures are powers of two, half
size, 8-bit only (`capture.rs:1-4`, `:33-40`).

These are complementary: XCL gives a per-frame fraction with an explicit decode limit;
VIctory gives a short history and a transition event. Neither is a gameplay oracle. The
local data makes the blind spot concrete: frame 2048 is 99.93% non-dark and is a legal
notice. The right use is "did the present path carry pixels at frame N, and did the
sequence change shape", never "the game rendered correctly".

Risk: half-size and 8-bit capture change the numbers; XCL's BMP is quarter-size and may
be 10-bit. Compare fractions only within one capture pipeline, and keep
`gameplay_verified: false` in any normalized output.

### 5.3 Frame clock: the clearest behavioral divergence

XCL honors `ScheduleFrameEventX` offsets, keeps a per-token origin, answers
`GetFrameStatisticsX`, and runs its own high-resolution timer rather than the monitor's
vblank (`frame.rs:1-14`, `:46-55`). VIctory ignores offsets ("every event is at the
tick"), makes the token the frame number, and returns no statistics
(`frame.rs:9-10`, `:71-80`, `:162-175`); its README already reports frame-pacing drift on
one screen in release builds (`README.md:41`).

This is the most concrete candidate for a compatibility improvement, but not a small
one. Changing when the title wakes changes frame counts, input timing, and which draws
are in flight. XCL's semantics are "as observed on Fortnite (UE)" (`frame.rs:9`), which
makes them evidence rather than a specification; a second title can pace differently.
Treat a pacing patch as a later, separately measured experiment (section 7, B3), and do
not mix its runs with runs from the current clock.

Local relevance: this title requests 33.333 ms during onboarding, and VIctory honors it
(five such lines in the captured session; 28 across seven logs in `PROGRESS.md`). Event
offsets may still matter inside each 33.333 ms interval, but the first thing an A/B must
record is the requested interval, not assume 16.667 ms.

Observables already exist: VIctory logs each frame wait with `timeout_ms`, `flags`, `hr`,
`tick`, and `wait_us` (`frame.rs:140-158`); XCL logs the first 40 frame-event calls with
`XCL_TRACE_FRAME_EVENTS` (`frame.rs:317`) and reports frame-event waits and timeouts in
its 2 s activity line (`host.rs:47-50`).

### 5.4 Input diagnostics: mostly a checklist

XCL's keyboard/mouse-to-pad translation is focus-gated and documented as a table
(`kbm.rs:1-20`); its scripted presses hold for 200 ms (`gameinput.rs:14`, `:258`).
VIctory's `VICTORY_KEYS` holds for 0.2 s and works without focus (`README.md:117`), and
its keyboard stand-in has no mouse-as-right-stick path in the verified variable list.
Leonida's SDL3 GameInput shim is the broadest checklist: DualSense adaptive triggers,
motion, rumble, force feedback, and the fact that every pad is reported as an Xbox One
family device (`docs/gameinput.md`).

What it buys: a list of gaps to test later (mouse camera, rumble, motion), and a reminder
that focus is part of the experiment. Our own live run needed a verified foreground
window before synthetic input reached the title. What it does not buy: anything needed
for the first A/B. Scripted keys are sufficient and already exist.

### 5.5 Structured report versus logs

XCL writes a versioned, structured `report.json` with imports, called stubs, VFS
behavior, shader/recompiler counters, D3D12 statistics, audio, and runtime classes
(`report.rs:44-83`; `real.rs:96-133`; `shader.rs:150-190`; `dxc.rs:564-580`). VIctory's
equivalent facts are spread across log lines and two text files
(`host-pipelines.bin`, `early-pipelines.txt`).

This is Meraki's real diagnostic gap: not a missing runtime feature, but a missing
normalized artifact. A per-run JSON manifest produced outside the runtime captures the
same facts without modifying VIctory and without a runtime dependency.

Risk: XCL's field names, units, and semantics are not Meraki's. Importing them as a
schema would bake in a different project's choices. Define a small Meraki schema with
`source`, `unit`, `definition`, `precision`, and `metric_kind` on every value.

### 5.6 A translation-validation oracle

Leonida's strongest contribution is not its renderer; it is an independent translation
and validation pipeline for the same RDNA2 input: 26,503 records translated, `spirv-val`
over the corpus, and driver pipeline acceptance (`vk_pipeline_check`), with an explicit
statement that this checks acceptance, not shader output (`README.md:49-53`;
`docs/pipeline_check.md:218-240`). VIctory's offline pass counts DXIL emission and its
runtime drops draws whose shaders do not translate.

What it buys: a second opinion when a translation change is suspected. If a shader
translates and validates on the SPIR-V path but fails DXIL emission, the bug is more
likely in the DXIL emitter than in the RDNA2 decode. It also sets a precedent for
`--require-pass`-style test gating. What it does not buy: a rendering check, or
interchangeable code. SPIR-V and DXIL are different targets with different failure modes.

### 5.7 Memory and pipeline pressure

XCL's source comment records a concrete failure mode: tens of thousands of pipelines,
about 400 KB each in the driver, running the process out of commit
(`pso_async.rs:110-114`); its README claims about 15 GB committed in the menus for an
unnamed title (`README.md:26`). VIctory logs device removal after a failed submission
(`host.rs:567-573`) but no periodic commit line was found.

What it buys: a measurable hypothesis for world-entry instability (peak commit versus
dropped pipelines and device loss). What it does not buy: a technique to port. It needs
external process-memory sampling, so it belongs after the first harness, not in it.

## 6. Proposed integration: a diagnostics-only run comparator

Proposed, not implemented by this note. The deliverable is one Meraki-owned Python tool
(`tools/compare_runs.py`), its tests, and small fixtures; no Rust change, no runtime
dependency, no game data in the repository.

**Purpose.** Turn the artifacts Meraki already produces into one `comparison.json` with
provenance, units, precision, and explicit comparability rules, so an A/B verdict is a
computed result rather than a reading of two logs.

**Inputs.** One or more run manifests (or CLI flags) with: `--victory-log`,
`--capture-dir`, optional `--xcl-report`, `--label`, `--pair`, `--frame-window A:B`,
`--require-complete`, `--out`. Runs are grouped by `pair` and named A1, A2, B.

**Adapters.**

1. VIctory log: call `tools/render_log.py --json` for host/queue summaries and
   `tools/frame_pacing.py` for present-token timing when `victory_gpu::frame=debug` is
   enabled (subprocess or import). Do not write a second regex. `.local/research/metrics.py`
   and `analyze_fps.py` already duplicate those patterns with different field sets; that
   duplication is how the `indirect`/`dropped` misread survives.
2. Capture sampler: pure-Python PNG decode (zlib plus the five PNG filters), 8-bit RGB or
   RGBA, non-interlaced; step 4; non-dark when R+G+B > 30; record dimensions, sampled
   count, non-dark count, fraction, mean and max R+G+B. Reject 16-bit or interlaced input
   with a clear error rather than guessing. This is a reimplementation of a documented
   sampling rule, not a copy of XCL code.
3. XCL report (optional, for cross-check): a fixed allowlist of fields mapped into a
   `source: "xcl"` namespace (`d3d12.presents`, `d3d12.last_frame_dump`,
   `d3d12.fallback_pipelines`, `d3d12.failed_pipelines`,
   `d3d12.background_pipelines`, `d3d12.dxil_cache`, `shaders`, `called_stubs`, `vfs`).
   Unknown fields are ignored; missing fields become `null`. Never place an XCL value in
   a VIctory column.

**Output.** Versioned JSON, deterministic (sorted keys, hashed inputs, no wall-clock
fields beyond those parsed from logs):

```json
{
  "schema": "meraki.run-compare/1",
  "tool": {"name": "tools/compare_runs.py", "python": "3.13.14"},
  "runs": [{
    "id": "A1", "pair": "cache", "source": "victory",
    "provenance": {
      "commit": "d2a4bae", "adapter": "WARP", "resolution": "3840x2160",
      "log_sha256": "...", "captures_sha256": "..."
    },
    "window": {"first_frame": 129, "last_frame": 2048, "basis": "queue intervals"},
    "pacing": {
      "source": "host_aggregates",
      "samples": 47,
      "fps": {"mean": 8.19, "median": 7.5, "min": 4.5, "max": 14.5, "precision": 0.1},
      "ms_per_frame": {"mean": 132.2, "median": 133.3, "precision": 0.1},
      "draws_per_frame": {"mean": 21.36, "precision": 1},
      "dropped_per_frame": {"mean": 0.0, "precision": 1},
      "indirect_dropped_per_frame": {"mean": 0.0, "precision": 1}
    },
    "intervals": {
      "complete": true, "contiguous": true, "gaps": 0,
      "draws": 40018, "drawn": 40018, "dispatches": 1978, "dispatched": 1978,
      "counter_difference": {"draws": 0, "dispatches": 0,
        "meaning": "recorded minus executed; not a drop count"}
    },
    "frames": {
      "captured": 12,
      "sampled": [
        {"frame": 1, "sampled": 129600, "non_dark": 0, "fraction": 0.0},
        {"frame": 2048, "sampled": 129600, "non_dark": 129504, "fraction": 0.9993}
      ],
      "first_non_dark_frame": 256,
      "gameplay_verified": false,
      "gameplay_note": "presence of pixels does not establish gameplay"
    },
    "notes": []
  }],
  "comparisons": [{
    "a": "A1", "b": "A2", "comparable": true, "reason": null,
    "deltas": {"ms_per_frame.median": 0.4, "dropped_per_frame.mean": 0.0},
    "noise_floor": {"ms_per_frame.median": 0.8, "dropped_per_frame.mean": 0.0},
    "verdict": "within_noise"
  }]
}
```

**Rules the tool must enforce (and tests must prove).**

- `pacing.source` is `present_tokens` when `frame_pacing.py` found debug present lines,
  otherwise `host_aggregates`; never compute one percentile across the two.
- `comparable: false` if either run's queue intervals are incomplete, non-contiguous,
  have duplicate frames, or cover a different frame window.
- Deltas only between the same `source`, capture settings, resolution, and adapter.
- XCL rows are `cross_check` with `definition` and `unit`; they never produce a delta
  against VIctory.
- Report values at the logged precision: fps and ms to 0.1, counts integer. A `0.05` ms
  difference is `within_logging_precision`, not `changed`.
- `counter_difference` is never called "unexecuted" or "drops".
- `indirect` is labeled "dropped indirect executions", citing `list.rs:1177`.
- `non_dark_fraction` never sets `gameplay_verified` true.
- A capture with an unsupported format (16-bit, interlaced, or not PNG) is an error with
  the frame name, not a zero.
- Output is byte-identical across two runs on the same inputs.

**Tests (no game, no GPU).**

1. PNG decoder: synthetic 4x4 RGB and RGBA images, one per filter type 0-4; expected
   counts for step 1 and step 4; 16-bit and interlaced inputs rejected.
2. Log adapter: a complete interval set plus a truncated line and a duplicate frame;
   `comparable` becomes false and the gap is reported. Golden values from the existing
   session: 40,018 draws, 1,978 dispatches, frames 1-2048.
3. Capture golden (local only, not committed): frames 1-128 fraction 0.0, frame 256
   >= 0.999, frame 2048 >= 0.999. Game-derived images must not enter the repository.
4. XCL adapter: a synthetic `report.json` missing optional fields yields `null`, no
   crash; unknown fields ignored.
5. Precision: a sub-quantum delta is classified as within logging precision.
6. Negative control: `.local/review/frame4-only.log` (one interval) must be
   `comparable: false` or flagged; it must never produce a negative "unexecuted" count.
7. Determinism: two runs produce identical bytes and hashes.

**Acceptance criteria (verifiable without the game).**

- Reproduces the session totals above.
- Classifies frames 1-128 as zero non-dark and frames 256-2048 as at least 0.999.
- Exits nonzero on incomplete coverage when `--require-complete` is set.
- Processes the 12 existing PNGs in under 5 seconds on Python 3.13 (the scratch probe
  took about 1.6 seconds).
- Imports only the standard library (`json`, `struct`, `zlib`, `hashlib`,
  `argparse`, `pathlib`, `subprocess`); no Pillow, no new build surface.
- `python -B -m unittest discover -s tests` passes, matching the existing test style.

**Non-goals.** No game launch, no VIctory patch, no `xcl run`, no XCL build dependency,
no archive or asset work, no code reuse from XCL or Leonida, no claim that a captured
frame is gameplay.

**Why this is the small integration.** It is one Python module plus tests and tiny
fixtures, built from artifacts Meraki already produces. It turns an ambiguous log-reading
exercise into a reproducible comparison, and it creates the vocabulary (window,
precision, comparability, noise floor) that every later experiment needs.

## 7. Controlled A/B tests

The harness above is only useful if it can tell a real change from noise. This is the
smallest protocol that can do that, in the order it should be attempted.

### 7.1 Preconditions

- The user clears the terms gate first. The local runs stop at onboarding; accepting
  consent is not something the harness or a worker should automate.
- WARP only (`VICTORY_D3D12_WARP=1`), diagnostics build, one title package, the same
  resolution, and one session at a time. Hardware world entry can hang the display and
  reset the driver (VIctory `README.md:26-29`); do not run it unattended.
- Fix the frame window before looking at any number. For onboarding use frames 1-2048
  (the last power-of-two capture), recorded as `first_frame` / `last_frame` in the
  manifest. For the world, record the first frame after mission entry and use a window
  of equal length in every arm.
- Enable `VICTORY_LOG=info,victory_gpu::frame=debug` for any arm that needs per-frame
  timing; otherwise only host aggregates exist. Record the title's requested frame
  interval in the manifest.
- Keep the data directory shared (saves, overlay, persistent storage). Vary the cache
  directory only in the arm that is about the cache. `VICTORY_DATA_DIR`,
  `VICTORY_CACHE_DIR`, and `VICTORY_GAME_DIR` are read by the config
  (`victory-core/src/config.rs:88-97`), with defaults under `%LOCALAPPDATA%\victory`.
- Announce each live run and close it with the Windows system-close path used by the
  launcher; do not call `terminate()`.

### 7.2 Design

- **A/A first.** Two runs with identical settings establish the noise floor. Onboarding
  A/A can be warm/warm (cheap). If the first experiment varies the cache, the strict form
  is cold/cold; if that is too expensive, use warm/warm and require a larger effect,
  because warm variance may understate cold variance.
- **One variable per arm.** Change one environment value, cache state, or binary build
  between A and B, and record it in the manifest.
- **Three candidate B arms, in increasing cost:**

  **B1 - cold versus warm pipeline/shader cache (no code change).**
  Cold: a fresh `VICTORY_CACHE_DIR`. Warm: the cache left by a completed run. Measure
  time to frame 1024 and 2048 (from log timestamps), the library-save counters
  (`made`, `loaded`, `started_early`), dropped draws/dispatches per frame, median
  ms/frame, and the first non-dark frame. This isolates a mechanism VIctory already
  has; it is a rehearsal for the harness, not a new feature.

  **B2 - shader loop limit in the world (`VICTORY_SHADER_LOOP_LIMIT=512` versus default).**
  VIctory's README proposes exactly this test: if a lower limit makes world frames much
  faster, loops hitting the limit are what makes them slow (`README.md:127`). This is
  world-only, after the terms gate and mission entry. Note that the shader cache key
  includes the loop limit (`shader_cache.rs:39-45`), so the first run with a new limit is
  cold by construction: run it twice and measure the second. Also note that a lower limit
  can change output; a speed win with different pixels is not a compatibility win.

  **B3 - frame-clock offsets and statistics (needs a patch; deferred).**
  Reimplement offset handling and `GetFrameStatisticsX` in `victory-gpu::frame`, gated by
  an option. Build two binaries from the same base with only that difference; each build
  has its own shader cache key (BLAKE3 of the executable), so warm each build before
  measuring. Compare frame-wait logs (`timeout_ms`, `flags`, `hr`, `tick`, `wait_us`),
  median ms/frame, and whether frame numbers stay aligned between arms. Do not start this
  until B1 has produced a noise floor and B2 has shown whether world time is shader-bound.

### 7.3 Decision rule

Primary metric: **median ms/frame** in the pinned window, because the mean is dominated
by loading outliers. Secondary: dropped draws and dispatches per frame, `indirect`
(dropped indirect executions), the first non-dark frame, and, for B1, the library
counters.

B is an improvement only if all of these hold:

1. The primary metric improves by more than the A/A noise floor.
2. Dropped work does not increase.
3. The non-dark frame sequence does not get worse (the same or an earlier first non-dark
   frame, no new sustained black span).
4. Draws per frame do not fall enough to explain the speedup (doing less work is not a
   win).

Otherwise the verdict is `inconclusive`, not "no effect".

### 7.4 What would falsify the experiment

- A/A differs by at least as much as B-A on the primary metric: the run is too noisy for
  this arm; increase the window or add runs.
- Coverage is incomplete, non-contiguous, or a different length: no verdict.
- For B1, `loaded` / `started_early` do not move in the expected direction: the cache
  manipulation failed; that is an invalid run, not a negative result.
- For B2, ms/frame improves but the captured pixels change materially: the limit changed
  output; not a compatibility win.
- For B3, frame numbers no longer align between arms: the comparison basis changed;
  restart with a frame-independent metric (wall-clock intervals) and say so.

### 7.5 Evidence layout

One directory per arm under `.local/runs/<stamp>/` (untracked):

```
.local/runs/20261124-101500/
  A1/ runtime.log  frames/  run.json
  A2/ runtime.log  frames/  run.json
  B1/ runtime.log  frames/  run.json
  comparison.json
```

`run.json` records: label, pair, source, commit, executable hash, adapter, resolution,
data/cache directory identity (not contents), environment variables that matter, frame
window, and the cache state (cold/warm). `comparison.json` is the tool's output; it must
embed the input hashes so a later reader can tell whether the logs changed.

## 8. Bottom line

1. The pinned revisions and declared licenses match the project records. Use XCL
   and Leonida source observations to design independent Meraki tests.
2. XCL's most useful contributions to Meraki are diagnostic, not runtime: a structured
   run report, a coarse but explicit frame-content sample, a principled frame clock, and
   scripted input. VIctory already has the pipeline/shader cache ideas that XCL also
   implements; that convergence is evidence the design is right, not a gap to port.
3. The local evidence already shows why a harness is needed: frames 1-128 are exactly
   black, frame 2048 (legal terms) is 99.93% non-dark, and the same session reads as
   about 14.6-14.9 fps on the picker, 8.2 fps over the whole run, and 7.5 fps median
   from host samples. The window and the estimator decide the number; none of these
   facts is a rendering verdict on its own.
4. The small integration to build first is `tools/compare_runs.py`: one JSON artifact,
   one PNG sampler, one log adapter, explicit precision and comparability rules, and a
   cold/warm A/B as its first customer. It requires no Rust change and no game launch to
   verify its mechanics.

## 9. Not verified / open questions

- XCL was never run against this package. Its "newer retail game" row is unnamed; do not
  assume it is this title. Its test suite was built and listed, not executed, and the
  local machine's DXC/GPU/runtime prerequisites were not validated for XCL.
- VIctory never reached gameplay locally. The world window, the first-mission input test,
  and the 60 fps hardware target are all unmeasured. The 0.5-1.8 s/frame and hardware
  reset statements are upstream claims.
- Whether frame-event offsets matter for this title is unknown. VIctory's shortcut is
  documented; no experiment has compared it with an offset-honoring clock on this title.
- The pipeline-cache effect on this title is unmeasured. XCL's 51,000-pipeline and
  2,170-versus-94-150 numbers are the author's measurements on another title.
- Leonida's 26,503-shader claims are upstream claims; nothing was built or run. Its
  duplicated README row (23,841 versus 21,545 wave64) is an internal inconsistency;
  `docs/design.md` uses 23,841.
- Meraki has no declared license in the checkout. Until that is decided, all
  cross-project code reuse is blocked, not only XCL's.

## 10. References

Pinned upstream:

- XCL: <https://github.com/ivall/xcl/tree/e50836bdf6f5c026f281d545ed86fb2f07ba6e6a>
- VIctory: <https://github.com/Marvisak/VIctory/tree/d2a4bae1f49533ef5cb512fd1b1ba1513f2e1989>
- Leonida: <https://github.com/ItsNotRexed/Leonida/tree/aa2988cc555bad7ecd508b48a702adbb32fe7c95>

Local evidence (untracked unless noted):

- `.local/xcl` - scratch XCL checkout and debug build.
- `.local/research/non_dark_probe.py` - scratch PNG sampler used for the table in 4.4.
- `.local/gameplay-20261123-212748` - 12 captured frames, `runtime.log`, `stdout.log`.
- `.local/live-gameplay/REPORT-20261123.md` - live WARP onboarding session.
- `.local/review/REPORT.md` - audit of `tools/render_log.py`.
- `tools/render_log.py` (tracked) - existing log parser and JSON emitter.
- `tools/frame_pacing.py`, `tests/test_frame_pacing.py` (tracked) - present-call pacing
  tool; needs `victory_gpu::frame=debug` for per-frame timing, otherwise reports host
  aggregates and says so.
- `PROGRESS.md`, `README.md` (tracked) - Meraki status at the time of writing.
