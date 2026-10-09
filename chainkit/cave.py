"""The Burnout Chain code cave (Dominator boost rules for Burnout Revenge), generated with the mips DSL.

Everything lives in the top of the 16 KB .sndata hole (PAL 0x4A3678..0x4A7680, USA 0x4A34F8..0x4A7500): data at
REGION, the relocated HUD message table at MSGTAB, code at CODE. MusicKit uses the bottom of the hole (its song
table, <= 1200 bytes). Every patched address is listed in hooks() below; README.md explains the rules in plain words.
The code is written with PAL addresses; Layout(region) translates them for the USA build (regions.py).
"""
import struct

from . import regions
from .mips import Asm, f2u, hi16, lo16

# ------------------------------------------------------------------------------------------- game addresses
PAL_ADDRS = dict(
    # boost class (Revenge FUN_002a3a00 family) and hook return points
    STOP=0x2A4288, STOPREQ=0x2A4180, GROW=0x2A3FA0, SHRINK_ORIG=0x2A3FD0, TICK_ORIG=0x2A2560,
    ADD_RET=0x2A3F10, DRAIN_RET=0x2A3AA8, TAKEDOWN_SKIP=0x114AB8, TINT_RET=0x15E3C0, LABELFN=0x15DB48,
    START=0x2A4078,                  # FUN_002a4078(boost, controller): start boosting
    HELD=0x1F2220,                   # FUN_001f2220(pad controller): "boost held" (controller+0x1388 bit 1)
    PADVAL=0x111B80,                 # FUN_00111b80(pad): the boost control's value (button / trigger, any scheme)
    # globals
    CRASHFLAG=0x54BB9F, NCARS=0x1ED82B4, CARPTRS=0x1ED82C0, DT=0x1D618CC,
    HUDBASE=0x1C02720, MSG_SEND=0x16D668,
    SND_OBJ=0x1C89430, SND_GAIN=0x236D78, SND_LOSE=0x236E30,
    TBL_SIZES=0x4670D0, TBL_MULT=0x4670E0, TBL_RATE=0x4670F0, MINBOOST=0x4670C0,
    SETTEX=0x323528, QUAD=0x324418, BARCOL=0x1C021D0, LABELTXT=0x1C02388,
    MODE_OBJ=0x54BB68,               # current game-mode object; its vtable pointer at +0x118 identifies the mode
    EVENT=0x1C10E98,                 # current event; +0x20 = event type (10 = Burning Lap)
    HUDTEX=0x1F67490,                # 30 HUD texture pointers (name table 0x4AFD40); 28 = TalkIcon, 12 = chev_sml
    MSGTAB_OLD=0x45CE78, MSG_COUNT=190,
)
NOT_ADDRESSES = {"MSG_COUNT"}


def addresses(region=regions.PAL):
    """PAL_ADDRS translated for `region`, plus the hole layout (data 0x3680 and code 0x2680 below the hole end)."""
    a = {k: (v if k in NOT_ADDRESSES else regions.t(region, v)) for k, v in PAL_ADDRS.items()}
    lo, hi = region["hole"]
    a.update(HOLE_START=lo, HOLE_END=hi, REGION=hi - 0x3680, CODE=hi - 0x2680)
    return a


PAL = addresses(regions.PAL)

# car / boost object fields
C_CTRL, C_IDX, C_SPEED, C_TIME, C_BOOST, C_HUDCAR = 0x2C10, 0x3B20, 0x54, 0x24EC, 0x2430, 0x6AC
B_IDX, B_MAX, B_AMT, B_TOTAL, B_RATE, B_MIN, B_MULT, B_CAR, B_INF1, B_INF2, B_ACTIVE, B_STOPREQ = (
    0x38, 0x3C, 0x40, 0x44, 0x48, 0x4C, 0x50, 0x94, 0x98, 0x99, 0x9A, 0x9C)
B_AUTO = 0x9E            # Perfect-Start auto-boost latch (car+0x24CE): set by FUN_0011ff28, cleared only by a crash

# data region layout (offsets from REGION)
STATE = 0x000            # 8 x 32 bytes, indexed by car+0x3B20
S_SUPER, S_ARROWS, S_CHAIN, S_SLOW, S_ANIM, S_FULLT, S_GRACE, S_TIME = 0, 4, 8, 12, 16, 20, 24, 28
S_BEST = S_FULLT        # (v8: the unused best-chain word is the full-hold / cooldown timer)
S_EARNED = 1            # byte: the player earned boost this race (no supercharge from a bar that starts full)
S_RELEASED = 2          # byte: the stop request came from the boost button input (FUN_001dc2f0 / FUN_00204ac8)
S_PAUSED = 3            # byte: the game interrupted a supercharged boost (camera, crashbreaker, ...): keep it
G = 0x100                # globals
G_ONLINE, G_TINTED, G_LABELPTR, G_MODEOFF = 0x00, 0x04, 0x08, 0x0C   # G_MODEOFF: 1 = mode switched off
G_MAGIC = 0x10           # "CHAINKIT" + version u32
G_FSAVE = 0x1C           # float spill (SUB)
G_TUNE = 0x20            # tunables (see TUNABLES): scalars 0x20..0x4C, colours 0x50/0x60/0x70
G_SHADOW, G_LIT, G_DARK = 0x50, 0x60, 0x70   # arrow colours (qwords RGBA, 1.0 = full)
G_POS, G_SPOS, G_CORN, G_UVS = 0x80, 0x88, 0x90, 0xB0
G_EMPTYW = 0xD0
MSGBUF = 0x200           # 64 bytes: one-line "BURNOUT! x<N>" (UTF-16)
ORIGP1 = 0x240           # saved handle of the localized BigMessageBurnoutPart1 text
LABELBUF = 0x300         # (unused since v5)
NAMES = 0xEF0            # message names (ASCII; after the mode table)
SCORN = 0x3C0            # shadow quad corners (32 bytes)
MSGTAB = 0x400           # relocated + extended message table
MAGIC = b"CHAINKIT"
VERSION = 10             # 10: arrow count / margins (edge to edge); 9: SUPERCHARGE LOST always; 8: release = no button while the player drives; 7: debug message ids moved to free ids; 6: autopilot boost start refused; 3: per-mode switches, per-action fill factors, label/hint switches; 4: BTN hook;
                         # 5: button read from the pad, checked every frame

# (name, offset in G_TUNE block, type, default, help)
TUNABLES = [
    ("arrow_gain", 0x00, "f", 1.0, "global multiplier on the per-skill arrow weights (w_*)"),
    ("drain_mult", 0x04, "f", 3.0, "supercharged drain multiplier (Dominator 3.0)"),
    ("refill_cap", 0x08, "f", 0.8, "partial refill cap as fraction of the bar (Dominator 0.8)"),
    ("slow_speed", 0x0C, "f", 60.0 / 2.2369363, "supercharge is lost below this speed (m/s; 26.82 = 60 mph)"),
    ("slow_time", 0x10, "f", 3.0, "... after this many seconds of supercharge-boosting below slow_speed"),
    ("anim_time", 0x14, "f", 0.6, "drain pause after supercharge/refill (seconds)"),
    ("half", 0x18, "f", 0.5, "refill base / arrow pool size as fraction of the bar (Dominator 0.5)"),
    ("domination_chain", 0x1C, "i", 10, "chain that shows BURNOUT DOMINATION!"),
    ("wow_chain", 0x20, "i", 999, "chains above this show WOW"),
    ("flags", 0x24, "i", 0x5F, "bit0 popups, bit1 arrows, bit2 blue tint, bit3 sounds, bit4 slow rule, "
                                "bit5 no earning while boosting (Dominator), bit6 force the full 400-unit bar, "
                                "bit7 show Revenge's x2-x4 bar-size label, bit8 show the PRESS R1 TO BOOST hint, "
                                "bit9 SET = allow boosting without the button (setting only_boost_while_held = off), "
                                "bit10 debug pop-ups when a boost without the button is stopped, "
                                "bit11 bar fire also while the bar fills up (Revenge)"),
    ("arrow_tex_slot", 0x28, "i", 28, "HUD texture slot used for the arrows (28 = TalkIcon -> Boost_Arrow, 12 = chev_sml)"),
    ("fill_mult", 0x2C, "f", 1.15, "boost earned when not supercharged x this (way to the blue bar; 1.0 = Revenge)"),
    ("takedown_grace", 0x248 - G - G_TUNE, "f", 5.0, "seconds after a takedown in which a boost stop (takedown camera) keeps the supercharge"),
    ("fill_w_oncoming", 0xE00 - G - G_TUNE, "f", 0.83, "extra factor on the normal bar fill from ONCOMING (full bar ~5 s at 70 m/s)"),
    ("fill_w_drift", 0xE04 - G - G_TUNE, "f", 0.40, "extra factor on the normal bar fill from DRIFT (full bar ~4 s at 55 m/s)"),
    ("fill_w_slam", 0xE08 - G - G_TUNE, "f", 0.04, "extra factor on the normal bar fill from a SLAM (360 -> ~1/6 of the bar)"),
    ("fill_w_trading_paint", 0xE0C - G - G_TUNE, "f", 0.05, "extra factor on the normal bar fill from TRADING PAINT"),
    ("fill_w_rubbing", 0xE10 - G - G_TUNE, "f", 0.30, "extra factor on the normal bar fill from RUBBING (~20 units/s)"),
    ("arrows_slam", 0xE48 - G - G_TUNE, "f", 1.0 / 6, "arrows per SLAM while supercharge-boosting (fraction of the arrows)"),
    ("arrows_takedown", 0xE74 - G - G_TUNE, "f", 1.0, "arrows per TAKEDOWN while supercharged (fraction of the arrows)"),
    ("modes", 0xE70 - G - G_TUNE, "i", 0xFF, "modes with the mod (bits, see MODES); Crash mode and online are always vanilla"),
    ("arrow_count", 0xE78 - G - G_TUNE, "i", 18, "number of arrows drawn over the bar (look only; 18 fill it edge to edge)"),
    ("arrow_margin", 0xE7C - G - G_TUNE, "f", 2.0, "space between the bar's ends and the first / last arrow (bar design units of 290)"),
    ("full_hold_time", 0x2B8 - G - G_TUNE, "f", 0.0, "a bar that becomes full while boosting supercharges after this many seconds (0 = at once)"),
    ("resuper_cooldown", 0x2BC - G - G_TUNE, "f", 3.0, "no new supercharge for this many seconds after one was lost"),
    ("full_threshold", 0x2C0 - G - G_TUNE, "f", 0.98, "the bar counts as full from this fraction of max (boosting drains every frame after the award)"),
    ("fill_w_air", 0xE14 - G - G_TUNE, "f", 1.0, "extra factor on the normal bar fill from AIR"),
    ("fill_w_crash_escape", 0xE18 - G - G_TUNE, "f", 1.0, "extra factor on the normal bar fill from a CRASH ESCAPE"),
    ("fill_w_tailgating", 0xE1C - G - G_TUNE, "f", 1.0, "extra factor on the normal bar fill from TAILGATING"),
    ("fill_w_grinding", 0xE20 - G - G_TUNE, "f", 1.0, "extra factor on the normal bar fill from GRINDING"),
    ("fill_w_near_miss", 0xE24 - G - G_TUNE, "f", 1.0, "extra factor on the normal bar fill from a NEAR MISS"),
    ("fill_w_checked_traffic", 0xE28 - G - G_TUNE, "f", 1.0, "extra factor on the normal bar fill from CHECKED TRAFFIC"),
    ("shadow_rgba", 0x30, "c", (0.0, 0.0, 0.0, 0.85), "arrow outline/shadow colour (drawn 15% larger behind every arrow)"),
    ("lit_rgba", 0x40, "c", (0.15, 0.85, 1.0, 1.0), "lit arrow colour (Dominator supercharge cyan)"),
    ("dark_rgba", 0x50, "c", (0.05, 0.05, 0.1, 0.55), "unlit arrow colour (dark, translucent)"),
]
# Lower-left skill list (score trackers, car + offset; every update goes through FUN_002c8908(value, tracker)).
# Arrow weight = fraction of the arrow pool per unit of the tracker value (count / metre / second).
SKILLS = [  # (name, car offset, unit, default weight)
    # oncoming: full arrows after ~350 m = ~5 s at 70 m/s; drift: ~220 m = ~4 s at 55 m/s
    ("air", 0x25B4, "m", 0.02), ("oncoming", 0x25D0, "m", 0.003), ("drift", 0x25EC, "m", 0.0045),
    ("near_miss", 0x2674, "count", 0.34), ("checked_traffic", 0x2690, "count", 0.34),
    # contact skills (rubbing / grinding = trading paint) are weak: ~20 s of contact for all arrows
    ("rubbing", 0x28E8, "s", 0.05), ("tailgating", 0x2914, "s", 0.25), ("grinding", 0x2948, "s", 0.05)]
