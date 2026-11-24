# Meraki progress

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

A community report describes intro audio continuing over a black screen. VIctory's pinned README reports rendering the first mission's title card followed by a dark scene and identifies dropped draws from untranslated shaders. Compare a captured frame after mission entry with the same interval's draw, dispatch and missing-pipeline counters. In the local intro interval ending at frame 512, all 1,536 draws and 256 dispatches executed. This gives a working comparison point before world rendering. [Community report](https://www.reddit.com/r/FitGirlRepack/comments/1y3x934/rip_leonida/) and [VIctory runtime status](https://github.com/Marvisak/VIctory/blob/d2a4bae1f49533ef5cb512fd1b1ba1513f2e1989/README.md)

### Diagnostic capture and outstanding tasks

- Added opt-in capture to the launcher. A live WARP launch against the local title produced a PNG for frame 1 and a matching session log under .local/logs. Capture defaults to off.
- Host performance messages round missing-pipeline counts per frame and report only selected intervals. The separate queue counters recorded 13,194 issued and 13,194 executed draws from frames 513 through 1,024, along with 512 issued and executed dispatches.
- The offline shader pass on the local archive emitted DXIL for 12,272 of 14,001 vertex/pixel programs, 1,693 of 2,581 compute programs and 8,191 of 8,506 mesh programs that reached emission. The two most frequent reported blockers were 64-bit image atomics (653) and scalar memory reads as data (573). This pass measured emission only. A mission trace is needed to identify which failures affect the scene.
- Outstanding gameplay test: after the user completes the first-run terms screen, capture the transition into the first mission and verify visible world geometry and player-controlled movement. Compare the logged rendering counters at that transition with the working intro.
- Started a fresh WARP test with the launcher's persistent data folder and captured the first 128 presented frames. Session evidence is in `.local/gameplay-20261123-212748`. After onboarding, test camera input from a stationary position, then forward movement and release. Check the character's position against a fixed landmark before and after input so cutscene motion cannot be mistaken for player control.
- Tested menu input from Navigation Experience through UI Text Size, Finish Setup, copyright and photosensitivity notices. Reached the privacy and terms checkboxes with Confirm disabled. Closed the game and verified process exit. Both builds and the software-adapter probe passed independent validation.
