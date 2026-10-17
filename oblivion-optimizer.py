#!/usr/bin/env python3
"""Profile-based Engine.ini optimizer for The Elder Scrolls IV: Oblivion Remastered on Linux/Proton.

Linux + Proton (Steam) only. It locates the game's Proton prefix, composes a set of
Unreal Engine console variables from a base profile plus optional features and
one-off overrides, and writes them into the [SystemSettings] section of the user
Engine.ini between two marker lines. Nothing outside the markers is touched, a
timestamped backup is taken before every write, and `remove` restores stock behaviour.

Quick start:
  ./oblivion-optimizer.py list
  ./oblivion-optimizer.py apply lumen-lite --lock
  ./oblivion-optimizer.py apply lumen-lite --feature nofg --fps 60 --lock
  ./oblivion-optimizer.py apply lumen-off --feature dfao-off --lock
  ./oblivion-optimizer.py apply lumen-lite --set r.VolumetricFog.GridPixelSize=32 --unset grass.densityScale
  ./oblivion-optimizer.py status
  ./oblivion-optimizer.py remove

Only the Python standard library is used (Python 3.9+).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import shutil
import sys
from pathlib import Path

APP_ID = "2623190"
TOOL_NAME = "tes-oblivion-optimizer"
MARK_BEGIN = f"; >>> {TOOL_NAME} managed block - do not edit by hand, re-run the tool instead"
MARK_END = f"; <<< {TOOL_NAME} managed block end"
# Markers written by earlier versions of this tool; still recognised so they get replaced, not duplicated.
LEGACY_MARKS = [
    ("; >>> linux-tweaks managed block (oblivion_tweaks.py) - do not edit by hand",
     "; <<< linux-tweaks managed block end"),
]
DEFAULT_FEATURE = "common"

HERE = Path(__file__).resolve().parent
PROFILES_DIR = HERE / "profiles"
FEATURES_DIR = HERE / "features"

ENGINE_INI_REL = (
    "pfx/drive_c/users/steamuser/Documents/My Games/Oblivion Remastered/"
    "Saved/Config/Windows/Engine.ini"
)

STEAM_ROOT_CANDIDATES = [
    "~/.steam/steam",
    "~/.steam/debian-installation",
    "~/.local/share/Steam",
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam",
    "~/snap/steam/common/.local/share/Steam",
]

LAUNCH_OPTIONS = (
    "__GL_SHADER_DISK_CACHE_SKIP_CLEANUP=1 __GL_SHADER_DISK_CACHE_SIZE=12000000000 "
    "gamemoderun mangohud %command%"
)


# --------------------------------------------------------------------------- locating files

def steam_libraries(explicit_root: str | None) -> list[Path]:
    """Return every Steam library path reachable from the known Steam roots."""
    roots = [Path(explicit_root).expanduser()] if explicit_root else [
        Path(p).expanduser() for p in STEAM_ROOT_CANDIDATES
    ]
    libs: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        libs.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(errors="ignore")):
                libs.append(Path(m.group(1).replace("\\\\", "\\")))
    seen: set[Path] = set()
    out: list[Path] = []
    for lib in libs:
        try:
            real = lib.resolve()
        except OSError:
            continue
        if real not in seen:
            seen.add(real)
            out.append(real)
    return out


def find_compatdata(explicit_root: str | None) -> Path | None:
    env = os.environ.get("STEAM_COMPAT_DATA_PATH")
    if env and Path(env).is_dir():
        return Path(env)
    for lib in steam_libraries(explicit_root):
        candidate = lib / "steamapps" / "compatdata" / APP_ID
        if candidate.is_dir():
            return candidate
    return None


def find_engine_ini(args: argparse.Namespace) -> Path:
    if sys.platform != "linux":
        sys.exit("This tool targets Linux + Proton only. On Windows edit Engine.ini directly.")
    if args.engine_ini:
        return Path(args.engine_ini).expanduser()
    compat = find_compatdata(args.steam_root)
    if compat is None:
        sys.exit(
            "Could not find the Proton prefix for app 2623190.\n"
            "Run the game once, or pass --steam-root /path/to/Steam or --engine-ini /path/to/Engine.ini"
        )
    return compat / ENGINE_INI_REL


# --------------------------------------------------------------------------- profile files

def _read_block_file(kind_dir: Path, name: str, kind: str) -> tuple[str, list[tuple[str, str]]]:
    path = kind_dir / f"{name}.ini"
    if not path.is_file():
        available = ", ".join(p.stem for p in sorted(kind_dir.glob("*.ini")))
        sys.exit(f"Unknown {kind} '{name}'. Available: {available}")
    description = ""
    entries: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if not description:
                description = line[1:].strip()
            continue
        if line.startswith(";") or line.startswith("["):
            continue
        if "=" not in line:
            sys.exit(f"{path}: cannot parse line: {raw}")
        key, value = line.split("=", 1)
        entries.append((key.strip(), value.strip()))
    return description, entries


def read_profile(name: str):
    return _read_block_file(PROFILES_DIR, name, "profile")


def read_feature(name: str):
    return _read_block_file(FEATURES_DIR, name, "feature")


def list_names(kind_dir: Path) -> list[str]:
    return sorted(p.stem for p in kind_dir.glob("*.ini"))


# --------------------------------------------------------------------------- composing

class Composition:
    """Ordered cvar table; later sources override earlier ones, last writer wins."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.source: dict[str, str] = {}
        self.order: list[str] = []
        self.source_order: list[str] = []
        self.display: dict[str, str] = {}
        self.overridden: list[tuple[str, str, str]] = []  # (key, loser, winner)

    def add(self, source: str, entries: list[tuple[str, str]]) -> None:
        if source not in self.source_order:
            self.source_order.append(source)
        for key, value in entries:
            lower = key.lower()
            if lower in self.values and self.source[lower] != source:
                self.overridden.append((key, self.source[lower], source))
            if lower not in self.values:
                self.order.append(lower)
            self.values[lower] = value
            self.source[lower] = source
            self.display.setdefault(lower, key)

    def remove(self, key: str) -> bool:
        lower = key.lower()
        if lower not in self.values:
            return False
        del self.values[lower]
        del self.source[lower]
        self.order.remove(lower)
        return True

    def lines(self) -> list[str]:
        """One block per source, in the order sources were added; a key is listed under the source that won."""
        out: list[str] = []
        for src in self.source_order:
            keys = [k for k in self.order if self.source[k] == src]
            if not keys:
                continue
            out.append(f"; ---- {src} ----")
            out.extend(f"{self.display[k]}={self.values[k]}" for k in keys)
        return out


