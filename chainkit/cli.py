"""ChainKit command line (chainkit-cli.bat on Windows, ./chainkit-cli.sh on macOS / Linux).

  build    --iso SRC.iso [--out NEW.iso] [--dominator DOMINATOR.iso] [--preset NAME] [--settings FILE.json]
           [--set NAME=VALUE ...]                         new ISO with the mod (your ISO is only read)
  tune     SRC.iso NEW.iso [--preset/--settings/--set] [--dominator ...]
                                                          new ISO = an ISO that has the mod, with other settings
  validate SRC.iso NEW.iso [--dominator DOMINATOR.iso] [--quick]
  info     ISO                                            what is on an ISO (mod? settings? other kits?)
  settings [ISO] [--raw]                                  every setting (with the values of ISO)
  presets                                                 the presets
  export   (ISO | --preset NAME) FILE.json                save settings to a file (to edit or share)
  gui                                                     the window (ChainKit.bat / ChainKit.command)

Settings are applied in this order: --preset (or the ISO's own settings for tune), then --settings, then --set.
"""
import argparse
import json
import os
import sys

from . import cave, core, settings


def _parse_set(items):
    """--set NAME=VALUE: numbers / colours by setting name, switches by their own name (NAME=on|off)."""
    out = {}
    switches = []
    for it in items or []:
        k, sep, v = it.partition("=")
        k, v = k.strip(), v.strip()
        if sep and k in settings.SWITCHES:
            if v.lower() not in settings.ON_WORDS + settings.OFF_WORDS:
                raise core.KitError("--set %s: use on or off" % it)
            switches.append((k, v.lower() in settings.ON_WORDS))
            continue
        if not sep or k not in settings.TYPES:
            raise core.KitError("--set %s: unknown setting (run 'settings' for the list)" % it)
        t = settings.TYPES[k]
        try:
            out[k] = (v if t == "c" else int(v, 0) if t == "i" else float(v))
        except ValueError:
            raise core.KitError("--set %s: not a number" % it)
    if switches:
        out["__switches__"] = switches
    return out


def _values(a, base):
    if a.preset:
        if a.preset not in settings.PRESETS:
            raise core.KitError("unknown preset '%s' (presets: %s)" % (a.preset, ", ".join(settings.PRESETS)))
        base = settings.PRESETS[a.preset]
    v = dict(base)
    if a.settings:
        v.update(settings.load(a.settings))
    sets = _parse_set(a.set)
    switches = sets.pop("__switches__", [])
    v.update(sets)
    for name, on in switches:
        v = settings.set_switch(v, name, on)
    return settings.check(v)


def _progress(f, m):
    sys.stdout.write("\r%5.1f%%  %-50s" % (100 * f, m[:50]))
    sys.stdout.flush()
    if f >= 1.0:
        sys.stdout.write("\n")


