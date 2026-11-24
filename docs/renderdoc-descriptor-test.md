# RenderDoc descriptor test

Status: verified offline on 2026-11-24. Scope: synthetic D3D12 only. This
distills `.local/renderdoc-eval/EVALUATION.md` and
`.local/renderdoc-descriptors/REPORT.md`. All setup, captures, binaries,
caches, and evidence stay under `C:\Meraki\.local` (gitignored); nothing here
depends on `D:\` or `C:\Leonida`.

## Verdict

`rdc-cli` 0.7.0 plus a locally built RenderDoc 1.47 Python module can open a
D3D12 capture, resolve per-draw descriptors, export render targets, export full
draw snapshots, and assert pixels. The descriptor-retirement probe passed all
65 checks. The portable RenderDoc zip is not sufficient by itself: it ships
`renderdoccmd.exe` and `renderdoc.dll` but no `renderdoc.pyd`, so `rdc` replay
needs a Python-ABI-matched module built from source (or supplied separately).

## Verified toolchain

| Component | Version | Notes |
|---|---|---|
| Windows host | x64 | `rdc doctor` reports `platform: windows` |
| Python | 3.13.14 | repo venv at `.local\renderdoc-eval\venv` |
| rdc-cli | 0.7.0 | deps click, numpy, Pillow 13.0.0 |
| RenderDoc runtime/CLI | 1.47 | `renderdoccmd x64 v1.47` built from `b0e1370` |
| RenderDoc Python module | 1.47 | `renderdoc.pyd` built from `b0e1370` |
| VS Build Tools 2022 | 17.14.37012.4 | used for the module build |
| MCP SDK (optional) | 1.30.0 | pin `mcp[cli]<2`; 2.x removes `mcp.server.fastmcp` |

`rdc doctor` passes every check except the optional `win-vulkan-layer`
registration. Its nonzero exit code comes only from that Vulkan check; the
D3D12 path is unaffected.

Bare `python` on PATH is 3.13.14 but lacks Pillow/numpy. Use the full venv
interpreter: `C:\Meraki\.local\renderdoc-eval\venv\Scripts\python.exe`.

## Repo-local locations

| Path | Role |
|---|---|
| `C:\Meraki\.local\renderdoc-eval\env.ps1` | loads PATH, module, session, cache, temp |
| `...\renderdoc-eval\venv` | Python 3.13.14 + `rdc.exe` |
| `...\renderdoc-eval\renderdoc-1.47\RenderDoc_1.47_64` | portable runtime and `renderdoccmd.exe` |
| `...\renderdoc-eval\renderdoc-module` | built `renderdoc.pyd`/`renderdoc.dll` |
| `...\renderdoc-eval\rdc-data` | replay sessions |
| `...\renderdoc-eval\tmp` | `TEMP`/`TMP` for replay |
| `...\renderdoc-eval\synthetic-d3d12` | 320x240 smoke capture, EID 16 |
| `...\renderdoc-descriptors\src` | `descriptor_retire.cpp`, `renderdoc_app.h` |
| `...\renderdoc-descriptors\build` | `descriptor_retire.exe` |
| `...\renderdoc-descriptors\captures` | `descriptor-retire_frame3.rdc` |
| `...\renderdoc-descriptors\analysis` | per-EID descriptor JSON, RT PNGs, snapshots, verification |
| `...\renderdoc-descriptors\tools\verify.py` | 65-check validator |

`rdc open` writes the session to `%RDC_DATA_DIR%\sessions\<name>.json`;
`env.ps1` sets `RDC_SESSION=meraki-eval` and keeps the session cache out of
`%LOCALAPPDATA%`. It sets `RENDERDOC_PYTHON_PATH`; for a direct `import renderdoc`, also set `PYTHONPATH` to the same module directory.

## Capture

Verified form (from the eval):

```powershell
& 'C:\Meraki\.local\renderdoc-eval\renderdoc-1.47\RenderDoc_1.47_64\renderdoccmd.exe' `
  capture -d '<target-working-dir>' `
  -c 'C:\Meraki\.local\renderdoc-descriptors\captures\descriptor-retire.rdc' `
  -w 'C:\Meraki\.local\renderdoc-descriptors\build\descriptor_retire.exe'
```

- `-d` is the launched program's working directory.
- `-c` is the filename template; RenderDoc appends the frame suffix
  (`..._frame3.rdc`).
- `-w` waits for the target to exit. Do not pass `--`; `renderdoccmd` treats it
  as the executable.

Descriptor capture: `captures\descriptor-retire_frame3.rdc`, 1,542,741 bytes,
SHA-256 `69085208D3A019FE63937BEEE73BF3B9E7BF7507D2CAA91B9D838FF4F1C85B7B`.
The synthetic app is 192x144, uses one shader-visible two-slot
`CBV_SRV_UAV` heap, and submits four draws in two fence-separated phases.

## Replay and inspect

