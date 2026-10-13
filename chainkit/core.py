"""ChainKit core: put the Burnout Chain mod (Burnout Dominator's supercharge and Burnout chain) on a Burnout Revenge
ISO (Europe SLES-53507 or USA SLUS-21242), change the settings of an ISO that already has it, check the result.

Writes a NEW image (the source is only read), or saves into a game folder for PCSX2's Host Filesystem (hostfs.py):
    boot ELF            code + data in the top of the unused .sndata hole, hooks, PCSX2 CRC kept (elfpatch)
    MAIN{UK,FR,GE,US}.BIN  the HUD message texts (assets.TEXTS)
    DATA/GLOBAL.TXD     Dominator's Boost_Arrow in place of the online TalkIcon (same size and format) when you give
                        your own Burnout Dominator image; without it ChainKit's arrow (Revenge's chevron slash
                        repainted, made from your own disc - arrowart.py) in the same place
Works on the original disc and on MusicKit output and discs with changed car code (run MusicKit before ChainKit).
A HostFS game folder (made by MusicKit or ChainKit) can be the source too; it is then saved into itself.
"""
import hashlib
import os

from . import assets, cave, elfpatch, hostfs, iso, regions, settings
from .elf import Elf, crc

PAL_ELF = regions.PAL["elf"]
USA_ELF = regions.USA["elf"]
REVENGE_ELFS = tuple(regions.REGIONS)
SUPPORTED = "Europe / PAL (SLES-53507) or USA / NTSC (SLUS-21242)"
SLOT_DOMINATOR, SLOT_CHEVRON = 28, 12
# MusicKit: playlist struct, original song table (PAL addresses, translated per build), 41 original songs
MK_PLAYLIST, MK_TABLE_OLD, MK_SONGS = 0x460640, 0x460450, 41
CAR_CODE_SITE = 0x134D68               # car mods change the 4 words from here (PAL address)
GAME = "Burnout Revenge"               # HostFS boot image "Burnout Revenge (HostFS).iso" (the same name as MusicKit's)
NAHELAM_DIR = "Burnout Revenge"        # folder of the HostFS cheats for this game in Nahelam's repository
# a game folder must have these (directory: at least that many files, about 60% of the disc's; "/FILE": that file),
# else it is an incompletely extracted folder
REQUIRED = {"CNF": 1, "DATA": 6, "FE": 30, "IOP": 20, "LANGUAGE": 3, "OVID": 40, "PVEH": 160, "SOUND": 40, "TRACKS": 150,
            "/IOP/GTFSHOST.IRX": 1}
KEEP_HINT = ("To keep those changes, open this folder in step 1 (\"Folder...\", or --iso <folder>) and add or "
             "change the mod there; or choose an empty folder to start again from your ISO.")


class KitError(Exception):
    """A problem explained in plain words (shown in the window / printed by the command line)."""


def default_output(src, tag="Burnout Chain"):
    base, ext = os.path.splitext(src)
    return base + " (%s)" % tag + (ext or ".iso")


def default_folder(src):
    """Suggested HostFS folder for the ISO `src`: next to it, "<iso name> (HostFS)"."""
    return os.path.splitext(os.path.abspath(src))[0] + " (HostFS)"


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
    if what == "ISO" and os.path.isdir(path):
        try:
            return hostfs.FolderImage(path)
        except Exception as exc:
            raise KitError("%s is not a game folder (%s)" % (path, exc))
    if not os.path.isfile(path):
        raise KitError("%s not found: %s" % (what, path))
    try:
        return iso.IsoImage(path)
    except Exception as exc:
        raise KitError("%s is not a PS2 DVD image (%s)" % (os.path.basename(path), exc))


def elf_facts(elf, region=None):
    """Other kits on the executable: MusicKit (song table moved into the hole), a car mod (car code changed), and a
    song list broken by running MusicKit after ChainKit (MusicKit then sees the hole already opened, skips its own
    code changes and only raises the song count of the original 41-song table)."""
    region = region or elfpatch.region_of(elf)
    e = Elf(elf)
    ph = e.phdrs()
    hole_open = ph[0][2] + ph[0][4] == ph[1][2]
    pl = regions.t(region, MK_PLAYLIST)
    count, table = e.r32(pl + 4), e.r32(pl + 0x4C)
    site = regions.t(region, CAR_CODE_SITE)
    return dict(hole_open=hole_open, songs=count, musickit=hole_open and table == region["mk_table_new"],
                music_broken=table == regions.t(region, MK_TABLE_OLD) and count != MK_SONGS,
                cars_changed=any(e.r32(site + 4 * k) != w for k, w in enumerate(region["car_code_orig"])))


