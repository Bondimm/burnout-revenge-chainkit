"""ChainKit core: put the Burnout Chain mod (Burnout Dominator's supercharge and Burnout chain) on a Burnout Revenge
PAL ISO, change the settings of an ISO that already has it, check the result.

Always writes a NEW image (the source is only read):
    boot ELF            code + data in the top of the unused .sndata hole, hooks, PCSX2 CRC kept (elfpatch)
    MAIN{UK,FR,GE}.BIN  the HUD message texts (assets.TEXTS)
    DATA/GLOBAL.TXD     Dominator's Boost_Arrow in place of the online TalkIcon (same size and format) when you give
                        your own Burnout Dominator image; without it the arrows use Revenge's own chevron
Works on the original disc and on MusicKit / CarKit output (run MusicKit before ChainKit).
"""
import hashlib
import os

from . import assets, cave, elfpatch, iso, settings
from .elf import Elf, crc

PAL_ELF = "/SLES_535.07"
USA_ELF = "/SLUS_212.42"
SLOT_DOMINATOR, SLOT_CHEVRON = 28, 12
# MusicKit (PAL): playlist struct, original song table, table in the hole
MK_PLAYLIST, MK_TABLE_OLD, MK_TABLE_NEW, MK_SONGS = 0x460640, 0x460450, 0x4A3680, 41
# CarKit changes these words of the PAL executable
CARKIT_WORDS = {0x134D68: 0x3C02004B, 0x134D6C: 0xAFA3000C, 0x134D70: 0x2451DE38, 0x134D74: 0x24100002}


class KitError(Exception):
    """A problem explained in plain words (shown in the window / printed by the command line)."""


def default_output(src, tag="Burnout Chain"):
    base, ext = os.path.splitext(src)
    return base + " (%s)" % tag + (ext or ".iso")


def boot_elf(img):
    try:
        for line in img.read_file("/SYSTEM.CNF").decode("latin-1").splitlines():
            if line.replace(" ", "").upper().startswith("BOOT2="):
                return "/" + line.replace("/", "\\").split("\\")[-1].split(";")[0].strip().upper()
    except Exception:
        pass
    return None


def _open(path, what="ISO"):
    if not path:
        raise KitError("no %s chosen" % what)
    if not os.path.isfile(path):
        raise KitError("%s not found: %s" % (what, path))
    try:
        return iso.IsoImage(path)
    except Exception as exc:
        raise KitError("%s is not a PS2 DVD image (%s)" % (os.path.basename(path), exc))


def elf_facts(elf):
    """Other kits on the executable: MusicKit (song table moved into the hole), CarKit (car code changed), and a
    song list broken by running MusicKit after ChainKit (MusicKit then sees the hole already opened, skips its own
    code changes and only raises the song count of the original 41-song table)."""
    e = Elf(elf)
    ph = e.phdrs()
    hole_open = ph[0][2] + ph[0][4] == ph[1][2]
    count, table = e.r32(MK_PLAYLIST + 4), e.r32(MK_PLAYLIST + 0x4C)
    return dict(hole_open=hole_open, songs=count, musickit=hole_open and table == MK_TABLE_NEW,
                music_broken=table == MK_TABLE_OLD and count != MK_SONGS,
                carkit=any(e.r32(a) != w for a, w in CARKIT_WORDS.items()))


