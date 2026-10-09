"""ChainKit settings: defaults, presets, plain-words descriptions, human units and the settings file format.

Values are the raw numbers stored in the game executable (see cave.TUNABLES). The window and the descriptions
below show them in human units (seconds, %, km/h, "near misses for all arrows"); a settings file stores the raw
values, so a file exported and imported again gives exactly the same disc.
"""
import json
import math
import struct

from . import cave

KIT = "ChainKit"
FILE_VERSION = 1
TYPES = {n: t for n, off, t, d, h in cave.TUNABLES}
DEFAULTS = {n: d for n, off, t, d, h in cave.TUNABLES}
HELP = {n: h for n, off, t, d, h in cave.TUNABLES}
FLAGS = dict(popups=cave.FL_MSG, arrows=cave.FL_ARROWS, tint=cave.FL_TINT, sounds=cave.FL_SOUND, slow_rule=cave.FL_SLOW,
             no_earn_while_boosting=cave.FL_NOEARN, full_bar=cave.FL_FULLBAR, show_size_label=cave.FL_SHOWLABEL,
             show_boost_hint=cave.FL_SHOWHINT, boost_without_button=cave.FL_FREEBOOST, debug_boost=cave.FL_DEBUG,
             fill_fire=cave.FL_FILLFIRE)
MODES = {key: 1 << bit for bit, key, _ in cave.MODES if key != "online"}
ALL_MODES = sum(MODES.values())
ALL_FLAGS = sum(FLAGS.values())
MPH = 2.2369363
# reference speeds for "seconds" shown for the distance-based actions
ONCOMING_SPEED, DRIFT_SPEED = 70.0, 55.0          # m/s (about 250 / 200 km/h)
# Revenge's boost per metre (oncoming 0.3, drift 1.0) x the bar multiplier of the 4-segment bar (4)
ONCOMING_PER_M, DRIFT_PER_M, FULL_BAR = 0.3 * 4, 1.0 * 4, 400.0


def f32(x):
    return struct.unpack("<f", struct.pack("<f", float(x)))[0]


# ------------------------------------------------------------------------------------------- human units
def _inv(x):
    return 1.0 / x if x > 0 else 0.0


class Unit:
    """raw <-> shown value. `fmt` formats the shown value; lo/hi = slider range of the shown value."""

    def __init__(self, to_ui, from_ui, fmt, lo, hi, suffix=""):
        self.to_ui, self.from_ui, self.fmt, self.lo, self.hi, self.suffix = to_ui, from_ui, fmt, lo, hi, suffix


def pct(lo, hi):
    return Unit(lambda r: 100.0 * r, lambda u: u / 100.0, "%.0f %%", lo, hi)


def times(lo, hi):
    return Unit(lambda r: r, lambda u: u, "x%.2f", lo, hi)


def secs(lo, hi):
    return Unit(lambda r: r, lambda u: u, "%.1f s", lo, hi)


def per(fmt, lo, hi, scale=1.0):
    """weight per unit <-> amount for all arrows (count, metres, seconds)."""
    return Unit(lambda r: _inv(r * scale), lambda u: _inv(u * scale), fmt, lo, hi)


SPEED = Unit(lambda r: r * 3.6, lambda u: u / 3.6, "%.0f km/h", 20.0, 250.0)


class Item:
    def __init__(self, key, label, help_, unit=None, kind=None, bit=None, invert=False):
        self.key, self.label, self.help, self.unit, self.bit = key, label, help_, unit, bit
        self.invert = invert          # checkbox ticked = bit CLEAR
        self.kind = kind or ("colour" if TYPES.get(key) == "c" else "int" if TYPES.get(key) == "i" else "float")


def flag(name, label, help_, invert=False, cli=None):
    it = Item("flags", label, help_, kind="flag", bit=FLAGS[name], invert=invert)
    it.cli = cli or name
    return it


def is_on(item, values):
    """Checkbox state of a flag / mode item."""
    return bool(values[item.key] & item.bit) != item.invert


def mode(name, label, help_):
    it = Item("modes", label, help_, kind="mode", bit=MODES[name])
    it.cli = "mode_" + name
    return it


