"""PCSX2 cheat output (.pnach).

Without game files: the cheat's write classes are right - while the mod runs, its code only ever stores into
'runtime' words (never written by the cheat) or the message table (written once); the pnach parser / overlap check.
With your discs (read only): the cheat applied to the original executable's memory gives exactly the memory of the
ISO build with the same settings (texts from the cave, Revenge's chevron), for PAL and USA; a ChainKit ISO is
refused; optional overlap check against other cheats (CHAINKIT_OTHER_PNACH).
"""
import os
import random
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from chainkit import cave, core, elfpatch, pnach, regions, settings  # noqa: E402

import test_cave as T  # noqa: E402


def test_mod_code_only_writes_runtime_words_or_the_message_table():
    lay = cave.Layout(regions.PAL, inline_texts=True)
    stores = set()
    rnd = random.Random(7)
    for seed in range(12):
        g = T.Game(bar=rnd.choice([0, 3]), flags=T.TUNE["flags"] | rnd.choice([0, cave.FL_DEBUG]))
        orig = g.cpu.m.write

        def track(a, data, orig=orig):
            if lay.a["REGION"] <= a < lay.a["HOLE_END"]:
                for k in range(0, len(data), 4):
                    stores.add((a + k) & ~3)
            orig(a, data)
        g.cpu.m.write = track
        g.cpu.m.w32 = lambda a, v, w=track: w(a, (v & 0xFFFFFFFF).to_bytes(4, "little"))
        g.cpu.m.wf32 = lambda a, x, w=track: w(a, __import__("struct").pack("<f", x))
        hud = 0x60000; g.cpu.m.w32(hud + cave.C_HUDCAR, T.CAR); pptr = 0x61000; g.cpu.m.w32(pptr, hud)
        for k, x in enumerate((100.0, 400.0, 290.0, 28.0)):
            g.cpu.m.wf32(0x62000 + 4 * k, x)
        dist = 0.0
        for _ in range(400):
            ev = rnd.choice(["tick", "tick", "add", "track", "empty", "takedown", "boost", "hud", "tint", "drain",
                             "sub", "release", "shrink"])
            if ev == "tick":
                g.cpu.m.wf32(T.CAR + cave.C_TIME, g.f(T.CAR + cave.C_TIME) + 1 / 60); g.tick()
            elif ev == "add":
                g.cpu.m.w32(0x70000, rnd.choice([T.T(0x2CC4A0), T.T(0x2CE254), 0x123456])); g.add(rnd.choice([5.0, 300.0]))
            elif ev == "track":
                dist += 3.0; g.track("near_miss", dist)
            elif ev == "empty":
                g.empty(stopreq=rnd.randint(0, 1))
            elif ev == "takedown":
                g.run("TAKEDOWN", a0=T.BOOST)
            elif ev == "boost":
                g.boosting(rnd.random() < 0.6)
            elif ev == "hud":
                g.run("HUDLBL", a0=0x62000, a1=4, s2=hud)
            elif ev == "tint":
                g.run("TINT", a1=pptr)
            elif ev == "drain":
                g.drain()
            elif ev == "sub":
                g.run("SUB", s0=T.BOOST, f12=50.0)
            elif ev == "release":
                g.run("RELEASE", a0=T.BOOST)
            elif ev == "shrink":
                g.cpu.stubs[T.A["SHRINK_ORIG"]] = lambda cpu: None
                g.run("SHRINK", a0=T.BOOST)
    lay_pal = T.LAY                                        # the stores were made with the test build's addresses
    kinds = {pnach.classify(lay_pal, a) for a in stores}
    assert stores and kinds <= {"runtime", "once"}, sorted(hex(a) for a in stores
                                                            if pnach.classify(lay_pal, a) == "continuous")[:10]


def test_parse_and_overlaps():
    ours = "[A]\npatch=1,EE,204A5000,extended,00000001\npatch=1,EE,2010000C,extended,00000002\n"
    other = ("[B]\npatch=0,EE,104A5002,extended,0000FFFF\n[C]\npatch=0,EE,000B5000,extended,00000001\n"
             "patch=1,EE,00100010,byte,00000001\n")
    assert pnach.parse(ours) == [("A", 0x4A5000, 0x4A5004, 1), ("A", 0x10000C, 0x100010, 1)]
    hits = pnach.overlaps(ours, other)
    assert hits == [((0x4A5000, 0x4A5004), "B", (0x4A5002, 0x4A5004))]


