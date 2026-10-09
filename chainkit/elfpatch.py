"""Apply / inspect the Burnout Chain patch on the Burnout Revenge executable: Europe / PAL SLES_535.07 or
USA / NTSC SLUS_212.42 (the build is recognised by its PCSX2 CRC; regions.py).

Works on the original ELF and on MusicKit output and car mods:
- the code + data go into the top of the .sndata hole (PAL 0x4A4000..0x4A7680, USA 0x4A3E80..0x4A7500); if segment 0
  does not cover the hole yet it is extended exactly like MusicKit does (hole inserted into the file, later
  sections shifted);
- MusicKit's song table lives at the bottom of the hole (<= 1200 bytes), car mods use the gap after .text and code at
  PAL 0x134D68..0x134D74 - none of these overlap;
- the PCSX2 CRC (XOR of all ELF words) is kept with the compensation word after the file content.
"""
import struct

from . import cave, regions
from .elf import Elf, crc, _fix_crc

PAL_CRC = regions.PAL["crc"]
USA_CRC = regions.USA["crc"]
CRCS = {r["crc"]: r for r in (regions.PAL, regions.USA)}
CAR_CODE = (0x134D68, 0x134D78)             # PAL; translated per build


def region_of(data, allow_unknown=False):
    """The build of an executable (by its PCSX2 CRC, which every kit keeps)."""
    r = CRCS.get(crc(data))
    if r is None and not allow_unknown:
        raise ChainError("not a Burnout Revenge executable ChainKit knows (CRC %08X; supported: Europe "
                         "SLES-53507, USA SLUS-21242)" % crc(data))
    return r


def layout(data):
    return cave.Layout(region_of(data))


def text_range(e):
    """(start, end) of .text (the code ChainKit's branch check scans)."""
    for sh in e.sections():
        if sh[1] == 1 and sh[2] & 4 and sh[3] == e.phdrs()[0][2]:
            return sh[3], sh[3] + sh[5]
    s0 = e.phdrs()[0]
    return s0[2], s0[2] + s0[4]


def car_code_ranges(e, region):
    """Addresses a car mod may write: the car code site and the padding gap after .text."""
    out = [(regions.t(region, CAR_CODE[0]), regions.t(region, CAR_CODE[0]) + 0x10)]
    secs = sorted((sh for sh in e.sections() if sh[3] and sh[1] in (1, 8)), key=lambda sh: sh[3])
    t0, t1 = text_range(e)
    nxt = min((sh[3] for sh in secs if sh[3] >= t1), default=None)
    if nxt is not None:
        out.append(((t1 + 15) & ~15, nxt))
    return out


class ChainError(Exception):
    pass


def _segs(e):
    ph = e.phdrs()
    if len(ph) < 2 or ph[0][0] != 1 or ph[1][0] != 1:
        raise ChainError("unexpected ELF layout")
    return ph


def is_applied(data):
    e = Elf(data)
    r = region_of(data, allow_unknown=True)
    if r is None:
        return False
    lay = cave.Layout(r)
    try:
        off = e.file_offset(lay.g + cave.G_MAGIC)
    except KeyError:
        return False
    return bytes(e.d[off:off + 8]) == cave.MAGIC


def version(data):
    """ChainKit data version of a patched executable (None when the mod is not applied)."""
    if not is_applied(data):
        return None
    e = Elf(data)
    return e.r32(layout(data).g + cave.G_MAGIC + 8)


def _open_hole(e, lay):
    """Extend segment 0 over the .sndata hole (MusicKit's method). Returns a new Elf."""
    ph = _segs(e)
    s0, s1 = ph[0], ph[1]
    hole_start, hole_end = s0[2] + s0[4], s1[2]
    A = lay.a
    if not (hole_start <= A["REGION"] and A["HOLE_END"] == hole_end):
        raise ChainError("no room in the .sndata hole (unexpected executable)")
    hole = bytearray(hole_end - hole_start)
    s0_end_file, s1_off = s0[1] + s0[4], s1[1]
    shift = s0_end_file + len(hole) - s1_off
    out = bytearray(e.d[:s0_end_file]) + hole + e.d[s1_off:]
    ne = Elf(out)
    n0 = list(s0)
    n0[4] += len(hole)
    n0[5] += len(hole)
    ne.set_phdr(0, n0)
    for i in range(1, len(ph)):
        p = list(ph[i])
        if p[1] >= s1_off:
            p[1] += shift
        ne.set_phdr(i, p)
    if ne.shoff >= s1_off:
        ne.shoff += shift
        struct.pack_into("<I", ne.d, 0x20, ne.shoff)
    for i in range(ne.shnum):
        o = ne.shoff + 40 * i
        sh = list(struct.unpack_from("<10I", ne.d, o))
        if sh[5] == 0x4000 and hole_start <= sh[3] < hole_end:          # .sndata now inside segment 0
            sh[4] = n0[1] + sh[3] - n0[2]
        elif sh[4] >= s1_off:
            sh[4] += shift
        struct.pack_into("<10I", ne.d, o, *sh)
    return ne


