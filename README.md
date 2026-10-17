# The Elder Scrolls IV: Oblivion Remastered - Optimizer

Profile-based `Engine.ini` optimizer for **Oblivion Remastered on Linux via Proton (Steam)**.

It composes Unreal Engine 5 console variables from one *profile* (the global illumination /
reflection strategy) plus any number of *features* (independent toggles such as "Frame
Generation off", "Distance Field AO off", "classic shadow maps"), optional one-off overrides,
and writes them into the game's user `Engine.ini`. Everything it writes sits between two marker
lines, so switching profiles, adding or removing a feature, or going back to stock is one command.

> Linux + Proton only. The tool locates the Proton prefix inside your Steam libraries
> (`steamapps/compatdata/2623190`). On Windows the same `.ini` lines work, but this tool will not run there.

Tuned and tested on: Ryzen 5 5600, RTX 4060 8 GB, NVIDIA 595, Pop!_OS (COSMIC / Wayland),
Proton 11, 1080p, DLSS. Values are conservative enough for any 8 GB class GPU; see "Tuning".

## Requirements

* Linux, Steam, the game installed and run at least once with Proton (so the prefix exists).
* Python 3.9+ (standard library only).

## Quick start

```bash
git clone https://github.com/viniciusmorgado/tes-oblivion-optimizer.git
cd tes-oblivion-optimizer
./oblivion-optimizer.py list                  # what is available
./oblivion-optimizer.py apply lumen-lite --lock
```

Run it with the game **closed**. Launch the game normally afterwards; nothing else to do.

## Commands

| command | what it does |
|---|---|
| `list` | profiles and features with a one-line description each |
| `apply PROFILE [options]` | compose and write the block (replaces any previous block) |
| `show` | print the block currently in `Engine.ini` |
| `status` | where `Engine.ini` is, whether it is locked, what is applied, how many backups |
| `remove` | delete the block: the game behaves as if the tool was never used |
| `lock` / `unlock` | toggle read-only on `Engine.ini` (the game rewrites the file when menu settings change; read-only is the usual protection) |
| `launch-options` | print the suggested Steam launch options |

`apply` options:

| option | effect |
|---|---|
| `--feature NAME`, `-f NAME` | add a feature block; repeatable, applied in order, later wins |
| `--no-common` | leave out the default `common` feature |
| `--fps N` | pin the in-game frame rate limit to N (`Altar.GraphicsOptions.FrameRateLimit` + `t.MaxFPS`) |
| `--set CVAR=VALUE` | one-off override, wins over everything; repeatable |
| `--unset CVAR` | drop a cvar from the composition so the game's own value applies |
| `--lock` | make `Engine.ini` read-only after writing |
| `--dry-run` | print the block instead of writing |

Global options: `--steam-root PATH` (non-standard Steam location) and `--engine-ini PATH`
(skip detection entirely).

### Examples

```bash
# Lumen kept but cheap, Frame Generation kept (good default)
./oblivion-optimizer.py apply lumen-lite --lock

# Same, but DLSS as upscaler/AA only (no Frame Generation) and a hard 60 fps target
./oblivion-optimizer.py apply lumen-lite -f nofg --fps 60 --lock

# Maximum performance: Lumen off, no DFAO shimmer on foliage, SSR off (clean water)
./oblivion-optimizer.py apply lumen-off -f dfao-off -f ssr-off --lock

# Experiment: Screen Space GI as the GI method, aggressive trims, one tweak of your own
./oblivion-optimizer.py apply ssgi -f lowfx --set r.Streaming.PoolSize=2500 --lock

# Keep the profile but let the game decide the grass density again
./oblivion-optimizer.py apply lumen-lite --unset grass.densityScale --lock

# Back to stock
./oblivion-optimizer.py remove
```

## Profiles (pick one)

| profile | Lumen | what replaces it | evidence | expected |
|---|---|---|---|---|
| `lumen-lite` | on, software, console-class budget | Lumen reflections off, SSR instead; mesh-SDF tracing off; surface / radiance cache between the game's Series S profile and PC High | Epic Lumen performance guide + the game's own device profiles | +15-25 % GPU, lighting close to High; best quality/performance so far |
| `lumen-off` | off | skylight + Distance Field AO + SSAO, SSR for reflections | the route used by the most endorsed community mods and Steam guides | +20-40 % GPU outdoors; interiors flatter; small foliage may shimmer (add `dfao-off`) |
| `ssgi` | off | Screen Space GI forced as the GI method (`r.DynamicGlobalIlluminationMethod=2`), DFAO + SSAO | UE-correct, **not community-tested in this game** | same win as `lumen-off`, some colour bleed kept; same foliage caveat |

All three pin `r.Lumen.HardwareRayTracing=0`. Hardware Lumen crashes on NVIDIA 590/595 under
vkd3d-proton in several reports and costs 20-25 % for little visual gain.

## Features (combine freely)

| feature | default | what it changes | evidence |
|---|---|---|---|
| `common` | **on** | Virtual Shadow Maps between Medium and High, cheaper volumetric fog and clouds, grass/foliage density 0.6, lens flare / fringe / bloom / tonemapper trims, 2.3 GB texture streaming pool | game scalability tables; VSM Ultra->High measured -16 % |
| `nofg` | off | Frame Generation off (DLSS-G and FSR3 FI); DLSS upscaling and Reflex untouched | game's own `Altar.*` cvars |
| `dfao-off` | off | Distance Field AO off; removes the foliage shimmer when Lumen is off | community (Nexus "Lumen OFF without artifacts") |
| `ssr-off` | off | Screen Space Reflections off (this game's SSR breaks on water) | widely reported |
| `vsync-off` | off | in-game VSync off; pair with `--fps N` | - |
| `csm` | off | Virtual Shadow Maps off, 3 cascades x 2048 classic shadow maps | `r.Shadow.Virtual.Enable 0` measured +5-6 % |
| `lowfx` | off | Nanite 1.5 px/edge, no cloud shadows, fewer particles, view distance 0.7, grass 0.45 | pack-used, unmeasured |
| `pso` | off | PSO precompile pool at 50 % of threads, lazy shader load | unverified; the shipped configs do not set the pool to 0 as some mods claim |

Order matters only when two blocks touch the same cvar: profile overrides `common`, features
override the profile in the order given, `--fps` and `--set` override everything. The tool prints
a note for every override and groups the written block by the source that won.

## Writing your own profile or feature

Drop a file in `profiles/` (one GI strategy) or `features/` (one independent toggle):

```ini
# One-line description shown by `list`
; free comments start with a semicolon
r.SomeCvar=1
Altar.GraphicsOptions.Something=0
```

Only `key=value` lines are written; section headers are ignored (everything goes to
`[SystemSettings]`). Keep a feature to one concern so people can combine it.

## How it works (and why the menu is not enough)

* The in-game menu writes scalability groups (`sg.*`) to `GameUserSettings.ini` and its own
  options to `Save_Settings.sav`. Each group maps to a block of cvars in the game's scalability tables.
* Cvars in `[SystemSettings]` of the user `Engine.ini` are applied at *SetBySystemSettingsIni*
  priority, above scalability and game settings: they win over the menu, and the menu can no longer
  change them until the block is removed. Menu options that are not pinned keep working.
* The Windows device profile shipped in the game pins a few cvars at a higher priority
  (`r.ShaderPipelineCache.*`, `r.PSOPrecache.*`, `r.PostProcessing.Prefercompute`,
  `vts.Nanite.MaxWPOScale`); those cannot be changed from `Engine.ini`.
* Project defaults: Lumen is both the GI and the reflection method, hardware ray tracing is compiled
  out (`r.RayTracing=False`, so Lumen is always software Lumen), Virtual Shadow Maps and Nanite are on.
* What the menu's GI / reflection levels really do in this build:

  | setting | Low / Medium | High |
  |---|---|---|
  | Global Illumination | `r.Lumen.DiffuseIndirect.Allow=0` (Lumen GI off, only DFAO on Medium) | Lumen GI on **plus** mesh-SDF tracing |
  | Reflections | `r.Lumen.Reflections.Allow=0`, SSR 0 / 2 | Lumen reflections at half res |

  So the menu can switch Lumen off, but it leaves nothing in its place. The profiles above decide
  what runs instead and trim the rest.

Digital Foundry A/B-tested the most downloaded "engine tweaks" pack for this game and measured no
difference. This repository therefore only carries lines that change a rendering feature (Lumen,
VSM, fog, grass, Nanite, streaming); generic "threading / GC / async" lines are left out on purpose.

## Linux / Proton notes

* **Proton 10.0-2 or newer** is needed for DLSS Frame Generation to be selectable; NVAPI is on by
  default, no `PROTON_ENABLE_NVAPI` required.
* **ntsync** is used automatically by Proton 11 on kernels that expose `/dev/ntsync`.
* **Hardware Lumen** off (see above).
* **Resizable BAR**: check `nvidia-smi -q | grep -A1 "BAR1"`. 256 MiB means it is off in the UEFI;
  enabling it is a small free win. `VKD3D_CONFIG=no_upload_hvv` is not useful on 8 GB cards
  (vkd3d-proton only uses ReBAR upload heaps above 8 GB).
* **RAM**: the game wants 12-16 GB. Anything pushed to swap or zram shows up as hitching; close
  IDEs / browsers before playing.
* **CPU**: `gamemoderun` (package `gamemode`) switches the governor / EPP to performance while playing.
* **Frame cap vs refresh**: on a 100 Hz panel a 60 fps cap without VSync alternates 1 and 2 refreshes
  per frame. Use a divisor of the refresh rate (50 on 100 Hz) or set the display to 60 Hz.
* **Engine.ini persistence**: the game regenerates `Engine.ini` when menu settings change. `--lock`
  makes it read-only; your menu choices still save (they live elsewhere). `status` tells you if the
  block is still there.
* **Newer DLSS model (optional)**: `PROTON_ENABLE_NGX_UPDATER=1 DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE=on
  DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE_RENDER_PRESET_SELECTION=render_preset_latest` lets Proton use the
  driver's DLSS; the transformer presets look better and cost a few percent.
* **`PROTON_ENABLE_WAYLAND=1`** is experimental on NVIDIA and has broken Frame Generation for some users.

Suggested launch options (`gamemode` and `mangohud` installed; drop `mangohud` after measuring):

```
__GL_SHADER_DISK_CACHE_SKIP_CLEANUP=1 __GL_SHADER_DISK_CACHE_SIZE=12000000000 gamemoderun mangohud %command%
```

## Measuring

The first session after any change recompiles shaders and PSOs; judge after that. Compare the same
spots (a dense forest, the Imperial City waterfront, a cave) with MangoHud and look at the frametime
graph and the 1 % low, not the average: most of these lines remove spikes rather than raise the mean.

## Tuning for other hardware

* 6 GB GPUs: `--set r.Streaming.PoolSize=1800`, consider `-f lowfx`.
* 12 GB+ GPUs: `--set r.Streaming.PoolSize=3000`; `csm` and `lowfx` are probably unnecessary.
* CPU-bound (older 4/6 cores): `-f lowfx` (view distance and grass are CPU costs too), `--fps` at a
  value you can hold.

## Reverting

`./oblivion-optimizer.py remove` restores stock behaviour. Backups (`Engine.ini.bak-<timestamp>`)
are kept next to `Engine.ini`.

## Sources

* Game configuration extracted from `OblivionRemastered-Windows.pak` (`DefaultEngine.ini`,
  `DefaultScalability.ini`, `BaseScalability.ini`, `DefaultDeviceProfiles.ini`,
  `WindowsDeviceProfiles.ini`) and the cvar table of the shipping executable (UE 5.3.2).
* Epic, Lumen performance guide: https://dev.epicgames.com/documentation/en-us/unreal-engine/lumen-performance-guide-for-unreal-engine
* Epic, console variable priorities: https://dev.epicgames.com/documentation/en-us/unreal-engine/console-variables-cplusplus-in-unreal-engine
* LUMEN BEGONE: https://www.nexusmods.com/oblivionremastered/mods/183
* Lumen OFF without artifacts: https://www.nexusmods.com/oblivionremastered/mods/2516
* No More VRAM Leaks Crashes: https://www.nexusmods.com/oblivionremastered/mods/399
* Shadow quality / volumetric fog scalability bug: https://www.nexusmods.com/oblivionremastered/mods/3585
* Digital Foundry on tweak packs: https://overclock3d.net/news/software/digital-foundry-rubbishes-popular-oblivion-stutter-fix-mods/
* Measured per-setting costs: https://pcoptimizedsettings.com/elder-scrolls-oblivion-remastered-pc-optimized-settings-performance-guide/
* SSR water artefacts: https://steamcommunity.com/app/2623190/discussions/0/604154270792620665
* ProtonDB: https://www.protondb.com/app/2623190
* Proton changelog: https://github.com/ValveSoftware/Proton/wiki/Changelog
* vkd3d-proton: https://github.com/HansKristian-Work/vkd3d-proton
* dxvk-nvapi: https://github.com/jp7677/dxvk-nvapi

## License

BSD 3-Clause, see `LICENSE`.