# Awards recognised by their FUN_002a3e80 call site (the return address saved at 0(sp)): kind index into the
# factor arrays at REGION+0x24C (normal-bar fill) and REGION+0x2A0 (arrows while supercharge-boosting).
AWARD_SITES = [(0x2CC4A0, 0), (0x2CC4BC, 0),            # oncoming (FUN_002cc3a0)
               (0x2CC6DC, 1), (0x2CC6F8, 1),            # drift (FUN_002cc618)
               (0x2CE254, 2),                           # slam, attacker (FUN_002ce030)
               (0x2CDF58, 3), (0x2CDF70, 3),            # trading paint (FUN_002cde98)
               (0x2CE8AC, 4),                           # rubbing (FUN_002ce660)
               (0x2CC15C, 5), (0x2CC178, 5),            # air (FUN_002cc098)
               (0x2CAF34, 6),                           # crash escape (FUN_002caa18)
               (0x2CB370, 7),                           # tailgating (FUN_002cafe0)
               (0x2CCB18, 8),                           # grinding (FUN_002ccac0)
               (0x2CEDAC, 9),                           # near miss (FUN_002ce9b0)
               (0x2CCD20, 10)]                          # checked traffic (FUN_002cccc8)
AWARD_KINDS = 11
AWARD_TABLE, AWARD_FILL, AWARD_ARROWS = 0xD80, 0xE00, 0xE40
MODE_TAB = 0xE80             # {u32 mode vtable, u32 mode bit} ..., 0
# Game modes (bit, key, vtables of the mode object at *MODE_OBJ + 0x118). Burning Lap and Preview Lap share one
# mode class; the event type (10 = Burning Lap) tells them apart. Online modes are always vanilla (bit 8 is never
# set); Crash mode is recognised by its own flag byte.
MODES = [(0, "race", (0x49EB20,)), (1, "road_rage", (0x49E750,)), (2, "burning_lap", (0x49DBF8,)),
         (3, "preview_lap", ()), (4, "eliminator", (0x49E388,)), (5, "traffic_attack", (0x49D820,)),
         (6, "splitscreen", (0x49B5D0,)), (7, "other", ()), (8, "online", (0x49B208, 0x49D448, 0x49EEE8))]
MB_BURNING, MB_PREVIEW, MB_OTHER = 1 << 2, 1 << 3, 1 << 7
SKILL_OFFS = 0x390           # region offset: 8 x u32 car offsets
SKILL_W = 0x320              # region offset: 8 x f32 weights (tunables w_<name>)
for _k, (_n, _o, _u, _w) in enumerate(SKILLS):
    TUNABLES.append(("w_" + _n, SKILL_W - G - G_TUNE + 4 * _k, "f", _w,
                     "arrows per %s of %s (fraction of the arrow pool)" % (_u, _n.replace("_", " "))))
FL_MSG, FL_ARROWS, FL_TINT, FL_SOUND, FL_SLOW, FL_NOEARN, FL_FULLBAR = 1, 2, 4, 8, 16, 32, 64
FL_SHOWLABEL, FL_SHOWHINT, FL_FREEBOOST, FL_DEBUG, FL_FILLFIRE = 128, 256, 512, 1024, 2048
H_CAR = 0x6CC            # boost-bar HUD element -> its car
C_PAD = 0x37B0           # car -> pointer to its pad object pointer (human cars)
BYPAD = 0xF80            # region: 8 bytes, 1 = the running boost has been backed by the button (tap vs game boost)
BLKT = 0xFA0             # region: 8 floats, race time of the last BOOST BLOCKED debug pop-up
CTRLT = 0xFC0            # region: 8 floats, race time of the last frame the GAME drove the car (camera / autopilot)
C_INPUT, C_AUTO = 0x2CA9, 0x3B28    # car: 0 = the pad is not read at all; != 0 = autopilot (game drives)
REGRAB = 0.3             # s after the game gives control back in which pressing boost again keeps the supercharge
P_CAR = 0x2E80           # pad controller (FUN_00204ac8's object) -> its car
# design units of the boost bar sprite (FUN_0015daa0: 290 x 28) and the arrow row
DESIGN = dict(w=290.0, h=28.0, x0=26.0, dx=15.9, y=14.0, aw=13.0, ah=16.0, n=16.0)
G_DESIGN = 0xE0  # w,h,x0,dx,y,aw,ah,n (32 bytes, 0xE0..0x100)

# new HUD messages: (name, id, display flags, level). Text = BigMessage<name>Part1/Part2 in MAIN*.BIN.
# Display flags (entry byte 1, read by FUN_00170160): bit0 set = the first of the two big-message slots
# (like PERFECT START / RACE TIME UP / medals), clear = the second slot used by takedowns, awards, Took-1st...
# The supercharge messages use slot 0 so a takedown sign (slot 1, higher id = higher priority) no longer
# interrupts and overdraws them; the BURNOUT messages stay with the awards in slot 1.
NEW_MESSAGES = [("BlueBoostAvailable", 0x74, 0x03, 0x02), ("Burnout", 0x75, 0x02, 0x03),
                ("BurnoutLost", 0x76, 0x03, 0xFF), ("BurnoutDomination", 0x77, 0x02, 0x04),
                ("BurnoutWow", 0x78, 0x02, 0x04),
                ("DebugBoostPad", 0x79, 0x03, 0x02), ("DebugBoostAuto", 0xA7, 0x03, 0x02),
                ("DebugBoostTap", 0xA8, 0x03, 0x02), ("DebugBoostBlock", 0xA9, 0x03, 0x02)]
# Ids must be free in the game's own table (0x7A..0x7F, 0x7B ... are taken: v15's debug ids collided) and must not be
# one the game refuses to queue (FUN_0016d5f8: 1-6, 0x66-0x6A, 0xB7, 0xBD-0xC0, 0xC5-0xC7, 0xE3-0xEB).
FREE_MSG_IDS = (0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0xA7, 0xA8, 0xA9, 0xAA, 0xAB, 0xAC, 0xAD, 0xAE, 0xAF)
REFUSED_MSG_IDS = (set(range(1, 7)) | set(range(0x66, 0x6B)) | {0xB7} | set(range(0xBD, 0xC1))
                   | set(range(0xC5, 0xC8)) | set(range(0xE3, 0xEC)))
HUD_SEGS = 0x6DE         # boost-bar HUD element + 0x6FE (displayed segments), relative to the draw context (+0x20)
M_SUPER, M_BURNOUT, M_LOST, M_DOMI, M_WOW, M_DBGPAD, M_DBGAUTO = 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0xA7
M_DBGTAP, M_DBGBLOCK = 0xA8, 0xA9


# Region words the code changes while the game runs (offsets from REGION): a PCSX2 cheat must never rewrite them
# every frame. The message table is filled once and then rewritten by the game itself (FUN_0016fcf8 turns the name
# pointers into text handles), so a cheat writes it once only. Everything else in the hole is constant.
RUNTIME_RANGES = [(STATE, STATE + 0x100), (G + G_ONLINE, G + G_MAGIC), (G + G_FSAVE, G + G_TUNE),
                  (G + G_POS, G + G_UVS), (MSGBUF, ORIGP1 + 8), (LABELBUF, LABELBUF + 0x20), (SCORN, SCORN + 0x20),
                  (BYPAD, CTRLT + 32)]
# inline texts (PCSX2 cheat) sit at the very end of the hole, right after the code
# Dominator arrow in a PCSX2 cheat: the cheat cannot change GLOBAL.TXD, so the cave keeps a copy of Boost_Arrow's
# texture data (record bytes 0x248..0x580: the GS upload packet with CLUT and pixels - the game uses them exactly as
# loaded from the file) and copies it over the loaded TalkIcon record (HUD texture slot 28) before each draw. It sits
# in the bottom of the hole after MusicKit's song table (95 songs at most).
TEX_FROM, TEX_SIZE = 0x248, 0x580


class Layout:
    def __init__(self, region=regions.PAL, inline_texts=False, tex_copy=False):
        """inline_texts: the pop-up texts come from the cave itself (PCSX2 cheat: no MAIN*.BIN entries).
        tex_copy: the Dominator arrow comes from the cave too (PCSX2 cheat with the user's Dominator art)."""
        self.region = region
        self.inline = inline_texts
        self.tex_copy = tex_copy
        self.a = a = addresses(region)
        R = a["REGION"]
        self.state, self.g, self.labelbuf, self.msgbuf = R + STATE, R + G, R + LABELBUF, R + MSGBUF
        self.names, self.msgtab, self.code = R + NAMES, R + MSGTAB, a["CODE"]
        self.msg_count = a["MSG_COUNT"] + len(NEW_MESSAGES)
        assert self.msgtab + 12 * self.msg_count <= R + AWARD_TABLE      # (no overlap with the tables after it)
        assert CTRLT + 32 <= self.code - R
        self.burnout_entry = self.msgtab + 12 * (a["MSG_COUNT"] + 1)   # NEW_MESSAGES[1]
        size = sum((2 * (len(inline_text(n)) + 1) + 3) & ~3 for n, _, _, _ in NEW_MESSAGES)
        self.texts = (a["HOLE_END"] - size) & ~15
        self.text_addr = {}
        p = self.texts
        for name, mid, _, _ in NEW_MESSAGES:
            self.text_addr[mid] = p
            p += (2 * (len(inline_text(name)) + 1) + 3) & ~3
        assert p <= a["HOLE_END"]
        assert self.texsrc + TEX_SIZE - TEX_FROM <= R

    @property
    def texsrc(self):
        """Address of the arrow texture copy (tex_copy): after MusicKit's song table (95 songs at most)."""
        return (self.region["mk_table_new"] + 95 * 12 + 15) & ~15

    def entry(self, mid):
        """Address of the message table entry of one of our messages."""
        k = [m for _, m, _, _ in NEW_MESSAGES].index(mid)
        return self.msgtab + 12 * (self.a["MSG_COUNT"] + k)

    def once_range(self):
        return self.msgtab, self.msgtab + 12 * self.msg_count

    def t(self, pal_addr):
        """Address in this build of what is at `pal_addr` in the PAL build."""
        return regions.t(self.region, pal_addr)


def inline_text(name):
    """English pop-up text of one of our messages (PCSX2 cheat: no string-table entries)."""
    from . import assets
    return assets.TEXTS["BigMessage%sPart1" % name]["UK"]


def build_texts(lay):
    """UTF-16 texts at lay.texts (inline texts only)."""
    out = bytearray()
    for name, mid, _, _ in NEW_MESSAGES:
        assert lay.texts + len(out) == lay.text_addr[mid]
        b = (inline_text(name) + "\0").encode("utf-16-le")
        out += b + b"\0" * (((len(b) + 3) & ~3) - len(b))
    return bytes(out)


def parse_colour(v):
    """(r,g,b,a) tuple or "r,g,b,a" string -> 4 floats (1.0 = full; keep <= 1.0)."""
    if isinstance(v, str):
        v = [float(x) for x in v.replace(" ", "").split(",")]
    v = tuple(float(x) for x in v)
    if len(v) != 4 or not all(0.0 <= x <= 1.0 for x in v):
        raise ValueError("colour must be 4 values 0..1 (r,g,b,a): %r" % (v,))
    return v


def tune_addr(lay, name):
    for n, off, t, d, h in TUNABLES:
        if n == name:
            return lay.g + G_TUNE + off, t
    raise KeyError(name)


