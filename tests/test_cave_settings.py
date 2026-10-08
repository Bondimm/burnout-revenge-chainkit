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
    g.cpu.m.w32(A["REGION"] + 0xE30, modes)
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
    g = Game(); g.cpu.m.w32(A["REGION"] + 0xE30, 0xFF & ~mode_bit("other"))
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
