"""Disc data for the Burnout Chain mod: HUD message strings (MAIN*.BIN) and the arrow texture (DATA/GLOBAL.TXD)."""
import struct

from .strtable import StringTable, string_hash

# Texts as Burnout Dominator shows them (EU discs: MAINUK / MAINFR / MAINGE). "x%1" is Revenge's own
# "boost bar segments" string, formatted by the game.
TEXTS = {
    "BigMessageBlueBoostAvailablePart1": {"UK": "SUPERCHARGE READY!", "FR": "SUPERCHARGE PRET !", "GE": "SUPER-BOOST BEREIT!"},
    "BigMessageBurnoutPart1": {"UK": "BURNOUT!", "FR": "BURNOUT !", "GE": "BURNOUT!"},
    "BigMessageBurnoutLostPart1": {"UK": "SUPERCHARGE LOST", "FR": "SUPERCHARGE PERDU", "GE": "SUPER-BOOST VERLOREN"},
    "BigMessageBurnoutDominationPart1": {"UK": "BURNOUT DOMINATION!", "FR": "DOMINATION BURNOUT !", "GE": "BURNOUT-DOMINATION!"},
    "BigMessageBurnoutWowPart1": {"UK": "BURNOUT!", "FR": "BURNOUT !", "GE": "BURNOUT!"},
}
# one line, no second line under the award sign (it overlapped the stars)
TEXTS["BigMessageBurnoutWowPart1"] = {"UK": "BURNOUT! WOW", "FR": "BURNOUT ! WOW", "GE": "BURNOUT! WOW"}
for _t in TEXTS.values():          # USA disc: MAINUS.BIN (English, same texts)
    _t["US"] = _t["UK"]
LANGS = ("UK", "FR", "GE", "US")
STRING_FILES = {lang: "/LANGUAGE/STRINGS/MAIN%s.BIN" % lang for lang in LANGS}


def add_strings(data, lang):
    t = StringTable(data)
    for name, texts in TEXTS.items():
        h = string_hash(name)
        cur = t.entries.get(h)
        if cur is not None and cur != texts[lang]:
            raise ValueError("string id %s already used with another text (%r)" % (name, cur))
        t.entries[h] = texts[lang]
    return t.build()


def strings_present(data, lang):
    t = StringTable(data)
    return all(t.get(n) == tx[lang] for n, tx in TEXTS.items())


# ------------------------------------------------------------------------------------------------ textures
# Criterion texture bundle (both games): u32 ?, u32 magic 0xBCDEED81, u32 count, u32 index offset (0x10);
# index = count x {u32 id, 0, u32 record offset, 0}; a record is self-relative, name at +0xA8 (32 bytes).
GLOBAL_TXD = "/DATA/GLOBAL.TXD"
DOMINATOR_TXD = "/DATA/GLOBALE.TXD"
TARGET = "TalkIcon"          # online voice-chat icon, 32x32 4-bit like Boost_Arrow; HUD texture slot 28
SOURCE = "Boost_Arrow"
PIXPTR = 0x104               # record field: pixel data address (load-base dependent)


def txd_records(data):
    n = struct.unpack_from("<I", data, 8)[0]
    io = struct.unpack_from("<I", data, 12)[0]
    offs = sorted(struct.unpack_from("<4I", data, io + 16 * i)[2] for i in range(n))
    out = {}
    for k, o in enumerate(offs):
        end = offs[k + 1] if k + 1 < n else len(data)
        name = data[o + 0xA8:o + 0xC8].split(b"\0")[0].decode("latin-1")
        out[name] = (o, end - o)
    return out


def merge_arrow(revenge_txd, dominator_txd):
    """Replace the TalkIcon record with Dominator's Boost_Arrow (same size/format), keeping the name."""
    r = txd_records(revenge_txd)
    d = txd_records(dominator_txd)
    ro, rs = r[TARGET]
    do, ds = d[SOURCE]
    if rs != ds:
        raise ValueError("texture records differ in size (%d / %d)" % (rs, ds))
    rec = bytearray(dominator_txd[do:do + ds])
    if rec[:0xA8] != revenge_txd[ro:ro + 0xA8]:
        raise ValueError("texture headers differ (format mismatch)")
    rec[0xA8:0xC8] = revenge_txd[ro + 0xA8:ro + 0xC8]          # keep the name
    # +0x104 = address of the pixel data for the GS upload (file offset + the game's load base; Dominator's
    # differs). Copying Dominator's value made the game upload unrelated memory (boxes with digit-like glyphs
    # in PCSX2). Keep Revenge's own value: the record sits at the same offset.
    rec[PIXPTR:PIXPTR + 4] = revenge_txd[ro + PIXPTR:ro + PIXPTR + 4]
    for k in range(0xC8, 0x240, 4):                             # every other header field must match
        if rec[k:k + 4] != revenge_txd[ro + k:ro + k + 4]:
            raise ValueError("texture record field %#x differs" % k)
    out = bytearray(revenge_txd)
    out[ro:ro + rs] = rec
    return bytes(out)


def arrow_merged(revenge_txd, dominator_txd=None):
    """True when TalkIcon holds Dominator's Boost_Arrow pixels with Revenge's own header (incl. +0x104)."""
    r = txd_records(revenge_txd)
    ro, rs = r[TARGET]
    if dominator_txd is None:
        return None
    d = txd_records(dominator_txd)
    do, ds = d[SOURCE]
    pix = revenge_txd[ro + 0x240:ro + rs] == dominator_txd[do + 0x240:do + ds]
    # +0x104 must follow Revenge's layout: pixel address = record offset + 0x250 + Revenge's load constant,
    # derived from the first texture record of the same file.
    o0 = min(o for o, s in r.values())
    base = struct.unpack_from("<I", revenge_txd, o0 + PIXPTR)[0] - o0
    ptr_ok = struct.unpack_from("<I", revenge_txd, ro + PIXPTR)[0] == base + ro
    return pix and ptr_ok
