"""PCSX2 cheat (.pnach) output: the Burnout Chain mod as memory writes instead of a modified disc.

The cheat writes exactly the memory our ISO patch produces (same code, same data), built with two differences that
a cheat cannot avoid because it cannot change disc files:
- the arrows use Revenge's own chevron texture (no Dominator Boost_Arrow in GLOBAL.TXD): arrow_tex_slot = 12;
- the pop-up texts come from the cave (English UTF-16 texts after the code; the message is pointed at its text
  right before it is posted) instead of new MAIN*.BIN string entries.

Every 32-bit word that differs from the original executable's loaded memory becomes one line, all with place 0
("once, when the game's executable has been loaded" - PCSX2 Patch::ApplyBootPatches):
- the hooks and the cave code / constants never change, so one write at boot is enough (Revenge never reloads its
  executable; the .sndata hole is not used by anything else);
- the HUD message table must be written exactly once, before the game's own init (FUN_0016fcf8) turns its name
  pointers into text handles - a continuous write would undo that;
- runtime state (per-car state, timers, scratch buffers) is never written (zero at boot, like the zero-filled hole
  of the ISO version).
Everything at boot also means a consistent state: switching the cheat on or off takes effect at the next boot,
never half-way through a race. (Same choice as Nehalem's Single Event Mod cheat.)
File name: <SERIAL>_<CRC>_chainkit.pnach - PCSX2 loads every <SERIAL>_<CRC>*.pnach in its cheats folder
(Patch::GetPnachTemplate with wildcard), so it never replaces another cheat for the same game.
"""
import re
import struct

from . import cave, elfpatch, settings
from .elf import Elf

SERIAL = {"PAL": "SLES-53507", "USA": "SLUS-21242"}
TITLE = {"PAL": "Burnout Revenge (PAL-E) [SLES-53507]", "USA": "Burnout Revenge (NTSC-U) [SLUS-21242]"}
SECTION = "Burnout Chain (ChainKit)"


def file_name(region):
    return "%s_%08X_chainkit.pnach" % (SERIAL[region["key"]], region["crc"])


def loaded_words(data):
    """{address: word} of every PT_LOAD segment's file bytes (what the PS2 loader copies into memory)."""
    e = Elf(data)
    out = {}
    for ph in e.phdrs():
        if ph[0] != 1:
            continue
        n = ph[4] // 4
        for k, w in enumerate(struct.unpack_from("<%dI" % n, e.d, ph[1])):
            out[ph[2] + 4 * k] = w
    return out


def classify(lay, addr):
    """'once' (message table), 'runtime' (never written) or 'continuous'."""
    lo, hi = lay.once_range()
    if lo <= addr < hi:
        return "once"
    off = addr - lay.a["REGION"]
    for a, b in cave.RUNTIME_RANGES:
        if a <= off < b:
            return "runtime"
    return "continuous"


def arrow_blob(revenge_txd, dominator_txd):
    """Boost_Arrow's texture data for the cheat (record bytes TEX_FROM..TEX_SIZE) - checked to fit TalkIcon exactly
    like the ISO version's merge."""
    from . import assets
    merged = assets.merge_arrow(revenge_txd, dominator_txd)
    ro, rs = assets.txd_records(merged)[assets.TARGET]
    if rs != cave.TEX_SIZE:
        raise elfpatch.ChainError("unexpected arrow texture size %#x" % rs)
    return merged[ro + cave.TEX_FROM:ro + rs]