GROUPS = [
    ("Game modes", "The mod is used in the modes ticked here. Crash mode and online races always play like the "
                   "original game.", [
        mode("race", "Race and Grand Prix", "Normal races, also every race of a Grand Prix."),
        mode("road_rage", "Road Rage", "Takedown events. A takedown fills the bar and supercharges it."),
        mode("burning_lap", "Burning Lap", "One-lap time trials."),
        mode("preview_lap", "Preview Lap", "Preview Lap events (the game runs them with the Burning Lap mode)."),
        mode("eliminator", "Eliminator", "Last car at the end of each lap is out."),
        mode("traffic_attack", "Traffic Attack", "Score by checking traffic. Checked cars give boost and arrows."),
        mode("splitscreen", "Split-screen races", "Two players on one PlayStation 2 (Race, Road Rage ...)."),
        mode("other", "Other events", "Any event not listed above (for example special World Tour events)."),
    ]),
    ("Supercharge and Burnout rules", "How the supercharged (blue) bar works.", [
        flag("full_bar", "Always the full 4-segment bar",
             "Your bar is always the full 4 segments, like in Dominator. Off: Revenge's own bar sizes "
             "(the bar grows with takedowns and shrinks when you crash)."),
        flag("no_earn_while_boosting", "No boost earning while boosting (Dominator rule)",
             "Dominator rule: while you boost on a normal bar, driving skills give no boost. Off: you keep "
             "earning, so a long boost can fill the bar and supercharge it."),
        Item("drain_mult", "Supercharged boost drains faster", "A supercharged bar empties this many times faster "
             "than a normal one (Dominator: x3).", times(1.0, 6.0)),
        Item("half", "Refill base", "When a supercharged bar runs empty it refills to this much of the bar plus "
             "the lit arrows. Also the size of the arrow pool (Dominator: 50 %).", pct(10, 100)),
        Item("refill_cap", "Partial refill (not all arrows lit)", "If not all arrows were lit, the bar refills "
             "to at most this much and the supercharge is lost (Dominator: 80 %).", pct(10, 100)),
        Item("full_threshold", "Bar counts as full at", "The bar supercharges when it is at least this full. "
             "Slightly below 100 % so a bar that the game keeps topped up while you boost still counts.",
             pct(80, 100)),
        flag("slow_rule", "Lose the supercharge when too slow",
             "Supercharge-boosting below the speed below for the time below ends the supercharge."),
        Item("slow_speed", "Too slow below", "Speed for the rule above (96 km/h = 60 mph).", SPEED),
        Item("slow_time", "Too slow for", "Seconds below that speed before the supercharge is lost.", secs(0.5, 10)),
        Item("takedown_grace", "Takedown camera grace", "After a takedown, a hit while you are not boosting does "
             "not end the supercharge for this many seconds. Letting go of boost never counts while the game drives "
             "your car (takedown camera); once you drive again you have 0.3 s to press boost, otherwise it is a "
             "release. (With 'Only boost while the button is held' off, this grace also covers letting go.)",
             secs(0, 15)),
        Item("resuper_cooldown", "Wait before supercharging again", "After a supercharge was lost, the bar can "
             "only supercharge again after this many seconds.", secs(0, 10)),
        Item("full_hold_time", "Full while boosting: wait", "When the bar becomes full while you are boosting, "
             "it supercharges after this many seconds (0 = at once).", secs(0, 5)),
        Item("anim_time", "Pause after a refill", "After the bar supercharges or refills, it does not drain for "
             "this many seconds.", secs(0, 3)),
        Item("domination_chain", "BURNOUT DOMINATION! at chain", "The chain length that shows "
             "BURNOUT DOMINATION! instead of BURNOUT! xN.", Unit(lambda r: r, lambda u: int(u), "%d", 2, 50)),
        Item("wow_chain", "BURNOUT! WOW above chain", "Chains longer than this show BURNOUT! WOW "
             "(999 = never).", Unit(lambda r: r, lambda u: int(u), "%d", 2, 999)),
    ]),
    ("Normal bar fill (before the supercharge)", "How fast driving fills the normal bar on the way to the "
                                                 "supercharge. 100 % = the amount the original game gives.", [
        Item("fill_mult", "All actions", "Speed for every action at once. The single actions below are "
             "multiplied by this.", pct(25, 400)),
        Item("fill_w_oncoming", "Oncoming", "Driving in the oncoming lane.", pct(0, 300)),
        Item("fill_w_drift", "Drift", "Drifting.", pct(0, 300)),
        Item("fill_w_near_miss", "Near miss", "Passing traffic closely.", pct(0, 300)),
        Item("fill_w_air", "Air", "Jumps.", pct(0, 300)),
        Item("fill_w_checked_traffic", "Checked traffic", "Ramming traffic cars out of the way "
             "(Traffic Attack ...).", pct(0, 300)),
        Item("fill_w_tailgating", "Tailgating", "Driving close behind a rival.", pct(0, 300)),
        Item("fill_w_grinding", "Grinding", "Scraping along a rival.", pct(0, 300)),
        Item("fill_w_rubbing", "Rubbing", "Rubbing against a rival (per second).", pct(0, 300)),
        Item("fill_w_trading_paint", "Trading paint", "Short hits on a rival.", pct(0, 300)),
        Item("fill_w_slam", "Slam", "Slamming a rival. Revenge gives a lot (360); 4 % is about 1/6 of the bar.",
             pct(0, 300)),
        Item("fill_w_crash_escape", "Crash escape", "Getting away after a near-crash.", pct(0, 300)),
    ]),
    ("Arrows (while supercharge-boosting)", "The arrows over the bar. The more are lit when the bar runs "
                                            "empty, the more it refills; all lit = BURNOUT and the chain goes up.", [
        Item("arrow_gain", "All actions", "Speed for every action at once.", pct(25, 400)),
        Item("w_near_miss", "Near misses for all arrows", "How many near misses light all arrows.",
             per("%.1f", 1, 20)),
        Item("w_checked_traffic", "Checked cars for all arrows", "How many checked traffic cars light all "
             "arrows.", per("%.1f", 1, 20)),
        Item("w_oncoming", "Oncoming: seconds for all arrows", "Seconds of oncoming driving at about 250 km/h "
             "that light all arrows.", per("%.1f s", 1, 30, ONCOMING_SPEED)),
        Item("w_drift", "Drift: seconds for all arrows", "Seconds of drifting at about 200 km/h that light all "
             "arrows.", per("%.1f s", 1, 30, DRIFT_SPEED)),
        Item("w_air", "Air: metres for all arrows", "Metres of jumps that light all arrows.", per("%.0f m", 5, 300)),
        Item("w_tailgating", "Tailgating: seconds for all arrows", "", per("%.1f s", 1, 60)),
        Item("w_grinding", "Grinding: seconds for all arrows", "", per("%.1f s", 1, 60)),
        Item("w_rubbing", "Rubbing: seconds for all arrows", "", per("%.1f s", 1, 60)),
        Item("arrows_slam", "Slams for all arrows", "How many slams light all arrows.", per("%.1f", 1, 20)),
        Item("arrows_takedown", "Takedown lights", "Part of the arrows a takedown lights (Dominator: all).",
             pct(0, 100)),
    ]),
    ("Display and sound", "", [
        flag("popups", "Pop-up messages", "SUPERCHARGE READY!, BURNOUT! xN, BURNOUT DOMINATION!, "
             "SUPERCHARGE LOST."),
        flag("sounds", "Sounds", "A sound when the bar supercharges, on every BURNOUT and when the supercharge "
             "is lost."),
        flag("tint", "Blue bar while supercharged", "The boost bar turns blue while it is supercharged."),
        flag("boost_without_button", "Only boost while the button is held",
             "Your car boosts only while you hold the boost button. Any boost the button does not back (for "
             "example a boost the game keeps going after a takedown or a Perfect Start) stops at once. Off: "
             "Revenge's own behaviour (a tap gives a short boost, a Perfect Start boosts on its own).", invert=True,
             cli="only_boost_while_held"),
        flag("arrows", "Arrows", "Draw the arrows over the bar. Off: no arrows are drawn and none are lit, "
             "so every refill is partial."),
        flag("show_size_label", "Show the x2 - x4 bar-size label", "Revenge's label at the end of the bar. "
             "Hidden by default (the bar is always x4 and the label covered the arrows)."),
        flag("show_boost_hint", "Show the PRESS R1 TO BOOST hint", "Revenge shows it when you have boost and "
             "do not use it for 5 seconds. Hidden by default: with this mod you often wait for the supercharge "
             "on purpose."),
        flag("fill_fire", "Bar fire while the bar fills up",
             "Revenge also draws the fire on the boost bar while a refill is being animated (after a takedown or "
             "a BURNOUT), even when you are not boosting. Off: the fire shows only while you really boost."),
        flag("debug_boost", "Debug: show stopped boosts",
             "For testing: pop-ups name every boost the mod stops or refuses. BOOST STOP: TAP END = you let go "
             "(a tap ends at once); BOOST BLOCKED: GAME START = the game (takedown autopilot) tried to boost without "
             "your button; BOOST STOP: PAD / AUTO = a boost the button did not back was stopped."),
        Item("arrow_count", "Number of arrows", "How many arrows are drawn over the bar. Only the look: the "
             "share of the arrows each action lights stays the same. 18 fill the bar edge to edge.",
             Unit(lambda r: r, lambda u: int(u), "%d", 8, 32)),
        Item("arrow_margin", "Arrow row margin", "Space between the ends of the bar and the first / last arrow "
             "(the bar is 290 units long).", Unit(lambda r: r, lambda u: u, "%.1f", 0, 40)),
        Item("lit_rgba", "Lit arrow colour", "Colour of a lit arrow (Dominator: cyan)."),
        Item("dark_rgba", "Unlit arrow colour", "Colour of an unlit arrow."),
        Item("shadow_rgba", "Arrow outline", "Dark outline drawn behind every arrow."),
    ]),
]
ITEMS = [it for _, _, items in GROUPS for it in items]
SHOWN = {it.key for it in ITEMS}
HIDDEN = [n for n in DEFAULTS if n not in SHOWN]      # arrow_tex_slot: set from the arrow texture choice