def build(lay=None, tunables=None, old_table=None):
    lay = lay or cave.Layout()
    code, labels = cave.build_code(lay)
    data = cave.build_data(lay, old_table, tunables)
    return lay, code, labels, data


def patch(data, tunables=None, inline_texts=False, tex_blob=None):
    """Return (patched ELF bytes, report dict). `data` = the PAL or USA executable (original, car mod and/or
    MusicKit output). inline_texts: the pop-up texts come from the cave (used for the PCSX2 cheat)."""
    if is_applied(data):
        raise ChainError("the Burnout Chain patch is already applied (use 'tune' to change settings)")
    target = crc(data)
    lay = cave.Layout(region_of(data), inline_texts, tex_copy=tex_blob is not None)
    A = lay.a
    e = Elf(data)
    ph = _segs(e)
    merged = ph[0][2] + ph[0][4] == ph[1][2]
    # original words at every hook site (translated for the USA build): a wrong address can never be written
    for va, old, new, what in cave.hooks(lay, {k: 0 for k in ("ADD", "DRAIN", "EMPTY", "TICK", "TAKEDOWN", "CRASH",
                                                               "TINT", "HUDLBL", "SUB", "TRACK", "SHRINK", "RELEASE", "PROMPT",
                                                               "BTN", "HUDFIRE", "ASTART")}):
        if e.r32(va) != old:
            raise ChainError("unexpected code at %#x (%08x, expected %08x): unsupported or modified executable"
                             % (va, e.r32(va), old))
    old_table = bytes(e.d[e.file_offset(A["MSGTAB_OLD"]):][:12 * A["MSG_COUNT"]])
    lay, code, labels, region = build(lay, tunables, old_table)
    if merged:
        o = e.file_offset(A["REGION"])
        if any(e.d[o:o + (A["HOLE_END"] - A["REGION"])]):
            raise ChainError("the top of the .sndata hole is already in use by another patch")
        ne = e
    else:
        ne = _open_hole(e, lay)
    o = ne.file_offset(A["REGION"])
    ne.d[o:o + len(region)] = region
    o = ne.file_offset(lay.code)
    ne.d[o:o + len(code)] = code
    if lay.inline:
        t = cave.build_texts(lay)
        o = ne.file_offset(lay.texts)
        ne.d[o:o + len(t)] = t
    if tex_blob is not None:
        assert len(tex_blob) == cave.TEX_SIZE - cave.TEX_FROM
        o = ne.file_offset(lay.texsrc)
        if any(ne.d[o:o + len(tex_blob)]):
            raise ChainError("the space for the arrow texture is in use (MusicKit with more than 95 songs?)")
        ne.d[o:o + len(tex_blob)] = tex_blob
    hk = cave.hooks(lay, labels)
    for va, old, new, what in hk:
        ne.w32(va, new)
    appended = len(ne.d) > ne.content_end()
    out = _fix_crc(ne.d, target, appended)
    rep = dict(hole_opened=not merged, code=(lay.code, lay.code + len(code)), data=(A["REGION"], lay.code),
               hooks=hk, labels=labels, crc=crc(out), region=lay.region["key"])
    return out, rep


def tune(data, tunables):
    """Rewrite the tunables of an already patched executable (keeps the CRC)."""
    if not is_applied(data):
        raise ChainError("the Burnout Chain patch is not applied")
    if version(data) != cave.VERSION:
        raise ChainError("this image was made with an older ChainKit build; build it again from your ISO without "
                         "the mod")
    target = crc(data)
    e = Elf(data)
    lay = layout(data)
    known = {n for n, *_ in cave.TUNABLES}
    for name, val in tunables.items():
        if name not in known:
            raise ChainError("unknown setting %s (known: %s)" % (name, ", ".join(sorted(known))))
        addr, t = cave.tune_addr(lay, name)
        o = e.file_offset(addr)
        if t == "c":
            struct.pack_into("<4f", e.d, o, *cave.parse_colour(val))
        else:
            struct.pack_into("<f" if t == "f" else "<I", e.d, o,
                             float(val) if t == "f" else int(val, 0) if isinstance(val, str) else int(val))
    return _fix_crc(e.d, target, len(e.d) > e.content_end())


def read_tunables(data):
    e = Elf(data)
    lay = layout(data)
    out = {}
    for name, off, t, d, h in cave.TUNABLES:
        addr, _ = cave.tune_addr(lay, name)
        if t == "c":
            out[name] = tuple(round(x, 3) for x in struct.unpack_from("<4f", e.d, e.file_offset(addr)))
        else:
            out[name] = struct.unpack_from("<f" if t == "f" else "<I", e.d, e.file_offset(addr))[0]
    return out


# replaced second instructions of two-word hooks (no branch of the game may land on them), PAL addresses
INNER = (0x2A3EEC, 0x2A3A9C, 0x15E3BC, 0x15DCF4, 0x15DD0C, 0x2A3F54, 0x2C890C, 0x16D35C, 0x1617B8)