def writes(elf_data, values, tex_blob=None):
    """[(address, word, 'once'|'continuous')] for the cheat. elf_data = the game's executable (original, MusicKit or
    CarKit output; not one that already has ChainKit). tex_blob = arrow_blob(...) for Dominator's arrow."""
    if elfpatch.is_applied(elf_data):
        raise elfpatch.ChainError("this executable already has the Burnout Chain mod (ISO version): make the cheat "
                                  "from your ISO without the mod, and do not use both together")
    values = settings.check(values)
    # Dominator's arrow (copied into TalkIcon by the cave, slot 28) or Revenge's chevron (slot 12)
    values["arrow_tex_slot"] = 28 if tex_blob is not None else 12
    region = elfpatch.region_of(elf_data)
    lay = cave.Layout(region, inline_texts=True, tex_copy=tex_blob is not None)
    patched, _ = elfpatch.patch(elf_data, values, inline_texts=True, tex_blob=tex_blob)
    before, after = loaded_words(elf_data), loaded_words(patched)
    out = []
    for addr in sorted(after):
        w = after[addr]
        if before.get(addr, 0) == w:
            continue
        kind = classify(lay, addr)
        if kind == "runtime":
            if w:
                raise AssertionError("runtime word %#x is not zero" % addr)
            continue
        out.append((addr, w, kind))
    return out, region


def render(elf_data, values, preset=None, tex_blob=None):
    """The .pnach file text."""
    ws, region = writes(elf_data, values, tex_blob)
    key = region["key"]
    if tex_blob is not None:
        arrows = "Burnout Dominator's arrow from your own disc (personal use only: do not share this file)"
    else:
        arrows = "Revenge's chevron"
    name = preset or settings.preset_of(settings.check(values)) or "custom"
    desc = ("Burnout Dominator's supercharge and Burnout chain. Settings: %s. Arrows: %s. Do not use together "
            "with a ChainKit ISO." % (name, arrows))
    lines = ["gametitle=%s" % TITLE[key], "",
             "[%s]" % SECTION, "author=Bondimm (ChainKit)", "description=%s" % desc,
             "// %d words, all written once when the game boots (patch=0): switch the cheat on, then start "
             "(or restart) the game." % len(ws)]
    if tex_blob is not None:
        lines.append("// Contains texture data of Burnout Dominator (Electronic Arts) taken from your own disc: "
                     "for your personal use only - do not share or upload this file.")
    for addr, w, kind in ws:
        lines.append("patch=0,EE,2%07X,extended,%08X" % (addr, w))
    return "\n".join(lines) + "\n", region


def parse(text):
    """{(section, address): (word, place)} of the 32-bit writes (2xxxxxxx), plus 8/16-bit writes as their
    address ranges. Returns [(section, start, end, place)]."""
    out = []
    section = None
    for line in text.splitlines():
        line = line.split("//")[0].strip()
        m = re.match(r"\[(.+)\]$", line)
        if m:
            section = m.group(1)
            continue
        m = re.match(r"patch\s*=\s*(\d+)\s*,\s*EE\s*,\s*([0-9A-Fa-f]{8})\s*,\s*(\w+)\s*,\s*([0-9A-Fa-f]+)", line)
        if not m:
            continue
        place, a, kind = int(m.group(1)), int(m.group(2), 16), m.group(3).lower()
        size = {"byte": 1, "short": 2, "word": 4}.get(kind)
        if kind == "extended":
            size = {0: 1, 1: 2, 2: 4}.get(a >> 28, 4)
            a &= 0x0FFFFFFF
        out.append((section, a, a + (size or 4), place))
    return out


def overlaps(ours_text, other_text):
    """[(our address range, other section, other range)] where both cheats write the same memory."""
    ours = parse(ours_text)
    other = parse(other_text)
    hits = []
    other_sorted = sorted(other, key=lambda x: x[1])
    for _, a0, a1, _ in ours:
        for sec, b0, b1, _ in other_sorted:
            if b0 >= a1:
                break
            if a0 < b1 and b0 < a1:
                hits.append(((a0, a1), sec, (b0, b1)))
    return hits


def apply(elf_data, pnach_text):
    """Memory image (dict) of the original executable with the cheat's writes applied (for checks)."""
    mem = loaded_words(elf_data)
    for line in pnach_text.splitlines():
        m = re.match(r"patch=(\d),EE,2([0-9A-F]{7}),extended,([0-9A-F]{8})", line.strip())
        if m:
            mem[int(m.group(2), 16)] = int(m.group(3), 16)
    return mem