class Disc:
    """A Burnout Revenge image (Europe or USA): what is on it (mod applied? its settings, other kits)."""

    def __init__(self, path):
        self.path = path
        self.img = _open(path)
        self.is_folder = getattr(self.img, "is_folder", False)
        if self.is_folder:
            missing = hostfs.missing_parts(self.img, REQUIRED)
            if missing:
                self.close()
                raise KitError(hostfs.incomplete_message(missing))
        try:
            self.elf_path = boot_elf(self.img)
            if self.elf_path not in REVENGE_ELFS or self.elf_path not in self.img.entries:
                raise KitError("not Burnout Revenge for PS2 (boot file %s). ChainKit needs Burnout Revenge %s."
                               % (self.elf_path or "missing", SUPPORTED))
            self.region = regions.REGIONS[self.elf_path]
            self.elf = self.img.read_file(self.elf_path)
            self.crc = crc(self.elf)
            if self.crc != self.region["crc"]:
                raise KitError("the game executable was changed by another tool (CRC %08X); ChainKit needs it as "
                               "on the disc or as MusicKit leaves it" % self.crc)
            self.applied = elfpatch.is_applied(self.elf)
            self.version = elfpatch.version(self.elf)
            self.values = None
            if self.applied and self.version == cave.VERSION:
                self.values = settings.check(elfpatch.read_tunables(self.elf))
            self.langs = [l for l in assets.LANGS if assets.STRING_FILES[l] in self.img.entries]
            self.__dict__.update(elf_facts(self.elf, self.region))
        except Exception:
            self.close()
            raise

    @property
    def outdated(self):
        return self.applied and self.version != cave.VERSION

    @property
    def arrow_art(self):
        """'chainkit', 'dominator', 'chevron' (older builds) for an image with the mod, else None."""
        if not self.values:
            return None
        if self.values["arrow_tex_slot"] != SLOT_DOMINATOR:
            return "chevron"
        if not hasattr(self, "_art"):
            from . import arrowart
            self._art = "chainkit" if arrowart.is_chainkit(self.img.read_file(assets.GLOBAL_TXD)) else "dominator"
        return self._art

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
        s = "Burnout Revenge %s" % self.region["short"] + (" with the Burnout Chain mod" if self.applied else "")
        extra = [k for k, on in (("MusicKit songs (%d)" % self.songs, self.musickit), ("changed cars", self.cars_changed))
                 if on]
        return s + (" + " + ", ".join(extra) if extra else "")

    def close(self):
        try:
            self.img.f.close()
        except Exception:
            pass

    def hostfs_steps(self, folder=None):
        """How to play a HostFS folder in PCSX2 (numbered steps)."""
        return hostfs.instructions(GAME, NAHELAM_DIR, self.elf_path, self.crc, folder)

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
    if boot in REVENGE_ELFS:
        raise KitError("that is a Burnout Revenge image; the arrow art comes from Burnout Dominator")
    raise KitError("no Boost_Arrow texture found - is this a Burnout Dominator disc image?")


def _base(d, out, to_folder):
    """Where ChainKit reads the texts and textures it changes: the folder itself when an ISO is saved into a folder
    that already has the game (_check_folder made sure its executable is the ISO's, so other differences there are
    other mods' texts or textures - they are kept), else the source."""
    if to_folder and not d.is_folder and hostfs.is_game_folder(out):
        return hostfs.FolderImage(out)
    return d.img


def _read(d, base, path, log):
    """File `path` from `base` (see _base), or from the source when `base` does not have it."""
    if base is d.img or path not in base.entries:
        return d.img.read_file(path)
    data = base.read_file(path)
    if data != d.img.read_file(path):
        log("kept another mod's changes in the folder's %s" % path.lstrip("/"))
    return data


def _arrow(disc, dominator, log, base=None):
    """GLOBAL.TXD with Dominator's arrow (None without a Dominator image or when the image already has it)."""
    if not dominator:
        return None
    dtxd = dominator_txd(dominator)
    txd = _read(disc, base or disc.img, assets.GLOBAL_TXD, log)
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