def compose(profile: str, features: list[str], no_common: bool, fps: int | None,
            sets: list[str], unsets: list[str]) -> Composition:
    comp = Composition()
    if not no_common:
        comp.add(f"feature:{DEFAULT_FEATURE}", read_feature(DEFAULT_FEATURE)[1])
    comp.add(f"profile:{profile}", read_profile(profile)[1])
    for feat in features:
        if feat == DEFAULT_FEATURE:
            continue
        comp.add(f"feature:{feat}", read_feature(feat)[1])
    if fps is not None:
        comp.add("fps-cap", [
            ("Altar.GraphicsOptions.FrameRateLimit", str(fps)),
            ("t.MaxFPS", str(fps)),
        ])
    if sets:
        parsed = []
        for item in sets:
            if "=" not in item:
                sys.exit(f"--set expects CVAR=VALUE, got '{item}'")
            k, v = item.split("=", 1)
            parsed.append((k.strip(), v.strip()))
        comp.add("override", parsed)
    for key in unsets:
        if not comp.remove(key):
            print(f"note: --unset {key}: not present in the composition", file=sys.stderr)
    return comp


def header_line(profile: str, features: list[str], no_common: bool, fps: int | None,
                sets: list[str], unsets: list[str]) -> str:
    parts = [f"profile={profile}"]
    feats = ([] if no_common else [DEFAULT_FEATURE]) + [f for f in features if f != DEFAULT_FEATURE]
    parts.append("features=" + (",".join(feats) or "-"))
    parts.append(f"fps={fps if fps is not None else '-'}")
    if sets:
        parts.append("set=" + ";".join(sets))
    if unsets:
        parts.append("unset=" + ";".join(unsets))
    parts.append("applied=" + _dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    return "; " + " ".join(parts)


def build_block(header: str, comp: Composition) -> str:
    body = [MARK_BEGIN, header, "[SystemSettings]", *comp.lines(), MARK_END]
    return "\n".join(body) + "\n"


# --------------------------------------------------------------------------- Engine.ini editing

def split_managed(text: str) -> tuple[str, str | None, str]:
    """Return (before, managed_block_or_None, after); legacy marker pairs are recognised too."""
    lines = text.splitlines(keepends=True)
    for begin, end_mark in [(MARK_BEGIN, MARK_END), *LEGACY_MARKS]:
        start = end = None
        for i, line in enumerate(lines):
            stripped = line.rstrip("\r\n")
            if start is None and stripped == begin:
                start = i
            elif start is not None and stripped == end_mark:
                end = i
                break
        if start is not None and end is not None:
            return "".join(lines[:start]), "".join(lines[start:end + 1]), "".join(lines[end + 1:])
    return text, None, ""


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = path.with_name(f"Engine.ini.bak-{stamp}")
    shutil.copy2(path, dst)
    return dst


def set_readonly(path: Path, readonly: bool, quiet: bool = False) -> None:
    if not path.exists():
        return
    path.chmod(0o444 if readonly else 0o644)
    if not quiet:
        print(f"{'Locked (read-only)' if readonly else 'Unlocked'}: {path}")


def write_engine_ini(path: Path, new_text: str) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bak = backup(path)
    if path.exists():
        path.chmod(0o644)
    path.write_text(new_text, encoding="utf-8")
    return bak


# --------------------------------------------------------------------------- commands

def cmd_list(_args: argparse.Namespace) -> None:
    print("Profiles (pick exactly one):")
    for name in list_names(PROFILES_DIR):
        print(f"  {name:12s} {read_profile(name)[0]}")
    print(f"\nFeatures (combine freely with --feature; '{DEFAULT_FEATURE}' is on unless --no-common):")
    for name in list_names(FEATURES_DIR):
        print(f"  {name:12s} {read_feature(name)[0]}")


def cmd_apply(args: argparse.Namespace) -> None:
    ini = find_engine_ini(args)
    comp = compose(args.profile, args.feature, args.no_common, args.fps, args.set, args.unset)
    header = header_line(args.profile, args.feature, args.no_common, args.fps, args.set, args.unset)
    block = build_block(header, comp)
    for key, loser, winner in comp.overridden:
        print(f"note: {key} from {loser} overridden by {winner}", file=sys.stderr)
    text = ini.read_text(encoding="utf-8") if ini.exists() else ""
    before, _old, after = split_managed(text)
    if before and not before.endswith("\n"):
        before += "\n"
    if before and not before.endswith("\n\n"):
        before += "\n"
    new_text = before + block + after
    if args.dry_run:
        sys.stdout.write(block)
        return
    bak = write_engine_ini(ini, new_text)
    print(f"Applied: {header[2:]}\n  -> {ini}")
    if bak:
        print(f"Backup: {bak}")
    if args.lock:
        set_readonly(ini, True)


def cmd_show(args: argparse.Namespace) -> None:
    ini = find_engine_ini(args)
    if not ini.exists():
        print(f"{ini} does not exist yet (run the game once).")
        return
    _b, block, _a = split_managed(ini.read_text(encoding="utf-8"))
    print(block if block else "No managed block present (stock configuration).")


def cmd_status(args: argparse.Namespace) -> None:
    ini = find_engine_ini(args)
    print(f"Engine.ini : {ini}")
    if not ini.exists():
        print("state      : file missing (run the game once)")
        return
    mode = ini.stat().st_mode & 0o222
    print(f"lock       : {'read-only (locked)' if mode == 0 else 'writable'}")
    _b, block, _a = split_managed(ini.read_text(encoding="utf-8"))
    if block is None:
        print("applied    : nothing (stock)")
    else:
        print("applied    : " + block.splitlines()[1][2:])
        count = sum(1 for l in block.splitlines() if "=" in l and not l.startswith(";"))
        print(f"cvars      : {count}")
    backups = sorted(ini.parent.glob("Engine.ini.bak-*"))
    print(f"backups    : {len(backups)}" + (f" (latest {backups[-1].name})" if backups else ""))


def cmd_remove(args: argparse.Namespace) -> None:
    ini = find_engine_ini(args)
    if not ini.exists():
        print("Engine.ini does not exist; nothing to remove.")
        return
    before, block, after = split_managed(ini.read_text(encoding="utf-8"))
    if block is None:
        print("No managed block found; nothing to remove.")
        set_readonly(ini, False, quiet=True)
        return
    bak = write_engine_ini(ini, before.rstrip("\n") + "\n" + after)
    print(f"Removed managed block (stock behaviour restored, file left writable)\n  -> {ini}\nBackup: {bak}")


def cmd_lock(args: argparse.Namespace) -> None:
    set_readonly(find_engine_ini(args), True)


def cmd_unlock(args: argparse.Namespace) -> None:
    set_readonly(find_engine_ini(args), False)


def cmd_launch_options(_args: argparse.Namespace) -> None:
    print(LAUNCH_OPTIONS)


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="oblivion-optimizer",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--engine-ini", help="explicit path to the user Engine.ini (skips detection)")
    ap.add_argument("--steam-root", help="Steam installation root to search (default: known locations)")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list profiles and features").set_defaults(func=cmd_list)

    p_apply = sub.add_parser("apply", help="compose and write a profile into Engine.ini")
    p_apply.add_argument("profile", help="base profile name (see list)")
    p_apply.add_argument("--feature", "-f", action="append", default=[], metavar="NAME",
                         help="add a feature block (repeatable, applied in order)")
    p_apply.add_argument("--no-common", action="store_true",
                         help=f"do not include the default '{DEFAULT_FEATURE}' feature")
    p_apply.add_argument("--fps", type=int, metavar="N", help="pin the in-game frame rate limit to N")
    p_apply.add_argument("--set", action="append", default=[], metavar="CVAR=VALUE",
                         help="one-off override, wins over profile and features (repeatable)")
    p_apply.add_argument("--unset", action="append", default=[], metavar="CVAR",
                         help="drop a cvar from the composition so the game default applies (repeatable)")
    p_apply.add_argument("--lock", action="store_true", help="make Engine.ini read-only afterwards")
    p_apply.add_argument("--dry-run", action="store_true", help="print the block instead of writing")
    p_apply.set_defaults(func=cmd_apply)

    sub.add_parser("show", help="print the managed block currently in Engine.ini").set_defaults(func=cmd_show)
    sub.add_parser("status", help="where Engine.ini is, lock state, what is applied").set_defaults(func=cmd_status)
    sub.add_parser("remove", help="remove the managed block (back to stock)").set_defaults(func=cmd_remove)
    sub.add_parser("lock", help="make Engine.ini read-only").set_defaults(func=cmd_lock)
    sub.add_parser("unlock", help="make Engine.ini writable").set_defaults(func=cmd_unlock)
    sub.add_parser("launch-options", help="print suggested Steam launch options").set_defaults(func=cmd_launch_options)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
