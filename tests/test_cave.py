"""Runs the generated cave code in the mips interpreter against a fake Revenge memory (design v4: native bar).
PAL by default; test_cave_usa.py runs every test again with the USA addresses."""
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from chainkit import cave, regions             # noqa: E402
from chainkit.mips import Cpu, RI              # noqa: E402

# The same suite runs for the USA build: tests/test_cave_usa.py loads this file with REGION_KEY = "USA".
REGION = regions.BY_KEY[globals().get("REGION_KEY", "PAL")]
INLINE = globals().get("INLINE", False)       # PCSX2 cheat build: texts from the cave (test_cave_cheat.py)
TEXCOPY = globals().get("TEXCOPY", False)     # ... with the Dominator arrow copied from the cave
LAY = cave.Layout(REGION, INLINE, TEXCOPY)
TEXBLOB = bytes((k * 7 + 3) & 0xFF for k in range(cave.TEX_SIZE - cave.TEX_FROM))   # stand-in texture data
A = LAY.a
T = LAY.t                                      # PAL address -> address in this build
OTHER_RA = 0x2CE9B8                            # a return address that is no award call site (in both builds)
CODE, LAB = cave.build_code(LAY)
CAR = 0x1ED82F0
CAR2 = CAR + 0x3B30
BOOST = CAR + 0x2430
SENT = 0xDEAD0000
SIZES = (100.0, 200.0, 300.0, 400.0)
TUNE = {n: d for n, off, t, d, h in cave.TUNABLES}


class Game:
    def __init__(self, ctrl=0, idx=0, bar=3, flags=None):
        self.cpu = c = Cpu()
        m = c.m
        tun = {"flags": flags} if flags is not None else None
        m.write(A["REGION"], cave.build_data(LAY, bytes(12 * A["MSG_COUNT"]), tun))
        m.write(LAY.code, CODE)
        if INLINE:
            m.write(LAY.texts, cave.build_texts(LAY))
        if TEXCOPY:
            m.write(LAY.texsrc, TEXBLOB)
        for i, (s, mu) in enumerate(zip(SIZES, (1, 2, 3, 4))):
            m.wf32(A["TBL_SIZES"] + 4 * i, s); m.wf32(A["TBL_MULT"] + 4 * i, mu); m.wf32(A["TBL_RATE"] + 4 * i, 10)
        m.wf32(A["MINBOOST"], 1.0)
        m.wf32(A["DT"], 1 / 60)
        m.w32(A["NCARS"], 1); m.w32(A["CARPTRS"], CAR)
        m.w32(CAR + cave.C_CTRL, ctrl); m.w32(CAR + cave.C_IDX, idx); m.wf32(CAR + cave.C_SPEED, 50.0)
        m.wf32(CAR + cave.C_TIME, 10.0)
        m.write(CAR + cave.C_INPUT, b"\1")         # the player drives (pad read, no autopilot)
        m.w32(BOOST + cave.B_CAR, CAR); self.set_bar(bar); m.wf32(BOOST + cave.B_RATE, 10.0)
        m.w32(A["HUDTEX"] + 4 * 28, 0x01234560)
        for k in range(10):     # bar colours: (k, 0, 100+k, 0)
            m.wf32(A["BARCOL"] + 16 * k, k); m.wf32(A["BARCOL"] + 16 * k + 8, 100 + k)
        self.calls = []
        def rec(name, fn=None):
            def stub(cpu):
                self.calls.append((name, cpu.gr(4) & 0xFFFFFFFF, cpu.gr(5) & 0xFFFFFFFF, cpu.gr(6) & 0xFFFFFFFF))
                if fn:
                    fn(cpu)
            return stub
        def stop(cpu):                       # FUN_002a4288: boosting ends
            cpu.m.write(BOOST + cave.B_ACTIVE, b"\0"); cpu.m.write(BOOST + cave.B_STOPREQ, b"\0")
        def sub_orig(cpu):                   # the original FUN_002a3f28 tail from 0x2A3F58
            amt = cpu.ff(1) - cpu.ff(12) * cpu.ff(0)
            cpu.m.wf32(BOOST + cave.B_AMT, max(amt, 0.0))
            cpu.g[31] = SENT                 # inline code: the real epilogue restores $ra from the stack
        def grow(cpu):                       # FUN_002a3fa0: takedown grows the bar one segment
            i = self.u(BOOST + cave.B_IDX)
            if i < 3:
                self.set_bar(i + 1)
        def track_ret(cpu):                  # rest of FUN_002c8908: store the new value
            self.track_f0 = cpu.ff(0)
            cpu.m.wf32(cpu.gr(5) + 4, cpu.ff(12))
        quads = self.quads = []
        def quad(cpu):
            col = struct.unpack("<4f", (cpu.g[4] & ((1 << 128) - 1)).to_bytes(16, "little"))
            quads.append((col, (cpu.m.f32(cpu.gr(5)), cpu.m.f32(cpu.gr(5) + 4))))
        for name, addr, fn in [("msg", A["MSG_SEND"], None), ("gain", A["SND_GAIN"], None),
                               ("lose", A["SND_LOSE"], None), ("stop", A["STOP"], stop), ("stopreq", A["STOPREQ"], None),
                               ("grow", A["GROW"], grow), ("tick_orig", A["TICK_ORIG"], None),
                               ("label", A["LABELFN"], None), ("settex", A["SETTEX"], None), ("quad", A["QUAD"], quad),
                               ("add_ret", A["ADD_RET"], None), ("drain_ret", A["DRAIN_RET"], None),
                               ("tint_ret", A["TINT_RET"], None), ("td_skip", A["TAKEDOWN_SKIP"], None),
                               ("sub_ret", T(0x2A3F8C), lambda cpu: cpu.g.__setitem__(31, SENT)),
                               ("sub_orig", T(0x2A3F58), sub_orig), ("track_ret", T(0x2C8910), track_ret)]:
            c.stubs[addr] = rec(name, fn)

    # helpers
    def set_bar(self, i):
        self.cpu.m.w32(BOOST + cave.B_IDX, i); self.cpu.m.wf32(BOOST + cave.B_MAX, SIZES[i])
    def f(self, a): return self.cpu.m.f32(a)
    def u(self, a): return self.cpu.m.u32(a)
    def st(self, off, idx=0): return LAY.state + 32 * idx + off
    def set_amt(self, x): self.cpu.m.wf32(BOOST + cave.B_AMT, x)
    def amt(self): return self.f(BOOST + cave.B_AMT)
    def max(self): return self.f(BOOST + cave.B_MAX)
    def arrows(self): return self.f(self.st(cave.S_ARROWS))
    def boosting(self, on): self.cpu.m.write(BOOST + cave.B_ACTIVE, bytes([1 if on else 0]))
    def is_boosting(self): return self.cpu.m.read(BOOST + cave.B_ACTIVE, 1)[0]
    def super(self): return self.cpu.m.read(self.st(cave.S_SUPER), 1)[0]
    def names(self): return [c[0] for c in self.calls]
    def msgs(self): return [c[2] for c in self.calls if c[0] == "msg"]

    def run(self, label, **regs):
        c = self.cpu
        c.g[29] = 0x70000
        for k, v in regs.items():
            if k.startswith("f"):
                c.sf(int(k[1:]), v)
            else:
                c.g[RI[k]] = v
        c.call(LAB[label], SENT)
        return self

    def add(self, x):
        return self.run("ADD", s0=BOOST, f20=x)

    def tick(self):
        return self.run("TICK", a0=BOOST, a1=CAR)

    def drain(self):
        return self.run("DRAIN", s0=BOOST, f0=self.f(BOOST + cave.B_RATE))

    def empty(self, stopreq=0):
        self.cpu.m.write(BOOST + cave.B_STOPREQ, bytes([stopreq]))
        return self.run("EMPTY", a0=BOOST, f12=5.0)

    def track(self, skill, value, car=CAR):
        off = dict((n, o) for n, o, u, w in cave.SKILLS)[skill]
        return self.run("TRACK", a1=car + off, a0=car + off, f12=value)


