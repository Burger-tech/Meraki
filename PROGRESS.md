# Meraki progress

- Polished the Windows launcher UI while preserving package discovery, Inspect, Check imports, WARP launch, opt-in diagnostic frames, live logs and graceful Stop. The package card now shows the full executable path, package folder, manifest state and archive badges. The status band tracks the active action, session clock and latest runtime frame/FPS line. The diagnostics column shows the runtime build, session log and capture folder with open buttons, and live output highlights errors, warnings and progress. Added 11 launcher unit tests and 6 withdrawn-root Tk UI tests; all 113 tests pass. No live game run was performed.
- Evaluated native C++ Win32 against Tk for the launcher. Meraki retains Tk: no MSVC toolchain is present in the workspace, and a native rewrite would duplicate the tested process, log and Stop paths without an equivalent UI verification harness. Tk keeps feature parity and remains covered by the Python regression suite plus real widget construction tests under .local.

- Completed the [upstream comparison](docs/upstream-comparison.md) for XCL `e50836b`, VIctory `d2a4bae`, and the local read-only Leonida checkout `aa2988c`. XCL built in debug and listed 745 test entries. XCL game execution and runtime integration remain unverified. The first controlled experiment compares cold and warm shader and pipeline caches on the same package and scene.

### Live gameplay acceptance

- The isolated Rust capture candidate copies timed readback data into owned memory and encodes it on a bounded worker queue. The diagnostics build and 67 GPU tests passed, with one ignored. A short RX 7800 XT startup run saved five timed frames with a 2.533-second median and 4.300-second maximum gap and exited with code 0. A matched test is still needed to quantify render-thread overhead. Queued frames may be lost at process exit.
- DeepSeek is evaluating RenderDoc and `rdc-cli` on a synthetic Direct3D 12 scene for render-target and binding inspection. Timed runtime capture remains the live screenshot path.

- The 60 FPS study found 111 of 111 title interval requests at 33.333 ms across 23 logs. VIctory passes the requested interval through. In sampled hardware mission-transition frames, title-memory copies and copy-back dominated frame time. The synthetic timing model does not establish how the title's simulation would respond to a faster clock. Keep native pacing while validating the first mission at 15–30 FPS.

- A direct hardware capture smoke test saved five startup images at a 2.506-second median gap. The final image showed the account-picker prompts over a dark menu background. The run ended with exit code 0 after a Windows system-close request. This short run did not advance into the mission. Local evidence: `.local/sol-capture-20261124-112128`.

- Hardware is now the default in the launcher and live-test briefs. WARP remains an explicit diagnostic option. The launcher suite passed all 114 tests. The live tester will use the title's native pacing and prioritize working first-mission graphics and controls.

- The isolated timed-capture candidate built in diagnostics and release. GPU diagnostics tests passed (59 passed, one ignored). With `VICTORY_CAPTURE_TIMED=1`, it captures the first eligible rendered frame at or after each 2.5-second interval, records the actual gap, and caps saved frames. The live tester has the binary. A live WARP run saved 120 timed images with a 2.57-second median and 3.27-second maximum gap. Capture overhead remains unverified.

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
- The first performance target is 15–30 FPS on hardware during player-controlled gameplay. Verify camera and movement in a visibly rendered scene before measuring. Record the renderer, resolution, duration, and frame pacing. Keep the title's native frame clock.
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

- The descriptor retirement follow-up reproduced a premature release when a completed command list is replayed without reset. The revised patch keeps lists armed until reset or drop, and skips retirement after a failed fence wait. Game-free diagnostics tests passed (62 passed, one ignored). A full diagnostics executable and one RX 7800 XT mission test are underway.

- The first descriptor bounds candidate built and passed 468 workspace tests with seven ignored. Review found a live-test blocker: its minimum clamp can send an invalid index near the limit to the wrong typed-null slot. A follow-up is implementing exact boundary selection and checking the generated DXIL before a hardware run.

- The retirement review reproduced unbounded retention from an idle command list and found that failed fence waits must block reclamation. Its revised model passed 56 GPU tests with one ignored. A separate build is checking replayed command lists before a live run, since a completed submission can still leave a list eligible for replay.

- A game-free D3D12 regression confirmed that replacing a descriptor slot in `ffe310e` can drop its previous resource reference while a list is live. A retirement patch passed the regression and 53 GPU tests, with one ignored. The patch retains the old allocation but leaves the slot pointing to the new resource. Review is underway for retention growth with long-lived lists before a live hardware run. Neither hardware crash has been tied to this exact code path.

- The fxceless source audit found that emitted view handles can omit a bounds check when the full heap is available, and sampler bounds can exceed the actual heap. The DRED address is consistent with an out-of-range descriptor index, although the triggering instruction is not identified. A defensive candidate is assigned to use live heap limits and preserve valid accesses, with CPU and shader IR tests.