class Disc:
    """A Burnout Revenge PAL image: what is on it (mod applied? its settings, other kits)."""

    def __init__(self, path):
        self.path = path
        self.img = _open(path)
        try:
            self.elf_path = boot_elf(self.img)
            if self.elf_path == USA_ELF:
                raise KitError("this is the USA version of Burnout Revenge (SLUS-21242). ChainKit supports the PAL "
                               "version (SLES-53507) only for now.")
            if self.elf_path != PAL_ELF or PAL_ELF not in self.img.entries:
                raise KitError("not Burnout Revenge PAL (boot file %s). ChainKit needs Burnout Revenge PAL "
                               "(SLES-53507)." % (self.elf_path or "missing"))
            self.elf = self.img.read_file(self.elf_path)
            self.crc = crc(self.elf)
            if self.crc != elfpatch.PAL_CRC:
                raise KitError("the game executable was changed by another tool (CRC %08X); ChainKit needs it as "
                               "on the disc or as MusicKit / CarKit leave it" % self.crc)
            self.applied = elfpatch.is_applied(self.elf)
            self.version = elfpatch.version(self.elf)
            self.values = None
            if self.applied and self.version == cave.VERSION:
                self.values = settings.check(elfpatch.read_tunables(self.elf))
            self.langs = [l for l in assets.LANGS if assets.STRING_FILES[l] in self.img.entries]
            self.__dict__.update(elf_facts(self.elf))
        except Exception:
            self.close()
            raise

    @property
    def outdated(self):
        return self.applied and self.version != cave.VERSION

    @property
    def arrow_art(self):
        """'dominator', 'chevron' (mod applied) or None."""
        if not self.values:
            return None
        return "dominator" if self.values["arrow_tex_slot"] == SLOT_DOMINATOR else "chevron"

    def problems(self):
        """Plain-words reasons why this disc cannot be used (empty = fine)."""
        out = []
        if self.music_broken:     # (MusicKit 2026-10 refuses such an image; an older / other tool may not)
            out.append("MusicKit was run AFTER ChainKit on this disc: the song list is broken. Run MusicKit on your "
                       "original ISO first, then ChainKit on MusicKit's output.")
        if self.outdated:
            out.append("this disc has the mod from an older ChainKit build; its settings cannot be changed. Build it "
                       "again from your ISO without the mod.")
        return out

    def summary(self):
        s = "Burnout Revenge PAL" + (" with the Burnout Chain mod" if self.applied else "")
        extra = [k for k, on in (("MusicKit songs (%d)" % self.songs, self.musickit), ("CarKit cars", self.carkit))
                 if on]
        return s + (" + " + ", ".join(extra) if extra else "")

    def close(self):
        try:
            self.img.f.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def dominator_txd(path):
    """GLOBAL texture bundle of a Burnout Dominator image (the one holding Boost_Arrow)."""
    img = _open(path, "Burnout Dominator ISO")
    try:
        boot = boot_elf(img)
        for k in sorted(k for k in img.entries if k.startswith("/DATA/GLOBAL") and k.endswith(".TXD")):
            data = img.read_file(k)
            try:
                if assets.SOURCE in assets.txd_records(data):
                    return data
            except Exception:
                continue
    finally:
        img.f.close()
    if boot in (PAL_ELF, USA_ELF):
        raise KitError("that is a Burnout Revenge image; the arrow art comes from Burnout Dominator")
    raise KitError("no Boost_Arrow texture found - is this a Burnout Dominator disc image?")


def _arrow(disc, dominator, log):
    """GLOBAL.TXD with Dominator's arrow (None without a Dominator image or when the image already has it)."""
    if not dominator:
        return None
    dtxd = dominator_txd(dominator)
    txd = disc.img.read_file(assets.GLOBAL_TXD)
    if assets.arrow_merged(txd, dtxd):
        return None
    try:
        out = assets.merge_arrow(txd, dtxd)
    except ValueError as exc:
        raise KitError("the Dominator arrow texture does not fit (%s)" % exc)
    log("arrow texture: Burnout Dominator's Boost_Arrow")
    return out


def _check_out(src, out):
    if not out:
        raise KitError("choose where to save the new ISO")
    if os.path.abspath(out) == os.path.abspath(src):
        raise KitError("the new ISO must be a different file (your ISO is never changed)")
    d = os.path.dirname(os.path.abspath(out))
    if not os.path.isdir(d):
        raise KitError("folder not found: %s" % d)


def build(src, out, values=None, dominator=None, log=print, progress=None):
    """New image with the mod. values = settings dict (missing = defaults). Returns the values written."""
    _check_out(src, out)
    values = settings.check(values)
    with Disc(src) as d:
        for p in d.problems():
            raise KitError(p)
        if d.applied:
            raise KitError("this ISO already has the Burnout Chain mod - open it to change its settings")
        log("source: %s (%s)" % (os.path.basename(src), d.summary()))
        txd = _arrow(d, dominator, log)
        values["arrow_tex_slot"] = SLOT_DOMINATOR if txd else SLOT_CHEVRON
        if not txd:
            log("arrow texture: Revenge's own chevron (no Burnout Dominator ISO chosen)")
        reps = {}
        try:
            elf, rep = elfpatch.patch(d.elf, values)
        except elfpatch.ChainError as exc:
            raise KitError(str(exc))
        reps[d.elf_path] = elf
        log("executable: %d hooks, code %#x-%#x, PCSX2 CRC %08X kept%s" % (
            len(rep["hooks"]), rep["code"][0], rep["code"][1], rep["crc"],
            "" if rep["hole_opened"] else " (reuses the space MusicKit opened)"))
        for lang in d.langs:
            p = assets.STRING_FILES[lang]
            reps[p] = assets.add_strings(d.img.read_file(p), lang)
        log("HUD texts: %s" % ", ".join(d.langs))
        if txd:
            reps[assets.GLOBAL_TXD] = txd
        d.img.build(out, reps, progress)
    log("saved %s" % out)
    return values