# every on/off switch by its own name (command line --set NAME=on|off, settings list): no bit masks needed
SWITCHES = {it.cli: it for it in ITEMS if it.kind in ("flag", "mode")}
ON_WORDS, OFF_WORDS = ("on", "1", "yes", "true"), ("off", "0", "no", "false")


def set_switch(values, name, on):
    """values with switch `name` turned on/off (handles the inverted ones)."""
    it = SWITCHES[name]
    bit_set = bool(on) != it.invert
    v = dict(values)
    v[it.key] = (v[it.key] | it.bit) if bit_set else (v[it.key] & ~it.bit)
    return v


# ------------------------------------------------------------------------------------------- presets
PRESET_INFO = {
    "Default (tested)": "The settings tested in PCSX2: Dominator's supercharge and Burnout chain with Revenge's "
                        "driving, a little faster to fill.",
    "Dominator rules": "Closer to Burnout Dominator: no boost earning while boosting on a normal bar, no wait "
                       "before a new supercharge.",
    "Easy": "Fills faster, drains slower, refills more, no slow-speed rule.",
    "Hard": "Fills slower, drains faster, refills less, the slow-speed rule starts at 113 km/h (70 mph) after "
            "2 seconds, and no earning while boosting.",
}


def _preset(**changes):
    v = dict(DEFAULTS)
    flags_on = changes.pop("flags_on", 0)
    flags_off = changes.pop("flags_off", 0)
    v.update(changes)
    v["flags"] = (v["flags"] | flags_on) & ~flags_off
    return v