- The fxceless `578d459` hardware run rendered detailed intro cards and reached mission entry with audio. Credits overlapped and froze, then the mission went black. Menus and credits had a 33.3 ms median presentation interval; mission entry measured 0.95 presents per second. The device was removed after an eight-list submission. DRED reported a fault address far beyond the view and sampler heap ranges. That calculation does not prove which descriptor caused the fault. The process exited, and no retry was made. Evidence: `.local/fxceless-live/session-20261124-113816/REPORT-20261124-live.md`.

- The compute lowerer investigation isolated all 253 previously emitted programs lost at `ffe310e` to `3dd467c`, which keeps values live through successive control-flow joins. The old output substituted zero where the title needed a descriptor word. Keep the liveness fix. Correct emission requires support for descriptor contents used as data. The synthetic probe recovered the counts by reverting liveness only as an experiment.

- The fxceless fork at `578d459` built in diagnostics and passed 116 GPU tests and 184 shader tests, with three ignored. A visible RX 7800 XT run is assigned with native pacing and default runtime flags.
- DRED matched both hardware fault addresses to recently freed textures, but the report does not expose their allocation base, sizes, or access type. The strongest lead is a descriptor slot being remade while an open submission still references its previous texture. The proposed regression records a table use, remakes the slot, and verifies the previous binding remains valid until the list retires.

- A user-supplied screenshot from the [VIctory livestream](https://rumble.com/v7iuddk-gta-6-time.html) shows a lit dialogue scene with visible character and environment geometry beyond Meraki's black-frame checkpoint. Stream playback could not be verified here. The build, settings, and timestamp are unknown. Public VIctory main matched Meraki's `ffe310e` pin when checked. Use the image as a visual checkpoint for the fork comparison.

- Added [fxceless/victory-gta6](https://github.com/fxceless/victory-gta6) as an isolated comparison candidate. The fork reports prologue geometry, HUD, and pad input at 2–3.5 FPS on an RTX 4070, with missing lighting in shadow. Its meshlet buffer views, descriptor handling, and texture synchronization changes are relevant to the local black scene. DeepSeek is building and reviewing the exact revision before a local hardware test.

- The updated VIctory `ffe310e` diagnostic build reached the opening credits on the RX 7800 XT. The first 60 seconds averaged 28.94 presents per second. Credits averaged 0.45, and the run ended after token 3540 with `0x887A0006` and a DRED page fault. No mission geometry or player control was verified. This was a cold-cache run with a changed driver and concurrent offline translation. Evidence: `.local/upstream-hardware/REPORT.md`.

- On the same shader archive, offline DXIL emissions fell from 22,156 at `d2a4bae` to 21,886 at `ffe310e`. Compute fell from 1,693 to 1,441. Resource tracking reached 234 more programs, while more programs then failed emission. The new test executable matches the freshly built diagnostics binary by SHA-256. This census omitted DXIL validation and pipeline creation. DeepSeek is investigating which previously emitted shaders were lost.

- The older PR #32 hardware probe lost the RX 7800 XT with `0x887A0006` during a staging-texture upload after token 1708. DRED recorded a page fault and breadcrumbs stopped at command 14 of 1,319. No Windows display-reset event or dump was found. Menus and intro averaged 26.55 presents per second in the first minute, with 33.84 ms p95. No playable world appeared. The driver changed after the reboot, and a bounded run on `ffe310e` is assigned. This comparison changes both runtime and driver.

- Sol's source review identified four changes to watch in the next mission trace: `3c81420` drops work when fresh descriptor tables cannot be allocated, `e8d3b64` increases the dynamic descriptor range where supported, `a4e7f1d` initializes pending descriptors before publishing the heap, and `cbb50b8` corrects the dimension of null UAVs. Check whether descriptor exhaustion still precedes device removal and capture the first in-world frame.

- Updated the VIctory pin from `d2a4bae` to `ffe310e`. Both runtime profiles built and all 113 Meraki tests passed. The fetched README reports 30 FPS in menus and a dark scene after the first-mission title card. The update includes descriptor heap replay, CPU-written texture upload fixes, and per-lane descriptor shader lowering. Offline shader coverage comparison is underway. Updated mission visuals and frame rate still need local verification.

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

- Test sub-agent hardware arm (2026-11-24): single visible RX 7800 XT run on timed-capture ffe310e diag ran menus at a 33.3 ms median and reached the Vice City, Two Years Ago title card, then went black from frame 5780 with one flat-navy artifact frame and growing 3.5-5.4 s present gaps. Host device removed at 10:53:02 after a 30-list submission: page fault in freed 2048x2048 texture f72 (type 34). No mission geometry or player control; no terms accepted. Process exited, no repeat. Evidence: .local/hardware-60/REPORT-20261124-gpu.md.