# ------------------------------------------------------------------------------------------------ data
def build_data(lay, old_table, tunables=None):
    """Bytes for REGION..CODE. old_table = the original 190 x 12-byte message entries."""
    a = lay.a
    R = a["REGION"]
    d = bytearray(lay.code - R)
    def w32(addr, v):
        struct.pack_into("<I", d, addr - R, v & 0xFFFFFFFF)
    def wf(addr, x):
        struct.pack_into("<f", d, addr - R, x)
    d[lay.g + G_MAGIC - R:lay.g + G_MAGIC - R + 8] = MAGIC
    w32(lay.g + G_MAGIC + 8, VERSION)
    tv = {n: dflt for n, off, t, dflt, h in TUNABLES}
    tv.update(tunables or {})
    for n, off, t, dflt, h in TUNABLES:
        if t == "c":
            for k, x in enumerate(parse_colour(tv[n])):
                wf(lay.g + G_TUNE + off + 4 * k, x)
        else:
            (wf if t == "f" else w32)(lay.g + G_TUNE + off, tv[n])
    for k, x in enumerate((0, 0, 1, 0, 0, 1, 1, 1)):        # TL, TR, BL, BR
        wf(lay.g + G_UVS + 4 * k, float(x))
    for k, key in enumerate(("w", "h", "x0", "dx", "y", "aw", "ah", "n")):
        wf(lay.g + G_DESIGN + 4 * k, DESIGN[key])
    for k, (n, off, u, w) in enumerate(SKILLS):
        w32(R + SKILL_OFFS + 4 * k, off)
    for k, (ra_, kind) in enumerate(AWARD_SITES):
        w32(R + AWARD_TABLE + 8 * k, lay.t(ra_)); w32(R + AWARD_TABLE + 8 * k + 4, kind)
    assert AWARD_TABLE + 8 * len(AWARD_SITES) <= AWARD_FILL and AWARD_FILL + 4 * AWARD_KINDS <= AWARD_ARROWS
    k = 0
    for bit, key, vts in MODES:
        for vt in vts:
            w32(R + MODE_TAB + 8 * k, lay.t(vt)); w32(R + MODE_TAB + 8 * k + 4, 1 << bit); k += 1
    assert R + MODE_TAB + 8 * k + 4 <= lay.code
    # message names + table
    p = lay.names
    name_ptr = {}
    for name, _, _, _ in NEW_MESSAGES:
        b = name.encode() + b"\0"
        d[p - R:p - R + len(b)] = b
        name_ptr[name] = p
        p += (len(b) + 3) & ~3
    assert p <= R + BYPAD and lay.names >= R + MODE_TAB + 8 * k + 4
    assert len(old_table) == 12 * a["MSG_COUNT"]
    t = bytearray(old_table)
    for name, mid, b1, lvl in NEW_MESSAGES:
        t += struct.pack("<3I", mid | (b1 << 8) | (0x01 << 16) | (lvl << 24), name_ptr[name], 0)
    d[lay.msgtab - R:lay.msgtab - R + len(t)] = t
    return bytes(d)


# ------------------------------------------------------------------------------------------------ code
class CaveAsm(Asm):
    def __init__(self, lay):
        super().__init__(lay.code)
        self.lay, self.A = lay, lay.a
        self._n = 0

    def L(self, stem):
        self._n += 1
        return "%s_%d" % (stem, self._n)

    def gaddr(self, off):
        return self.lay.g + off

    def active(self, car, boost, fail):
        """Branch to fail unless: human car, not Crash mode, not online, mode switched on, no infinite boost."""
        A = self.A
        self.lw("t0", C_CTRL, car); self.bnez("t0", fail); self.nop()
        self.mem("lbu", "t0", A["CRASHFLAG"], "t0"); self.bnez("t0", fail); self.nop()
        self.mem("lw", "t0", self.gaddr(G_ONLINE), "t0"); self.bnez("t0", fail); self.nop()
        self.mem("lw", "t0", self.gaddr(G_MODEOFF), "t0"); self.bnez("t0", fail); self.nop()
        self.lbu("t0", B_INF1, boost); self.bnez("t0", fail); self.nop()
        self.lbu("t0", B_INF2, boost); self.bnez("t0", fail); self.nop()

    def stateptr(self, car, out):
        self.lw(out, C_IDX, car); self.andi(out, out, 7); self.sll(out, out, 5)
        self.la("t0", self.lay.state); self.addu(out, out, "t0")

    def gflag(self, bit, skip, tmp="t0"):
        self.mem("lw", tmp, self.gaddr(G_TUNE + 0x24), tmp); self.andi(tmp, tmp, bit); self.beqz(tmp, skip); self.nop()

    def bypad(self, car, out):
        """out = address of the car's 'boost backed by the button' byte (uses t0)."""
        self.lw(out, C_IDX, car); self.andi(out, out, 7)
        self.la("t0", self.A["REGION"] + BYPAD); self.addu(out, out, "t0")

    def game_driving(self, car, out):
        """out = 1 while the game, not the player, controls the car (takedown camera / autopilot). Uses t0."""
        self.lbu(out, C_INPUT, car); self.sltiu(out, out, 1)
        self.lbu("t0", C_AUTO, car); self.sltu("t0", "zero", "t0"); self.or_(out, out, "t0")

    def regrab_window(self, car, out):
        """out = 1 within REGRAB s after the game gave control back. Uses t0, f0-f2."""
        no = self.L("rw")
        self.lw("t0", C_IDX, car); self.andi("t0", "t0", 7); self.sll("t0", "t0", 2)
        self.la(out, self.A["REGION"] + CTRLT); self.addu("t0", "t0", out)
        self.li(out, 0)
        self.lwc1("f0", C_TIME, car); self.lwc1("f1", 0, "t0"); self.sub_s("f0", "f0", "f1")
        self.mtc1("zero", "f2"); self.nop(); self.c_lt_s("f0", "f2"); self.bc1t(no); self.nop()   # clock went back
        self.lif("f2", REGRAB, tmp="t0"); self.c_lt_s("f0", "f2"); self.bc1f(no); self.nop()
        self.li(out, 1)
        self.label(no)

    def debug_msg(self, car, mid):
        skip = self.L("nodbg")
        self.gflag(FL_DEBUG, skip)
        self.send_msg(car, mid)
        self.label(skip)

    def gfloat(self, freg, toff):
        self.mem("lwc1", freg, self.gaddr(G_TUNE + toff), "t0")

    def send_msg(self, car, mid, param_reg=None, set_text=True):
        """FUN_0016d668(hud(car), id, param, -1, 0, 0, -1) when popups are enabled. With inline texts (PCSX2
        cheat) the message's text handle is set to our own UTF-16 text first (no second line)."""
        skip = self.L("nomsg")
        self.gflag(FL_MSG, skip)
        if self.lay.inline and set_text:
            self.la("t3", self.lay.text_addr[mid]); self.la("t4", self.lay.entry(mid))
            self.sw("t3", 4, "t4"); self.sw("zero", 8, "t4")
        self.lw("t0", C_IDX, car)
        # t1 = idx * 0x2E8 (= 512+128+64+32+8)
        self.sll("t1", "t0", 9)
        for sh in (7, 6, 5, 3):
            self.sll("t2", "t0", sh); self.addu("t1", "t1", "t2")
        self.la("a0", self.A["HUDBASE"]); self.addu("a0", "a0", "t1")
        self.li("a1", mid)
        if param_reg:
            self.move("a2", param_reg)
        else:
            self.li("a2", 0)
        self.li("a3", -1); self.li("t0", 0); self.li("t1", 0); self.li("t2", -1)
        self.jal(self.A["MSG_SEND"]); self.nop()
        self.label(skip)

    def sound(self, fn):
        skip = self.L("nosnd")
        self.gflag(FL_SOUND, skip)
        self.la("a0", self.A["SND_OBJ"]); self.jal(fn); self.nop()
        self.label(skip)

    def force_full(self, boost):
        """Bar size index 3 (400 units) with its table values, like FUN_002a4020(b, 3). Uses t1-t3, f0, f1."""
        A = self.A
        done = self.L("ff")
        self.lw("t1", B_IDX, boost); self.li("t2", 3); self.beq("t1", "t2", done); self.nop()
        self.sw("t2", B_IDX, boost)
        self.mem("lw", "t3", A["TBL_SIZES"] + 12, "t3"); self.sw("t3", B_MAX, boost)
        self.mem("lwc1", "f0", A["TBL_RATE"] + 12, "t3"); self.swc1("f0", B_RATE, boost)
        self.mem("lw", "t3", A["TBL_MULT"] + 12, "t3"); self.sw("t3", B_MULT, boost)
        self.mem("lwc1", "f1", A["MINBOOST"], "t3"); self.mul_s("f1", "f0", "f1"); self.swc1("f1", B_MIN, boost)
        self.label(done)

    def swap_bar_colours(self):
        """Swap R and B of the 10 boost-bar colour vectors 0x1C021D0..0x1C02260 (self-inverse)."""
        lp = self.L("swap")
        self.la("t1", self.A["BARCOL"]); self.li("t2", 10)
        self.label(lp)
        self.lw("t3", 0, "t1"); self.lw("t4", 8, "t1"); self.sw("t4", 0, "t1"); self.sw("t3", 8, "t1")
        self.addiu("t2", "t2", -1); self.bnez("t2", lp); self.addiu("t1", "t1", 16)

    def push(self, size, regs):
        self.addiu("sp", "sp", -size)
        for k, rg in enumerate(regs):
            self.sd(rg, 8 * k, "sp")

    def pop(self, size, regs):
        for k, rg in enumerate(regs):
            self.ld(rg, 8 * k, "sp")
        self.addiu("sp", "sp", size)


