# Meraki progress

- Polished the Windows launcher UI while preserving package discovery, Inspect, Check imports, WARP launch, opt-in diagnostic frames, live logs and graceful Stop. The package card now shows the full executable path, package folder, manifest state and archive badges. The status band tracks the active action, session clock and latest runtime frame/FPS line. The diagnostics column shows the runtime build, session log and capture folder with open buttons, and live output highlights errors, warnings and progress. Added 11 launcher unit tests and 6 withdrawn-root Tk UI tests; all 113 tests pass. No live game run was performed.
- Evaluated native C++ Win32 against Tk for the launcher. Meraki retains Tk: no MSVC toolchain is present in the workspace, and a native rewrite would duplicate the tested process, log and Stop paths without an equivalent UI verification harness. Tk keeps feature parity and remains covered by the Python regression suite plus real widget construction tests under .local.

- Completed the [upstream comparison](docs/upstream-comparison.md) for XCL `e50836b`, VIctory `d2a4bae`, and the local read-only Leonida checkout `aa2988c`. XCL built in debug and listed 745 test entries. XCL game execution and runtime integration remain unverified. The first controlled experiment compares cold and warm shader and pipeline caches on the same package and scene.

### Live gameplay acceptance

- Launcher capture now records per-frame host Present events alongside screenshots for the frame-pacing tool. The full 113-test suite passed after the change. Following the unrelated PC restart, no game process or completed new hardware result was found.

- Keep one visible game instance and one desktop test owner. Prepare the next candidate while the current run is active. Start the next comparison after verifying that the prior process exited. Let loading and shader compilation continue while logs or frames show progress.
- Capture the mission card, first rendered world frame or sustained black screen, and any failure. Keep timing logs running between captures. For each retry, record the build, cache state, scene, and single change under test. Confirm camera and movement before using a run to assess the 30 FPS target.

- The Navigation Experience input audit found that the prior 80 ms Continue presses were shorter than the roughly 100 ms setup frames, with foreground focus unverified for those presses. Later runs advanced the same screen to UI Text Size. Live tests now verify focus, hold Continue for 400–500 ms, and confirm the expected screen after release.

- The visible DeepSeek WARP test advanced from the account picker to Navigation Experience after focused Right and Enter input. Two focused Continue attempts left that screen unchanged. The account picker averaged 14.86 FPS and setup averaged 10.28 FPS. The worker requested Windows system close and verified that the process exited. This second run took 7 minutes 12 seconds, exceeding the five-minute test cap. Player-controlled gameplay and the 60 FPS hardware target remain unverified. Local report: `.local/live-gameplay/REPORT-20261123.md`.
- Across seven local logs, all 28 frame-interval requests from the title were 33.333 ms during startup and onboarding. VIctory honors the requested interval and calls Direct3D Present with sync interval zero. The measured menu cadence is therefore separate from host vsync.
- In those WARP sessions, GPU wait accounted for 72–87% of median frame time at 4K. This identifies a menu bottleneck. First-mission GPU cost remains unverified.
- A device-only D3D12 probe confirmed that the RX 7800 XT and WARP pass VIctory's shader model 6.6 and mesh shader checks. Both reported shader model 6.8 and mesh shader Tier 1. The pinned runtime sizes presentation from the title texture and has no independent resolution override. See the [hardware test plan](docs/hardware-gameplay-test.md).
- The frame-pacing tool counts logged host present calls, including repeated title tokens. It does not infer presentations from token gaps. All 96 tests passed. Live gameplay measurement is pending.
- A controlled 60 Hz versus 120 Hz advertised-mode comparison can test whether display modes influence the menu's requested interval. An unchanged request would leave other title settings and gameplay modes untested.

- Run interactive gameplay tests with the game window visible on the Windows desktop. Announce each live run before launch, share milestones during the run, and close the game afterward. Use the launcher to keep the live log available.
- The performance target is sustained 60 FPS during player-controlled gameplay, with a 16.67 ms frame budget. Verify camera and movement in a visibly rendered scene before measuring. Record the renderer, resolution, duration, and frame pacing. Use WARP to diagnose rendering and use hardware results to evaluate the performance target. Upstream reports hardware GPU resets on world entry, so establish a controlled hardware test after the mission renders.
- During the first visible mission, record an idle baseline, rotate the camera in both directions, then move forward and backward against a fixed landmark. Capture the matching frames and use the black-frame probe history to distinguish a fade from sustained dark output. Confirm keyboard focus before sending input.
- Launcher Stop now requests VIctory's Windows system-close path. A visible WARP smoke test presented frames and reached the runtime suspend handler. VIctory hit its one-second suspension deadline and exited with code 0. Pipeline cache persistence remains unverified.

DeepSeek implemented 11 launcher regression tests covering runtime routing, archive headers, and opt-in captures. All passed with `python -B -m unittest discover -s tests -v`.