def supercharged(bar=3, flags=None):
    g = Game(bar=bar, flags=flags)
    g.tick()
    g.cpu.m.write(g.st(cave.S_EARNED), b"\1")           # the player earned boost this race
    g.set_amt(g.max())
    g.tick()
    assert g.super() == 1
    g.calls.clear()
    return g


# ------------------------------------------------------------------------------------------- earning / supercharge
def test_fill_mult_and_supercharge_once():
    g = Game(bar=0, flags=TUNE["flags"] & ~cave.FL_FULLBAR); g.tick()
    g.add(20.0)
    assert g.amt() == pytest.approx(20 * TUNE["fill_mult"])
    g.boosting(True); g.add(10.0)                        # Revenge rule: earning while boosting (not supercharged)
    assert g.amt() == pytest.approx(30 * TUNE["fill_mult"])
    g.boosting(False); g.add(200.0); assert g.amt() == 100.0
    g.tick(); g.tick(); g.tick()
    assert g.super() == 1 and g.msgs() == [cave.M_SUPER] and g.names().count("gain") == 1


def test_dominator_no_earn_option():
    g = Game(flags=TUNE["flags"] | cave.FL_NOEARN); g.tick(); g.set_amt(100.0); g.boosting(True)
    g.add(50.0)
    assert g.amt() == 100.0


def test_native_option_race_start_is_silent_and_keeps_bar_size():
    g = Game(bar=0, flags=TUNE["flags"] & ~cave.FL_FULLBAR); g.cpu.m.wf32(CAR + cave.C_TIME, 0.0)
    for k in range(120):                                 # 2 s of race start, Revenge's own small bar
        g.cpu.m.wf32(CAR + cave.C_TIME, k / 60); g.tick()
    assert g.u(BOOST + cave.B_IDX) == 0 and g.max() == 100.0
    assert g.calls == [c for c in g.calls if c[0] == "tick_orig"]  # no sound, no message


def test_full_bar_default_forces_400():
    g = Game(bar=0); g.tick()
    assert g.u(BOOST + cave.B_IDX) == 3 and g.max() == 400.0 and g.f(BOOST + cave.B_MIN) == 10.0


def test_supercharged_add_changes_nothing():
    g = supercharged(); g.boosting(True); g.set_amt(300.0)
    g.add(100.0)
    assert g.amt() == 300.0 and g.arrows() == 0.0


# ------------------------------------------------------------------------------------------- skill list -> arrows
@pytest.mark.parametrize("skill,unit,w", [(n, u, w) for n, o, u, w in cave.SKILLS])
def test_every_skill_list_entry_lights_arrows(skill, unit, w):
    for bar in (0, 3):
        g = supercharged(bar, flags=TUNE["flags"] & ~cave.FL_FULLBAR); g.boosting(True)
        pool = 0.5 * SIZES[bar]
        g.track(skill, 1.0)                              # 1 count / metre / second
        assert g.arrows() == pytest.approx(min(pool, w * pool)), (skill, bar)
        assert g.track_f0 == 0.0                         # original 2nd instruction re-executed (old value)
        g.track(skill, 101.0)                            # +100 units -> capped at the pool
        assert g.arrows() == pytest.approx(min(pool, w * pool * 101)), (skill, bar)


