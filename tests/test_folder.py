"""HostFS folder output with your own disc images (CHAINKIT_ISO_PAL / CHAINKIT_ISO_USA / CHAINKIT_ISO; skipped
without). The quick tests copy only the files ChainKit reads and writes into pytest's temp folder; the end-to-end
test extracts the whole disc (~2.5 GB per ISO, one at a time) and runs only with CHAINKIT_FULL_TEST=1.
"""
import os
import shutil
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from chainkit import arrowart, assets, core, elfpatch, hostfs, iso, settings  # noqa: E402

ISOS = [p for p in (os.environ.get(v, "") for v in ("CHAINKIT_ISO_PAL", "CHAINKIT_ISO_USA", "CHAINKIT_ISO"))
        if p and os.path.exists(p)]
ISOS = list(dict.fromkeys(os.path.abspath(p) for p in ISOS))
quiet = lambda *a: None   # noqa: E731
needs_iso = pytest.mark.skipif(not ISOS, reason="set CHAINKIT_ISO_PAL and/or CHAINKIT_ISO_USA")


@pytest.fixture(autouse=True)
def _mini_folders_ok(request, monkeypatch):
    """The quick tests use folders with only the files the kit reads: skip the check for a complete game folder."""
    if not request.node.name.startswith(("test_folder_end_to_end", "test_gui_folder_flow")):
        monkeypatch.setattr(core, "REQUIRED", {})