PRESETS = {
    "Default (tested)": _preset(),
    "Dominator rules": _preset(flags_on=cave.FL_NOEARN, resuper_cooldown=0.0),
    "Easy": _preset(fill_mult=1.6, arrow_gain=1.5, drain_mult=2.0, refill_cap=0.9, takedown_grace=6.0,
                    resuper_cooldown=1.5, flags_off=cave.FL_SLOW),
    "Hard": _preset(fill_mult=0.9, arrow_gain=0.75, drain_mult=3.5, refill_cap=0.7, slow_speed=70.0 / MPH,
                    slow_time=2.0, flags_on=cave.FL_NOEARN),
}

# raw value limits (checked for every value from the window, the command line or a settings file)
LIMITS = dict(drain_mult=(0.1, 20.0), refill_cap=(0.01, 1.0), half=(0.01, 1.0), full_threshold=(0.5, 1.0),
              slow_speed=(0.0, 150.0), slow_time=(0.0, 120.0), anim_time=(0.0, 10.0), takedown_grace=(0.0, 60.0),
              resuper_cooldown=(0.0, 60.0), full_hold_time=(0.0, 60.0), fill_mult=(0.0, 20.0),
              arrow_gain=(0.0, 20.0), arrows_takedown=(0.0, 1.0), domination_chain=(1, 9999),
              wow_chain=(1, 9999), flags=(0, ALL_FLAGS), modes=(0, ALL_MODES), arrow_tex_slot=(12, 28),
              arrow_count=(1, 32), arrow_margin=(0.0, 100.0))