```powershell
. C:\Meraki\.local\renderdoc-eval\env.ps1

$cap = 'C:\Meraki\.local\renderdoc-descriptors\captures\descriptor-retire_frame3.rdc'
& $rdc open $cap
& $rdc info --json
& $rdc events --json
& $rdc draws --json
```

Per draw, resolve the descriptor actually used:

```powershell
& $rdc descriptors 18 --json
& $rdc descriptors 27 --json
& $rdc descriptors 45 --json
& $rdc descriptors 54 --json
```

Export the full state snapshot and the render target:

```powershell
& $rdc snapshot 18 -o 'C:\Meraki\.local\renderdoc-descriptors\analysis\snapshot-eid-18'
& $rdc rt 18 -o 'C:\Meraki\.local\renderdoc-descriptors\analysis\rt-eid-18.png'
```

`snapshot` writes `pipeline.json`, `shader_vs.txt`, `shader_ps.txt`, and
`color0.png`. Repeat with EIDs 27, 45, 54.

Read and assert exported pixels:

```powershell
& $rdc pick-pixel 96 72 18 --json
& $rdc assert-pixel 18 96 72 --expect "0.8509804 0.1490196 0.2 1.0" --tolerance 0.002 --json
& $rdc assert-clean --min-severity high
& $rdc close
```

Argument order differs: `pick-pixel X Y [EID]`, `assert-pixel EID X Y`.

Check the PNGs directly with the venv Python:

```powershell
& 'C:\Meraki\.local\renderdoc-eval\venv\Scripts\python.exe' -c `
  "from PIL import Image; rt=Image.open(r'C:\Meraki\.local\renderdoc-descriptors\analysis\rt-eid-18.png').convert('RGBA'); sn=Image.open(r'C:\Meraki\.local\renderdoc-descriptors\analysis\snapshot-eid-18\color0.png').convert('RGBA'); print(rt.size, rt.getpixel((96,72)), rt.getcolors(1<<24), rt.tobytes()==sn.tobytes())"
```

Run the full validator:

```powershell
& 'C:\Meraki\.local\renderdoc-eval\venv\Scripts\python.exe' `
  C:\Meraki\.local\renderdoc-descriptors\tools\verify.py
```

Expected: `status PASS`, 65 checks, no failures. A Pillow `getdata`
deprecation warning is harmless (`$LASTEXITCODE` is 0).

## Descriptor result

| EID | Marker | Texture | SRV | Center pixel (96,72) |
|---:|---|---|---:|---|
| 18 | `RetirePhase1_Red` | `MerakiDesc_Red` | 286 | `(217,38,51,255)` |
| 27 | `RetirePhase1_Green` | `MerakiDesc_Green` | 287 | `(38,191,64,255)` |
| 45 | `RetirePhase2_Blue` | `MerakiDesc_Blue` | 288 | `(26,64,217,255)` |
| 54 | `RetirePhase2_Yellow` | `MerakiDesc_Yellow` | 289 | `(230,204,26,255)` |

For every draw, `rdc descriptors` reports Pixel stage / `Image` / index 0 /
array element 0 / `R8G8B8A8_UNORM` / binding `src` / set 0, with the expected
resource name. An independent `GetReadOnlyResources` read via `rdc script`
agrees on all four resource IDs, descriptor store `ResourceId::285`, index 0,
and array element 0. All exports are uniform 192x144, and each
`snapshot-eid-N\color0.png` matches its `rt-eid-N.png` byte-for-byte.

## What this does and does not prove

This is offline replay of Meraki-owned synthetic captures:

- Proves RenderDoc recorded the correct per-draw descriptor after a
  fence-ordered descriptor remake, and that snapshots and RT exports agree.
- Proves the local `rdc` + RenderDoc module toolchain works on D3D12.
- Does not run the title, Victory host heap code, or any live game path.
- Does not reproduce or clear a premature descriptor release, black mission
  scene, device removal, or frame-pacing issue. The probe submits only valid
  D3D12: slots are remade only after the first submission is complete.
- Does not validate `D:\` or `C:\Leonida` content; neither was read or modified.

Live runtime validation is separate: launch the title on hardware rendering,
confirm keyboard focus, use `W/A/S/D` to move menu selection and `Enter` to
activate, and capture/DRED the failing run. See
`docs/hardware-gameplay-test.md` for that procedure. A synthetic pass is a
tooling and recording check, not evidence that a live defect is fixed.

## Tool caveats

- `rdc bindings` can omit or fail to resolve a root/table resource. Use
  `rdc descriptors` for per-draw resolved IDs.
- `rdc pipeline` gives topology and pipeline IDs only; deeper state needs
  `rdc script` with the RenderDoc API.
- `rdc doctor` nonzero is expected on this host because of the optional Vulkan
  implicit-layer check.
- Portable RenderDoc 1.47 has no `renderdoc.pyd`; module ABI matching is the
  main setup cost on a clean Windows machine.
- MCP wrapper: unpinned `mcp[cli]>=1.0.0` resolves to 2.x and breaks import;
  pin `mcp[cli]<2`.

