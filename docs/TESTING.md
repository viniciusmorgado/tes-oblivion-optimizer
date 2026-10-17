# Test log

What was tried, in order, on the reference machine, what each step changed relative to the
previous one, what was deliberately left alone, and the observed effect. Observations are
qualitative (played, not benchmarked) unless a number is given. Add your own runs at the end,
same format.

Reference machine: Ryzen 5 5600, RTX 4060 8 GB, 32 GB RAM, NVIDIA 595.104, Pop!_OS (COSMIC,
Wayland), Proton 11.0-2e, 1920x1080 @ 100 Hz, game 1.512.105 (UE 5.3.2).

In-game settings held constant across every run: all quality groups High (`sg.*=2`), DLSS as
upscaler and anti-aliasing, Frame Generation on, Lumen Hardware RT off, VSync on, no frame cap,
texture quality High. These were not touched by any profile.

## Run 0 - stock (baseline)

* Engine.ini: only the `[Core.System]` paths the game writes itself.
* Effect: playable but at the limit; dense exteriors drop hard, software Lumen GI + Lumen
  reflections + mesh-SDF tracing (all forced by "High") are the dominant GPU costs.

## Run 1 - `ssgi` profile (+ `common`)

Changed from stock:

| area | cvars | from | to |
|---|---|---|---|
| GI method | `r.DynamicGlobalIlluminationMethod` | 1 (Lumen) | 2 (Screen Space GI) |
| Reflection method | `r.ReflectionMethod` | 1 (Lumen) | 2 (SSR) |
| Lumen | `r.Lumen.DiffuseIndirect.Allow`, `r.Lumen.Reflections.Allow`, `r.Lumen.TranslucencyReflections.FrontLayer.*`, `r.Lumen.HardwareRayTracing`, `r.Lumen.TraceMeshSDFs.Allow` | on | off |
| SSGI | `r.SSGI.Quality` 3, `r.SSGI.LeakFreeReprojection` 1 | scalability value 2 | 3 |
| AO fallback | `r.DistanceFieldAO` 1, `r.AOQuality` 1, `r.AmbientOcclusionLevels` 2, `r.AmbientOcclusionMaxQuality` 60 | DFAO on (High), SSAO max 30 (game override) | explicit |
| Skylight | `r.SkylightIntensityMultiplier` | 1.0 | 0.8 |
| `common` | VSM LOD bias 0/0.5/1/2 and 4 SMRT rays; fog grid 24 px, supersample 1; cloud samples 384/40, shadow map 256; grass/foliage density 0.6, LOD distance 0.8; lens flare 0, fringe 0, bloom 35 %, tonemapper 2, half-res motion blur gather; sky atmosphere 32 samples; SSS sample set 0; streaming pool 2300 MB | High values (VSM bias -0.5, 8 rays; fog 16 px x4; grass 0.8; pool 2000) | as listed |

Left alone: SSR quality (menu toggle still works), DLSS/FG/Reflex, texture quality, motion
blur, DoF, PSO/shader pipeline cache (pinned by the game's device profile, cannot be changed).

Observed:

* Frame rate up substantially ("substancialmente") versus stock; biggest gain of all runs.
* Bushes and leaves look wrong: shimmering/flicker on small foliage. Cause: Distance Field AO
  becoming the only ambient term once Lumen is gone (the community sees the same with the
  `r.Lumen.DiffuseIndirect.Allow=0` route). Fix is the `dfao-off` feature, at the cost of
  flatter interiors.
* Frame pacing not stable despite the high average. Likely contributors: first-session
  shader/PSO recompilation after a renderer change, VSync on + Frame Generation, host RAM
  pressure (16 GB used by other apps plus 8 GB in zram before launch).

Verdict: fastest, but not the look wanted.

## Run 2 - `lumen-lite` profile (+ `common`)

Changed from Run 1: Lumen GI back on, SSGI not used; Lumen cost cut instead.

| area | cvars | from (High) | to |
|---|---|---|---|
| GI method | `r.DynamicGlobalIlluminationMethod` | 1 | 1 (unchanged, explicit) |
| Lumen reflections | `r.Lumen.Reflections.Allow`, `r.Lumen.TranslucencyReflections.FrontLayer.*` | on | off; `r.ReflectionMethod=2` (SSR) |
| Mesh SDF tracing | `r.Lumen.TraceMeshSDFs.Allow` | 1 (High re-enables it) | 0 (global SDF only) |
| Surface cache | `AtlasSize` 2048, `CardTexelDensityScale` 50, `CardMaxResolution` 256, `CardCaptureFactor` 32 | 4096 / 100 / 512 / 64 | between the game's Series S profile and PC High |
| Global SDF | `r.LumenScene.GlobalSDF.Resolution` 128, `SimpleCoverageBasedExpand` 1 | default | as listed |
| Radiosity | `ProbeSpacing` 8, `HemisphereProbeResolution` 3 | same | unchanged, explicit |
| Final gather | `ScreenProbeGather.DownsampleFactor` 32, `TracingOctahedronResolution` 8, `RadianceCache.ProbeResolution` 16, `ProbeAtlasResolutionInProbes` 64, `NumProbesToTraceBudget` 200, `ShortRangeAO` 0, `DiffuseIndirect.SSAO` 1 | 32 / 8 / 32 (game High) / 128 / 300 / 0 / 1 | as listed |
| Translucency volume | `GridPixelSize` 64, `TraceFromVolume` 0, `RadianceCache.ProbeResolution` 8 | same | unchanged, explicit |
| `common` | same block as Run 1 | | |

Left alone: same list as Run 1, plus DFAO (stays at the game's High value, no longer the
only AO source because Lumen is back).

Observed:

* Less frame rate than `ssgi`, clearly more than stock.
* Foliage normal again; lighting close to the stock High look.
* Judged "by far the best optimized" setup of the session: the balance the user wanted. This
  run is what the `balanced` preset reproduces.

## Not tested yet

* `lumen-off` (community route, GI method stays Lumen but disallowed) with or without
  `dfao-off`: expected to match `ssgi` performance without the SSGI colour bleed.
* `nofg` + `--fps 60` on top of `lumen-lite` (`balanced-60` preset): the apply was prepared
  but the game was running both times, so Run 2 was played with Frame Generation on and no cap.
* `csm`, `lowfx`, `pso`, `ssr-off`, `vsync-off` features: defined, not yet played.
* Any numbers: no MangoHud captures yet. Suggested spots for a repeatable comparison: Imperial
  City waterfront facing the city, the Great Forest west of Chorrol, an Ayleid ruin interior.

## System-side findings (not part of any profile)

* Resizable BAR is off on the reference machine (BAR1 = 256 MiB); enabling it in the UEFI
  is pending.
* 16 GB of host RAM in use and 8 GB in zram swap before launching the game; not yet
  re-tested with the IDE and browsers closed.
* `amd-pstate-epp` at `balance_performance`; `gamemoderun` not yet installed.
* Proton 11 reports ntsync active; NVAPI/DLSS/FG work without extra variables.

## Template for new entries

```
## Run N - <preset or profile + features> (<date>, <hardware>)
Changed from Run N-1: ...
Left alone: ...
Observed: average / 1 % low / pacing / visual notes
Verdict:
```