def build_code(lay):
    A = lay.a
    TR = lay.t
    a = CaveAsm(lay)
    T = G_TUNE

    # ---------------------------------------------------------------- ADD (inline, from FUN_002a3e80 @0x2A3EE8)
    # s0 = boost, f20 = amount after the earn multipliers. Exits to the original epilogue.
    # ---------------------------------------------------------------- TRACK (FUN_002c8908 entry, leaf)
    # Every entry of the lower-left skill list (NEAR MISS, ONCOMING, DRIFT, AIR, CHECKED TRAFFIC, TAILGATING,
    # GRINDING, RUBBING) is updated through FUN_002c8908(f12 = new value, a0 = tracker = car + fixed offset).
    # While supercharge-boosting the increase lights arrows: delta x w_<skill> x pool x arrow_gain.
    # a1 = tracker (the displaced `move a1,a0` ran in the delay slot); keeps a1/f12; returns to 0x2C8910.
    a.label("TRACK")
    a.lwc1("f0", 4, "a1"); a.sub_s("f1", "f12", "f0")                   # delta = new - old
    a.mtc1("zero", "f2"); a.nop(); a.c_lt_s("f2", "f1"); a.bc1f("TR_out"); a.nop()
    a.mem("lw", "t2", A["NCARS"], "t1")
    a.sltiu("t3", "t2", 13); a.bnez("t3", "TR_cnt"); a.nop(); a.li("t2", 12)
    a.label("TR_cnt")
    a.la("t3", A["CARPTRS"])
    a.label("TR_car")
    a.blez("t2", "TR_out"); a.nop()
    a.lw("t4", 0, "t3"); a.beqz("t4", "TR_nextcar"); a.nop()
    a.subu("t5", "a1", "t4")                                              # tracker - car
    a.la("t6", lay.a["REGION"] + SKILL_OFFS); a.li("t7", 0)
    a.label("TR_skill")
    a.lw("v0", 0, "t6"); a.beq("v0", "t5", "TR_found"); a.nop()
    a.addiu("t6", "t6", 4); a.addiu("t7", "t7", 1); a.slti("v0", "t7", len(SKILLS)); a.bnez("v0", "TR_skill"); a.nop()
    a.label("TR_nextcar")
    a.addiu("t3", "t3", 4); a.b("TR_car"); a.addiu("t2", "t2", -1)
    a.label("TR_found")                                                   # t4 = car, t7 = skill index
    a.addiu("t9", "t4", C_BOOST)
    a.active("t4", "t9", "TR_out")
    a.gflag(FL_ARROWS, "TR_out")
    a.stateptr("t4", "t8")
    a.lbu("t1", S_SUPER, "t8"); a.beqz("t1", "TR_out"); a.nop()
    a.lbu("t1", B_ACTIVE, "t9"); a.beqz("t1", "TR_out"); a.nop()
    a.sll("t7", "t7", 2); a.la("t6", lay.a["REGION"] + SKILL_W); a.addu("t6", "t6", "t7")
    a.lwc1("f0", 0, "t6"); a.mul_s("f1", "f1", "f0")                     # x weight
    a.gfloat("f0", 0x00); a.mul_s("f1", "f1", "f0")                      # x arrow_gain
    a.lwc1("f2", B_MAX, "t9"); a.gfloat("f0", 0x18); a.mul_s("f2", "f2", "f0")   # pool = half x max
    a.mul_s("f1", "f1", "f2")
    a.lwc1("f0", S_ARROWS, "t8"); a.add_s("f0", "f0", "f1")
    a.c_lt_s("f2", "f0"); a.bc1f("TR_st"); a.nop(); a.mov_s("f0", "f2")
    a.label("TR_st")
    a.swc1("f0", S_ARROWS, "t8")
    a.label("TR_out")
    a.lwc1("f0", 4, "a1")                                               # original 2nd instruction
    a.j(TR(0x2C8910)); a.nop()

    a.label("ADD")
    a.lw("t9", B_CAR, "s0")
    a.active("t9", "s0", "A_orig")
    a.stateptr("t9", "t8")
    # which award? t4 = kind (AWARD_SITES) or -1, from FUN_002a3e80's saved return address
    a.lw("t3", 0, "sp"); a.li("t4", -1)
    a.la("t5", lay.a["REGION"] + AWARD_TABLE); a.li("t6", len(AWARD_SITES))
    a.label("A_site")
    a.lw("t7", 0, "t5"); a.bne("t7", "t3", "A_snext"); a.nop()
    a.lw("t4", 4, "t5"); a.b("A_sdone"); a.nop()
    a.label("A_snext")
    a.addiu("t6", "t6", -1); a.bgtz("t6", "A_site"); a.addiu("t5", "t5", 8)
    a.label("A_sdone")
    a.lbu("t1", S_SUPER, "t8"); a.lbu("t2", B_ACTIVE, "s0")
    # supercharged: the bar belongs to the chain (drain / refill); arrows come from the skill list (TRACK),
    # plus per-award arrows (slam) while boosting
    a.beqz("t1", "A_notsuper"); a.nop()
    a.beqz("t2", "A_exit"); a.nop()
    a.bltz("t4", "A_exit"); a.nop()
    a.sll("t5", "t4", 2); a.la("t6", lay.a["REGION"] + AWARD_ARROWS); a.addu("t6", "t6", "t5")
    a.lwc1("f0", 0, "t6"); a.mtc1("zero", "f1"); a.nop(); a.c_lt_s("f1", "f0"); a.bc1f("A_exit"); a.nop()
    a.lwc1("f2", B_MAX, "s0"); a.gfloat("f3", 0x18); a.mul_s("f2", "f2", "f3")        # pool
    a.mul_s("f0", "f0", "f2"); a.lwc1("f1", S_ARROWS, "t8"); a.add_s("f1", "f1", "f0")
    a.c_lt_s("f2", "f1"); a.bc1f("A_ast"); a.nop(); a.mov_s("f1", "f2")
    a.label("A_ast")
    a.swc1("f1", S_ARROWS, "t8"); a.b("A_exit"); a.nop()
    a.label("A_notsuper")
    a.beqz("t2", "A_fill"); a.nop()
    a.gflag(FL_NOEARN, "A_fill")
    a.b("A_exit"); a.nop()                                  # Dominator option: can't earn while you burn
    a.label("A_fill")
    a.li("t1", 1); a.sb("t1", S_EARNED, "t8")              # earned this race -> may supercharge
    a.gfloat("f0", 0x2C); a.mul_s("f20", "f20", "f0")     # fill_mult: faster way to the blue bar
    # per-award pacing (oncoming, drift, slam, trading paint, rubbing)
    a.bltz("t4", "A_orig"); a.nop()
    a.sll("t5", "t4", 2); a.la("t6", lay.a["REGION"] + AWARD_FILL); a.addu("t6", "t6", "t5")
    a.lwc1("f0", 0, "t6"); a.mul_s("f20", "f20", "f0")
    a.label("A_orig")                                       # original FUN_002a3e80 tail
    a.lwc1("f0", B_AMT, "s0"); a.lwc1("f1", B_TOTAL, "s0"); a.add_s("f0", "f0", "f20")
    a.lwc1("f2", B_MAX, "s0"); a.add_s("f1", "f1", "f20"); a.c_lt_s("f2", "f0")
    a.swc1("f0", B_AMT, "s0"); a.bc1f("A_exit"); a.swc1("f1", B_TOTAL, "s0")
    a.swc1("f2", B_AMT, "s0")
    a.label("A_exit")
    a.j(A["ADD_RET"]); a.nop()

    # ---------------------------------------------------------------- DRAIN (inline, FUN_002a3a00 @0x2A3A98)
    # s0 = boost, f0 = drain rate. amount -= dt * rate (x drain_mult when supercharged, 0 during the refill pause)
    a.label("DRAIN")
    a.mem("lwc1", "f2", A["DT"], "t1")
    a.lw("t9", B_CAR, "s0")
    a.active("t9", "s0", "D_plain")
    a.stateptr("t9", "t8")
    a.lbu("t1", S_SUPER, "t8"); a.beqz("t1", "D_plain"); a.nop()
    a.lwc1("f3", S_ANIM, "t8"); a.mtc1("zero", "f1"); a.nop()
    a.c_lt_s("f1", "f3"); a.bc1f("D_fast"); a.nop()
    a.mtc1("zero", "f0"); a.b("D_plain"); a.nop()
    a.label("D_fast")
    a.gfloat("f1", 0x04); a.mul_s("f0", "f0", "f1")
    a.label("D_plain")
    a.lwc1("f1", B_AMT, "s0"); a.mul_s("f0", "f2", "f0"); a.sub_s("f1", "f1", "f0"); a.swc1("f1", B_AMT, "s0")
    a.j(A["DRAIN_RET"]); a.nop()

    # ---------------------------------------------------------------- SUB (inline, FUN_002a3f28 @0x2A3F50)
    # s0 = boost, f12 = boost units lost (slam victim, checked/wrecked traffic, crash wipe). Dominator rule: while
    # supercharge-boosting the bar never drops below half (so a hit cannot "release" the boost and kill the chain);
    # supercharged but idle -> the supercharge is lost; otherwise the original code.
    a.label("SUB")
    a.lw("t9", B_CAR, "s0")
    a.active("t9", "s0", "S_orig")
    a.stateptr("t9", "t8")
    a.lbu("t1", S_SUPER, "t8"); a.beqz("t1", "S_orig"); a.nop()
    a.lbu("t2", B_ACTIVE, "s0"); a.beqz("t2", "S_idle"); a.nop()
    a.lwc1("f0", B_MULT, "s0"); a.mul_s("f0", "f12", "f0"); a.lwc1("f4", B_AMT, "s0"); a.sub_s("f1", "f4", "f0")
    a.lwc1("f2", B_MAX, "s0"); a.gfloat("f3", 0x18); a.mul_s("f2", "f2", "f3")       # floor = min(amount, half)
    a.c_lt_s("f4", "f2"); a.bc1f("S_fl"); a.nop(); a.mov_s("f2", "f4")
    a.label("S_fl")
    a.c_lt_s("f1", "f2"); a.bc1f("S_st"); a.nop(); a.mov_s("f1", "f2")
    a.label("S_st")
    a.swc1("f1", B_AMT, "s0"); a.j(TR(0x2A3F8C)); a.nop()          # original epilogue
    a.label("S_idle")
    a.mem("swc1", "f12", a.gaddr(G_FSAVE), "t1")
    a.move("a0", "t8"); a.jal("LOSE"); a.move("a1", "t9")
    a.mem("lwc1", "f12", a.gaddr(G_FSAVE), "t1")
    a.label("S_orig")
    a.lwc1("f0", B_MULT, "s0"); a.lwc1("f1", B_AMT, "s0")      # replaced 0x2A3F50 + its delay slot copy
    a.j(TR(0x2A3F58)); a.nop()

    # ---------------------------------------------------------------- helpers: a0 = state, a1 = car
    REGS3 = ["ra", "s0", "s1"]
    a.label("SUPER_ON")
    a.push(0x20, REGS3); a.move("s0", "a0"); a.move("s1", "a1")
    a.li("t1", 1); a.sb("t1", S_SUPER, "s0"); a.sw("zero", S_ARROWS, "s0"); a.sw("zero", S_SLOW, "s0")
    a.gfloat("f0", 0x14); a.swc1("f0", S_ANIM, "s0")
    a.send_msg("s1", M_SUPER)
    a.sound(A["SND_GAIN"])
    a.pop(0x20, REGS3); a.jr("ra"); a.nop()

    a.label("LOSE")
    a.push(0x20, REGS3); a.move("s0", "a0"); a.move("s1", "a1")
    a.lbu("t1", S_SUPER, "s0"); a.beqz("t1", "LO_ret"); a.nop()
    a.sb("zero", S_SUPER, "s0"); a.sw("zero", S_ARROWS, "s0"); a.sw("zero", S_SLOW, "s0"); a.sw("zero", S_ANIM, "s0")
    a.mem("lwc1", "f0", lay.a["REGION"] + 0x2BC, "t1"); a.neg_s("f0", "f0"); a.swc1("f0", S_FULLT, "s0")   # cooldown
    a.sw("zero", S_CHAIN, "s0")
    # SUPERCHARGE LOST every time a supercharge ends (v1-v16 showed it only when a chain was running, so a partial
    # refill without any BURNOUT before it was silent)
    a.send_msg("s1", M_LOST)
    a.sound(A["SND_LOSE"])
    a.label("LO_ret")
    a.pop(0x20, REGS3); a.jr("ra"); a.nop()

    a.label("WFMT")                                         # a0 = UTF-16 buffer, a1 = n -> "x<n>" (n <= 9999)
    a.sltiu("t1", "a1", 10000); a.bnez("t1", "WF_ok"); a.nop(); a.li("a1", 9999)
    a.label("WF_ok")
    a.li("t0", ord("x")); a.sh("t0", 0, "a0"); a.addiu("a0", "a0", 2); a.li("t5", 0)
    for p in (1000, 100, 10, 1):
        lp, dn, em, sk = a.L("wl"), a.L("wd"), a.L("we"), a.L("ws")
        a.li("t1", p); a.li("t2", 0)
        a.label(lp)
        a.slt("t3", "a1", "t1"); a.bnez("t3", dn); a.nop()
        a.subu("a1", "a1", "t1"); a.b(lp); a.addiu("t2", "t2", 1)
        a.label(dn)
        if p != 1:
            a.bnez("t2", em); a.nop(); a.beqz("t5", sk); a.nop()
        a.label(em)
        a.addiu("t3", "t2", 0x30); a.sh("t3", 0, "a0"); a.addiu("a0", "a0", 2); a.li("t5", 1)
        a.label(sk)
    a.sh("zero", 0, "a0"); a.jr("ra"); a.nop()

    a.label("BURNMSG")                                      # message for the chain just completed
    a.push(0x20, REGS3); a.move("s0", "a0"); a.move("s1", "a1")
    a.lw("t4", S_CHAIN, "s0")
    a.mem("lw", "t5", a.gaddr(T + 0x1C), "t5"); a.bne("t4", "t5", "BM_notdomi"); a.nop()
    a.send_msg("s1", M_DOMI, "t4"); a.b("BM_snd"); a.nop()
    a.label("BM_notdomi")
    a.mem("lw", "t5", a.gaddr(T + 0x20), "t5"); a.slt("t6", "t5", "t4"); a.beqz("t6", "BM_burn"); a.nop()
    a.send_msg("s1", M_WOW, "t4"); a.b("BM_snd"); a.nop()
    a.label("BM_burn")
    # one line: "BURNOUT!" (chain 1) or "<localized BURNOUT!> x<N>" written into our buffer; no second line
    a.la("t7", lay.burnout_entry + 8); a.sw("zero", 0, "t7")
    if lay.inline:                                          # cheat: our own "BURNOUT!" text
        a.la("t6", lay.text_addr[M_BURNOUT]); a.la("t3", lay.a["REGION"] + ORIGP1); a.sw("t6", 0, "t3")
        a.la("t7", lay.burnout_entry + 4); a.b("BM_orig"); a.nop()
    a.la("t7", lay.burnout_entry + 4); a.lw("t6", 0, "t7"); a.la("t5", lay.msgbuf); a.beq("t6", "t5", "BM_orig"); a.nop()
    a.la("t3", lay.a["REGION"] + ORIGP1); a.sw("t6", 0, "t3")       # save the game's text handle
    a.label("BM_orig")
    a.la("t3", lay.a["REGION"] + ORIGP1); a.lw("t6", 0, "t3")
    a.slti("t1", "t4", 2); a.beqz("t1", "BM_fmt"); a.nop()
    a.sw("t6", 0, "t7"); a.b("BM_send"); a.nop()                   # chain 1: the plain text
    a.label("BM_fmt")
    a.beqz("t6", "BM_send"); a.nop()
    a.la("a0", lay.msgbuf); a.li("t2", 24)
    a.label("BM_copy")
    a.lhu("t1", 0, "t6"); a.beqz("t1", "BM_cdone"); a.nop(); a.blez("t2", "BM_cdone"); a.nop()
    a.sh("t1", 0, "a0"); a.addiu("t6", "t6", 2); a.addiu("t2", "t2", -1); a.b("BM_copy"); a.addiu("a0", "a0", 2)
    a.label("BM_cdone")
    a.li("t1", 0x20); a.sh("t1", 0, "a0"); a.addiu("a0", "a0", 2)
    a.jal("WFMT"); a.move("a1", "t4")
    a.la("t7", lay.burnout_entry + 4); a.la("t6", lay.msgbuf); a.sw("t6", 0, "t7")
    a.label("BM_send")
    a.lw("t4", S_CHAIN, "s0")
    a.send_msg("s1", M_BURNOUT, "t4", set_text=False)
    a.label("BM_snd")
    a.sound(A["SND_GAIN"])
    a.pop(0x20, REGS3); a.jr("ra"); a.nop()

    # ---------------------------------------------------------------- TICK (jal from 0x2A3E3C, every car every frame)
    # a0 = boost, a1 = car; tail-calls the original FUN_002a2560(a0, a1).
    # ---------------------------------------------------------------- MODECHK (leaf, t0-t3 only)
    # G_MODEOFF = 1 when the current game mode is switched off in the `modes` setting.
    a.label("MODECHK")
    a.li("t3", MB_OTHER)
    a.mem("lw", "t0", A["MODE_OBJ"], "t0"); a.beqz("t0", "MC_have"); a.nop()
    a.lw("t0", 0x118, "t0"); a.la("t1", A["REGION"] + MODE_TAB)
    a.label("MC_loop")
    a.lw("t2", 0, "t1"); a.beqz("t2", "MC_have"); a.nop()
    a.bne("t2", "t0", "MC_next"); a.nop()
    a.lw("t3", 4, "t1"); a.b("MC_have"); a.nop()
    a.label("MC_next")
    a.b("MC_loop"); a.addiu("t1", "t1", 8)
    a.label("MC_have")
    a.li("t2", MB_BURNING); a.bne("t3", "t2", "MC_mask"); a.nop()
    a.mem("lw", "t0", A["EVENT"], "t0"); a.beqz("t0", "MC_prev"); a.nop()
    a.lw("t0", 0x20, "t0"); a.li("t2", 10); a.beq("t0", "t2", "MC_mask"); a.nop()
    a.label("MC_prev")
    a.li("t3", MB_PREVIEW)
    a.label("MC_mask")
    a.mem("lw", "t0", A["REGION"] + 0xE70, "t0"); a.andi("t0", "t0", 0xFF)       # online (bit 8) never on
    a.and_("t0", "t0", "t3"); a.sltiu("t0", "t0", 1)
    a.mem("sw", "t0", a.gaddr(G_MODEOFF), "t1")
    a.jr("ra"); a.nop()

    R6 = ["ra", "a0", "a1", "s0", "s1", "s2"]
    a.label("TICK")
    a.push(0x30, R6)
    a.move("s0", "a0"); a.lw("s1", B_CAR, "a0")
    a.lw("t0", C_CTRL, "s1"); a.bnez("t0", "T_done"); a.nop()
    # online = any remote car (controller type 2) in the race
    a.mem("lw", "t2", A["NCARS"], "t1")
    a.sltiu("t3", "t2", 13); a.bnez("t3", "T_cnt"); a.nop(); a.li("t2", 12)
    a.label("T_cnt")
    a.la("t3", A["CARPTRS"]); a.li("t4", 0)
    a.label("T_scan")
    a.blez("t2", "T_scanned"); a.nop()
    a.lw("t5", 0, "t3"); a.beqz("t5", "T_next"); a.nop()
    a.lw("t6", C_CTRL, "t5"); a.addiu("t6", "t6", -2); a.bnez("t6", "T_next"); a.nop()
    a.li("t4", 1)
    a.label("T_next")
    a.addiu("t3", "t3", 4); a.b("T_scan"); a.addiu("t2", "t2", -1)
    a.label("T_scanned")
    a.mem("sw", "t4", a.gaddr(G_ONLINE), "t1")
    a.jal("MODECHK"); a.nop()
    a.stateptr("s1", "s2")
    a.active("s1", "s0", "T_inactive")
    # new race (race clock went backwards) -> reset the state
    a.lwc1("f0", C_TIME, "s1"); a.lwc1("f1", S_TIME, "s2"); a.swc1("f0", S_TIME, "s2")
    a.sub_s("f1", "f1", "f0"); a.lif("f3", 0.5); a.c_lt_s("f3", "f1"); a.bc1f("T_noreset"); a.nop()   # jumped back > 0.5 s
    a.sb("zero", S_SUPER, "s2"); a.sw("zero", S_ARROWS, "s2"); a.sw("zero", S_CHAIN, "s2"); a.sw("zero", S_SLOW, "s2")
    a.sw("zero", S_ANIM, "s2"); a.sw("zero", S_BEST, "s2"); a.sw("zero", S_GRACE, "s2"); a.sb("zero", S_EARNED, "s2")
    a.sb("zero", S_RELEASED, "s2"); a.sb("zero", S_PAUSED, "s2")
    a.label("T_noreset")
    # boost only while the button is held - also while the pad controller is not asked (takedown camera,
    # autopilot): any boost the player's boost control does not back is stopped every frame
    # remember the last frame the game drove the car (for the REGRAB window after it gives control back)
    a.game_driving("s1", "t1"); a.beqz("t1", "T_ownctl"); a.nop()
    a.lw("t1", C_IDX, "s1"); a.andi("t1", "t1", 7); a.sll("t1", "t1", 2)
    a.la("t2", A["REGION"] + CTRLT); a.addu("t2", "t2", "t1")
    a.lwc1("f0", C_TIME, "s1"); a.swc1("f0", 0, "t2")
    a.label("T_ownctl")
    # (debug pop-ups: TAP END = the button was let go, AUTO = a boost the button never backed)
    a.mem("lw", "t0", a.gaddr(T + 0x24), "t0"); a.andi("t0", "t0", FL_FREEBOOST); a.bnez("t0", "T_btnok"); a.nop()
    a.lbu("t1", B_ACTIVE, "s0"); a.bnez("t1", "T_bact"); a.nop()
    a.bypad("s1", "t6"); a.sb("zero", 0, "t6"); a.b("T_btnok"); a.nop()
    a.label("T_bact")
    a.move("a0", "s1"); a.jal("PADHELD"); a.nop()
    a.beqz("v0", "T_bstop"); a.nop()
    a.bypad("s1", "t6"); a.li("t1", 1); a.sb("t1", 0, "t6"); a.b("T_btnok"); a.nop()
    a.label("T_bstop")
    a.move("a0", "s1"); a.jal("BSTOP"); a.nop()
    a.bypad("s1", "t6"); a.lbu("t1", 0, "t6"); a.sb("zero", 0, "t6")
    a.bnez("t1", "T_btap"); a.nop()
    a.debug_msg("s1", M_DBGAUTO); a.b("T_btnok"); a.nop()
    a.label("T_btap")
    a.debug_msg("s1", M_DBGTAP)
    a.label("T_btnok")
    # optional (flag bit6): Dominator's always-full 400-unit bar. Off by default: Revenge's own bar sizes per mode
    # (and the takedown growth / crash shrink) are kept; forcing it made the HUD play 3 segment-gain sounds.
    a.gflag(FL_FULLBAR, "T_sized")
    a.force_full("s0")
    a.label("T_sized")
    a.mem("lwc1", "f2", A["DT"], "t1")                      # takedown grace timer runs down
    a.lwc1("f0", S_GRACE, "s2"); a.mtc1("zero", "f1"); a.nop(); a.c_lt_s("f1", "f0"); a.bc1f("T_nograce"); a.nop()
    a.sub_s("f0", "f0", "f2"); a.swc1("f0", S_GRACE, "s2")
    a.label("T_nograce")
    a.lbu("t1", S_SUPER, "s2"); a.bnez("t1", "T_super"); a.nop()
    # not supercharged: a full bar becomes SUPERCHARGED (not while boosting: no earning then, and a supercharge
    # lost to the slow rule must not come straight back while the bar is still full)
    # S_FULLT < 0: cooldown after a lost supercharge; > 0: time the bar has stayed full while boosting
    a.lwc1("f3", S_FULLT, "s2"); a.mtc1("zero", "f1"); a.nop(); a.c_lt_s("f3", "f1"); a.bc1f("T_nocool"); a.nop()
    a.add_s("f3", "f3", "f2"); a.c_lt_s("f3", "f1"); a.bc1t("T_coolst"); a.nop(); a.mov_s("f3", "f1")
    a.label("T_coolst")
    a.swc1("f3", S_FULLT, "s2"); a.b("T_done"); a.nop()
    a.label("T_nocool")
    a.lbu("t1", S_EARNED, "s2"); a.beqz("t1", "T_done"); a.nop()   # a bar that is full at the start is not earned
    a.lwc1("f0", B_AMT, "s0"); a.lwc1("f1", B_MAX, "s0")
    a.mem("lwc1", "f3", lay.a["REGION"] + 0x2C0, "t1"); a.mul_s("f1", "f1", "f3")   # x full_threshold
    a.c_lt_s("f0", "f1"); a.bc1t("T_notfull"); a.nop()
    a.lwc1("f3", S_FULLT, "s2")
    a.lbu("t1", B_ACTIVE, "s0"); a.beqz("t1", "T_superon"); a.nop()
    # boosting with the bar kept full (earning >= drain, e.g. Burning Lap / fast cars): supercharge after a moment
    a.add_s("f3", "f3", "f2"); a.swc1("f3", S_FULLT, "s2")
    a.mem("lwc1", "f0", lay.a["REGION"] + 0x2B8, "t1"); a.c_lt_s("f3", "f0"); a.bc1t("T_done"); a.nop()
    a.b("T_superon"); a.nop()
    a.label("T_notfull")
    a.sw("zero", S_FULLT, "s2"); a.b("T_done"); a.nop()
    a.label("T_superon")
    a.sw("zero", S_FULLT, "s2")
    a.mtc1("zero", "f2"); a.nop(); a.c_lt_s("f2", "f1"); a.bc1f("T_done"); a.nop()
    a.move("a0", "s2"); a.jal("SUPER_ON"); a.move("a1", "s1")
    a.b("T_done"); a.nop()
    a.label("T_super")
    # Revenge's "Perfect Start" latch (boost+0x9E, only cleared by a crash) makes every later boost ignore the
    # release (FUN_002a4180 returns while it is set). With burnout refills such a boost never ends -> the car
    # "boosts on its own". A supercharged car always follows the player's button.
    a.sb("zero", B_AUTO, "s0")
    a.mem("lwc1", "f2", A["DT"], "t1")
    a.lwc1("f0", S_ANIM, "s2"); a.mtc1("zero", "f1"); a.nop(); a.c_lt_s("f1", "f0"); a.bc1f("T_noanim"); a.nop()
    a.sub_s("f0", "f0", "f2"); a.c_lt_s("f0", "f1"); a.bc1f("T_animst"); a.nop(); a.mov_s("f0", "f1")
    a.label("T_animst")
    a.swc1("f0", S_ANIM, "s2")
    a.label("T_noanim")
    a.lbu("t1", B_ACTIVE, "s0"); a.beqz("t1", "T_idle"); a.nop()
    a.sb("zero", S_PAUSED, "s2"); a.b("T_boosting"); a.nop()      # boost resumed after a game interruption
    a.label("T_idle")
    # supercharged and idle: anything that took boost away (slam, crash) ends the supercharge
    a.sw("zero", S_SLOW, "s2")
    a.lbu("t1", S_PAUSED, "s2"); a.beqz("t1", "T_nopause"); a.nop()
    # paused (the game stopped the boost: takedown camera ...). With "only boost while held" it lasts while the game
    # drives, then REGRAB s; after that the button must be down (the pad controller restarts the boost), else it
    # was a release: supercharge + chain lost. (Option off: Revenge's own timing - the pause holds.)
    a.mem("lw", "t0", a.gaddr(T + 0x24), "t0"); a.andi("t0", "t0", FL_FREEBOOST); a.bnez("t0", "T_done"); a.nop()
    a.game_driving("s1", "t1"); a.bnez("t1", "T_done"); a.nop()
    a.regrab_window("s1", "t1"); a.bnez("t1", "T_done"); a.nop()
    a.move("a0", "s1"); a.jal("PADHELD"); a.nop()
    a.bnez("v0", "T_done"); a.nop()
    a.move("a0", "s2"); a.jal("LOSE"); a.move("a1", "s1")
    a.b("T_done"); a.nop()
    a.label("T_nopause")
    a.lwc1("f0", S_GRACE, "s2"); a.mtc1("zero", "f1"); a.nop(); a.c_lt_s("f1", "f0"); a.bc1t("T_done"); a.nop()
    a.lwc1("f0", B_AMT, "s0"); a.lwc1("f1", B_MAX, "s0")
    a.mem("lwc1", "f3", lay.a["REGION"] + 0x2C0, "t1"); a.mul_s("f1", "f1", "f3")
    a.c_lt_s("f0", "f1"); a.bc1f("T_done"); a.nop()
    a.move("a0", "s2"); a.jal("LOSE"); a.move("a1", "s1")
    a.b("T_done"); a.nop()
    a.label("T_boosting")
    a.gflag(FL_SLOW, "T_done")
    a.lwc1("f0", C_SPEED, "s1"); a.gfloat("f1", 0x0C); a.c_lt_s("f0", "f1"); a.bc1f("T_fast"); a.nop()
    a.lwc1("f3", S_SLOW, "s2"); a.add_s("f3", "f3", "f2"); a.swc1("f3", S_SLOW, "s2")
    a.gfloat("f1", 0x10); a.c_lt_s("f1", "f3"); a.bc1f("T_done"); a.nop()
    a.move("a0", "s2"); a.jal("LOSE"); a.move("a1", "s1")
    a.b("T_done"); a.nop()
    a.label("T_fast")
    a.sw("zero", S_SLOW, "s2"); a.b("T_done"); a.nop()
    a.label("T_inactive")                                    # online / crash mode / cheat: drop silently
    a.sb("zero", S_SUPER, "s2"); a.sw("zero", S_CHAIN, "s2"); a.sw("zero", S_ARROWS, "s2")
    a.label("T_done")
    a.pop(0x30, R6)
    a.j(A["TICK_ORIG"]); a.nop()

    # ---------------------------------------------------------------- EMPTY (jal from 0x2A3E0C instead of stop)
    # a0 = boost, f12 = time. Bar empty while supercharge-boosting -> refill / BURNOUT; release -> lose supercharge.
    R4 = ["ra", "s0", "s1", "s2"]
    a.label("EMPTY")
    a.push(0x30, R4); a.swc1("f12", 0x20, "sp")
    a.move("s0", "a0"); a.lw("s1", B_CAR, "a0")
    a.active("s1", "s0", "E_stop")
    a.stateptr("s1", "s2")
    a.lbu("t1", S_SUPER, "s2"); a.beqz("t1", "E_stop"); a.nop()
    a.lbu("t2", B_STOPREQ, "s0"); a.beqz("t2", "E_empty"); a.nop()
    # Who stopped the boost? Only the boost-button input paths set S_RELEASED. Any other stop (takedown camera,
    # crashbreaker, aftertouch, events) and stops within the takedown grace are a PAUSE: supercharge + chain kept.
    a.lbu("t3", S_RELEASED, "s2"); a.sb("zero", S_RELEASED, "s2")
    a.beqz("t3", "E_pause"); a.nop()
    a.lwc1("f0", S_GRACE, "s2"); a.mtc1("zero", "f1"); a.nop(); a.c_lt_s("f1", "f0"); a.bc1t("E_pause"); a.nop()
    a.move("a0", "s2"); a.jal("LOSE"); a.move("a1", "s1")         # boost released: supercharge (and chain) lost
    a.b("E_stop"); a.nop()
    a.label("E_pause")
    a.li("t1", 1); a.sb("t1", S_PAUSED, "s2")
    a.b("E_stop"); a.nop()
    a.label("E_empty")
    a.lwc1("f0", B_MAX, "s0"); a.gfloat("f1", 0x18); a.mul_s("f1", "f0", "f1")
    a.lwc1("f2", S_ARROWS, "s2"); a.add_s("f1", "f1", "f2")         # refill = half + arrows
    a.c_lt_s("f1", "f0"); a.bc1t("E_partial"); a.nop()
    # BURNOUT: full refill, chain++
    a.swc1("f0", B_AMT, "s0"); a.lwc1("f3", B_TOTAL, "s0"); a.add_s("f3", "f3", "f0"); a.swc1("f3", B_TOTAL, "s0")
    a.sw("zero", S_ARROWS, "s2"); a.sw("zero", S_SLOW, "s2"); a.gfloat("f3", 0x14); a.swc1("f3", S_ANIM, "s2")
    a.lw("t4", S_CHAIN, "s2"); a.addiu("t4", "t4", 1); a.sw("t4", S_CHAIN, "s2")
    a.b("E_nobest"); a.nop()                                   # (best chain no longer stored)
    a.label("E_nobest")
    a.move("a0", "s2"); a.jal("BURNMSG"); a.move("a1", "s1")
    a.b("E_ret"); a.nop()
    a.label("E_partial")
    a.gfloat("f3", 0x08); a.mul_s("f3", "f0", "f3"); a.c_lt_s("f3", "f1"); a.bc1f("E_pst"); a.nop(); a.mov_s("f1", "f3")
    a.label("E_pst")
    a.swc1("f1", B_AMT, "s0"); a.lwc1("f3", B_TOTAL, "s0"); a.add_s("f3", "f3", "f1"); a.swc1("f3", B_TOTAL, "s0")
    a.move("a0", "s2"); a.jal("LOSE"); a.move("a1", "s1")          # keeps boosting on the partial bar
    a.label("E_ret")
    a.pop(0x30, R4); a.jr("ra"); a.nop()
    a.label("E_stop")
    a.move("a0", "s0"); a.lwc1("f12", 0x20, "sp")
    a.pop(0x30, R4); a.j(A["STOP"]); a.nop()

    # ---------------------------------------------------------------- PROMPT (FUN_0016d190 @0x16D358, inline)
    # "PRESS R1 TO BOOST!" (HUD prompt 0 = BOOST PROMPT PART1/2, FUN_00175628 case 0) is requested when the bar is
    # >= the boost minimum and the player has not boosted for 5 s (s1 = per-player HUD, timer +0x220, prompt +0x21C).
    # Mod cars never get it (they wait for the supercharge on purpose); Crash mode / AI / online stay vanilla.
    a.label("PROMPT")
    a.bc1t("PR_chk"); a.nop()
    a.j(TR(0x16D36C)); a.nop()                                   # timer <= 5 s: original path (v0 set in delay slot)
    a.label("PR_chk")
    a.lw("t9", 0x214, "s1"); a.beqz("t9", "PR_orig"); a.nop()
    a.addiu("t8", "t9", C_BOOST)
    a.active("t9", "t8", "PR_orig")
    a.mem("lw", "t0", a.gaddr(T + 0x24), "t0"); a.andi("t0", "t0", FL_SHOWHINT); a.bnez("t0", "PR_orig"); a.nop()
    a.sw("zero", 0x220, "s1"); a.j(TR(0x16D378)); a.nop()       # no prompt, restart the timer
    a.label("PR_orig")
    a.sw("zero", 0x21C, "s1"); a.sw("zero", 0x220, "s1"); a.j(TR(0x16D378)); a.nop()

    # ---------------------------------------------------------------- SHRINK (jal from 0x11A2DC, the wreck handler)
    # FUN_0011a280 shrinks the bar one segment on a wreck (FUN_002a3fd0). With the fixed full bar a mod car keeps
    # all 4 segments (Revenge's crash boost loss still applies). Growth on takedowns is already a no-op at size 4.
    a.label("SHRINK")
    a.lw("t9", B_CAR, "a0")
    a.active("t9", "a0", "SH_orig")
    a.push(0x20, ["ra", "a0"])
    a.stateptr("t9", "a0"); a.jal("LOSE"); a.move("a1", "t9")      # a wreck ends supercharge + chain
    a.pop(0x20, ["ra", "a0"])
    a.gflag(FL_FULLBAR, "SH_orig")
    a.jr("ra"); a.nop()                                      # fixed full bar: no shrink
    a.label("SH_orig")
    a.j(A["SHRINK_ORIG"]); a.nop()

    # ---------------------------------------------------------------- RELEASE (jal from the boost-button input paths)
    # FUN_001dc2f0 @0x1DC944 and FUN_00204ac8 @0x204E98 request a stop because the boost button is not held.
    # ---------------------------------------------------------------- boost only while the button is held
    # Revenge's "boost held" answer (pad controller +0x1388 bit 1, FUN_001f2220) is NOT only the button: it is also
    # set by a game flag (controller +0x7224, set by FUN_002afeb8) and by the Perfect-Start latch. And while the
    # car is driven automatically (car +0x3B28 / +0x2CA9 states: takedown camera, autopilot) the pad controller is
    # not asked at all. So the rule reads the player's boost control itself: FUN_00111b80(pad) (all control
    # schemes), pad = *(car + 0x37B0), pressed above 0.1 like the game.
    # PADHELD: a0 = car -> v0 = 1 when pressed (also 1 when the car has no pad: never stop then)
    a.label("PADHELD")
    a.push(0x10, ["ra"])
    a.lw("t0", C_PAD, "a0"); a.beqz("t0", "PH_yes"); a.nop()
    a.lw("a0", 0, "t0"); a.beqz("a0", "PH_yes"); a.nop()
    a.jal(A["PADVAL"]); a.nop()
    a.lif("f1", 0.1); a.c_lt_s("f1", "f0"); a.bc1t("PH_yes"); a.nop()
    a.b("PH_ret"); a.li("v0", 0)
    a.label("PH_yes")
    a.li("v0", 1)
    a.label("PH_ret")
    a.pop(0x10, ["ra"]); a.jr("ra"); a.nop()

    # BSTOP: a0 = car. Stop a boost the button does not back, through the game's own stop (FUN_002a4288: flames,
    # sound, camera end as usual), also clearing the Perfect-Start latch. Supercharge rules stay: inside the
    # takedown grace supercharge + chain are kept (paused), otherwise letting go loses them.
    RS = ["ra", "s0"]
    a.label("BSTOP")
    a.push(0x10, RS); a.move("s0", "a0")
    a.stateptr("s0", "t7")
    a.lbu("t1", S_SUPER, "t7"); a.beqz("t1", "BS_stop"); a.nop()
    # The player let go - a real release (supercharge + chain lost) unless the game is driving the car (takedown
    # camera / autopilot) or has just given control back (REGRAB s to press boost again): then it is a pause.
    a.game_driving("s0", "t1"); a.bnez("t1", "BS_pause"); a.nop()
    a.regrab_window("s0", "t1"); a.bnez("t1", "BS_pause"); a.nop()
    a.move("a0", "t7"); a.jal("LOSE"); a.move("a1", "s0")
    a.b("BS_stop"); a.nop()
    a.label("BS_pause")
    a.li("t1", 1); a.sb("t1", S_PAUSED, "t7")
    a.label("BS_stop")
    a.addiu("a0", "s0", C_BOOST); a.sb("zero", B_AUTO, "a0")
    a.lwc1("f12", C_TIME, "s0")
    a.jal(A["STOP"]); a.nop()
    a.pop(0x10, RS); a.jr("ra"); a.nop()

    # BTN (jal from 0x204E4C instead of FUN_001f2220): the pad controller's per-frame "boost held?" query.
    # A forced "held" without the button becomes "not held" (so the game does not start / keep a boost), and a
    # running boost is stopped at once. Returns the (corrected) answer.
    RB = ["ra", "s0", "s1", "s2"]
    a.label("BTN")
    a.push(0x20, RB); a.move("s0", "a0")
    a.jal(A["HELD"]); a.nop()
    a.move("s1", "v0")
    a.beqz("s1", "B_chk"); a.nop()
    a.label("B_chk")
    a.lw("s2", P_CAR, "s0"); a.beqz("s2", "B_out"); a.nop()
    a.addiu("t8", "s2", C_BOOST)
    a.active("s2", "t8", "B_out")
    a.mem("lw", "t0", a.gaddr(T + 0x24), "t0"); a.andi("t0", "t0", FL_FREEBOOST); a.bnez("t0", "B_out"); a.nop()
    a.move("a0", "s2"); a.jal("PADHELD"); a.nop()
    a.bnez("v0", "B_out"); a.nop()
    a.li("s1", 0)                                                   # forced "held" is not the button
    a.lbu("t1", B_ACTIVE + C_BOOST, "s2"); a.beqz("t1", "B_out"); a.nop()
    a.move("a0", "s2"); a.jal("BSTOP"); a.nop()
    a.bypad("s2", "t6"); a.lbu("t1", 0, "t6"); a.sb("zero", 0, "t6")
    a.bnez("t1", "B_tap"); a.nop()
    a.debug_msg("s2", M_DBGPAD); a.b("B_out"); a.nop()               # forced "held" (game flag / latch)
    a.label("B_tap")
    a.debug_msg("s2", M_DBGTAP)                                      # the player let go (tap end)
    a.label("B_out")
    a.move("v0", "s1")
    a.pop(0x20, RB); a.jr("ra"); a.nop()

    # ---------------------------------------------------------------- HUDFIRE (j from 0x1617B4, bar HUD FUN_00161070)
    # The boost bar's fire overlay is drawn while boosting OR while the displayed bar is still rising (s3: a refill
    # being animated - takedown refills, BURNOUT refills). For mod cars the fire follows the real boost only
    # (option bit11 restores Revenge's fill fire). s0 = HUD element (car at +0x6CC); here the car is not boosting.
    a.label("HUDFIRE")
    a.beqz("s3", "HF_nofire"); a.nop()
    a.lw("t9", H_CAR, "s0"); a.beqz("t9", "HF_fire"); a.nop()
    a.addiu("t8", "t9", C_BOOST)
    a.active("t9", "t8", "HF_fire")
    a.mem("lw", "t0", a.gaddr(T + 0x24), "t0"); a.andi("t0", "t0", FL_FILLFIRE); a.bnez("t0", "HF_fire"); a.nop()
    a.label("HF_nofire")                                           # original beql taken: its delay slot + target
    a.lw("v1", 0x56C, "s0"); a.j(TR(0x161A44)); a.nop()
    a.label("HF_fire")
    a.j(TR(0x1617BC)); a.nop()

    # ---------------------------------------------------------------- ASTART (jal from 0x1DC924 instead of the start)
    # The game's own driving routine (FUN_001dc2f0) drives the player's car while the race mode's autopilot is on
    # (car +0x3B28, set by FUN_002cf7a8 from the mode's per-player update FUN_00114760 / FUN_00117aa8 - the
    # takedown camera) and starts boosts by itself. For a player mod car a start without the boost control
    # pressed is refused, so not one frame of boost appears. AI cars (controller type != 0) are untouched.
    a.label("ASTART")
    a.push(0x20, ["ra", "a0", "a1"])
    a.lw("t9", B_CAR, "a0"); a.beqz("t9", "AS_go"); a.nop()
    a.active("t9", "a0", "AS_go")
    a.mem("lw", "t0", a.gaddr(T + 0x24), "t0"); a.andi("t0", "t0", FL_FREEBOOST); a.bnez("t0", "AS_go"); a.nop()
    a.move("a0", "t9"); a.jal("PADHELD"); a.nop()
    a.bnez("v0", "AS_go"); a.nop()
    a.ld("t9", 8, "sp"); a.lw("t9", B_CAR, "t9")                   # (a0 saved at 8(sp))
    a.gflag(FL_DEBUG, "AS_no")
    a.lw("t1", C_IDX, "t9"); a.andi("t1", "t1", 7); a.sll("t1", "t1", 2)
    a.la("t2", A["REGION"] + BLKT); a.addu("t2", "t2", "t1")
    a.lwc1("f0", C_TIME, "t9"); a.lwc1("f1", 0, "t2"); a.sub_s("f1", "f0", "f1")
    a.lif("f2", 2.0); a.c_lt_s("f1", "f2"); a.bc1f("AS_msg"); a.nop()
    a.mtc1("zero", "f2"); a.nop(); a.c_lt_s("f1", "f2"); a.bc1f("AS_no"); a.nop()   # clock went back: new race
    a.label("AS_msg")
    a.swc1("f0", 0, "t2")
    a.push(0x10, ["s0"]); a.move("s0", "t9")
    a.send_msg("s0", M_DBGBLOCK)
    a.pop(0x10, ["s0"])
    a.label("AS_no")
    a.pop(0x20, ["ra", "a0", "a1"]); a.jr("ra"); a.li("v0", 0)      # refused: no boost
    a.label("AS_go")
    a.pop(0x20, ["ra", "a0", "a1"]); a.j(A["START"]); a.nop()

    a.label("RELEASE")
    a.lw("t9", B_CAR, "a0")
    a.active("t9", "a0", "RL_go")
    a.stateptr("t9", "t8"); a.li("t1", 1); a.sb("t1", S_RELEASED, "t8")
    a.label("RL_go")
    a.j(A["STOPREQ"]); a.nop()

    # ---------------------------------------------------------------- TAKEDOWN (jal from 0x114A9C instead of bar grow)
    a.label("TAKEDOWN")
    a.push(0x20, ["ra", "a0", "s0"])
    a.jal(A["GROW"]); a.nop()
    a.ld("s0", 8, "sp"); a.lw("t9", B_CAR, "s0")
    a.active("t9", "s0", "K_norm")
    a.stateptr("t9", "t8")
    # every mode: the takedown camera stops the boost -> grace period, so that stop keeps supercharge + chain
    a.mem("lwc1", "f0", lay.a["REGION"] + 0x248, "t1"); a.swc1("f0", S_GRACE, "t8")
    a.li("t1", 1); a.sb("t1", S_EARNED, "t8")
    a.lbu("t1", S_SUPER, "t8"); a.beqz("t1", "K_superon"); a.nop()
    # supercharged: ALL arrows lit; Revenge's takedown refill (amount = max) runs as usual after the return
    a.lwc1("f0", B_MAX, "s0"); a.gfloat("f1", 0x18); a.mul_s("f0", "f0", "f1")        # pool
    a.mem("lwc1", "f2", A["REGION"] + 0xE74, "t1"); a.mul_s("f2", "f0", "f2")       # x arrows_takedown
    a.lwc1("f3", S_ARROWS, "t8"); a.add_s("f2", "f2", "f3")
    a.c_lt_s("f0", "f2"); a.bc1f("K_ast"); a.nop(); a.mov_s("f2", "f0")
    a.label("K_ast")
    a.swc1("f2", S_ARROWS, "t8")
    a.b("K_norm"); a.nop()
    a.label("K_superon")                                    # Dominator: a takedown = instant supercharge
    a.move("a0", "t8"); a.jal("SUPER_ON"); a.move("a1", "t9")  # (the caller then sets amount = max)
    a.label("K_norm")
    a.pop(0x20, ["ra", "a0", "s0"]); a.jr("ra"); a.nop()

    # ---------------------------------------------------------------- CRASH (jal from 0x11DBA4 instead of stop request)
    a.label("CRASH")
    a.push(0x20, ["ra", "a0", "s0"])
    a.move("s0", "a0"); a.lw("t9", B_CAR, "s0")
    a.active("t9", "s0", "C_out")
    a.stateptr("t9", "a0"); a.jal("LOSE"); a.move("a1", "t9")
    a.label("C_out")
    a.pop(0x20, ["ra", "a0", "s0"]); a.j(A["STOPREQ"]); a.nop()

    # ---------------------------------------------------------------- TINT (FUN_0015e3b8 entry; addiu sp moved to delay slot)
    a.label("TINT")
    a.sq("s0", 0x810, "sp")                                 # displaced 2nd instruction
    a.mem("lw", "t0", a.gaddr(G_TINTED), "t9")
    a.beqz("t0", "TI_chk"); a.nop()
    a.swap_bar_colours(); a.mem("sw", "zero", a.gaddr(G_TINTED), "t9")
    a.label("TI_chk")
    a.move("t8", "ra"); a.jal("MODECHK"); a.nop(); a.move("ra", "t8")   # (also before the first car update)
    a.lw("t3", 0, "a1"); a.beqz("t3", "TI_out"); a.nop()
    a.lbu("t0", 0x535, "t3"); a.bnez("t0", "TI_out"); a.nop()
    a.lw("t4", C_HUDCAR, "t3"); a.beqz("t4", "TI_out"); a.nop()
    a.addiu("t5", "t4", C_BOOST)
    a.active("t4", "t5", "TI_out")
    # fixed full bar: the HUD's displayed segment count (element+0x6FE = this+0x6DE) follows the forced size at
    # once, so FUN_00161070 never animates a size change (no "segment gained/lost" sounds) and the bar sprite
    # (width = segments x 0.25) is always full length.
    a.gflag(FL_FULLBAR, "TI_tint")
    a.force_full("t5")                                       # also before the first car update (countdown)
    a.lw("t3", 0, "a1")                                      # (force_full used t3)
    a.li("t1", 4); a.sb("t1", HUD_SEGS, "t3")
    a.label("TI_tint")
    a.gflag(FL_TINT, "TI_out")
    a.stateptr("t4", "t6")
    a.lbu("t0", S_SUPER, "t6"); a.beqz("t0", "TI_out"); a.nop()
    a.swap_bar_colours(); a.li("t0", 1); a.mem("sw", "t0", a.gaddr(G_TINTED), "t9")
    a.label("TI_out")
    a.j(A["TINT_RET"]); a.nop()

    # ---------------------------------------------------------------- HUDLBL (jal from 0x15F09C instead of FUN_0015db48)
    # a0 = bar rect (x,y,w,h), a1 = segment count, a2/a3/f12-f14 passed through; caller s2 = HUD element + 0x20.
    RH = ["ra", "s0", "s1", "s3", "s4", "a0", "a1", "a2", "a3"]
    a.label("HUDLBL")
    a.push(0x80, RH)
    for k, fr in enumerate(("f12", "f13", "f14", "f20", "f21", "f22", "f23")):
        a.swc1(fr, 0x48 + 4 * k, "sp")
    a.move("s0", "a0"); a.li("s3", 0); a.sw("zero", 0x64, "sp")
    a.sll("t1", "a1", 3); a.la("t2", A["LABELTXT"]); a.addu("t2", "t2", "t1")
    a.mem("sw", "t2", a.gaddr(G_LABELPTR), "t9")              # default: the original "xN" bar-size label
    a.lw("s1", C_HUDCAR, "s2"); a.beqz("s1", "H_call"); a.nop()
    a.addiu("t5", "s1", C_BOOST)
    a.active("s1", "t5", "H_call")
    a.stateptr("s1", "s4")
    # Revenge's bar-size label ("x2".."x4") is hidden for mod cars: segment count 1 -> FUN_0015db48 skips it.
    # The chain is shown by the BURNOUT pop-up ("BURNOUT!" / "x<N>"), as in Dominator.
    a.mem("lw", "t0", a.gaddr(T + 0x24), "t0"); a.andi("t0", "t0", FL_SHOWLABEL); a.bnez("t0", "H_sup"); a.nop()
    a.li("t0", 1); a.sw("t0", 0x64, "sp")
    a.label("H_sup")
    a.lbu("s3", S_SUPER, "s4")
    a.label("H_call")
    for k, rg in enumerate(("a0", "a1", "a2", "a3")):
        a.ld(rg, 0x28 + 8 * k, "sp")
    a.lw("t0", 0x64, "sp"); a.beqz("t0", "H_show"); a.nop(); a.move("a1", "t0")
    a.label("H_show")
    for k, fr in enumerate(("f12", "f13", "f14")):
        a.lwc1(fr, 0x48 + 4 * k, "sp")
    a.jal(A["LABELFN"]); a.nop()
    a.mem("lw", "t0", a.gaddr(G_TINTED), "t9"); a.beqz("t0", "H_arrows"); a.nop()
    a.swap_bar_colours(); a.mem("sw", "zero", a.gaddr(G_TINTED), "t9")
    a.label("H_arrows")
    a.beqz("s3", "H_ret"); a.nop()
    a.gflag(FL_ARROWS, "H_ret")
    # texture = HUD texture slot arrow_tex_slot
    a.mem("lw", "t1", a.gaddr(T + 0x28), "t1"); a.sll("t1", "t1", 2); a.la("t2", A["HUDTEX"]); a.addu("t2", "t2", "t1")
    a.lw("a0", 0, "t2"); a.beqz("a0", "H_ret"); a.nop()
    if lay.tex_copy:                                         # cheat with Dominator art: refresh the texture data
        a.la("t3", lay.texsrc); a.addiu("t4", "a0", TEX_FROM); a.li("t5", (TEX_SIZE - TEX_FROM) // 4)
        a.label("H_tcopy")
        a.lw("t6", 0, "t3"); a.sw("t6", 0, "t4"); a.addiu("t3", "t3", 4); a.addiu("t5", "t5", -1)
        a.bnez("t5", "H_tcopy"); a.addiu("t4", "t4", 4)
    a.jal(A["SETTEX"]); a.nop()
    # n = arrow_count (1..32); lit = arrows / (half * max) * n
    a.mem("lw", "t2", A["REGION"] + 0xE78, "t2")
    a.slti("t1", "t2", 1); a.beqz("t1", "H_n1"); a.nop(); a.li("t2", 1)
    a.label("H_n1")
    a.slti("t1", "t2", 33); a.bnez("t1", "H_n2"); a.nop(); a.li("t2", 32)
    a.label("H_n2")
    a.lwc1("f0", S_ARROWS, "s4"); a.lwc1("f1", B_MAX + C_BOOST, "s1"); a.gfloat("f2", 0x18); a.mul_s("f1", "f1", "f2")
    a.mtc1("zero", "f2"); a.nop(); a.c_lt_s("f2", "f1"); a.bc1f("H_ret"); a.nop()
    a.div_s("f0", "f0", "f1"); a.mtc1("t2", "f1"); a.nop(); a.cvt_s_w("f1", "f1"); a.mul_s("f0", "f0", "f1")
    a.cvt_w_s("f0", "f0"); a.mfc1("s3", "f0")
    # scales
    a.la("s4", a.gaddr(0))                                   # s4 = globals base from here on
    a.lwc1("f20", 8, "s0"); a.lwc1("f1", G_DESIGN + 0, "s4"); a.div_s("f20", "f20", "f1")
    a.lwc1("f21", 12, "s0"); a.lwc1("f1", G_DESIGN + 4, "s4"); a.div_s("f21", "f21", "f1")
    a.lwc1("f0", G_DESIGN + 20, "s4"); a.mul_s("f0", "f0", "f20"); a.gfloat("f1", 0x18); a.mul_s("f0", "f0", "f1")
    a.lwc1("f2", G_DESIGN + 24, "s4"); a.mul_s("f2", "f2", "f21"); a.mul_s("f2", "f2", "f1")
    a.neg_s("f3", "f0"); a.neg_s("f4", "f2")
    for k, (x, y) in enumerate((("f3", "f4"), ("f0", "f4"), ("f3", "f2"), ("f0", "f2"))):   # TL TR BL BR
        a.swc1(x, G_CORN + 8 * k, "s4"); a.swc1(y, G_CORN + 8 * k + 4, "s4")
    SC = SCORN - G                                           # shadow corners, 30% larger
    a.lif("f5", 1.3)
    for fr in ("f0", "f2", "f3", "f4"):
        a.mul_s(fr, fr, "f5")
    for k, (x, y) in enumerate((("f3", "f4"), ("f0", "f4"), ("f3", "f2"), ("f0", "f2"))):
        a.swc1(x, SC + 8 * k, "s4"); a.swc1(y, SC + 8 * k + 4, "s4")
    a.lwc1("f22", G_DESIGN + 16, "s4"); a.mul_s("f22", "f22", "f21"); a.lwc1("f1", 4, "s0"); a.add_s("f22", "f22", "f1")
    # row layout, edge to edge: x0 = margin + aw/2, dx = (W - 2 margin - aw) / (n - 1) (design units; runtime scratch)
    a.mem("lw", "t2", A["REGION"] + 0xE78, "t2")
    a.slti("t1", "t2", 2); a.beqz("t1", "H_n3"); a.nop(); a.li("t2", 2)
    a.label("H_n3")
    a.slti("t1", "t2", 33); a.bnez("t1", "H_n4"); a.nop(); a.li("t2", 32)
    a.label("H_n4")
    a.addiu("t2", "t2", -1); a.mtc1("t2", "f2"); a.nop(); a.cvt_s_w("f2", "f2")               # n - 1
    a.mem("lwc1", "f3", A["REGION"] + 0xE7C, "t1")                                          # margin
    a.lwc1("f4", G_DESIGN + 20, "s4"); a.lif("f5", 0.5); a.mul_s("f5", "f4", "f5")          # aw / 2
    a.add_s("f6", "f3", "f5"); a.swc1("f6", G_SPOS, "s4")                                    # x0
    a.lwc1("f6", G_DESIGN + 0, "s4"); a.sub_s("f6", "f6", "f3"); a.sub_s("f6", "f6", "f3"); a.sub_s("f6", "f6", "f4")
    a.div_s("f6", "f6", "f2"); a.swc1("f6", G_SPOS + 4, "s4")                                # dx
    a.li("s1", 0)
    a.label("H_loop")
    a.mtc1("s1", "f0"); a.nop(); a.cvt_s_w("f0", "f0")
    a.lwc1("f1", G_SPOS + 4, "s4"); a.mul_s("f0", "f0", "f1"); a.lwc1("f1", G_SPOS, "s4"); a.add_s("f0", "f0", "f1")
    a.mul_s("f0", "f0", "f20"); a.lwc1("f1", 0, "s0"); a.add_s("f0", "f0", "f1")
    a.swc1("f0", G_POS, "s4"); a.swc1("f22", G_POS + 4, "s4")
    a.lq("a0", G_SHADOW, "s4")                               # outline / shadow behind the arrow
    a.addiu("a1", "s4", G_POS); a.li("a2", 4); a.addiu("a3", "s4", SC); a.addiu("t0", "s4", G_UVS)
    a.jal(A["QUAD"]); a.nop()
    a.slt("t1", "s1", "s3"); a.beqz("t1", "H_dark"); a.nop()
    a.lq("a0", G_LIT, "s4"); a.b("H_draw"); a.nop()
    a.label("H_dark")
    a.lq("a0", G_DARK, "s4")
    a.label("H_draw")
    a.addiu("a1", "s4", G_POS); a.li("a2", 4); a.addiu("a3", "s4", G_CORN); a.addiu("t0", "s4", G_UVS)
    a.jal(A["QUAD"]); a.nop()
    a.mem("lw", "t2", A["REGION"] + 0xE78, "t2")
    a.slti("t1", "t2", 33); a.bnez("t1", "H_n5"); a.nop(); a.li("t2", 32)
    a.label("H_n5")
    a.addiu("s1", "s1", 1); a.slt("t1", "s1", "t2"); a.bnez("t1", "H_loop"); a.nop()
    a.label("H_ret")
    for k, fr in enumerate(("f20", "f21", "f22", "f23")):
        a.lwc1(fr, 0x54 + 4 * k, "sp")
    a.pop(0x80, RH); a.jr("ra"); a.nop()

    code = a.assemble()
    assert lay.code + len(code) <= lay.texts, "cave too large"
    return code, dict(a.labels)


# ------------------------------------------------------------------------------------------------ hooks
def hooks(lay, labels):
    """[(vaddr, original word, new word, meaning)] for the executable of lay.region (PAL addresses translated)."""
    A = lay.a
    TR = lay.t
    J = lambda t: (2 << 26) | ((t >> 2) & 0x3FFFFFF)
    JAL = lambda t: (3 << 26) | ((t >> 2) & 0x3FFFFFF)
    L = labels
    n = lay.msg_count
    mt = lay.msgtab
    hi, lo = hi16(mt), lo16(mt)
    last = 12 * (n - 1)
    mo, lt = A["MSGTAB_OLD"], A["LABELTXT"]
    raw = [
        (0x2A3EC4, 0x50A00009, 0x50A00008, "beql a1,zero -> 0x2A3EE8 (into the ADD jump)"),
        (0x2A3EE8, 0xC6000040, J(L["ADD"]), "j ADD (add boost: fill_mult; nothing while supercharged)"),
        (0x2C8908, 0x0080282D, J(L["TRACK"]), "j TRACK (skill-list tracker update -> arrows)"),
        (0x2C890C, 0xC4A00004, 0x0080282D, "move a1,a0 (moved into the delay slot)"),
        (0x2A3EEC, 0xC6010044, 0x00000000, "nop"),
        (0x2A3A98, 0xC6010040, J(L["DRAIN"]), "j DRAIN (x3 drain when supercharged)"),
        (0x2A3F50, 0xC6000050, J(L["SUB"]), "j SUB (boost loss: floor at half while supercharge-boosting)"),
        (0x2A3A9C, 0x46001002, 0x00000000, "nop"),
        (0x2A3E0C, JAL(A["STOP"]), JAL(L["EMPTY"]), "jal EMPTY (bar empty -> burnout refill / release -> lose)"),
        (0x2A3E3C, JAL(A["TICK_ORIG"]), JAL(L["TICK"]), "jal TICK (per-car frame update)"),
        (0x114A9C, JAL(A["GROW"]), JAL(L["TAKEDOWN"]), "jal TAKEDOWN (takedown while supercharge-boosting = all arrows)"),
        (0x11A2DC, JAL(A["SHRINK_ORIG"]), JAL(L["SHRINK"]), "jal SHRINK (wreck: supercharge lost, no bar shrink)"),
        (0x1DC944, JAL(A["STOPREQ"]), JAL(L["RELEASE"]), "jal RELEASE (boost button released, input path 1)"),
        (0x16D358, 0x45000004, J(L["PROMPT"]), "j PROMPT (no PRESS R1 TO BOOST hint for mod cars)"),
        (0x204E98, JAL(A["STOPREQ"]), JAL(L["RELEASE"]), "jal RELEASE (boost button released, input path 2)"),
        (0x204E4C, JAL(A["HELD"]), JAL(L["BTN"]), "jal BTN (boost only while the button is held)"),
        (0x1DC924, JAL(A["START"]), JAL(L["ASTART"]), "jal ASTART (autopilot boost start: only with the button)"),
        (0x1617B4, 0x526000A3, J(L["HUDFIRE"]), "j HUDFIRE (bar fire only while boosting; was beql s3,zero)"),
        (0x1617B8, 0x8E03056C, 0x00000000, "nop (the beql delay slot, done in HUDFIRE)"),
        (0x15E3B8, 0x27BDF780, J(L["TINT"]), "j TINT (blue boost bar while supercharged)"),
        (0x15E3BC, 0x7FB00810, 0x27BDF780, "addiu sp,sp,-0x880 (moved into the delay slot)"),
        (0x15F09C, JAL(A["LABELFN"]), JAL(L["HUDLBL"]), "jal HUDLBL (chain label + arrows)"),
        (0x15DCE4, 0x3C080000 | hi16(lt), 0x3C080000 | hi16(lay.g + G_LABELPTR), "lui t0,%hi(label pointer)"),
        (0x15DCF4, 0x25080000 | lo16(lt), 0x8D080000 | lo16(lay.g + G_LABELPTR), "lw t0,%lo(label pointer)(t0)"),
        (0x15DD0C, 0x00484021, 0x00000000, "nop (was addu t0,v0,t0)"),
        # HUD message table relocation (3 functions: lui, addiu base, addiu last entry, loop count)
        (0x16FCFC, 0x3C020000 | hi16(mo), 0x3C020000 | hi, "msg table hi"), (0x16FD0C, 0x24420000 | lo16(mo), 0x24420000 | lo, "msg table lo"),
        (0x16FD1C, 0x245108DC, 0x24510000 | last, "last entry"), (0x16FD24, 0x241300BD, 0x24130000 | (n - 1), "count-1"),
        (0x16FDD8, 0x3C020000 | hi16(mo), 0x3C020000 | hi, "msg table hi"), (0x16FDE0, 0x24420000 | lo16(mo), 0x24420000 | lo, "msg table lo"),
        (0x16FDE8, 0x244308DC, 0x24430000 | last, "last entry"), (0x16FDE4, 0x240700BD, 0x24070000 | (n - 1), "count-1"),
        (0x16FED4, 0x3C020000 | hi16(mo), 0x3C020000 | hi, "msg table hi"), (0x16FEEC, 0x24420000 | lo16(mo), 0x24420000 | lo, "msg table lo"),
        (0x16FEF4, 0x244508DC, 0x24450000 | last, "last entry"), (0x16FEE8, 0x240600BD, 0x24060000 | (n - 1), "count-1"),
    ]
    return [(TR(va), old, new, what) for va, old, new, what in raw]
