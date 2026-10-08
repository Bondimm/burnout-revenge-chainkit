"""Cave code: the kit settings (per-mode switches, per-action factors, label / hint switches, takedown arrows)."""
import importlib

import pytest

# test_cave_usa.py loads this file with BASE_MODULE = the USA copy of test_cave
_base = globals().get("BASE_MODULE") or importlib.import_module("test_cave")
A, BOOST, CAR, LAY, TUNE, T, Game, award, cave, prompt_hud, supercharged = (getattr(_base, n) for n in (
    "A", "BOOST", "CAR", "LAY", "TUNE", "T", "Game", "award", "cave", "prompt_hud", "supercharged"))

MODE_OBJ = 0x5A000


def in_mode(g, vtable, event_type=None):
    """Point the game-mode object (and the current event) at a mode."""
    m = g.cpu.m
    m.w32(A["MODE_OBJ"], MODE_OBJ); m.w32(MODE_OBJ + 0x118, vtable)
    if event_type is not None:
        m.w32(A["EVENT"], 0x5B000); m.w32(0x5B000 + 0x20, event_type)
    return g


def modes_game(modes, vtable, event_type=None, **kw):
    g = Game(**kw)
    g.cpu.m.w32(A["REGION"] + 0xE70, modes)
    return in_mode(g, vtable, event_type)


def mode_bit(key):
    return {k: 1 << b for b, k, _ in cave.MODES}[key]


VT = {"race": T(0x49EB20), "road_rage": T(0x49E750), "burning": T(0x49DBF8), "eliminator": T(0x49E388),
      "traffic_attack": T(0x49D820), "splitscreen": T(0x49B5D0), "online_race": T(0x49B208),
      "unknown": 0x49DFC0}        # (a mode class not in the table)


def is_vanilla(g):
    g.tick(); g.set_amt(g.max()); g.cpu.m.write(g.st(cave.S_EARNED), b"\1"); g.tick()
    return g.super() == 0


@pytest.mark.parametrize("key,vt,ev", [("race", VT["race"], None), ("road_rage", VT["road_rage"], None),
                                       ("burning_lap", VT["burning"], 10), ("preview_lap", VT["burning"], 3),
                                       ("eliminator", VT["eliminator"], None),
                                       ("traffic_attack", VT["traffic_attack"], None),
                                       ("splitscreen", VT["splitscreen"], None), ("other", VT["unknown"], None)])
def test_each_mode_can_be_switched_off(key, vt, ev):
    assert not is_vanilla(modes_game(0xFF, vt, ev))
    assert is_vanilla(modes_game(0xFF & ~mode_bit(key), vt, ev))
    assert not is_vanilla(modes_game(mode_bit(key), vt, ev))          # only this mode on


def test_online_modes_always_vanilla():
    assert is_vanilla(modes_game(0xFF, VT["online_race"]))
    assert is_vanilla(modes_game(0xFFFFFFFF, VT["online_race"]))


def test_switched_off_mode_is_vanilla_in_every_hook():
    g = modes_game(0xFF & ~mode_bit("race"), VT["race"], bar=0)
    hud = 0x60000; g.cpu.m.w32(hud + cave.C_HUDCAR, CAR); g.cpu.m.write(hud + cave.HUD_SEGS, b"\1")
    pptr = 0x61000; g.cpu.m.w32(pptr, hud)
    g.run("TINT", a1=pptr)                                               # before the first car update
    assert g.u(BOOST + cave.B_IDX) == 0 and g.cpu.m.read(hud + cave.HUD_SEGS, 1)[0] == 1
    g.tick(); g.set_amt(10.0); g.add(20.0)
    assert g.amt() == 30.0
    g.calls.clear(); g.run("TAKEDOWN", a0=BOOST)
    assert g.names() == ["grow"] and g.super() == 0
    hud2, seen = prompt_hud(g, 6.0)
    assert g.u(hud2 + 0x21C) == 0                                        # PRESS R1 hint as in the game


def test_mode_object_missing_counts_as_other():
    g = Game(); g.cpu.m.w32(A["REGION"] + 0xE70, 0xFF & ~mode_bit("other"))
    assert is_vanilla(g)


