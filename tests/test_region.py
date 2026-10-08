"""Europe (PAL) and USA builds: the address translation and the code built for each build.

Without game files: the USA code contains no PAL address, and both builds share the same code shape.
With your discs (read only): CHAINKIT_ISO_PAL + CHAINKIT_ISO_USA re-derive USA_MAP with tools/derive_region.py and
check it against the data in both executables.
"""
import os
import struct
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from chainkit import cave, core, elfpatch, regions  # noqa: E402
from chainkit.elf import Elf  # noqa: E402

ISO_PAL = os.environ.get("CHAINKIT_ISO_PAL", "")
ISO_USA = os.environ.get("CHAINKIT_ISO_USA", "")
both = pytest.mark.skipif(not (ISO_PAL and os.path.exists(ISO_PAL) and ISO_USA and os.path.exists(ISO_USA)),
                          reason="set CHAINKIT_ISO_PAL and CHAINKIT_ISO_USA (original discs, read only)")


def _targets(code, base):
    """Every absolute address the code uses: j/jal targets and lui+addiu/ori/load/store pairs."""
    out = set()
    words = struct.unpack("<%dI" % (len(code) // 4), code)
    hi = {}
    for i, w in enumerate(words):
        op = w >> 26
        if op in (2, 3):
            out.add(((base + 4 * i) & 0xF0000000) | ((w & 0x3FFFFFF) << 2))
        elif op == 0x0F:
            hi[(w >> 16) & 31] = (w & 0xFFFF) << 16
        elif (w >> 21) & 31 in hi and op in (0x09, 0x0D, 0x23, 0x24, 0x2B, 0x31, 0x39, 0x28, 0x20):
            imm = w & 0xFFFF
            v = hi[(w >> 21) & 31]
            out.add(v | imm if op == 0x0D else (v + (imm - 0x10000 if imm & 0x8000 else imm)) & 0xFFFFFFFF)
    return out


def test_every_pal_address_has_a_usa_address():
    used = set(regions.PAL_CODE_ADDRS) | set(regions.PAL_DATA_ADDRS) | set(regions.PAL_COMPUTED)
    assert used <= set(regions.USA_MAP)
    for k, v in cave.PAL_ADDRS.items():
        if k not in cave.NOT_ADDRESSES:
            assert v in regions.USA_MAP, k
    for ra, _ in cave.AWARD_SITES:
        assert ra in regions.USA_MAP
    # the shifts stay small (same compiler output, the USA build is a little shorter)
    for a, b in regions.USA_MAP.items():
        assert abs(b - a) <= 0x300, hex(a)


def test_usa_code_uses_no_pal_address():
    pal, usa = cave.Layout(regions.PAL), cave.Layout(regions.USA)
    pcode, plab = cave.build_code(pal)
    ucode, ulab = cave.build_code(usa)
    assert len(pcode) == len(ucode) and sorted(plab) == sorted(ulab)
    moved = {a for a, b in regions.USA_MAP.items() if a != b}
    leaked = _targets(ucode, usa.code) & moved
    assert not leaked, [hex(x) for x in leaked]
    # all game addresses of the PAL code appear translated in the USA code
    pal_game = {x for x in _targets(pcode, pal.code) if x in regions.USA_MAP}
    usa_game = _targets(ucode, usa.code)
    assert {regions.USA_MAP[x] for x in pal_game} <= usa_game


def test_hole_layout_per_build():
    for r in (regions.PAL, regions.USA):
        lay = cave.Layout(r)
        lo, hi = r["hole"]
        assert hi - lo == 0x4008 and lay.a["REGION"] - lo >= 0x800
        assert r["musickit_table"][1] <= lay.a["REGION"]
        code, _ = cave.build_code(lay)
        assert lay.code + len(code) <= hi
    assert cave.Layout(regions.PAL).a["REGION"] == 0x4A4000          # unchanged PAL layout


def test_hooks_per_build():
    for r in (regions.PAL, regions.USA):
        lay = cave.Layout(r)
        hk = cave.hooks(lay, cave.build_code(lay)[1])
        assert len(hk) == 36 and len({va for va, *_ in hk}) == 36
    usa = cave.Layout(regions.USA)
    hk = {va: old for va, old, new, what in cave.hooks(usa, cave.build_code(usa)[1])}
    assert hk[0x2A3CF4] == (3 << 26) | (0x2A4170 >> 2)                  # jal stop, translated


# ------------------------------------------------------------------------------------------- with both discs
@pytest.fixture(scope="module")
def elfs():
    with core.Disc(ISO_PAL) as p, core.Disc(ISO_USA) as u:
        assert p.region["key"] == "PAL" and u.region["key"] == "USA"
        assert not p.hole_open and not u.hole_open, "use the original discs"
        return p.elf, u.elf


@both
def test_usa_map_is_derived_from_the_discs(elfs, tmp_path):
    import derive_region
    pp, up = tmp_path / "pal.elf", tmp_path / "usa.elf"
    pp.write_bytes(elfs[0]); up.write_bytes(elfs[1])
    m, data = derive_region.usa_map(str(pp), str(up))
    assert m == regions.USA_MAP


@both
def test_usa_data_matches_pal_data(elfs):
    p, u = Elf(elfs[0]), Elf(elfs[1])
    T = lambda a: regions.t(regions.USA, a)  # noqa: E731
    # boost bar tables (sizes, multipliers, rates, minimum)
    for a, n in ((0x4670C0, 1), (0x4670D0, 4), (0x4670E0, 4), (0x4670F0, 4)):
        assert [p.r32(a + 4 * k) for k in range(n)] == [u.r32(T(a) + 4 * k) for k in range(n)], hex(a)
    # the HUD message table: same ids / flags, text handles moved like the rest of .data
    for k in range(cave.PAL_ADDRS["MSG_COUNT"]):
        pe = struct.unpack_from("<3I", p.d, p.file_offset(0x45CE78 + 12 * k))
        ue = struct.unpack_from("<3I", u.d, u.file_offset(T(0x45CE78) + 12 * k))
        assert pe[0] == ue[0], k
    # mode classes: the first virtual function is the aligned function
    code_map = {a: b for a, b in regions.USA_MAP.items()}
    for _, _, vts in cave.MODES:
        for vt in vts:
            pf, uf = p.r32(vt + 12), u.r32(T(vt) + 12)
            assert 0x100000 <= uf < 0x45A450 and abs(uf - pf) <= 0x300, hex(vt)
    # MusicKit: the playlist points at the original song table
    assert u.r32(T(0x460640) + 0x4C) == T(0x460450) and u.r32(T(0x460640) + 4) == 41
    assert code_map


@both
def test_patch_both_builds(elfs):
    from chainkit import settings
    for elf, key in zip(elfs, ("PAL", "USA")):
        out, rep = elfpatch.patch(elf, settings.DEFAULTS)
        assert rep["region"] == key and elfpatch.check(out, lambda *a: None) == []
        assert elfpatch.region_of(out)["key"] == key and elfpatch.version(out) == cave.VERSION


@both
def test_pad_controller_layout_same_in_both_builds(elfs):
    """BTN reads the car of the pad controller at +0x2E80: check the game's own code at the hook in both builds."""
    for elf, key in zip(elfs, ("PAL", "USA")):
        e = Elf(elf)
        site = regions.t(regions.BY_KEY[key], 0x204E4C)
        assert e.r32(site) == (3 << 26) | (regions.t(regions.BY_KEY[key], 0x1F2220) >> 2)
        assert e.r32(site + 0xC) == 0x8E040000 | cave.P_CAR            # lw a0, 0x2E80(s0) after the call
        held = regions.t(regions.BY_KEY[key], 0x1F2220)
        assert 0x90821388 in [e.r32(held + 4 * k) for k in range(24)]  # lbu v0, 0x1388(a0): the pad bits


@both
def test_pad_query_used_by_the_controller_in_both_builds(elfs):
    """PADHELD calls FUN_00111b80(**(car + 0x37B0)) like the pad controller does before its 'boost held' query."""
    for elf, key in zip(elfs, ("PAL", "USA")):
        e = Elf(elf)
        r = regions.BY_KEY[key]
        site = regions.t(r, 0x204E4C)
        win = [e.r32(site - 4 * k) for k in range(1, 200)]
        assert (3 << 26) | (regions.t(r, 0x111B80) >> 2) in win, key
        assert 0x8CA20000 | cave.C_PAD in win, key                     # lw v0, 0x37B0(a1)
