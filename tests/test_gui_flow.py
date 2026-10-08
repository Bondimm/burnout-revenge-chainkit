"""GUI flow test without a window: drives the ChainKit window's logic (ChainKitGui) the way its buttons, file
dialogs and drag-and-drop do - select the ISO, pick the Dominator ISO, choose a preset, change settings, save a
settings file, save the new ISO (the real background job, incl. the check), reopen it, change its settings, save
again, reopen.

Writes two disc images of ~4 GB (one at a time) into pytest's temp folder (choose it with --basetemp) and only
reads your ISOs. Runs only with CHAINKIT_FULL_TEST=1 and CHAINKIT_ISO set (CHAINKIT_DOMINATOR is optional):

    set CHAINKIT_FULL_TEST=1
    set CHAINKIT_ISO=D:\\path\\to\\Burnout Revenge.iso
    set CHAINKIT_DOMINATOR=D:\\path\\to\\Burnout Dominator.iso
    .venv\\Scripts\\python -m pytest tests\\test_gui_flow.py -v
(macOS: export ... and .venv/bin/python)
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from chainkit import core, gui, settings  # noqa: E402

ISO = os.environ.get("CHAINKIT_ISO", "")
DOM = os.environ.get("CHAINKIT_DOMINATOR", "")
pytestmark = pytest.mark.skipif(not (os.environ.get("CHAINKIT_FULL_TEST") and ISO and os.path.exists(ISO)),
                                reason="set CHAINKIT_FULL_TEST=1 and CHAINKIT_ISO")


def _wait(g, timeout=3600):
    t = time.time()
    while g.busy():
        assert time.time() - t < timeout, "job '%s' did not finish" % g.job.title
        time.sleep(0.2)
    return g.job


def test_gui_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAINKIT_HOME", str(tmp_path / "home"))
    log = gui.Log(os.path.join(gui.app_dir(), "gui.log"))
    g = gui.ChainKitGui(log, {})
    out1, out2 = str(tmp_path / "flow step1.iso"), str(tmp_path / "flow step2.iso")
    try:
        # ---- nothing selected: Save disabled, pressing it only logs why
        assert g.save_problem() and g.disc is None
        g.build()
        assert g.job is None and log.errors()

        # ---- 1) select the ISO (drag and drop does the same as Browse...)
        g.drop([ISO])
        assert _wait(g).ok and g.disc is not None and not g.disc.applied, log.errors()[-3:]
        assert g.out_path == core.default_output(ISO) and g.values == settings.DEFAULTS
        assert g.save_problem() is None                       # a new ISO with the defaults can be saved at once

        # ---- 2) the Dominator ISO (optional): a Revenge ISO is refused there
        g.set_dominator(ISO)
        assert not _wait(g).ok and not g.dom_ok and "Burnout Revenge image" in g.dom_error
        assert "Dominator ISO cannot be used" in g.save_problem()
        g.set_dominator(DOM)
        if DOM:
            assert _wait(g).ok and g.dom_ok
        assert g.save_problem() is None

        # ---- settings: preset, single changes, mode switch, colour; save them to a file
        g.apply_preset("Easy")
        g.set_value("fill_w_drift", 0.5)
        g.set_bit("modes", settings.MODES["traffic_attack"], False)
        g.set_bit("flags", settings.FLAGS["show_size_label"], True)
        g.set_value("lit_rgba", (1.0, 0.5, 0.0, 1.0))
        wanted = dict(g.values)
        sfile = str(tmp_path / "my settings.json")
        assert g.export_settings(sfile)

        # ---- remembered for the next start of the window
        g.save_settings()
        saved = json.load(open(os.path.join(gui.app_dir(), "settings.json"), encoding="utf-8"))
        g2 = gui.ChainKitGui(log, saved)
        _wait(g2)
        assert not settings.changed(g2.values, wanted) and g2.iso_path == ISO and g2.out_path == g.out_path
        _wait(g2)

        # ---- 3) save: the output must be a new file
        g.out_path = ISO
        assert "different file" in g.save_problem()
        g.out_path = str(tmp_path / "no such folder" / "x.iso")
        assert "folder" in g.save_problem()
        g.out_path = out1
        g.build()
        assert g.busy() and g.save_problem()                  # Save disabled while saving
        n_err = len(log.errors())
        g.load_disc(out2)                                     # opening another ISO meanwhile is refused
        assert len(log.errors()) > n_err
        assert _wait(g).ok, log.errors()[-5:]
        assert g.last_save["ok"] and g.last_save["out"] == out1

        # ---- reopen the saved ISO: the mod and these settings are found, nothing to save yet
        g.open_saved()
        assert _wait(g).ok and g.disc.applied and g.disc.path == out1
        assert not settings.changed(g.values, dict(wanted, arrow_tex_slot=28 if DOM else 12))
        assert g.disc.arrow_art == ("dominator" if DOM else "chevron")
        assert "already has the mod" in g.save_problem()
        assert g.out_path != out1

        # ---- change settings of the modded ISO (tune) and save again
        g.reset_defaults()
        g.import_settings(sfile)                              # the settings file gives the same values back
        assert not g.changed_settings()
        g.apply_preset("Hard")
        g.set_bit("modes", settings.MODES["road_rage"], False)
        wanted2 = dict(g.values)
        assert g.changed_settings()
        g.out_path = out2
        assert g.save_problem() is None
        g.build()
        assert _wait(g).ok, log.errors()[-5:]
        assert core.validate(out1, out2, DOM or None, log=lambda *a: None, quick=True)
        g.open_saved()
        assert _wait(g).ok and g.disc.path == out2
        assert not settings.changed(g.values, wanted2) and not g.changed_settings()
        assert g.disc.arrow_art == ("dominator" if DOM else "chevron")
    finally:
        if log.file:
            log.file.close()
        for p in (out1, out2):
            if os.path.exists(p):
                os.remove(p)