def test_default_settings_switch_every_offline_mode_on():
    assert TUNE["modes"] == 0xFF
    for key, vt in VT.items():
        if key != "online_race":
            assert not is_vanilla(in_mode(Game(), vt, 10 if key == "burning" else None)), key


# ------------------------------------------------------------------------------------------- label / hint switches
def test_show_size_label_switch():
    g = supercharged(flags=TUNE["flags"] | cave.FL_SHOWLABEL)
    hud = 0x60000; g.cpu.m.w32(hud + cave.C_HUDCAR, CAR)
    g.run("HUDLBL", a0=0x62000, a1=4, s2=hud)
    lab = [c for c in g.calls if c[0] == "label"][0]
    assert lab[2] == 4                                                   # Revenge's x4 label stays


def test_show_press_r1_hint_switch():
    g = Game(flags=TUNE["flags"] | cave.FL_SHOWHINT); g.tick()
    hud, seen = prompt_hud(g, 6.0)
    assert g.u(hud + 0x21C) == 0 and seen == ["after"]


# ------------------------------------------------------------------------------------------- per-action factors
NEW_KINDS = {"air": T(0x2CC15C), "crash_escape": T(0x2CAF34), "tailgating": T(0x2CB370), "grinding": T(0x2CCB18),
             "near_miss": T(0x2CEDAC), "checked_traffic": T(0x2CCD20)}


@pytest.mark.parametrize("name,ra", sorted(NEW_KINDS.items()))
def test_new_action_factors_default_to_revenge_and_can_be_changed(name, ra):
    g = Game(); g.tick(); g.set_amt(0.0); award(g, ra, 40.0)
    assert g.amt() == pytest.approx(40.0 * TUNE["fill_mult"])           # default 1.0 = as before
    g = Game(); g.tick(); g.cpu.m.wf32(cave.tune_addr(LAY, "fill_w_" + name)[0], 0.5)
    g.set_amt(0.0); award(g, ra, 40.0)
    assert g.amt() == pytest.approx(40.0 * TUNE["fill_mult"] * 0.5)


def test_every_award_kind_has_a_fill_setting():
    names = {n for n, *_ in cave.TUNABLES}
    kinds = {k for _, k in cave.AWARD_SITES}
    assert kinds == set(range(cave.AWARD_KINDS))
    fill = [n for n in names if n.startswith("fill_w_")]
    assert len(fill) == cave.AWARD_KINDS


def test_takedown_arrow_fraction():
    g = supercharged(); g.boosting(True)
    g.cpu.m.wf32(cave.tune_addr(LAY, "arrows_takedown")[0], 0.25)
    g.run("TAKEDOWN", a0=BOOST)
    assert g.arrows() == pytest.approx(50.0)
    g.run("TAKEDOWN", a0=BOOST)
    assert g.arrows() == pytest.approx(100.0)
    for _ in range(4):
        g.run("TAKEDOWN", a0=BOOST)
    assert g.arrows() == 200.0                                           # capped at the pool


def test_tunable_addresses_do_not_overlap():
    used = []
    for n, off, t, d, h in cave.TUNABLES:
        a, _ = cave.tune_addr(LAY, n)
        used.append((a, a + (16 if t == "c" else 4), n))
    used.sort()
    for (a0, e0, n0), (a1, e1, n1) in zip(used, used[1:]):
        assert e0 <= a1, (n0, n1)
    for a, e, n in used:
        assert A["REGION"] <= a and e <= LAY.code, n
        assert not (LAY.msgtab <= a < LAY.msgtab + 12 * LAY.msg_count), n


# ------------------------------------------------------------------------------------------- boost only while held
CTRL = 0x5C000          # the human pad controller object (car at +0x2E80)
PADPP, PADOBJ = 0x5D000, 0x5D100   # car + 0x37B0 -> PADPP -> PADOBJ (the pad)


def set_pad(g, button, forced=False):
    """The player's boost control (FUN_00111b80) and Revenge's "boost held" answer (button OR forced)."""
    m = g.cpu.m
    m.w32(CTRL + cave.P_CAR, CAR); m.w32(CAR + cave.C_PAD, PADPP); m.w32(PADPP, PADOBJ)
    g.cpu.stubs[A["PADVAL"]] = lambda cpu: cpu.sf(0, 1.0 if button else 0.0)
    g.cpu.stubs[A["HELD"]] = lambda cpu: cpu.g.__setitem__(2, 1 if (button or forced) else 0)