def _value_args(p):
    p.add_argument("--preset", help="start from a preset (see 'presets')")
    p.add_argument("--settings", metavar="FILE.json", help="settings file (from 'export' or the window)")
    p.add_argument("--set", action="append", metavar="NAME=VALUE", help="one setting (see 'settings')")
    p.add_argument("--dominator", metavar="DOMINATOR.iso", help="your Burnout Dominator ISO (arrow art)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="chainkit", description="Burnout Dominator's supercharge and Burnout chain for "
                                 "Burnout Revenge (PS2, Europe and USA). Always writes a new ISO.")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("build", help="new ISO with the mod")
    p.add_argument("--iso", required=True); p.add_argument("--out"); _value_args(p)
    p.add_argument("--no-validate", action="store_true")
    p = sub.add_parser("tune", help="change the settings of an ISO that has the mod (writes a new ISO)")
    p.add_argument("source"); p.add_argument("output"); _value_args(p)
    p.add_argument("--no-validate", action="store_true")
    p = sub.add_parser("validate", help="check a new ISO against the ISO it was made from")
    p.add_argument("source"); p.add_argument("output"); p.add_argument("--dominator"); p.add_argument("--quick", action="store_true")
    p = sub.add_parser("info", help="what is on an ISO"); p.add_argument("iso")
    p = sub.add_parser("settings", help="list the settings"); p.add_argument("iso", nargs="?")
    p.add_argument("--raw", action="store_true", help="raw names and values (for --set)")
    sub.add_parser("presets", help="list the presets")
    p = sub.add_parser("export", help="save settings to a .json file")
    p.add_argument("args", nargs="+", metavar="ISO FILE.json | FILE.json")
    p.add_argument("--preset")
    p = sub.add_parser("gui", help="open the window")
    p.add_argument("--shot", metavar="FILE.png", help=argparse.SUPPRESS)
    p.add_argument("--demo", metavar="DEMO.json", help=argparse.SUPPRESS)
    p.add_argument("--size", metavar="WxH", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    try:
        return _run(a, ap)
    except (core.KitError, ValueError, OSError) as exc:
        print("\nERROR: %s" % exc, file=sys.stderr)
        return 2


def _run(a, ap):
    if a.cmd == "gui":
        from . import gui
        demo = None
        if a.demo:
            with open(a.demo, encoding="utf-8") as f:
                demo = json.load(f)
        size = tuple(int(x) for x in a.size.lower().split("x")) if a.size else None
        return gui.main(a.shot, demo, size)
    if a.cmd == "build":
        out = a.out or core.default_output(a.iso)
        values = _values(a, settings.DEFAULTS)
        core.build(a.iso, out, values, a.dominator, progress=_progress)
        return 0 if a.no_validate or core.validate(a.iso, out, a.dominator) else 1
    if a.cmd == "tune":
        with core.Disc(a.source) as d:
            if not d.values:
                for p in d.problems():
                    raise core.KitError(p)
                raise core.KitError("this ISO does not have the Burnout Chain mod yet - use 'build'")
            base = d.values
        values = _values(a, base)
        core.tune(a.source, a.output, values, a.dominator, progress=_progress)
        return 0 if a.no_validate or core.validate(a.source, a.output, a.dominator) else 1
    if a.cmd == "validate":
        return 0 if core.validate(a.source, a.output, a.dominator, quick=a.quick) else 1
    if a.cmd == "info":
        with core.Disc(a.iso) as d:
            print(d.summary())
            for p in d.problems():
                print("PROBLEM: " + p)
            if d.applied and not d.musickit:
                print("note: to add MusicKit songs, run MusicKit on the ISO without ChainKit first, then ChainKit")
            if d.values:
                print("arrow art: %s" % ("Burnout Dominator" if d.arrow_art == "dominator" else "Revenge's chevron"))
                print("settings: %s" % (settings.preset_of(d.values) or "custom"))
                for line in settings.describe(d.values):
                    print(line)
        return 0
    if a.cmd == "settings":
        values = settings.DEFAULTS
        if a.iso:
            with core.Disc(a.iso) as d:
                if not d.values:
                    raise core.KitError("this ISO does not have the Burnout Chain mod (or an older version)")
                values = d.values
        if a.raw:
            for name, off, t, default, help_ in cave.TUNABLES:
                v = values[name]
                txt = ",".join("%g" % x for x in v) if t == "c" else ("%g" % v if t == "f" else "%#x" % v)
                print("%-24s %-22s %s" % (name, txt, help_))
        else:
            for line in settings.describe(values):
                print(line)
        return 0
    if a.cmd == "presets":
        for name, info in settings.PRESET_INFO.items():
            print("%-18s %s" % (name, info))
        return 0
    if a.cmd == "export":
        if a.preset:
            if len(a.args) != 1:
                raise core.KitError("export --preset NAME FILE.json")
            if a.preset not in settings.PRESETS:
                raise core.KitError("unknown preset '%s'" % a.preset)
            values, path = settings.PRESETS[a.preset], a.args[0]
        else:
            if len(a.args) != 2:
                raise core.KitError("export ISO FILE.json   or   export --preset NAME FILE.json")
            with core.Disc(a.args[0]) as d:
                if not d.values:
                    raise core.KitError("this ISO does not have the Burnout Chain mod")
                values = d.values
            path = a.args[1]
        settings.save(path, values)
        print("saved %s" % os.path.abspath(path))
        return 0
    ap.print_help()
    return 0