The rendering-log audit reproduced misleading totals from truncated, missing, and repeated frame records. The parser now reports interval coverage and distinguishes draw counter differences from dropped-pipeline diagnostics. All 48 tests passed. The local boot log still reports complete coverage through frame 1024 with 16,430 draws and 957 dispatches executed. A separate worker is preparing the first-mission input and capture test.

## November 23, 2026

- Integrated VIctory at d2a4bae1f49533ef5cb512fd1b1ba1513f2e1989 as a submodule. Build.ps1 builds from the Meraki root.
- Implemented a Tk launcher with package discovery, executable inspection, WARP execution, process control and local session logs.
- Verified the Inspect action using package 1.0.2.1 on D:\. The three principal archives have the RPF9 on-disk signature documented by Leonida. This header check covers format identification only.
- Tested preparation of game_scarlett_master.exe on Windows 11 25H2 (build 26200). VIctory resolved 88 emulated platform imports, 427 host imports and 72 imports from the title's DLLs. All four title DLLs also loaded with zero missing imports.
- The WARP diagnostic run opened the account picker, accepted Enter and rendered the animated opening sequence. Local screenshots and runtime traces are under .local/smoke.
- Frame 900 showed the legal notices screen. The loader had already opened levels.rpf during startup, so opening that archive is insufficient evidence that the world loaded.
- Verified the launcher's Check imports action end to end against the local package. It completed with exit code 0 and reported the bindings for each module.
- The first-run flow reached Rockstar Games Legal Terms & Policies. Terms of Service was unchecked and Confirm was disabled. Testing stopped there for the user to review the terms. Locally verified milestones currently end at onboarding.

### World rendering investigation

- Live WARP results: the prewarmed PR #254 run reported 26 hits and two misses and still lost the device at mission entry. The PR #32 timing probe attributed about 96% of loading frame time to GPU wait. The removal probe first detected `0x887A0005` before submission at frame 1593, after the prior Present. This locates detection, while the triggering operation remains unknown. All test processes exited.
- With monitors off, desktop captures were stale, but VIctory captured frames and accepted focused input. The presentation resolution fell from 4K to 1080p, so those timing samples require a separate comparison. A bounded RX 7800 XT test is assigned to check mission entry on an adapter that supports the fixed compute wave sizes.

- Headless tests isolated the pre-removal WARP compute pipeline refusals to fixed wave-size requirements. WARP reports 4 lanes and rejects shaders requiring 32 or 64. The RX 7800 XT reports 32–64 lanes and accepted all 299 tested compute pipelines, including 118 with fixed wave sizes. WARP remains useful for diagnostics but cannot verify full mission rendering on this host. Device removal is a separate unresolved failure.

- The isolated PR #32 removal probe built and passed both focused tests. It records the first failed check before a submission or around Present, including the numeric HRESULT, frame, and submission. It is queued for a separate WARP run if device removal persists after the prewarmed-cache comparison.

- A headless C++ WARP harness passed four aligned texture-copy and readback cases in three consecutive runs, including a correctly sized mip-1 copy. Fences completed and all active bytes matched. The test covers the basic D3D12 transfer path. The mission failure still needs a trace that identifies the first device-removal result around Present and submission.

- Across six runs, the shader audit found 491 translation failures in 3,911 attempts, including 302 compute failures. A separate 352 pre-removal compute pipeline refusals returned `E_INVALIDARG` after translation had succeeded. The synthetic translator fixture passed four cases and does not reproduce host pipeline failures or device removal. A focused host pipeline investigation is assigned.

- VIctory PR #254 `0e6b2b4` built in diagnostics and passed 12 focused cache tests. Offline translation wrote 22,156 nonempty cache entries in about 287 seconds. The prewarmed candidate is queued for a visible WARP comparison after the frame-time probe exits.

- The opt-in PR #32 frame-time probe built and passed 55 focused GPU tests with one ignored. It separates preparation, GPU wait, copy-back, and residual time. A visible WARP run was assigned to validate the probe at mission entry. Existing mission-loading samples measured 1.29–3.06 presents per second and still ended in device removal. These samples do not measure gameplay.

- Four DeepSeek workstreams are assigned: diagnose the last texture-copy submission, build the shader-cache candidate, rank mission shader failures, and prepare performance instrumentation or a focused optimization. Compare one runtime change at a time. After the mission renders, test player control and fix visible rendering defects before measuring sustained 30 FPS.

- The warm-cache WARP run reached Lucia's mission loading card and then went black. It logged descriptor exhaustion (104 slots requested), a 1,242 ms submission with 32 lists, and GPU device removal. The mission-loading window measured 3.25 observed presents per second with a 932.7 ms p95 interval. Player control was never visible. The next run compares the isolated queue-ordering candidate against this failure sequence. Local evidence: `.local/live-gameplay/session-20261124-0030-warm`.

