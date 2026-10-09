"""PS2 texture records (ps2tex) and ChainKit's own arrow (arrowart).

Without game files: the GS swizzle model is a bijection and a synthetic record round-trips.
With your discs (CHAINKIT_ISO, optional CHAINKIT_DOMINATOR): decode -> encode is byte-identical for Revenge's
TalkIcon and chev_sml and for Dominator's Boost_Arrow; the decoded arrow has the expected shape; ChainKit's arrow
keeps TalkIcon's header (+0x104 included) and passes the same checks as Dominator's art.
"""
import os
import random
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from chainkit import arrowart, assets, core, ps2tex  # noqa: E402


def test_psmt4_over_psmct16_is_a_bijection():
    seen = set()
    for y in range(32):
        for x in range(32):
            seen.add(ps2tex.gs_bit_address(ps2tex.PSMT4, x, y, 0, 2) // 4)
    up = set()
    for y in range(16):
        for x in range(16):
            a = ps2tex.gs_bit_address(ps2tex.PSMCT16, x, y, 0, 1)
            up.update((a + k) // 4 for k in range(0, 16, 4))
    assert len(seen) == 1024 and seen == up


def fake_record():
    r = bytearray(0x580)
    struct.pack_into("<5I", r, 4, 0x250, 0x4D0, 32, 32, 4)
    tex0 = (2 << 14) | (ps2tex.PSMT4 << 20) | (5 << 26) | (5 << 30)
    struct.pack_into("<Q", r, 0x3C, tex0)
    struct.pack_into("<Q", r, 0x110 + 0x20, (1 << 48) | (ps2tex.PSMCT16 << 56))
    struct.pack_into("<Q", r, 0x150 + 0x20, (1 << 48) | (0x1C << 32))
    struct.pack_into("<2I", r, 0x200 + 0x20, 16, 16)
    struct.pack_into("<2I", r, 0x480 + 0x20, 8, 3)
    return bytes(r)


def test_synthetic_record_round_trip():
    rnd = random.Random(1)
    tr = ps2tex.TexRecord(fake_record())
    img = [[rnd.randrange(16) for _ in range(32)] for _ in range(32)]
    clut = [(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256), rnd.randrange(129)) for _ in range(16)]
    rec = tr.encode(img, clut)
    back = ps2tex.TexRecord(rec)
    assert back.decode() == (img, clut)
    assert back.encode(img, clut) == rec


def test_arrow_repaint_from_a_slash():
    mask = [[1.0 if 0 <= x - y <= 7 else 0.0 for x in range(16)] for y in range(8)]   # a slash like chev_sml
    a = arrowart.repaint(mask)
    assert len(a) == 32 and all(len(r) == 32 for r in a)
    assert max(max(r) for r in a) == 1.0 and min(min(r) for r in a) == 0.0
    rec = arrowart.encode(a, fake_record())
    img, clut = ps2tex.TexRecord(rec).decode()
    assert clut == [(255, 255, 255, v) for v in arrowart.RAMP]
    covered = sum(1 for r in img for v in r if v >= 8)
    assert 150 < covered < 700                                           # a solid slash, not a box or nothing


# ------------------------------------------------------------------------------------------- with discs
ISO = os.environ.get("CHAINKIT_ISO", "") or os.environ.get("CHAINKIT_ISO_PAL", "")
DOM = os.environ.get("CHAINKIT_DOMINATOR", "")
disc = pytest.mark.skipif(not (ISO and os.path.exists(ISO)), reason="set CHAINKIT_ISO")


@pytest.fixture(scope="module")
def txd():
    with core.Disc(ISO) as d:
        return d.img.read_file(assets.GLOBAL_TXD)


@disc
@pytest.mark.parametrize("name", ["TalkIcon", "chev_sml"])
def test_revenge_records_round_trip(txd, name):
    o, s = assets.txd_records(txd)[name]
    if name == "TalkIcon" and arrowart.is_chainkit(txd):
        pytest.skip("this ISO already has an arrow in TalkIcon")
    rec = txd[o:o + s]
    tr = ps2tex.TexRecord(rec)
    assert tr.encode(*tr.decode()) == rec


@disc
@pytest.mark.skipif(not (DOM and os.path.exists(DOM)), reason="set CHAINKIT_DOMINATOR")
def test_dominator_arrow_round_trip_and_shape():
    d = core.dominator_txd(DOM)
    o, s = assets.txd_records(d)[assets.SOURCE]
    rec = d[o:o + s]
    tr = ps2tex.TexRecord(rec)
    img, clut = tr.decode()
    assert tr.encode(img, clut) == rec
    # a ">" arrow: the widest row is in the middle, the top and bottom rows are empty
    widths = [sum(1 for v in row if clut[v][3] > 0x40) for row in img]
    assert widths[0] == 0 and widths[-1] == 0 and max(widths[12:20]) >= 10


@disc
def test_chainkit_arrow_keeps_talkicon_header(txd):
    if arrowart.is_chainkit(txd):
        pytest.skip("this ISO already has an arrow in TalkIcon")
    ro, rs = assets.txd_records(txd)[assets.TARGET]
    mine = arrowart.chainkit_record(txd)
    orig = txd[ro:ro + rs]
    tr = ps2tex.TexRecord(orig)
    pix = {off for off, _, _, _ in tr.bitmap_map()}
    clut = set(range(tr.clut_off, tr.clut_off + 64))
    diff = {k for k in range(rs) if mine[k] != orig[k]}
    assert diff and diff <= pix | clut                       # header (incl. +0x104 and the name) unchanged
    merged = arrowart.merge(txd)
    assert arrowart.is_chainkit(merged, txd) and len(merged) == len(txd)
    if DOM and os.path.exists(DOM):
        assets.merge_arrow(merged, core.dominator_txd(DOM))  # Dominator's art can still replace ours later