def tune(src, out, values, dominator=None, log=print, progress=None):
    """New image = `src` (which has the mod) with other settings. Only the executable changes (and the arrow art,
    when a Dominator image is given for an image that does not have it yet). Returns the values written."""
    _check_out(src, out)
    values = settings.check(values)
    with Disc(src) as d:
        for p in d.problems():
            raise KitError(p)
        if not d.applied:
            raise KitError("this ISO does not have the Burnout Chain mod yet - save a new ISO with the mod first")
        log("source: %s (%s)" % (os.path.basename(src), d.summary()))
        reps = {}
        txd = _arrow(d, dominator, log)
        if txd:
            reps[assets.GLOBAL_TXD] = txd
            values["arrow_tex_slot"] = SLOT_DOMINATOR
        else:
            values["arrow_tex_slot"] = d.values["arrow_tex_slot"]
        diff = settings.changed(values, d.values)
        log("settings changed: %s" % (", ".join(diff) if diff else "none"))
        try:
            reps[d.elf_path] = elfpatch.tune(d.elf, values)
        except elfpatch.ChainError as exc:
            raise KitError(str(exc))
        d.img.build(out, reps, progress)
    log("saved %s" % out)
    return values


def save(src, out, values=None, dominator=None, log=print, progress=None):
    """build() or tune(), whichever fits the source image."""
    with Disc(src) as d:
        applied = d.applied
    return (tune if applied else build)(src, out, values, dominator, log, progress)


def _sha(img, path):
    h = hashlib.sha1()
    f, e = img.open_file(path)
    with f:
        left = e.size
        while left > 0:
            b = f.read(min(left, 1 << 22))
            if not b:
                break
            h.update(b)
            left -= len(b)
    return h.hexdigest()


def validate(src, out, dominator=None, log=print, quick=False):
    """Check a saved image against the image it was made from. Returns True when everything is OK."""
    ok = True
    s, o = Disc(src), None
    try:
        o = Disc(out)
        probs = elfpatch.check(o.elf, log)
        log("executable: %s" % ("OK" if not probs else "%d problem(s)" % len(probs)))
        ok &= not probs
        log("PCSX2 game CRC: %08X -> %08X %s" % (s.crc, o.crc, "(unchanged)" if s.crc == o.crc else "CHANGED"))
        ok &= s.crc == o.crc
        for lang in s.langs:
            good = assets.strings_present(o.img.read_file(assets.STRING_FILES[lang]), lang)
            log("texts %s: %s" % (lang, "OK" if good else "MISSING"))
            ok &= good
        art = o.arrow_art
        if dominator:
            merged = assets.arrow_merged(o.img.read_file(assets.GLOBAL_TXD), dominator_txd(dominator))
            log("arrow texture: %s" % ("Burnout Dominator's Boost_Arrow" if merged else "NOT merged"))
            ok &= bool(merged) and art == "dominator"
        else:
            log("arrow texture: %s" % ("Burnout Dominator's Boost_Arrow" if art == "dominator"
                                       else "Revenge's chevron"))
        if s.musickit or o.musickit:
            kept = s.songs == o.songs and o.musickit == s.musickit
            log("MusicKit song list: %s" % ("kept (%d songs)" % o.songs if kept else "CHANGED"))
            ok &= kept
        if o.music_broken:
            log("MusicKit song list: BROKEN (MusicKit was run after ChainKit)")
            ok = False
        changed = {s.elf_path, assets.GLOBAL_TXD} | set(assets.STRING_FILES.values())
        missing = [k for k in s.img.entries if k not in o.img.entries]
        if missing:
            log("missing files: %s" % ", ".join(missing[:5]))
            ok = False
        if not quick:
            same = diff = 0
            for k, e in s.img.entries.items():
                if k in changed or k not in o.img.entries or k.endswith("/"):
                    continue
                if e.size == o.img.entries[k].size and _sha(s.img, k) == _sha(o.img, k):
                    same += 1
                else:
                    diff += 1
                    if diff <= 5:
                        log("changed unexpectedly: %s" % k)
            log("untouched files identical: %d (%d differ)" % (same, diff))
            ok &= diff == 0
        if o.values:
            p = settings.preset_of(o.values)
            n = len([x for x in settings.changed(o.values) if x != "arrow_tex_slot"])
            log("settings: %s" % (p or "custom (%d changed from the defaults)" % n))
    finally:
        s.close()
        if o:
            o.close()
    log("RESULT: %s" % ("OK" if ok else "FAILED"))
    return ok