def test_skill_list_needs_supercharge_boosting():
    g = Game(); g.tick(); g.boosting(True); g.track("near_miss", 1.0)
    assert g.arrows() == 0.0
    g = supercharged(); g.track("near_miss", 1.0)        # supercharged but idle
    assert g.arrows() == 0.0
    g = supercharged(); g.boosting(True)
    g.cpu.m.wf32(CAR + 0x2674 + 4, 3.0); g.track("near_miss", 0.0)   # tracker reset -> nothing
    assert g.arrows() == 0.0
    g.run("TRACK", a1=CAR + 0x2000, a0=CAR + 0x2000, f12=50.0)       # unknown tracker
    assert g.arrows() == 0.0


def test_skill_list_ai_car_ignored():
    g = supercharged(); g.boosting(True)
    m = g.cpu.m
    m.w32(A["NCARS"], 2); m.w32(A["CARPTRS"] + 4, CAR2); m.w32(CAR2 + cave.C_CTRL, 1)
    m.w32(CAR2 + cave.C_BOOST + cave.B_CAR, CAR2)
    g.track("drift", 50.0, car=CAR2)
    assert g.arrows() == 0.0


def test_three_near_misses_fill_the_pool():
    g = supercharged(); g.boosting(True)
    for n in (1.0, 2.0, 3.0):
        g.track("near_miss", n)
    assert g.arrows() == 200.0


# ------------------------------------------------------------------------------------------- takedown / modes
def test_takedown_lights_all_arrows_boosting_or_not():
    g = supercharged(bar=1, flags=TUNE["flags"] & ~cave.FL_FULLBAR); g.boosting(True); g.set_amt(120.0)
    g.run("TAKEDOWN", a0=BOOST)
    assert g.u(BOOST + cave.B_IDX) == 2                              # bar grew (Revenge)
    assert g.arrows() == 150.0 and g.names()[-1] == "grow"            # pool of the grown bar; Revenge refills
    g2 = supercharged(); g2.run("TAKEDOWN", a0=BOOST)                 # camera ended the boost
    assert g2.arrows() == 200.0 and g2.names()[-1] == "grow"          # original: amount = max


def test_takedown_not_supercharged_is_instant_supercharge():
    g = Game(); g.tick(); g.set_amt(50.0)
    g.run("TAKEDOWN", a0=BOOST)
    assert g.super() == 1 and g.msgs() == [cave.M_SUPER]


def test_road_rage_takedowns_keep_the_chain():
    """Supercharge-boosting through takedowns: bar grows, chain continues, burnout fills the grown bar."""
    g = supercharged(bar=0, flags=TUNE["flags"] & ~cave.FL_FULLBAR); g.boosting(True); g.cpu.m.w32(g.st(cave.S_CHAIN), 2)
    g.set_amt(30.0); g.run("TAKEDOWN", a0=BOOST)
    assert g.super() == 1 and g.u(BOOST + cave.B_IDX) == 1
    for _ in range(4):
        g.tick()
    assert g.super() == 1
    g.set_amt(0.0); g.empty()
    assert g.amt() == 200.0 and g.u(g.st(cave.S_CHAIN)) == 3


def test_crash_shrinks_bar_and_ends_supercharge():
    g = supercharged(bar=2)
    g.set_bar(1); g.set_amt(200.0)                       # FUN_002a3fd0 on a wreck: shrink + clamp
    g.cpu.m.wf32(BOOST + cave.B_AMT, 150.0)              # + Revenge's crash boost loss
    g.tick()
    assert g.super() == 0


# ------------------------------------------------------------------------------------------- empty / release
def test_burnout_chain_and_partial():
    g = supercharged(); g.boosting(True)
    g.cpu.m.wf32(g.st(cave.S_ARROWS), 200.0); g.set_amt(0.0)
    txt = 0x64000; g.cpu.m.write(txt, "BURNOUT!".encode("utf-16-le") + b"\0\0")   # the game's text handle
    g.cpu.m.w32(LAY.burnout_entry + 4, txt)
    g.empty()
    assert g.amt() == 400.0 and g.u(g.st(cave.S_CHAIN)) == 1 and "stop" not in g.names()
    handle = LAY.text_addr[cave.M_BURNOUT] if INLINE else txt       # cheat build: its own "BURNOUT!" text
    assert g.msgs() == [cave.M_BURNOUT] and g.u(LAY.burnout_entry + 8) == 0 and g.u(LAY.burnout_entry + 4) == handle
    g.calls.clear(); g.cpu.m.wf32(g.st(cave.S_ARROWS), 250.0); g.set_amt(0.0)
    g.empty()
    assert g.u(g.st(cave.S_CHAIN)) == 2 and g.u(LAY.burnout_entry + 8) == 0          # one line only
    assert g.u(LAY.burnout_entry + 4) == LAY.msgbuf
    assert g.cpu.m.read(LAY.msgbuf, 24).decode("utf-16-le") == "BURNOUT! x2\0"
    g.calls.clear(); g.cpu.m.wf32(g.st(cave.S_ARROWS), 250.0); g.set_amt(0.0)
    g.empty()
    assert g.cpu.m.read(LAY.msgbuf, 24).decode("utf-16-le") == "BURNOUT! x3\0"     # rebuilt from the saved text
    g.cpu.m.w32(g.st(cave.S_CHAIN), 2)
    g.calls.clear(); g.cpu.m.wf32(g.st(cave.S_ARROWS), 150.0); g.set_amt(0.0)
    g.empty()
    assert g.amt() == 320.0 and g.super() == 0 and g.u(g.st(cave.S_CHAIN)) == 0
    assert g.msgs() == [cave.M_LOST] and "stop" not in g.names()