def _check_folder(d, folder):
    """KitError when `folder` cannot receive the game of `d`: a folder opened as the source is saved into itself;
    an ISO goes into an empty folder or a folder with the same game whose executable is still the ISO's (a folder
    with MusicKit songs or ChainKit already: open that folder instead, so nothing is lost)."""
    if not folder:
        raise KitError("choose the folder for PCSX2 HostFS")
    folder = os.path.abspath(folder)
    if d.is_folder:
        if os.path.normcase(folder) != os.path.normcase(os.path.abspath(d.path)):
            raise KitError("an opened folder is saved into itself (to fill another folder, open your ISO)")
        return
    if os.path.isfile(folder):
        raise KitError("this is a file - choose a folder")
    if os.path.isdir(folder) and os.listdir(folder):
        if not hostfs.is_game_folder(folder):
            raise KitError(hostfs.not_a_game_folder(folder))
        try:
            img = hostfs.FolderImage(folder)
        except ValueError as exc:
            raise KitError(str(exc))
        elf = hostfs.boot_elf(img.read_file("/SYSTEM.CNF"))
        if elf != d.elf_path:
            raise KitError("this folder has another game or version (%s, not %s)" % ((elf or "?").strip("/"),
                                                                                       d.elf_path.strip("/")))
        if elf in img.entries and img.read_file(elf) != d.elf:
            raise KitError("this folder already has changes in the game executable (MusicKit songs, ChainKit or "
                           "another mod): saving your ISO into it would remove them. " + KEEP_HINT)


def folder_plan(src, folder):
    """{"extract_bytes": bytes still to copy from the ISO, "has_game": the folder has the game already}."""
    with Disc(src) as d:
        _check_folder(d, folder)
        if d.is_folder:
            return {"extract_bytes": 0, "has_game": True}
        if not os.path.isdir(folder):
            return {"extract_bytes": sum(e.size for e in d.img.entries.values()), "has_game": False}
        return {"extract_bytes": hostfs.needed_bytes(d.img, folder), "has_game": hostfs.is_game_folder(folder)}


def _changed_paths(d):
    return {d.elf_path, assets.GLOBAL_TXD} | {assets.STRING_FILES[l] for l in d.langs}


def _write(d, out, reps, progress, log, to_folder):
    """Write `reps` as a new ISO `out`, or into the HostFS game folder `out` (+ its boot image)."""
    if not to_folder:
        d.img.build(out, reps, progress)
        return
    prog = progress or (lambda f, m: None)
    folder = os.path.abspath(out)
    if not d.is_folder:
        hostfs.extract(d.img, folder, lambda f, m: prog(0.8 * f, m), skip=reps)
    try:
        hostfs.write_files(folder, reps, lambda f, m: prog(0.8 + 0.18 * f, m),
                           extra_locked=[hostfs.boot_iso_path(folder, GAME)])
        boot = hostfs.write_boot_iso(folder, GAME)
    except hostfs.HostFSError as exc:
        raise KitError(str(exc))
    log("folder: %s (%s), boot image %s" % (folder, ", ".join(p.lstrip("/") for p in sorted(reps)),
                                             os.path.basename(boot)))
    hint = hostfs.boot_hint(folder, GAME)
    if hint:
        log(hint)
    prog(1.0, "done")


def _early_lock_check(d, out, to_folder):
    """Refuse before any work when the game runs from that folder (its files are in use)."""
    if not to_folder:
        return
    _check_folder(d, out)
    folder = os.path.abspath(out)
    if os.path.isdir(folder):
        img = hostfs.FolderImage(folder) if hostfs.is_game_folder(folder) else None
        try:
            hostfs.check_unlocked([hostfs.boot_iso_path(folder, GAME)] +
                                  [hostfs.host_path(folder, p, img) for p in sorted(_changed_paths(d))])
        except hostfs.HostFSError as exc:
            raise KitError(str(exc))


def build(src, out, values=None, dominator=None, log=print, progress=None, to_folder=False):
    """New image with the mod (or into the HostFS game folder `out`). values = settings dict (missing = defaults).
    Returns the values written."""
    if not to_folder:
        _check_out(src, out)
    values = settings.check(values)
    with Disc(src) as d:
        _early_lock_check(d, out, to_folder)
        for p in d.problems():
            raise KitError(p)
        if d.applied:
            raise KitError("this ISO already has the Burnout Chain mod - open it to change its settings")
        log("source: %s (%s)" % (os.path.basename(src), d.summary()))
        base = _base(d, out, to_folder)
        txd = _arrow(d, dominator, log, base)
        if not txd:
            from . import arrowart
            try:
                txd = arrowart.merge(_read(d, base, assets.GLOBAL_TXD, log))
            except Exception as exc:
                raise KitError("cannot put the arrow texture into GLOBAL.TXD (%s) - was it changed by another mod?"
                               % exc)
            log("arrow texture: ChainKit's arrow (Revenge's chevron slash repainted, made from your disc)")
        values["arrow_tex_slot"] = SLOT_DOMINATOR
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
            try:
                reps[p] = assets.add_strings(_read(d, base, p, log), lang)
            except ValueError as exc:
                raise KitError("%s: %s" % (p.lstrip("/"), exc))
        log("HUD texts: %s" % ", ".join(d.langs))
        if txd:
            reps[assets.GLOBAL_TXD] = txd
        _write(d, out, reps, progress, log, to_folder)
    log("saved %s" % out)
    return values