# ------------------------------------------------------------------------------------------- with discs
ISOS = [p for p in (os.environ.get("CHAINKIT_ISO_PAL", ""), os.environ.get("CHAINKIT_ISO_USA", ""),
                    os.environ.get("CHAINKIT_ISO", "")) if p and os.path.exists(p)]


@pytest.mark.skipif(not ISOS, reason="set CHAINKIT_ISO / CHAINKIT_ISO_PAL / CHAINKIT_ISO_USA")
@pytest.mark.parametrize("iso", ISOS)
def test_cheat_memory_equals_the_iso_build(iso):
    with core.Disc(iso) as d:
        if d.applied:
            pytest.skip("ISO already has the mod")
        elf, region = d.elf, d.region
    values = dict(settings.PRESETS["Hard"], flags=settings.PRESETS["Hard"]["flags"] | cave.FL_DEBUG)
    text, r = pnach.render(elf, values)
    assert r is region and text.startswith("gametitle=") and "[%s]" % pnach.SECTION in text
    patched, _ = elfpatch.patch(elf, dict(settings.check(values), arrow_tex_slot=12), inline_texts=True)
    want = pnach.loaded_words(patched)
    got = pnach.apply(elf, text)
    assert {a: w for a, w in want.items() if got.get(a, 0) != w} == {}
    assert set(got) - set(want) == set()
    # everything once at boot (patch=0); no runtime word is ever written
    lay = cave.Layout(region, inline_texts=True)
    for sec, a0, a1, place in pnach.parse(text):
        assert pnach.classify(lay, a0) != "runtime" and place == 0, hex(a0)
    assert pnach.file_name(region).endswith("_chainkit.pnach")
    # the cheat on a ChainKit executable is refused
    isoelf, _ = elfpatch.patch(elf, settings.DEFAULTS)
    with pytest.raises(elfpatch.ChainError, match="already has"):
        pnach.render(isoelf, settings.DEFAULTS)
    # with the user's Dominator art: the texture data sits after MusicKit's table, copied to TalkIcon by the cave
    dom = os.environ.get("CHAINKIT_DOMINATOR", "")
    if dom and os.path.exists(dom):
        with core.Disc(iso) as d:
            blob = pnach.arrow_blob(d.img.read_file("/DATA/GLOBAL.TXD"), core.dominator_txd(dom))
        text2, _ = pnach.render(elf, values, tex_blob=blob)
        patched2, _ = elfpatch.patch(elf, dict(settings.check(values), arrow_tex_slot=28), inline_texts=True,
                                     tex_blob=blob)
        want2 = pnach.loaded_words(patched2)
        got2 = pnach.apply(elf, text2)
        assert {a: w for a, w in want2.items() if got2.get(a, 0) != w} == {}
        lay2 = cave.Layout(region, inline_texts=True, tex_copy=True)
        assert all(got2.get(lay2.texsrc + k, 0) == int.from_bytes(blob[k:k + 4], "little") for k in range(0, len(blob), 4))
        assert "personal use only" in text2
    other = os.environ.get("CHAINKIT_OTHER_PNACH", "")
    if other and os.path.exists(other) and region["key"] == "PAL":
        assert pnach.overlaps(text, open(other, encoding="utf-8", errors="replace").read()) == []


@pytest.mark.skipif(not ISOS, reason="set CHAINKIT_ISO / CHAINKIT_ISO_PAL / CHAINKIT_ISO_USA")
@pytest.mark.parametrize("iso", ISOS)
def test_cheat_with_chainkit_arrow_equals_the_iso_build(iso):
    from chainkit import arrowart, assets
    with core.Disc(iso) as d:
        if d.applied:
            pytest.skip("ISO already has the mod")
        elf, txd = d.elf, d.img.read_file(assets.GLOBAL_TXD)
    blob = pnach.arrow_blob_record(arrowart.chainkit_record(txd))
    text, _ = pnach.render(elf, settings.DEFAULTS, tex_blob=blob, art="chainkit")
    patched, _ = elfpatch.patch(elf, dict(settings.DEFAULTS, arrow_tex_slot=28), inline_texts=True, tex_blob=blob)
    want, got = pnach.loaded_words(patched), pnach.apply(elf, text)
    assert {a: w for a, w in want.items() if got.get(a, 0) != w} == {}
    assert "ChainKit's arrow" in text and "personal use" in text
