"""Window logic without a window and without game files: presets, settings changes, settings files, the reasons
shown next to "Save new ISO", drag and drop of settings files, the remembered state."""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from chainkit import gui, settings  # noqa: E402


@pytest.fixture
def g(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAINKIT_HOME", str(tmp_path / "home"))
    log = gui.Log(os.path.join(gui.app_dir(), "gui.log"))
    yield gui.ChainKitGui(log, {})
    if log.file:
        log.file.close()


def wait(g):
    t = time.time()
    while g.busy():
        assert time.time() - t < 60
        time.sleep(0.05)
    return g.job


def test_nothing_selected(g):
    assert g.disc is None and "select your Burnout Revenge ISO" in g.save_problem()
    g.build()
    assert g.job is None and g.log.errors()


def test_missing_and_bogus_iso(g, tmp_path):
    g.load_disc(str(tmp_path / "missing.iso"))
    assert g.disc is None and g.disc_error == "ISO not found"
    bogus = tmp_path / "bogus.iso"
    bogus.write_bytes(b"\0" * (64 << 10))
    g.drop([str(bogus)])
    assert not wait(g).ok and g.disc is None and "not a PS2 DVD image" in g.disc_error
    assert g.log.errors()


def test_dominator_checks(g, tmp_path):
    g.set_dominator(str(tmp_path / "nope.iso"))
    assert not g.dom_ok and g.dom_error == "file not found"
    g.set_dominator("")
    assert not g.dom_ok and g.dom_path == "" and g.dom_error is None


def test_presets_reset_and_values(g):
    g.apply_preset("Easy")
    assert settings.preset_of(g.values) == "Easy"
    g.set_value("fill_mult", 99.0)                       # clamped to the allowed range
    assert g.values["fill_mult"] == settings.LIMITS["fill_mult"][1] and settings.preset_of(g.values) is None
    g.set_bit("modes", settings.MODES["traffic_attack"], False)
    assert not g.values["modes"] & settings.MODES["traffic_attack"]
    g.set_bit("flags", settings.FLAGS["show_boost_hint"], True)
    assert g.values["flags"] & settings.FLAGS["show_boost_hint"]
    g.set_value("lit_rgba", (1.0, 0.0, 0.5, 1.0))
    assert g.values["lit_rgba"] == (1.0, 0.0, 0.5, 1.0)
    assert len(g.changed_settings()) >= 4
    g.reset_defaults()
    assert g.values == settings.DEFAULTS and not g.changed_settings()


def test_settings_files_and_drop(g, tmp_path):
    g.apply_preset("Hard")
    g.set_value("w_drift", 0.01)
    p = str(tmp_path / "mine")
    assert g.export_settings(p) and os.path.exists(p + ".json")
    g.reset_defaults()
    g.drop([p + ".json"])
    assert g.values["w_drift"] == settings.f32(0.01) or g.values["w_drift"] == 0.01
    assert g.values["drain_mult"] == settings.PRESETS["Hard"]["drain_mult"]
    bad = tmp_path / "bad.json"
    bad.write_text("{\"drain_mult\": -5}")
    n = len(g.log.errors())
    assert not g.import_settings(str(bad)) and len(g.log.errors()) > n
    g.drop([str(tmp_path / "song.mp3")])
    assert len(g.log.errors()) > n + 1


def test_state_is_remembered(g):
    g.apply_preset("Dominator rules")
    g.iso_path, g.dom_path, g.out_path = "", "", "x.iso"
    g.open_groups = {"Arrows (while supercharge-boosting)"}
    g.save_settings()
    saved = json.load(open(os.path.join(gui.app_dir(), "settings.json"), encoding="utf-8"))
    g2 = gui.ChainKitGui(g.log, saved)
    assert settings.preset_of(g2.values) == "Dominator rules" and g2.out_path == "x.iso"
    assert g2.open_groups == {"Arrows (while supercharge-boosting)"}
    g3 = gui.ChainKitGui(g.log, {"values": {"drain_mult": "broken"}})       # a damaged file: defaults
    assert g3.values == settings.DEFAULTS


def test_demo_mode_reads_no_file(g):
    d = gui.ChainKitGui(g.log, {"demo": {"disc": {
        "path": "Burnout Revenge (Europe).iso", "summary": "Burnout Revenge Europe", "applied": True,
        "values": settings.to_json(settings.DEFAULTS)["settings"], "problems": [], "arrow_art": "dominator",
        "musickit": False, "carkit": False, "songs": 41, "crc": 0x7E83CC5B, "langs": ["UK"]}},
        "out": "Burnout Revenge (Europe) (Burnout Chain settings).iso"})
    assert d.disc.applied and d.job is None
    assert "already has the mod with these settings" in d.save_problem()
    d.set_value("drain_mult", 2.0)
    assert d.changed_settings() == ["drain_mult"] and d.save_problem() is None


def test_app_dir_per_platform(monkeypatch, tmp_path):
    monkeypatch.delenv("CHAINKIT_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    d = gui.app_dir()
    if os.name == "nt":
        assert d == str(tmp_path / "appdata" / "chainkit")
    elif sys.platform == "darwin":
        assert d.endswith(os.path.join("Library", "Application Support", "chainkit"))
    else:
        assert d == str(tmp_path / "xdg" / "chainkit")
    assert os.path.isdir(d)


def test_pnach_output_choice(g, tmp_path):
    from chainkit import core, regions
    d = gui.ChainKitGui(g.log, {"demo": {"disc": {
        "path": "Burnout Revenge (Europe).iso", "summary": "Burnout Revenge Europe", "applied": False,
        "values": None, "problems": [], "arrow_art": None, "musickit": False, "carkit": False, "songs": 41,
        "crc": 0x7E83CC5B, "langs": ["UK"], "region": regions.PAL}}})
    assert d.output_type == "iso" and d.pnach_dir == core.KIT_DIR
    d.output_type = "pnach"
    d.set_pnach_dir(str(tmp_path / "missing"))
    assert "folder" in d.save_problem()
    d.set_pnach_dir(str(tmp_path))
    assert d.save_problem() is None and d.pnach_path().endswith("SLES-53507_7E83CC5B_chainkit.pnach")
    open(d.pnach_path(), "w").write("[Single Event Mod]\n")
    assert "Replace it" in d.save_problem()                          # never overwrite without asking
    d.pnach_replace = True
    assert d.save_problem() is None
    d.disc.applied = True
    assert "without the mod" in d.save_problem()
    d.save_settings()
    saved = json.load(open(os.path.join(gui.app_dir(), "settings.json"), encoding="utf-8"))
    assert saved["output_type"] == "pnach" and saved["pnach_dir"] == str(tmp_path)


def test_pnach_check_command(tmp_path, capsys):
    from chainkit import cli
    a, b = tmp_path / "a.pnach", tmp_path / "b.pnach"
    a.write_text("[X]\npatch=0,EE,204A5000,extended,00000001\n")
    b.write_text("[Y]\npatch=0,EE,200B5000,extended,00000001\n")
    assert cli.main(["pnach-check", str(a), "--with", str(b)]) == 0
    b.write_text("[Y]\npatch=0,EE,204A5000,extended,00000002\n")
    assert cli.main(["pnach-check", str(a), "--with", str(b)]) == 1
    assert "also written by [Y]" in capsys.readouterr().out