def test_domination_and_wow():
    g = supercharged(); g.boosting(True)
    g.cpu.m.w32(g.st(cave.S_CHAIN), 9); g.cpu.m.wf32(g.st(cave.S_ARROWS), 200.0)
    g.empty()
    assert g.msgs() == [cave.M_DOMI]
    g.calls.clear(); g.cpu.m.w32(g.st(cave.S_CHAIN), 999); g.cpu.m.wf32(g.st(cave.S_ARROWS), 200.0)
    g.empty()
    assert g.msgs() == [cave.M_WOW]


def test_release_loses_and_stops():
    g = supercharged(); g.boosting(True); g.cpu.m.w32(g.st(cave.S_CHAIN), 3)
    g.run("RELEASE", a0=BOOST)                           # the boost-button input asks for the stop
    assert g.names()[-1] == "stopreq"
    g.empty(stopreq=1)
    assert g.super() == 0 and g.names()[-1] == "stop" and cave.M_LOST in g.msgs()


def test_drain_pause_then_triple():
    g = supercharged(); g.boosting(True)
    g.drain(); assert g.amt() == 400.0
    for _ in range(60):
        g.tick()
    g.drain()
    assert g.amt() == pytest.approx(400 - 30 / 60, abs=1e-3)


def test_hits_floor_at_half_while_supercharge_boosting():
    g = supercharged(); g.boosting(True); g.cpu.m.wf32(BOOST + cave.B_MULT, 4.0); g.set_amt(300.0)
    g.run("SUB", s0=BOOST, f12=70.0)
    assert g.amt() == 200.0 and g.super() == 1
    g.set_amt(100.0); g.run("SUB", s0=BOOST, f12=70.0)
    assert g.amt() == 100.0
    g2 = supercharged(); g2.cpu.m.wf32(BOOST + cave.B_MULT, 4.0)
    g2.run("SUB", s0=BOOST, f12=10.0)
    assert g2.super() == 0 and g2.amt() == 360.0


def test_slow_rule():
    g = supercharged(); g.boosting(True); g.cpu.m.wf32(CAR + cave.C_SPEED, 10.0)
    for _ in range(170):
        g.tick()
    assert g.super() == 1
    for _ in range(20):
        g.tick()
    assert g.super() == 0


def test_perfect_start_latch_cleared_only_when_supercharged():
    g = supercharged(); g.cpu.m.write(BOOST + cave.B_AUTO, b"\1"); g.boosting(True)
    g.tick()
    assert g.cpu.m.read(BOOST + cave.B_AUTO, 1)[0] == 0
    g2 = Game(); g2.tick(); g2.cpu.m.write(BOOST + cave.B_AUTO, b"\1"); g2.boosting(True); g2.set_amt(100.0)
    g2.tick()
    assert g2.cpu.m.read(BOOST + cave.B_AUTO, 1)[0] == 1


def test_ai_crash_mode_online_untouched():
    for setup in ("ai", "crash", "online"):
        g = Game(ctrl=1 if setup == "ai" else 0)
        if setup == "crash":
            g.cpu.m.write(A["CRASHFLAG"], b"\1")
        if setup == "online":
            g.cpu.m.w32(A["NCARS"], 2); g.cpu.m.w32(A["CARPTRS"] + 4, CAR2); g.cpu.m.w32(CAR2 + cave.C_CTRL, 2)
        g.tick(); g.set_amt(400.0); g.tick(); g.boosting(True)
        assert g.super() == 0, setup
        g.set_amt(100.0); g.add(50.0)
        assert g.amt() == 150.0, setup                    # original add, no fill_mult
        g.drain()
        assert g.amt() == pytest.approx(150 - 10 / 60, abs=1e-3), setup
        g.set_amt(0.0); g.empty()
        assert g.names()[-1] == "stop", setup


def test_countdown_clock_does_not_reset_but_restart_does():
    g = supercharged(); g.cpu.m.w32(g.st(cave.S_CHAIN), 3)
    for k in range(30):
        g.cpu.m.wf32(CAR + cave.C_TIME, 10.0 - k / 60); g.tick()
    assert g.super() == 1 and g.u(g.st(cave.S_CHAIN)) == 3
    g.cpu.m.wf32(CAR + cave.C_TIME, 0.0); g.set_amt(0.0); g.tick()
    assert g.super() == 0 and g.u(g.st(cave.S_CHAIN)) == 0


# ------------------------------------------------------------------------------------------- HUD
def test_wide_number():
    g = Game()
    for n, s in ((1, "x1"), (12, "x12"), (100, "x100"), (1009, "x1009"), (123456, "x9999")):
        g.run("WFMT", a0=0x63000, a1=n)
        assert g.cpu.m.read(0x63000, 2 * len(s) + 2).decode("utf-16-le") == s + "\0"