def _mini_folder(src, folder):
    """A game folder with only the files ChainKit reads and writes, copied from the disc image `src`."""
    img = iso.IsoImage(src)
    try:
        elf = core.boot_elf(img)
        for p in ["/SYSTEM.CNF", elf, assets.GLOBAL_TXD] + [v for v in assets.STRING_FILES.values()
                                                            if v in img.entries]:
            e = img.entries[p]
            target = hostfs.host_path(folder, e.path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(img.read_file(p))
    finally:
        img.f.close()
    return folder


@needs_iso
@pytest.mark.parametrize("src", ISOS)
def test_mod_saved_into_a_folder(src, tmp_path):
    folder = _mini_folder(src, str(tmp_path / "game"))
    with core.Disc(src) as d, core.Disc(folder) as f:
        assert f.is_folder and not d.is_folder and f.crc == d.crc and not f.applied
        assert f.langs == d.langs and f.elf == d.elf
        txd0 = d.img.read_file(assets.GLOBAL_TXD)
        strings0 = {l: d.img.read_file(assets.STRING_FILES[l]) for l in d.langs}
        values = settings.check(None)
        values["arrow_tex_slot"] = core.SLOT_DOMINATOR
        want_elf = elfpatch.patch(d.elf, values)[0]
    core.save(folder, folder, None, None, quiet, to_folder=True)       # a folder source is saved into itself
    with core.Disc(folder) as f:
        assert f.applied and f.crc == regions_crc(f) and f.arrow_art == "chainkit"
        assert f.elf == want_elf
        assert f.img.read_file(assets.GLOBAL_TXD) == arrowart.merge(txd0)
        for l, data in strings0.items():
            assert f.img.read_file(assets.STRING_FILES[l]) == assets.add_strings(data, l)
        steps = "\n".join(f.hostfs_steps())
        assert hostfs.pnach_name(f.elf_path, f.crc) in steps and core.NAHELAM_DIR in steps
    assert core.validate(folder, folder, log=quiet, quick=True)
    boot = hostfs.boot_iso_path(folder, core.GAME)
    b = iso.IsoImage(boot)
    try:
        assert os.path.basename(boot) == "Burnout Revenge (HostFS).iso"
        assert b.read_file(core.boot_elf(b)) == want_elf
    finally:
        b.f.close()
    # change a setting in place (tune), the arrow art stays
    values = settings.check(None)
    name = next(k for k in settings.TYPES if settings.TYPES[k] == "f")
    values[name] = values[name] * 2 + 1
    core.save(folder, folder, values, None, quiet)
    with core.Disc(folder) as f:
        assert f.values[name] == pytest.approx(values[name]) and f.arrow_art == "chainkit"
    assert core.validate(folder, folder, log=quiet, quick=True)
    with pytest.raises(core.KitError, match="into itself"):
        core.save(folder, str(tmp_path / "other"), values, None, quiet, to_folder=True)


def regions_crc(d):
    return d.region["crc"]


@needs_iso
def test_folder_checks_and_locks(tmp_path):
    src = ISOS[0]
    assert core.folder_plan(src, str(tmp_path / "new"))["has_game"] is False
    other = tmp_path / "other"
    other.mkdir()
    (other / "notes.txt").write_text("x")
    with pytest.raises(core.KitError, match="other files"):
        core.folder_plan(src, str(other))
    wrong = tmp_path / "wrong"
    wrong.mkdir()
    (wrong / "SYSTEM.CNF").write_bytes(b"BOOT2 = cdrom0:\\SLUS_999.99;1\r\n")
    with pytest.raises(core.KitError, match="another game"):
        core.folder_plan(src, str(wrong))
    folder = _mini_folder(src, str(tmp_path / "game"))
    plan = core.folder_plan(src, folder)
    assert plan["has_game"] and plan["extract_bytes"] > 0
    with core.Disc(folder) as f:
        elf_host = f.img.entries[f.elf_path].host
    core.save(folder, folder, None, None, quiet)                        # now the folder has the mod
    with pytest.raises(core.KitError, match="already has changes"):
        core.save(src, folder, None, None, quiet, to_folder=True)      # an ISO never overwrites it
    with pytest.raises(core.KitError, match="already has changes"):
        core.folder_plan(src, folder)
    if os.name == "nt":                                                 # the game running: refused, nothing written
        t0 = os.path.getmtime(elf_host)
        with open(hostfs.boot_iso_path(folder, core.GAME), "rb"):
            values = settings.check(None)
            values["arrow_tex_slot"] = core.SLOT_DOMINATOR
            name = next(k for k in settings.TYPES if settings.TYPES[k] == "f")
            values[name] = values[name] * 3 + 1
            with pytest.raises(core.KitError, match="PCSX2"):
                core.save(folder, folder, values, None, quiet)
        assert os.path.getmtime(elf_host) == t0


@pytest.mark.skipif(not (ISOS and os.environ.get("CHAINKIT_FULL_TEST")), reason="set CHAINKIT_FULL_TEST=1 and an ISO")
def test_folder_end_to_end(tmp_path):
    """ISO -> new folder (whole disc extracted), checked against the ISO; settings changed in the folder."""
    for src in ISOS:
        folder = str(tmp_path / ("game " + os.path.basename(src)))
        try:
            t = time.time()
            core.save(src, folder, None, None, quiet, to_folder=True)
            first = time.time() - t
            assert core.validate(src, folder, log=quiet)
            # other mods in the folder: a replaced file and an added file - notes only, kept by every save
            with core.Disc(src) as d:
                replaced = min((k for k in d.img.entries if k not in core._changed_paths(d)
                                and d.img.entries[k].size > 4096), key=lambda k: d.img.entries[k].size)
            hostfs.write_files(folder, {replaced: b"replaced by another mod", "/MODS/CAR.DAT": b"added"})
            lines = []
            assert core.validate(src, folder, log=lines.append)
            assert any(x.startswith("note:") and replaced.lstrip("/") in x for x in lines)
            assert any(x.startswith("note:") and "MODS/CAR.DAT" in x for x in lines)
            with core.Disc(folder) as f:
                assert f.applied
                values = dict(f.values)
            name = next(k for k in settings.TYPES if settings.TYPES[k] == "f")
            values[name] = values[name] + 1
            t = time.time()
            core.save(folder, folder, values, None, quiet)
            assert time.time() - t < first
            assert core.validate(src, folder, log=quiet)
            with core.Disc(folder) as f:
                assert f.values[name] == pytest.approx(values[name])
                assert f.img.read_file(replaced) == b"replaced by another mod"
                assert f.img.read_file("/MODS/CAR.DAT") == b"added"
        finally:
            shutil.rmtree(folder, ignore_errors=True)


@pytest.mark.skipif(not (ISOS and os.environ.get("CHAINKIT_FULL_TEST")), reason="set CHAINKIT_FULL_TEST=1 and an ISO")
def test_gui_folder_flow(tmp_path, monkeypatch):
    """The window's logic: ISO -> "Folder for PCSX2 HostFS" -> save (+ check) -> open the folder -> change a setting
    -> save into it."""
    from chainkit import gui
    monkeypatch.setenv("CHAINKIT_HOME", str(tmp_path / "home"))
    log = gui.Log(os.path.join(gui.app_dir(), "gui.log"))
    g = gui.ChainKitGui(log, {})
    g.save_settings = lambda: None
    folder = str(tmp_path / "game")

    def wait():
        t = time.time()
        while g.busy():
            assert time.time() - t < 3600
            time.sleep(0.2)
        return g.job

    try:
        g.drop([ISOS[0]])
        assert wait().ok and g.disc is not None and not g.disc.applied
        assert g.folder_path == core.default_folder(ISOS[0]) and not g.to_folder()
        g.output_type = "folder"
        g.set_folder(folder)
        assert g.to_folder() and g.save_problem() is None
        assert g.folder_info()["plan"]["extract_bytes"] > 0
        g.save()
        assert wait().ok, log.errors()[-5:]
        assert g.last_save["ok"] and g.last_save["folder"] and os.path.abspath(g.last_save["out"]) == folder
        assert "already has changes" in g.folder_info()["problem"]      # the ISO cannot go there again
        g.open_saved()
        assert wait().ok and g.disc.is_folder and g.disc.applied and g.to_folder()
        assert "change a setting" in g.save_problem()
        name = next(k for k in settings.TYPES if settings.TYPES[k] == "f")
        g.set_value(name, g.values[name] + 1)
        assert g.save_problem() is None
        g.save()
        assert wait().ok, log.errors()[-5:]
        assert g.disc.is_folder and g.disc.values[name] == pytest.approx(g.values[name])
        assert "change a setting" in g.save_problem()
    finally:
        if log.file:
            log.file.close()
        shutil.rmtree(folder, ignore_errors=True)


@needs_iso
def test_other_mods_in_the_folder(tmp_path, monkeypatch):
    """An ISO saved into a folder that already has the game: another mod's texts and textures there are kept (the mod
    is added on top, as when the folder is opened); a changed executable makes it refuse."""
    from chainkit import strtable
    src = ISOS[0]
    folder = _mini_folder(src, str(tmp_path / "game"))
    monkeypatch.setattr(hostfs, "extract", lambda *a, **k: 0)          # the quick test has no whole game folder
    with core.Disc(src) as d:
        p = assets.STRING_FILES[d.langs[0]]
        t = strtable.StringTable(d.img.read_file(p))
        h = sorted(t.entries)[0]
        t.entries[h] = "Text Mod"
        txd = bytearray(d.img.read_file(assets.GLOBAL_TXD))
        ro, rs = assets.txd_records(bytes(txd))[assets.TARGET]
        mod_at = 0x40 if not ro <= 0x40 < ro + rs else ro + rs        # a byte outside the arrow's texture
        txd[mod_at] ^= 0xFF
        elf0 = d.elf
    hostfs.write_files(folder, {p: t.build(), assets.GLOBAL_TXD: bytes(txd), "/MODS/EXTRA.DAT": b"x"})
    logs = []
    core.save(src, folder, None, None, logs.append, to_folder=True)
    with core.Disc(folder) as f:
        assert f.applied and f.arrow_art == "chainkit"
        texts = strtable.StringTable(f.img.read_file(p))
        assert texts.entries[h] == "Text Mod" and assets.strings_present(f.img.read_file(p), d.langs[0])
        assert f.img.read_file(assets.GLOBAL_TXD)[mod_at] == txd[mod_at]
        assert f.img.read_file("/MODS/EXTRA.DAT") == b"x"
    assert any("kept another mod's changes" in m for m in logs)
    with pytest.raises(core.KitError, match="already has changes"):     # now the executable has ChainKit
        core.save(src, folder, None, None, quiet, to_folder=True)
    values = settings.check(None)
    name = next(k for k in settings.TYPES if settings.TYPES[k] == "f")
    values[name] = values[name] * 2 + 1
    core.save(folder, folder, values, None, quiet)                     # the folder saved into itself keeps them too
    with core.Disc(folder) as f:
        assert strtable.StringTable(f.img.read_file(p)).entries[h] == "Text Mod"
        assert f.img.read_file(assets.GLOBAL_TXD)[mod_at] == txd[mod_at]
    # another tool's change in the executable: the ISO is refused, with the way forward
    hostfs.write_files(folder, {core.boot_elf(hostfs.FolderImage(folder)): elf0[:-4] + b"\1\2\3\4"})
    with pytest.raises(core.KitError, match="open this folder in step 1"):
        core.save(src, folder, None, None, quiet, to_folder=True)


@needs_iso
def test_folders_made_by_other_tools(tmp_path):
    """Lower-case names, the user's own ISO next to the files (Nahelam's guide), the game one level down, version
    numbers in names, an incomplete extraction."""
    src = ISOS[0]
    folder = _mini_folder(src, str(tmp_path / "game"))
    for root, dirs, files in os.walk(folder, topdown=False):             # lower-case names, as some extractors do
        for n in files + dirs:
            os.rename(os.path.join(root, n), os.path.join(root, n.lower()))
    with open(os.path.join(folder, "Burnout Revenge (Europe).iso"), "wb") as f:
        f.write(b"\0" * 4096)
    logs = []
    core.save(folder, folder, None, None, logs.append, to_folder=True)
    with core.Disc(folder) as f:
        assert f.applied
    names = [n for _, ds, fs in os.walk(folder) for n in ds + fs]
    assert not [n for n in names if n != n.lower() and not n.endswith(".iso")]          # no second copies
    assert any("Burnout Revenge (Europe).iso" in m and "(HostFS).iso" in m for m in logs)
    with pytest.raises(core.KitError, match="subfolder"):
        core.folder_plan(src, str(tmp_path))
    os.rename(os.path.join(folder, "system.cnf"), os.path.join(folder, "system.cnf;1"))
    with pytest.raises(core.KitError, match="version number"):
        core.Disc(folder)
    with pytest.raises(core.KitError, match="version number"):
        core.folder_plan(src, folder)


@needs_iso
def test_incomplete_folder(tmp_path, monkeypatch):
    folder = _mini_folder(ISOS[0], str(tmp_path / "game"))
    monkeypatch.setattr(core, "REQUIRED", {"TRACKS": 5, "/IOP/GTFSHOST.IRX": 1})
    with pytest.raises(core.KitError, match="incompletely extracted") as e:
        core.Disc(folder)
    assert "TRACKS (missing)" in str(e.value) and "IOP/GTFSHOST.IRX" in str(e.value)