def message_table(e, lay):
    """[(id, display flags, name, sign style)] of the HUD message table the patched game really uses (read back from the
    relocated lui/addiu pair and loop count of FUN_0016fcf0)."""
    hi, lo = e.r32(lay.t(0x16FCFC)) & 0xFFFF, e.r32(lay.t(0x16FD0C)) & 0xFFFF
    table = ((hi << 16) + (lo - 0x10000 if lo & 0x8000 else lo)) & 0xFFFFFFFF
    count = (e.r32(lay.t(0x16FD24)) & 0xFFFF) + 1
    out = []
    for k in range(count):
        w0, name_ptr, _ = struct.unpack_from("<3I", e.d, e.file_offset(table + 12 * k))
        try:
            o = e.file_offset(name_ptr)
            name = bytes(e.d[o:o + 40]).split(b"\0")[0].decode("latin-1")
        except KeyError:
            name = None
        out.append((w0 & 0xFF, (w0 >> 8) & 0xFF, name, (w0 >> 16) & 0xFF))
    return out


def message_problems(e, lay):
    """Every new HUD message must exist exactly once in the table the game uses, under its own name, with an id
    the game does not refuse (an id the original table already has would show the game's message instead)."""
    bad = []
    tab = message_table(e, lay)
    ids = [t[0] for t in tab]
    for name, mid, flags, lvl in cave.NEW_MESSAGES:
        hits = [t for t in tab if t[0] == mid]
        if len(hits) != 1:
            bad.append("message id %#x used %d times in the table (%s)" % (mid, len(hits), name))
        elif hits[0][2] != name or hits[0][1] != flags or hits[0][3] != cave.msg_style(mid):
            bad.append("message id %#x is %r, not %s" % (mid, hits[0][2], name))
        if mid in cave.REFUSED_MSG_IDS:
            bad.append("message id %#x is refused by the game" % mid)
    if len(set(ids)) != len(ids):
        bad.append("duplicate message ids in the table")
    # SUPERCHARGE LOST looks like the game's own negative messages: same red colour bit and sign style
    neg = [t for t in tab if t[2] and t[2].startswith(("BadSlam", "BadShunt", "BadNudge", "BadSideswipe"))]
    lost = [t for t in tab if t[0] == cave.M_LOST]
    if not neg:
        bad.append("the game's negative messages (BadSlam...) are not in the table")
    elif lost:
        if {t[3] for t in neg} != {lost[0][3]}:
            bad.append("SUPERCHARGE LOST sign style %d is not the negative messages' %s"
                       % (lost[0][3], sorted({t[3] for t in neg})))
        if {t[1] & cave.MSG_RED_BIT for t in neg} != {lost[0][1] & cave.MSG_RED_BIT}:
            bad.append("SUPERCHARGE LOST is not in the negative messages' red colour")
    return bad


def check(data, log=print):
    """Static checks of a patched executable. Returns a list of problems (empty = OK)."""
    bad = []
    e = Elf(data)
    region = region_of(data, allow_unknown=True)
    if region is None:
        return ["CRC %08X is not a known Burnout Revenge build" % crc(data)]
    lay = cave.Layout(region)
    A = lay.a
    if not is_applied(data):
        return bad + ["patch not applied"]
    code, labels = cave.build_code(lay)
    o = e.file_offset(lay.code)
    if bytes(e.d[o:o + len(code)]) != code:
        bad.append("cave code differs from this ChainKit version")
    bad += message_problems(e, lay)
    hk = cave.hooks(lay, labels)
    for va, old, new, what in hk:
        if e.r32(va) != new:
            bad.append("hook %#x not applied" % va)
    touched = [(va, va + 4) for va, *_ in hk] + [(A["REGION"], A["HOLE_END"])]
    for lo, hi in touched:
        for a, b in car_code_ranges(e, region) + [region["musickit_table"]]:
            if lo < b and a < hi:
                bad.append("overlap with a car mod/MusicKit at %#x" % lo)
        for p in region["pnach"]:
            if lo <= p < hi:
                bad.append("overlap with PCSX2 pnach at %#x" % p)
    inner = {lay.t(x) for x in INNER}
    t0, t1 = text_range(e)
    words = struct.unpack_from("<%dI" % ((t1 - t0) // 4), e.d, e.file_offset(t0))
    for i, w in enumerate(words):
        pc = t0 + 4 * i
        op = w >> 26
        t = None
        if op in (2, 3):
            t = (pc & 0xF0000000) | ((w & 0x3FFFFFF) << 2)
        elif op in (1, 4, 5, 6, 7, 0x14, 0x15, 0x16, 0x17) or (op == 0x11 and ((w >> 21) & 31) == 8):
            off = w & 0xFFFF
            t = pc + 4 + ((off - 0x10000 if off & 0x8000 else off) << 2)
        if t in inner:
            bad.append("branch at %#x lands on patched instruction %#x" % (pc, t))
    for p in bad:
        log("  PROBLEM: " + p)
    return bad