def test_hud_label_tint_and_arrows():
    g = supercharged(); g.boosting(True)
    hud = 0x60000
    g.cpu.m.w32(hud + cave.C_HUDCAR, CAR)
    pptr = 0x61000; g.cpu.m.w32(pptr, hud)
    g.run("TINT", a1=pptr)
    assert g.f(A["BARCOL"] + 16 * 3) == 103.0 and g.f(A["BARCOL"] + 16 * 3 + 8) == 3.0
    rect = 0x62000
    for k, x in enumerate((100.0, 400.0, 290.0, 28.0)):
        g.cpu.m.wf32(rect + 4 * k, x)
    g.cpu.m.wf32(g.st(cave.S_ARROWS), 100.0)                # half of the pool -> 9 of 18 arrows lit
    g.run("HUDLBL", a0=rect, a1=4, s2=hud)
    lab = [c for c in g.calls if c[0] == "label"][0]
    assert lab[2] == 1                                   # bar-size label hidden (segment count 1)
    assert g.f(A["BARCOL"] + 16 * 3) == 3.0
    n = TUNE["arrow_count"]
    assert g.names().count("quad") == 2 * n
    shadow, lit, dark = [tuple(round(x, 3) for x in TUNE[k]) for k in ("shadow_rgba", "lit_rgba", "dark_rgba")]
    cols = [tuple(round(x, 3) for x in q[0]) for q in g.quads]
    assert cols[0::2] == [shadow] * n and cols[1::2] == [lit] * (n // 2) + [dark] * (n - n // 2)
    xs = [q[1][0] for q in g.quads[1::2]]
    # edge to edge: first / last arrow 'arrow_margin' from the bar's ends (arrow 13 units wide, bar 290)
    m = TUNE["arrow_margin"]
    assert xs[0] == pytest.approx(100 + m + 6.5, abs=1e-3) and xs[-1] == pytest.approx(100 + 290 - m - 6.5, abs=1e-3)
    g.calls.clear(); g.quads.clear(); g.cpu.m.w32(g.st(cave.S_CHAIN), 7)
    g.run("HUDLBL", a0=rect, a1=4, s2=hud)                  # chain running: still no label (pop-ups show it)
    lab = [c for c in g.calls if c[0] == "label"][0]
    assert lab[1] == rect and lab[2] == 1


def test_hud_ai_keeps_original_label():
    g = Game(ctrl=1); hud = 0x60000; g.cpu.m.w32(hud + cave.C_HUDCAR, CAR)
    g.run("HUDLBL", a0=0x62000, a1=3, s2=hud)
    assert g.u(LAY.g + cave.G_LABELPTR) == A["LABELTXT"] + 24 and "quad" not in g.names()


# ------------------------------------------------------------------------------------------- sessions
class Sim:
    def __init__(self, bar=0, flags=None):
        self.g = g = Game(bar=bar, flags=flags)
        g.tick()
        self.nm = 0.0

    def frame(self, hold, event=0.0, near_miss=False, drift=0.0, hit=0.0):
        g = self.g
        if event:
            g.add(event)
        if near_miss:
            self.nm += 1; g.track("near_miss", self.nm)
        if drift:
            g.track("drift", self.g.f(CAR + 0x25EC + 4) + drift)
        if hit:
            g.run("SUB", s0=BOOST, f12=hit)
        if hold and not g.is_boosting() and g.amt() >= 10.0:
            g.boosting(True)
        if g.is_boosting():
            g.drain()
            if not hold:
                g.run("RELEASE", a0=BOOST); g.empty(stopreq=1)
            elif g.amt() <= 0:
                g.set_amt(0.0); g.empty()
        g.tick()


def test_long_chain_session_driven_by_the_skill_list():
    s = Sim(bar=3); g = s.g
    for _ in range(30):
        s.frame(False, event=20.0)
    assert g.super() == 1
    for frame in range(60 * 120):
        s.frame(True, near_miss=(frame % 90 == 0), drift=(0.5 if frame % 600 < 120 else 0.0),
                hit=(70.0 if frame % 200 == 100 else 0.0))
        assert g.super() == 1, frame
    assert g.u(g.st(cave.S_CHAIN)) >= 5
    s.frame(False)
    assert g.super() == 0 and g.u(g.st(cave.S_CHAIN)) == 0
    a0 = g.amt(); s.frame(False, event=10.0)
    assert g.amt() == pytest.approx(min(g.max(), a0 + 10.0 * TUNE["fill_mult"]))


def test_race_start_sequence_then_blue_quickly():
    s = Sim(bar=0, flags=TUNE["flags"] & ~cave.FL_FULLBAR); g = s.g
    for k in range(60):                                   # countdown / start: nothing happens
        s.frame(False)
    assert g.names().count("gain") == 0 and g.msgs() == []
    for k in range(5):                                    # a few skills fill the small start bar
        s.frame(False, event=20.0)
    assert g.super() == 1 and g.names().count("gain") == 1 and g.msgs() == [cave.M_SUPER]


# ------------------------------------------------------------------------------------------- v5: fixed full bar
def test_hud_segment_count_follows_forced_size():
    g = Game(bar=0); g.tick()
    hud = 0x60000; g.cpu.m.w32(hud + cave.C_HUDCAR, CAR); g.cpu.m.write(hud + cave.HUD_SEGS, b"\1")
    pptr = 0x61000; g.cpu.m.w32(pptr, hud)
    g.run("TINT", a1=pptr)
    assert g.cpu.m.read(hud + cave.HUD_SEGS, 1)[0] == 4         # no size-change animation / sounds
    gai = Game(ctrl=1, bar=0); gai.tick(); gai.cpu.m.w32(hud + cave.C_HUDCAR, CAR); gai.cpu.m.write(hud + cave.HUD_SEGS, b"\1")
    gai.cpu.m.w32(pptr, hud); gai.run("TINT", a1=pptr)
    assert gai.cpu.m.read(hud + cave.HUD_SEGS, 1)[0] == 1 and gai.u(BOOST + cave.B_IDX) == 0   # AI untouched


def test_race_start_full_bar_no_sounds_no_messages():
    g = Game(bar=0)
    for k in range(120):
        g.cpu.m.wf32(CAR + cave.C_TIME, k / 60); g.tick()
    assert g.u(BOOST + cave.B_IDX) == 3 and g.max() == 400.0
    assert all(c[0] == "tick_orig" for c in g.calls)


def test_wreck_does_not_shrink_mod_car():
    g = Game(); g.tick()
    g.run("SHRINK", a0=BOOST)
    assert "shrink" not in g.names()
    gai = Game(ctrl=1); gai.cpu.stubs[A["SHRINK_ORIG"]] = lambda cpu: gai.calls.append(("shrink",))
    gai.run("SHRINK", a0=BOOST)
    assert gai.names() == ["shrink"]


def test_takedown_keeps_size_four():
    g = supercharged(); g.boosting(True); g.set_amt(120.0)
    g.run("TAKEDOWN", a0=BOOST)
    assert g.u(BOOST + cave.B_IDX) == 3 and g.max() == 400.0 and g.arrows() == 200.0


def test_supercharge_messages_use_the_other_message_slot():
    d = cave.build_data(LAY, bytes(12 * A["MSG_COUNT"]))
    tab = d[LAY.msgtab - A["REGION"]:]
    flags = {}
    for k in range(5):
        w = struct.unpack_from("<I", tab, 12 * (A["MSG_COUNT"] + k))[0]
        flags[w & 0xFF] = (w >> 8) & 0xFF
    assert flags[cave.M_SUPER] & 1 and flags[cave.M_LOST] & 1
    assert not flags[cave.M_BURNOUT] & 1


# ------------------------------------------------------------------------------------------- v6
@pytest.mark.parametrize("path", ["takedown camera", "crashbreaker", "aftertouch", "impact time", "event / cutscene",
                                  "air / landing", "boost-start event", "subtract to empty"])
def test_game_interruptions_pause_instead_of_release(path):
    """Any stop request that does not come from the boost-button input keeps supercharge + chain."""
    g = supercharged(); g.boosting(True); g.cpu.m.w32(g.st(cave.S_CHAIN), 4); g.set_amt(250.0)
    g.empty(stopreq=1)                                   # the game's stop (no RELEASE before it)
    assert g.super() == 1 and g.u(g.st(cave.S_CHAIN)) == 4 and g.names()[-1] == "stop"
    g.boosting(False)
    for _ in range(30):
        g.tick()                                          # idle with a partial bar: not lost while paused
    assert g.super() == 1
    g.boosting(True); g.tick()                            # the boost resumes (button still held)
    assert g.cpu.m.read(g.st(cave.S_PAUSED), 1)[0] == 0 and g.super() == 1


def test_takedown_grace_keeps_supercharge_even_on_input_stop():
    g = supercharged(); g.boosting(True); g.cpu.m.w32(g.st(cave.S_CHAIN), 2)
    g.run("TAKEDOWN", a0=BOOST)
    g.run("RELEASE", a0=BOOST); g.empty(stopreq=1)        # input reads "not held" during the takedown camera
    assert g.super() == 1 and g.u(g.st(cave.S_CHAIN)) == 2
    for _ in range(int(60 * 5.1)):
        g.tick()
    g.boosting(True); g.run("RELEASE", a0=BOOST); g.empty(stopreq=1)   # a real release after the grace
    assert g.super() == 0


def test_hit_while_paused_still_ends_it():
    g = supercharged(); g.boosting(True); g.cpu.m.wf32(BOOST + cave.B_MULT, 4.0)
    g.empty(stopreq=1); g.boosting(False)
    g.run("SUB", s0=BOOST, f12=10.0)
    assert g.super() == 0


def test_wreck_ends_supercharge_and_keeps_size():
    g = supercharged(); g.cpu.m.w32(g.st(cave.S_CHAIN), 3)
    g.run("SHRINK", a0=BOOST)
    assert g.super() == 0 and g.u(g.st(cave.S_CHAIN)) == 0 and g.u(BOOST + cave.B_IDX) == 3
    assert cave.M_LOST in g.msgs()


def test_full_bar_at_spawn_is_not_supercharged():
    g = Game(bar=3); g.set_amt(400.0)
    for k in range(120):
        g.cpu.m.wf32(CAR + cave.C_TIME, k / 60); g.tick()
    assert g.super() == 0 and all(c[0] == "tick_orig" for c in g.calls)   # no sound / message at the start
    g.add(10.0); g.tick()                                 # after earning something (bar still full): now
    assert g.super() == 1 and g.msgs() == [cave.M_SUPER]


def test_tint_forces_size_before_the_first_car_update():
    g = Game(bar=0)                                       # no TICK yet (countdown): the draw comes first
    hud = 0x60000; g.cpu.m.w32(hud + cave.C_HUDCAR, CAR); pptr = 0x61000; g.cpu.m.w32(pptr, hud)
    g.run("TINT", a1=pptr)
    assert g.u(BOOST + cave.B_IDX) == 3 and g.max() == 400.0 and g.cpu.m.read(hud + cave.HUD_SEGS, 1)[0] == 4


def test_fill_pace_default():
    assert TUNE["fill_mult"] == 1.15


def test_wow_and_burnout_texts_are_one_line():
    from chainkit import assets
    assert "BigMessageBurnoutWowPart2" not in assets.TEXTS
    assert assets.TEXTS["BigMessageBurnoutWowPart1"]["UK"] == "BURNOUT! WOW"


# ------------------------------------------------------------------------------------------- v7: Crash mode = vanilla
def crash_game(**kw):
    g = Game(**kw); g.cpu.m.write(A["CRASHFLAG"], b"\1")
    return g


def test_crash_mode_every_hook_is_vanilla():
    g = crash_game(bar=0)
    for _ in range(5):
        g.tick()
    assert g.u(BOOST + cave.B_IDX) == 0 and g.max() == 100.0           # no forced size
    g.set_amt(10.0); g.add(20.0)
    assert g.amt() == 30.0                                               # no fill_mult / pacing
    g.set_amt(100.0); g.tick(); g.tick()
    assert g.super() == 0 and g.msgs() == []                             # no supercharge, no message/sound
    hud = 0x60000; g.cpu.m.w32(hud + cave.C_HUDCAR, CAR); g.cpu.m.write(hud + cave.HUD_SEGS, b"\1")
    pptr = 0x61000; g.cpu.m.w32(pptr, hud)
    g.run("TINT", a1=pptr)
    assert g.cpu.m.read(hud + cave.HUD_SEGS, 1)[0] == 1 and g.u(BOOST + cave.B_IDX) == 0
    assert g.f(A["BARCOL"] + 16 * 3) == 3.0                              # no tint
    g.calls.clear(); g.run("HUDLBL", a0=0x62000, a1=3, s2=hud)
    lab = [c for c in g.calls if c[0] == "label"][0]
    assert lab[2] == 3 and g.u(LAY.g + cave.G_LABELPTR) == A["LABELTXT"] + 24 and "quad" not in g.names()
    g.calls.clear(); g.run("RELEASE", a0=BOOST)
    assert g.names() == ["stopreq"] and g.cpu.m.read(g.st(cave.S_RELEASED), 1)[0] == 0
    g.calls.clear(); g.run("TAKEDOWN", a0=BOOST)
    assert g.names() == ["grow"] and g.f(g.st(cave.S_GRACE)) == 0.0 and g.cpu.m.read(g.st(cave.S_EARNED), 1)[0] == 0
    g.boosting(True); g.set_amt(0.0); g.calls.clear(); g.empty(stopreq=0)
    assert g.names()[-1] == "stop"
    g.cpu.m.wf32(BOOST + cave.B_MULT, 1.0); g.set_amt(50.0); g.run("SUB", s0=BOOST, f12=10.0)
    assert g.amt() == 40.0 and g.names()[-1] == "sub_orig"
    g.set_amt(50.0); g.drain()
    assert g.amt() == pytest.approx(50 - 10 / 60, abs=1e-4)
    g.track("near_miss", 1.0)
    assert g.arrows() == 0.0


def test_crash_mode_shrink_calls_the_original():
    g = crash_game(); seen = []
    g.cpu.stubs[A["SHRINK_ORIG"]] = lambda cpu: seen.append(1)
    g.run("SHRINK", a0=BOOST)
    assert seen == [1]


# ------------------------------------------------------------------------------------------- v7: pacing
def test_oncoming_and_drift_arrow_pacing():
    for skill, speed, secs in (("oncoming", 70.0, 5.0), ("drift", 55.0, 4.0)):
        g = supercharged(); g.boosting(True)
        frames = 0; dist = 0.0
        while g.arrows() < 200.0 and frames < 60 * 20:
            dist += speed / 60; g.track(skill, dist); frames += 1
        assert frames / 60 == pytest.approx(secs, rel=0.1), (skill, frames / 60)


def test_oncoming_and_drift_normal_fill_pacing():
    def call_from(g, ra, amount):
        g.cpu.m.w32(0x70000, ra)                       # FUN_002a3e80's saved $ra = the event's call site
        return g.run("ADD", s0=BOOST, f20=amount)
    for ra, per_m, speed, secs in ((T(0x2CC4A0), 0.3, 70.0, 5.0), (T(0x2CC6DC), 1.0, 55.0, 4.0)):
        g = Game(); g.tick(); g.set_amt(0.0)
        frames = 0
        while g.amt() < 400.0 and frames < 60 * 20:
            call_from(g, ra, per_m * 4 * speed / 60); frames += 1    # value x bar multiplier 4, per frame
        assert frames / 60 == pytest.approx(secs, rel=0.1), (hex(ra), frames / 60)
    g = Game(); g.tick(); g.set_amt(0.0); call_from(g, OTHER_RA, 60.0)   # other events: fill_mult only
    assert g.amt() == pytest.approx(60 * TUNE["fill_mult"])


# ------------------------------------------------------------------------------------------- v8
def award(g, ra, amount):
    g.cpu.m.w32(0x70000, ra)                             # FUN_002a3e80's saved $ra = the award's call site
    return g.run("ADD", s0=BOOST, f20=amount)


def test_slam_and_contact_awards_are_weak():
    g = Game(); g.tick(); g.set_amt(0.0)
    award(g, T(0x2CE254), 360 * 4)                          # slam: 1/6 of the bar
    assert g.amt() == pytest.approx(400 / 6, rel=0.05)
    g.set_amt(0.0); award(g, T(0x2CDF58), 3 * 4)           # trading paint
    assert g.amt() == pytest.approx(3 * 4 * 1.15 * 0.05)
    g.set_amt(0.0)
    for _ in range(60):
        award(g, T(0x2CE8AC), 15 * 4 / 60)                 # one second of rubbing
    assert g.amt() == pytest.approx(15 * 4 * 1.15 * 0.30, rel=1e-3)
    g.set_amt(0.0); award(g, OTHER_RA, 60 * 4)          # near miss untouched (fill_mult only)
    assert g.amt() == pytest.approx(min(400, 240 * 1.15))


def test_slam_lights_a_sixth_of_the_arrows_while_supercharge_boosting():
    g = supercharged(); g.boosting(True)
    award(g, T(0x2CE254), 1440.0)
    assert g.arrows() == pytest.approx(200 / 6, rel=1e-4) and g.amt() == 400.0
    award(g, T(0x2CDF58), 12.0)                             # trading paint: no arrows from the award itself
    assert g.arrows() == pytest.approx(200 / 6, rel=1e-4)
    g.track("rubbing", 1.0); g.track("grinding", 1.0)    # contact seconds in the skill list: 0.05 each
    assert g.arrows() == pytest.approx(200 / 6 + 2 * 0.05 * 200, rel=1e-4)


def test_supercharge_at_once_while_boosting_when_the_bar_fills():
    g = Game(); g.tick(); g.boosting(True); g.set_amt(390.0)
    award(g, OTHER_RA, 100.0)                            # bar reaches the top while R1 is held
    g.tick()
    assert g.super() == 1 and g.msgs() == [cave.M_SUPER] and g.names().count("gain") == 1
    g.drain(); g.tick(); g.drain()                       # supercharge-boosting continues (refill pause first)
    assert g.is_boosting()


def test_bar_kept_full_by_the_game_supercharges():
    g = Game(); g.tick(); g.boosting(True); award(g, OTHER_RA, 1.0)   # earned once
    for _ in range(3):
        g.set_amt(400.0); g.tick()                       # topped up every frame
    assert g.super() == 1 and g.msgs().count(cave.M_SUPER) == 1


def test_no_supercharge_ping_pong_after_a_loss():
    g = supercharged(); g.boosting(True); g.cpu.m.wf32(CAR + cave.C_SPEED, 10.0)
    for _ in range(200):
        g.tick()                                          # slow rule ends it with the bar still full
    assert g.super() == 0
    lost_at = g.msgs().count(cave.M_LOST)
    g.cpu.m.wf32(CAR + cave.C_SPEED, 50.0)
    for _ in range(int(60 * 2.5)):
        g.tick()
    assert g.super() == 0                                 # cooldown 3 s
    for _ in range(60):
        g.tick()
    assert g.super() == 1


def prompt_hud(g, timer):
    hud = 0x65000
    g.cpu.m.w32(hud + 0x214, CAR); g.cpu.m.wf32(hud + 0x220, timer); g.cpu.m.w32(hud + 0x21C, 0x11)
    seen = []
    g.cpu.stubs[T(0x16D378)] = lambda cpu: seen.append("after")
    g.cpu.stubs[T(0x16D36C)] = lambda cpu: seen.append("count")
    g.cpu.cc = timer > 5.0                                # the c.olt.s 5.0 < timer done by the game
    g.run("PROMPT", s1=hud)
    return hud, seen


def test_press_r1_hint_suppressed_for_mod_cars():
    g = Game(); g.tick()
    hud, seen = prompt_hud(g, 6.0)
    assert g.u(hud + 0x21C) == 0x11 and g.f(hud + 0x220) == 0.0 and seen == ["after"]
    hud, seen = prompt_hud(g, 2.0)
    assert seen == ["count"] and g.u(hud + 0x21C) == 0x11


def test_press_r1_hint_vanilla_in_crash_mode():
    g = crash_game(); g.tick()
    hud, seen = prompt_hud(g, 6.0)
    assert g.u(hud + 0x21C) == 0 and seen == ["after"]   # prompt 0 = PRESS R1 TO BOOST


# ------------------------------------------------------------------------------------------- v9: tolerant "full"
def test_bar_kept_full_while_boosting_never_hits_exact_max_still_supercharges():
    """Per frame: award (clamped to max), then the game's drain, then TICK -> the bar sits at max - drain."""
    g = Game(); g.tick(); g.boosting(True); g.set_amt(399.0)
    for f in range(30):
        award(g, OTHER_RA, 1.0)                            # continuous earning (>= drain)
        g.drain()                                          # 10 u/s -> 0.17 below max at TICK time
        assert g.super() or g.amt() < 400.0
        g.tick()
        if g.super():
            break
    assert g.super() == 1 and g.msgs() == [cave.M_SUPER]


def test_full_threshold_boundary():
    g = Game(); g.tick(); g.cpu.m.write(g.st(cave.S_EARNED), b"\1")
    g.set_amt(400 * 0.97); g.tick()
    assert g.super() == 0
    g.set_amt(400 * 0.981); g.tick()
    assert g.super() == 1


def test_supercharged_idle_bar_just_below_max_is_not_lost():
    g = supercharged(); g.set_amt(399.5)
    for _ in range(10):
        g.tick()
    assert g.super() == 1


def test_cheat_arrow_texture_is_copied_before_drawing():
    if not TEXCOPY:
        return
    g = supercharged(); g.boosting(True)
    hud = 0x60000; g.cpu.m.w32(hud + cave.C_HUDCAR, CAR)
    rec = 0x01234560                                     # HUD texture slot 28 = the loaded TalkIcon record
    seen = []
    g.cpu.stubs[A["SETTEX"]] = lambda cpu: seen.append(cpu.m.read(rec + cave.TEX_FROM, len(TEXBLOB)))
    g.run("HUDLBL", a0=0x62000, a1=4, s2=hud)
    assert seen == [TEXBLOB]


def test_arrow_count_and_margin_settings():
    g = supercharged(); g.boosting(True)
    hud = 0x60000; g.cpu.m.w32(hud + cave.C_HUDCAR, CAR)
    rect = 0x62000
    for k, x in enumerate((0.0, 400.0, 580.0, 56.0)):                   # a bar drawn twice as large
        g.cpu.m.wf32(rect + 4 * k, x)
    g.cpu.m.w32(cave.tune_addr(LAY, "arrow_count")[0], 16)
    g.cpu.m.wf32(cave.tune_addr(LAY, "arrow_margin")[0], 19.5)        # Revenge-like layout of v1-v17
    g.cpu.m.wf32(g.st(cave.S_ARROWS), 200.0)
    g.run("HUDLBL", a0=rect, a1=4, s2=hud)
    xs = [q[1][0] for q in g.quads[1::2]]
    assert len(xs) == 16 and xs[0] == pytest.approx(2 * 26.0, abs=1e-3) and xs[-1] == pytest.approx(2 * (290 - 26.0), abs=1e-3)
    g.calls.clear(); g.quads.clear(); g.cpu.m.w32(cave.tune_addr(LAY, "arrow_count")[0], 99)
    g.run("HUDLBL", a0=rect, a1=4, s2=hud)
    assert len(g.quads) == 64                                         # capped at 32 arrows