def pad(g, held, forced=False):
    """Run the pad controller's 'boost held?' query (hook BTN)."""
    set_pad(g, held, forced)
    g.calls.clear()
    g.run("BTN", a0=CTRL)
    return g.cpu.gr(2)


def test_boost_stops_at_once_without_the_button():
    g = Game(); g.tick(); g.set_amt(200.0); g.boosting(True)
    assert pad(g, held=True) == 1 and g.is_boosting() and "stop" not in g.names()
    assert pad(g, held=False) == 0 and not g.is_boosting() and g.names()[-1] == "stop"


def test_forced_held_without_the_button_is_refused():
    """Revenge's answer can be "held" without the button (game flag controller+0x7224, Perfect-Start latch)."""
    g = Game(); g.tick(); g.set_amt(300.0)
    assert pad(g, held=False, forced=True) == 0 and "stop" not in g.names()          # not boosting: no start
    g.boosting(True); g.cpu.m.write(BOOST + cave.B_AUTO, b"")
    assert pad(g, held=False, forced=True) == 0 and not g.is_boosting()
    assert g.cpu.m.read(BOOST + cave.B_AUTO, 1)[0] == 0                               # latch cleared


def test_takedown_then_no_button_stops_boost_but_keeps_supercharge():
    g = supercharged(); g.boosting(True)
    g.run("TAKEDOWN", a0=BOOST)                          # supercharged takedown: all arrows, grace starts
    assert g.super() == 1 and g.arrows() == 200.0
    pad(g, held=False)
    assert not g.is_boosting() and "stop" in g.names()
    assert g.super() == 1 and g.cpu.m.read(g.st(cave.S_PAUSED), 1)[0] == 1     # grace: supercharge kept
    assert cave.M_LOST not in g.msgs()


def test_takedown_then_button_held_keeps_boosting():
    g = supercharged(); g.boosting(True)
    g.run("TAKEDOWN", a0=BOOST)
    for _ in range(10):
        assert pad(g, held=True) == 1
        g.tick()
    assert g.is_boosting() and g.super() == 1


def test_letting_go_after_the_grace_loses_the_supercharge():
    g = supercharged(); g.boosting(True); g.cpu.m.w32(g.st(cave.S_CHAIN), 3)
    pad(g, held=False)
    assert not g.is_boosting() and g.super() == 0 and cave.M_LOST in g.msgs()


def test_every_frame_check_stops_boosts_the_pad_controller_never_sees():
    """Takedown camera / autopilot: the pad controller is not asked; the car tick checks the button itself."""
    g = supercharged(); g.boosting(True); g.run("TAKEDOWN", a0=BOOST)
    set_pad(g, button=True)
    for _ in range(5):
        g.tick()
    assert g.is_boosting()                               # button held: keeps boosting
    set_pad(g, button=False)
    g.calls.clear(); g.tick()
    assert not g.is_boosting() and "stop" in g.names() and g.super() == 1     # grace: supercharge kept, boost ends
    g.boosting(True); g.calls.clear(); g.tick()          # the game starts it again: stopped again
    assert not g.is_boosting()


def test_car_without_pad_is_never_stopped():
    g = Game(); g.tick(); g.boosting(True)
    g.calls.clear(); g.tick()                             # no pad pointer: treat as held
    assert g.is_boosting() and "stop" not in g.names()


def test_debug_popups_name_the_reason():
    g = Game(flags=TUNE["flags"] | cave.FL_DEBUG); g.tick(); g.boosting(True)
    pad(g, held=False, forced=True)                       # Revenge says "held", the button is not
    assert g.msgs() == [cave.M_DBGPAD]
    g.boosting(True); set_pad(g, button=False); g.calls.clear(); g.tick()
    assert g.msgs() == [cave.M_DBGAUTO]                   # a boost the button never backed
    g2 = Game(); g2.tick(); g2.boosting(True); pad(g2, held=False)
    assert g2.msgs() == []                                # off by default


