"""The patch on the real game executable, read from your Burnout Revenge PAL ISO (only read, nothing is written).

Runs only when CHAINKIT_ISO points to a Burnout Revenge PAL ISO WITHOUT the mod (MusicKit / CarKit output is fine):
    set CHAINKIT_ISO=D:\\path\\to\\Burnout Revenge.iso          (macOS: export CHAINKIT_ISO=...)
    .venv\\Scripts\\python -m pytest tests\\test_elf.py -v
"""
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from chainkit import cave, core, elfpatch, settings  # noqa: E402
from chainkit.elf import Elf, _fix_crc, crc  # noqa: E402

ISO = os.environ.get("CHAINKIT_ISO", "")
pytestmark = pytest.mark.skipif(not (ISO and os.path.exists(ISO)), reason="set CHAINKIT_ISO")


@pytest.fixture(scope="module")
def elf():
    with core.Disc(ISO) as d:
        assert not d.applied, "CHAINKIT_ISO must be an ISO without the mod"
        return d.elf


def test_patch_check_and_read_back(elf):
    for name, values in settings.PRESETS.items():
        v = dict(values, arrow_tex_slot=28)
        out, rep = elfpatch.patch(elf, v)
        assert crc(out) == elfpatch.PAL_CRC
        assert elfpatch.check(out, lambda *a: None) == [], name
        assert elfpatch.version(out) == cave.VERSION
        assert not settings.changed(settings.check(elfpatch.read_tunables(out)), v), name
        with pytest.raises(elfpatch.ChainError, match="already applied"):
            elfpatch.patch(out, v)


def test_tune_changes_only_the_settings(elf):
    base, _ = elfpatch.patch(elf, settings.DEFAULTS)
    v = dict(settings.PRESETS["Hard"], modes=0x5F, lit_rgba=(1.0, 0.2, 0.1, 1.0), fill_w_near_miss=0.5,
             flags=settings.PRESETS["Hard"]["flags"] | cave.FL_SHOWLABEL | cave.FL_SHOWHINT)
    tuned = elfpatch.tune(base, v)
    assert crc(tuned) == elfpatch.PAL_CRC and elfpatch.check(tuned, lambda *a: None) == []
    assert not settings.changed(settings.check(elfpatch.read_tunables(tuned)), settings.check(v))
    direct, _ = elfpatch.patch(elf, v)
    assert tuned == direct                       # tuning = building with these settings in the first place
    lay = cave.Layout()
    e0, e1 = Elf(base), Elf(tuned)
    lo, hi = e0.file_offset(cave.PAL["REGION"]), e0.file_offset(lay.code)
    diff = [i for i in range(0, len(base) - 4, 4) if base[i:i + 4] != tuned[i:i + 4]]
    assert all(lo <= i < hi for i in diff[:-1])  # data block only (+ the CRC word at the end)


def test_other_kits_detected(elf):
    f = core.elf_facts(elf)
    assert f["songs"] >= 41
    out, _ = elfpatch.patch(elf, settings.DEFAULTS)
    assert core.elf_facts(out)["music_broken"] is False
    if not f["musickit"]:
        # what an image looks like when a tool raised the song count after ChainKit without moving the table
        e = Elf(out)
        e.w32(core.MK_PLAYLIST + 4, 50)
        broken = _fix_crc(e.d, elfpatch.PAL_CRC, True)
        assert core.elf_facts(broken)["music_broken"]


def test_hooks_hit_the_expected_original_code(elf):
    e = Elf(elf)
    for va, old, new, what in cave.hooks(cave.Layout(), cave.build_code(cave.Layout())[1]):
        assert e.r32(va) == old, hex(va)
    for vt in [v for _, _, vts in cave.MODES for v in vts]:
        # every mode vtable points into the code segment (sanity check of the mode table)
        fn = struct.unpack_from("<I", e.d, e.file_offset(vt) + 12)[0]       # first virtual function
        assert 0x100000 <= fn < 0x400000, hex(vt)