def tune(src, out, values, dominator=None, log=print, progress=None, to_folder=False):
    """New image = `src` (which has the mod) with other settings. Only the executable changes (and the arrow art,
    when a Dominator image is given for an image that does not have it yet). Returns the values written."""
    if not to_folder:
        _check_out(src, out)
    values = settings.check(values)
    with Disc(src) as d:
        _early_lock_check(d, out, to_folder)
        for p in d.problems():
            raise KitError(p)
        if not d.applied:
            raise KitError("this ISO does not have the Burnout Chain mod yet - save a new ISO with the mod first")
        log("source: %s (%s)" % (os.path.basename(src), d.summary()))
        reps = {}
        txd = _arrow(d, dominator, log, _base(d, out, to_folder))
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
        _write(d, out, reps, progress, log, to_folder)
    log("saved %s" % out)
    return values


def save(src, out, values=None, dominator=None, log=print, progress=None, to_folder=False):
    """build() or tune(), whichever fits the source image. to_folder: `out` is a HostFS game folder (see
    hostfs.py); a folder opened as `src` is always saved into itself."""
    with Disc(src) as d:
        applied = d.applied
        to_folder = to_folder or d.is_folder
    return (tune if applied else build)(src, out, values, dominator, log, progress, to_folder)


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
    """Check a saved image (or HostFS folder) against the image it was made from (src = out for a folder saved into
    itself: only the mod is checked). Returns True when everything is OK."""
    ok = True
    s, o = Disc(src), None
    try:
        o = Disc(out)
        if o.is_folder:
            boot = hostfs.boot_iso_path(out, GAME)
            good = os.path.isfile(boot)
            if good:
                b = iso.IsoImage(boot)
                try:
                    good = b.read_file(o.elf_path) == o.elf and b.read_file("/SYSTEM.CNF") == o.img.read_file(
                        "/SYSTEM.CNF")
                finally:
                    b.f.close()
            log("boot image %s: %s" % (os.path.basename(boot), "OK" if good else "MISSING or DIFFERENT"))
            ok &= good
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
            log("arrow texture: %s" % {"dominator": "Burnout Dominator's Boost_Arrow", "chainkit": "ChainKit's arrow",
                                       "chevron": "Revenge's chevron"}.get(art, "-"))
            if art == "chainkit":
                from . import arrowart
                good = arrowart.is_chainkit(o.img.read_file(assets.GLOBAL_TXD), s.img.read_file(assets.GLOBAL_TXD))
                if not good and o.is_folder and arrowart.is_chainkit(o.img.read_file(assets.GLOBAL_TXD)):
                    log("note: ChainKit's arrow was made from the folder's GLOBAL.TXD (changed by another mod)")
                    good = True
                log("ChainKit arrow texture: %s" % ("OK" if good else "DIFFERENT"))
                ok &= good
        if s.musickit:
            kept = s.songs == o.songs and o.musickit == s.musickit
            log("MusicKit song list: %s" % ("kept (%d songs)" % o.songs if kept else "CHANGED"))
            ok &= kept
        elif o.musickit:          # MusicKit saved into the folder after it was made from `src`
            log("MusicKit song list: %d songs (added by MusicKit, not on %s)" % (o.songs, os.path.basename(src)))
        if o.music_broken:
            log("MusicKit song list: BROKEN (MusicKit was run after ChainKit)")
            ok = False
        changed = {s.elf_path, assets.GLOBAL_TXD} | set(assets.STRING_FILES.values())
        missing = [k for k in s.img.entries if k not in o.img.entries]
        if missing:
            log("missing files: %s" % ", ".join(missing[:5]))
            ok = False
        if not quick:
            same, other = 0, []
            for k, e in s.img.entries.items():
                if k in changed or k not in o.img.entries or k.endswith("/"):
                    continue
                if e.size == o.img.entries[k].size and _sha(s.img, k) == _sha(o.img, k):
                    same += 1
                elif o.is_folder and not s.is_folder:
                    other.append(k)             # another mod's file in the folder (ChainKit never writes it)
                else:
                    other.append(k)
                    if len(other) <= 5:
                        log("changed unexpectedly: %s" % k)
            log("untouched files identical: %d (%d differ)" % (same, len(other)))
            if o.is_folder and not s.is_folder:
                songs = [k for k in other if k.startswith("/TRACKS/") and "EATRAX" in k]
                other = [k for k in other if k not in songs]
                if songs:
                    log("note: %s: MusicKit's songs" % hostfs.short_list(songs))
                if other:
                    log("note: %d file%s differ from %s but ChainKit does not manage %s (another mod's files, kept as "
                        "they are): %s" % (len(other), "" if len(other) == 1 else "s", os.path.basename(src),
                                           "it" if len(other) == 1 else "them", hostfs.short_list(other)))
            else:
                ok &= not other
        if o.is_folder and not s.is_folder:
            added = sorted(e.path for k, e in o.img.entries.items() if k not in s.img.entries)
            if added:
                log("note: %d file%s in the folder %s not on %s (another mod's or your own, kept as they are): %s"
                    % (len(added), "" if len(added) == 1 else "s", "is" if len(added) == 1 else "are",
                       os.path.basename(src), hostfs.short_list(added)))
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