def check(values):
    """Complete + validate a settings dict (missing names = defaults). Raises ValueError in plain words."""
    out = dict(DEFAULTS)
    for name, v in (values or {}).items():
        if name not in TYPES:
            raise ValueError("unknown setting '%s' (run 'chainkit settings' for the list)" % name)
        t = TYPES[name]
        try:
            if t == "c":
                v = cave.parse_colour(v)
            elif t == "i":
                v = int(v, 0) if isinstance(v, str) else int(v)
                if isinstance(values[name], float) and values[name] != v:
                    raise ValueError
            else:
                v = float(v)
                if not math.isfinite(v):
                    raise ValueError
        except (TypeError, ValueError):
            raise ValueError("setting '%s': %r is not a valid %s" % (
                name, values[name], {"c": "colour (r,g,b,a from 0 to 1)", "i": "whole number"}.get(t, "number")))
        lo, hi = LIMITS.get(name, (0.0, 1000.0) if t == "f" else (0, 0xFFFFFFFF))
        if t != "c" and not lo <= v <= hi:
            raise ValueError("setting '%s' = %s is outside %s .. %s" % (name, v, lo, hi))
        if name == "arrow_tex_slot" and v not in (12, 28):
            raise ValueError("arrow_tex_slot must be 12 (Revenge chevron) or 28 (Dominator arrow)")
        out[name] = v
    return out


def same(a, b):
    """Equal as stored in the game (floats compared as 32-bit floats)."""
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        return f32(a) == f32(b)
    return a == b


def changed(values, base=None):
    """Names whose value differs from `base` (default: the defaults)."""
    base = base or DEFAULTS
    return [n for n in DEFAULTS if not same(values[n], base[n])]


def preset_of(values):
    """Name of the preset these values match exactly (ignoring the arrow texture slot), or None."""
    for name, p in PRESETS.items():
        if not [n for n in changed(values, p) if n != "arrow_tex_slot"]:
            return name
    return None


# ------------------------------------------------------------------------------------------- files
def to_json(values):
    v = check(values)
    return {"kit": KIT, "version": FILE_VERSION,
            "settings": {n: (list(v[n]) if TYPES[n] == "c" else v[n]) for n in DEFAULTS if n != "arrow_tex_slot"}}


def from_json(obj):
    if not isinstance(obj, dict):
        raise ValueError("not a ChainKit settings file")
    if "settings" in obj:
        if obj.get("kit") not in (None, KIT):
            raise ValueError("this settings file is for %s, not ChainKit" % obj.get("kit"))
        obj = obj["settings"]
    if not isinstance(obj, dict):
        raise ValueError("not a ChainKit settings file")
    obj = {k: v for k, v in obj.items() if k != "arrow_tex_slot"}
    return check(obj)


def save(path, values):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(to_json(values), f, indent=2)
        f.write("\n")


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError("%s is not a settings file (%s)" % (path, exc))
    return from_json(obj)


# ------------------------------------------------------------------------------------------- text
def shown(item, values):
    """The value of one window item as text (human units)."""
    v = values[item.key]
    if item.kind in ("flag", "mode"):
        return "on" if is_on(item, values) else "off"
    if item.kind == "colour":
        return "%.2f, %.2f, %.2f, %.2f" % tuple(v)
    if item.unit:
        return item.unit.fmt % item.unit.to_ui(v)
    return str(v)


def fill_seconds(values):
    """About how many seconds of oncoming (250 km/h) / drift (200 km/h) fill an empty 4-segment bar."""
    fm = values["fill_mult"]
    out = {}
    for name, per_m, speed in (("oncoming", ONCOMING_PER_M, ONCOMING_SPEED), ("drift", DRIFT_PER_M, DRIFT_SPEED)):
        rate = per_m * speed * fm * values["fill_w_" + name]
        out[name] = FULL_BAR / rate if rate > 0 else float("inf")
    return out


def describe(values=None):
    """Lines of text: every setting with its value in human units (and the raw name for the command line)."""
    values = check(values or {})
    lines = []
    for title, _, items in GROUPS:
        lines.append(title)
        for it in items:
            raw = it.key if it.kind not in ("flag", "mode") else "%s=on|off" % it.cli
            lines.append("  %-44s %-14s [%s]" % (it.label, shown(it, values), raw))
    return lines