def test_tap_ends_at_once_and_says_tap_end():
    """A tap: the button starts the boost (game path, not touched), letting go ends it at once."""
    for via_pad_controller in (True, False):
        g = Game(flags=TUNE["flags"] | cave.FL_DEBUG); g.tick(); g.set_amt(100.0)
        g.boosting(True); set_pad(g, button=True); g.tick()          # boosting with the button: backed
        assert g.is_boosting()
        g.calls.clear()
        if via_pad_controller:
            pad(g, held=False)
        else:
            set_pad(g, button=False); g.tick()
        assert not g.is_boosting() and g.msgs() == [cave.M_DBGTAP]


def astart(g, button, boost=BOOST):
    set_pad(g, button)
    started = []
    g.cpu.stubs[A["START"]] = lambda cpu: (started.append(cpu.gr(4)), cpu.g.__setitem__(2, 1))
    g.calls.clear()
    g.run("ASTART", a0=boost, a1=CTRL)
    return started


def test_autopilot_cannot_start_a_boost_without_the_button():
    g = Game(flags=TUNE["flags"] | cave.FL_DEBUG); g.tick(); g.set_amt(300.0)
    assert astart(g, button=False) == [] and g.cpu.gr(2) == 0
    assert g.msgs() == [cave.M_DBGBLOCK]
    assert astart(g, button=False) == [] and g.msgs() == []        # pop-up at most every 2 s
    g.cpu.m.wf32(CAR + cave.C_TIME, g.f(CAR + cave.C_TIME) + 2.5)
    astart(g, button=False)
    assert g.msgs() == [cave.M_DBGBLOCK]
    assert astart(g, button=True) == [BOOST]                       # with the button: the game's start


def test_autopilot_start_untouched_for_ai_option_and_crash_mode():
    for game in (Game(ctrl=1), _crash_game(), Game(flags=TUNE["flags"] | cave.FL_FREEBOOST)):
        game.tick()
        assert astart(game, button=False) == [BOOST]


def test_free_boost_option_and_vanilla_cases_untouched():
    g = Game(flags=TUNE["flags"] | cave.FL_FREEBOOST); g.tick(); g.boosting(True)
    assert pad(g, held=False, forced=True) == 1                       # option off: Revenge's answer
    assert g.is_boosting() and "stop" not in g.names()
    g.tick(); assert g.is_boosting()
    for game in (Game(ctrl=1), _crash_game()):
        game.tick(); game.boosting(True)
        pad(game, held=False)
        game.tick()
        assert game.is_boosting() and "stop" not in game.names()      # AI / Crash mode: vanilla


def _crash_game():
    g = Game(); g.cpu.m.write(A["CRASHFLAG"], b"")
    return g


# ------------------------------------------------------------------------------------------- bar fire follows the boost
def bar_fire(g, filling):
    """Run HUDFIRE for the boost-bar HUD element (not boosting); returns 'fire' or 'nofire'."""
    hud = 0x5E000
    g.cpu.m.w32(hud + cave.H_CAR, CAR); g.cpu.m.w32(hud + 0x56C, 0x5E800)
    seen = []
    g.cpu.stubs[T(0x161A44)] = lambda cpu: seen.append(("nofire", cpu.gr(3)))
    g.cpu.stubs[T(0x1617BC)] = lambda cpu: seen.append(("fire", None))
    g.run("HUDFIRE", s0=hud, s3=1 if filling else 0)
    return seen[0]


def test_bar_fire_only_while_boosting_for_mod_cars():
    g = supercharged()
    assert bar_fire(g, filling=True) == ("nofire", 0x5E800)        # refill animation: no fire for mod cars
    assert bar_fire(g, filling=False) == ("nofire", 0x5E800)


def test_bar_fire_while_filling_option_and_vanilla_cases():
    g = Game(flags=TUNE["flags"] | cave.FL_FILLFIRE); g.tick()
    assert bar_fire(g, filling=True)[0] == "fire"
    for game in (Game(ctrl=1), _crash_game()):
        game.tick()
        assert bar_fire(game, filling=True)[0] == "fire"            # AI / Crash mode: Revenge's own HUD
        assert bar_fire(game, filling=False)[0] == "nofire"