- Public VIctory main matched Meraki's pin when checked on November 24. Open [VIctory PR #32](https://github.com/Marvisak/VIctory/pull/32) implements cross-queue waits. Its exact head `8fd82c9` built in diagnostics with zero warnings. Focused GPU tests passed with 55 tests in the default configuration and 57 with diagnostics, with one ignored in each. The binary is available for a separate WARP test under `.local/victory-pr32/target/diag`. Open PRs #254 and #275 address shader-cache and pipeline compilation stalls and can be evaluated separately.
- A local diagnostic log recorded a 672 ms host submission followed by GPU device removal, along with shader translation and pipeline failures. The trace lacks queue-wait telemetry, so it cannot establish whether the ordering patch addresses that failure. Verify the scene and repeat the test with matched settings and separate cache roots.

- VIctory developers reported two separate failure modes at first-mission entry. Cold shader compilation can stall rendering long enough for the title to close. Once shaders are cached, a GPU ordering problem can still leave rendering passes reading data before it was written, producing a black screen or crash. Upstream reported a fix in progress. Both findings still need local reproduction against Meraki's pinned revision.
- Preserve the shader cache between matched runs. Compare cold and warm runs using separate workspace cache directories, and correlate compile activity with presentation gaps and exit timing. If the warm run remains dark, capture the affected frames and examine GPU submission ordering and missing writes alongside pipeline counters. Compare any upstream fix against the current pin on the same build and scene.

A community report describes intro audio continuing over a black screen. VIctory's pinned README reports rendering the first mission's title card followed by a dark scene and identifies dropped draws from untranslated shaders. Compare a captured frame after mission entry with the same interval's draw, dispatch and missing-pipeline counters. In the local intro interval ending at frame 512, all 1,536 draws and 256 dispatches executed. This gives a working comparison point before world rendering. [Community report](https://www.reddit.com/r/FitGirlRepack/comments/1y3x934/rip_leonida/) and [VIctory runtime status](https://github.com/Marvisak/VIctory/blob/d2a4bae1f49533ef5cb512fd1b1ba1513f2e1989/README.md)

### Diagnostic capture and outstanding tasks

- Added opt-in capture to the launcher. A live WARP launch against the local title produced a PNG for frame 1 and a matching session log under .local/logs. Capture defaults to off.
- Host performance messages round missing-pipeline counts per frame and report only selected intervals. The separate queue counters recorded 13,194 issued and 13,194 executed draws from frames 513 through 1,024, along with 512 issued and executed dispatches.
- The offline shader pass on the local archive emitted DXIL for 12,272 of 14,001 vertex/pixel programs, 1,693 of 2,581 compute programs and 8,191 of 8,506 mesh programs that reached emission. The two most frequent reported blockers were 64-bit image atomics (653) and scalar memory reads as data (573). This pass measured emission only. A mission trace is needed to identify which failures affect the scene.
- Outstanding gameplay test: after the user completes the first-run terms screen, capture the transition into the first mission and verify visible world geometry and player-controlled movement. Compare the logged rendering counters at that transition with the working intro.
- Started a fresh WARP test with the launcher's persistent data folder and captured the first 128 presented frames. Session evidence is in `.local/gameplay-20261123-212748`. After onboarding, test camera input from a stationary position, then forward movement and release. Check the character's position against a fixed landmark before and after input so cutscene motion cannot be mistaken for player control.
- Tested menu input from Navigation Experience through UI Text Size, Finish Setup, copyright and photosensitivity notices. Reached the privacy and terms checkboxes with Confirm disabled. Closed the game and verified process exit. Both builds and the software-adapter probe passed independent validation.
- Integrated the delegated runtime log summary and verified identical frame interval totals on UTF-8 and UTF-16 copies of the local boot log. The report distinguishes rounded host samples from frame interval counters.

### Live WARP mission attempts (2026-11-24, test sub-agent)

- Baseline b99f876 warm-cache retry and PR32 17655DC5 both reached the mission-entry black scene and lost the device (0x887A0004/5) within seconds. Removals: baseline 07:36:48, PR32 07:46:26. PR32 cut pipeline refusals 107->21 and removed the n=104 descriptor exhaustion, but did not fix the removal.
- DRED on PR #32 listed buffer-to-texture copies in the last attempted submission. Earlier resource creation calls already returned device removed, following first-chance exceptions in WARP. This places the observed failure before the listed submission. The initiating operation remains unidentified. A headless WARP copy and readback test is assigned to validate the basic transfer path independently.
- No terms screen appeared and no terms were accepted. Player controls remain unverified because no visible playable frame was rendered. Report: .local/live-gameplay/REPORT-20261124.md