# ------------------------------------------------------------------------------------------- PCSX2 cheat output
KIT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pcsx2_cheats_dirs():
    """PCSX2 cheats folders that exist on this computer (a suggestion only - ChainKit never writes there by itself)."""
    import sys
    home = os.path.expanduser("~")
    cands = []
    if sys.platform == "win32":
        docs = os.path.join(os.environ.get("USERPROFILE") or home, "Documents")
        cands += [os.path.join(docs, "PCSX2", "cheats")]
        for base in (os.environ.get("ProgramFiles", ""), os.environ.get("LOCALAPPDATA", "")):
            if base:
                cands.append(os.path.join(base, "PCSX2", "cheats"))
    elif sys.platform == "darwin":
        cands.append(os.path.join(home, "Library", "Application Support", "PCSX2", "cheats"))
    else:
        cands.append(os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "PCSX2", "cheats"))
        cands.append(os.path.join(home, ".var", "app", "net.pcsx2.PCSX2", "config", "PCSX2", "cheats"))
    return [c for c in cands if os.path.isdir(c)]


def pnach_target(src, out_dir):
    """(path, region) of the cheat file that would be written for this ISO."""
    from . import pnach
    with Disc(src) as d:
        region = d.region
    return os.path.join(out_dir, pnach.file_name(region)), region


def build_pnach(src, out_dir, values=None, force=False, check_with=(), log=print, dominator=None):
    """Write the PCSX2 cheat for the game on `src` (an ISO without the mod) into out_dir. Returns the path."""
    from . import pnach
    if not out_dir or not os.path.isdir(out_dir):
        raise KitError("folder not found: %s" % out_dir)
    values = settings.check(values)
    with Disc(src) as d:
        for p in d.problems():
            raise KitError(p)
        if d.applied:
            raise KitError("this ISO already has the Burnout Chain mod - make the cheat from your ISO without the "
                           "mod (and do not use the cheat together with a ChainKit ISO)")
        log("source: %s (%s)" % (os.path.basename(src), d.summary()))
        from . import arrowart
        gtxd = d.img.read_file(assets.GLOBAL_TXD)
        if dominator:
            try:
                blob = pnach.arrow_blob(gtxd, dominator_txd(dominator))
            except ValueError as exc:
                raise KitError("the Dominator arrow texture does not fit (%s)" % exc)
        else:
            blob = pnach.arrow_blob_record(arrowart.chainkit_record(gtxd))
        if d.musickit and d.songs > 95:
            raise KitError("this ISO has more than 95 MusicKit songs: no room for the arrow texture")
        try:
            text, region = pnach.render(d.elf, values, settings.preset_of(values), blob,
                                        art="dominator" if dominator else "chainkit")
        except elfpatch.ChainError as exc:
            raise KitError(str(exc))
    path = os.path.join(out_dir, pnach.file_name(region))
    if os.path.exists(path) and not force:
        raise KitError("%s exists already - choose to replace it (--force) or another folder" % path)
    for other in check_with or ():
        with open(other, encoding="utf-8", errors="replace") as f:
            hits = pnach.overlaps(text, f.read())
        log("overlap check with %s: %s" % (os.path.basename(other), "none" if not hits else
                                           "%d address(es) also written there, e.g. %#x" % (len(hits), hits[0][0][0])))
        if hits:
            raise KitError("the cheat would write memory that %s also writes" % os.path.basename(other))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    n = text.count("\npatch=")
    log("PCSX2 cheat: %s (%d memory writes, arrows: %s, English pop-up texts)" % (
        path, n, "Burnout Dominator's arrow - personal use only, do not share the file" if dominator
        else "ChainKit's arrow (made from your disc - personal use, do not share the file)"))
    return path
