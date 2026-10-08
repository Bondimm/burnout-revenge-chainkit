"""Settings: defaults, presets, checks, human units, settings files, command line (no game files needed)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from chainkit import cave, cli, settings  # noqa: E402


def test_every_setting_is_in_the_window_or_set_automatically():
    shown = {it.key for it in settings.ITEMS}
    assert set(settings.DEFAULTS) - shown == {"arrow_tex_slot"}
    assert settings.HIDDEN == ["arrow_tex_slot"]
    for it in settings.ITEMS:
        assert it.label and (it.help or it.key.startswith("w_")), it.key
    flags = [it.bit for it in settings.ITEMS if it.kind == "flag"]
    assert sorted(flags) == sorted(settings.FLAGS.values()) and sum(flags) == settings.ALL_FLAGS
    modes = [it.bit for it in settings.ITEMS if it.kind == "mode"]
    assert sum(modes) == settings.ALL_MODES == 0xFF == settings.DEFAULTS["modes"]


def test_defaults_and_presets_are_valid():
    assert settings.check({}) == settings.DEFAULTS
    for name, v in settings.PRESETS.items():
        assert settings.check(v) == v, name
        assert settings.preset_of(v) == name
        assert name in settings.PRESET_INFO
    assert settings.preset_of(settings.DEFAULTS) == "Default (tested)"
    assert settings.PRESETS["Dominator rules"]["flags"] & cave.FL_NOEARN
    assert not settings.PRESETS["Easy"]["flags"] & cave.FL_SLOW


def test_default_flags_match_the_tested_build():
    d = settings.DEFAULTS
    assert d["flags"] == 0x5F and d["fill_mult"] == 1.15 and d["full_threshold"] == 0.98
    for name in ("show_size_label", "show_boost_hint", "no_earn_while_boosting"):
        assert not d["flags"] & settings.FLAGS[name]


@pytest.mark.parametrize("bad,msg", [({"nope": 1}, "unknown"), ({"drain_mult": -1}, "outside"),
                                     ({"half": 2.0}, "outside"), ({"wow_chain": 2.5}, "whole number"),
                                     ({"lit_rgba": "1,2,3"}, "colour"), ({"fill_mult": float("nan")}, "number"),
                                     ({"modes": 0x1FF}, "outside"), ({"arrow_tex_slot": 13}, "arrow_tex_slot")])
def test_bad_values_are_explained(bad, msg):
    with pytest.raises(ValueError, match=msg):
        settings.check(bad)


def test_colour_strings_and_lists():
    v = settings.check({"lit_rgba": "0.2, 0.9, 1, 1", "dark_rgba": [0, 0, 0, 0.5]})
    assert v["lit_rgba"] == (0.2, 0.9, 1.0, 1.0) and v["dark_rgba"] == (0.0, 0.0, 0.0, 0.5)


def test_settings_file_round_trip(tmp_path):
    v = dict(settings.PRESETS["Hard"], fill_w_drift=0.123, lit_rgba=(0.5, 0.25, 1.0, 1.0), modes=0x7F)
    p = tmp_path / "s.json"
    settings.save(str(p), v)
    obj = json.loads(p.read_text())
    assert obj["kit"] == "ChainKit" and "arrow_tex_slot" not in obj["settings"]
    back = settings.load(str(p))
    assert not settings.changed(back, settings.check(v))
    # a plain {name: value} dict is accepted too
    p.write_text(json.dumps({"fill_mult": 2.0}))
    assert settings.load(str(p))["fill_mult"] == 2.0
    p.write_text(json.dumps({"kit": "MusicKit", "settings": {}}))
    with pytest.raises(ValueError, match="MusicKit"):
        settings.load(str(p))
    p.write_text("not json")
    with pytest.raises(ValueError, match="not a settings file"):
        settings.load(str(p))


def test_human_units_round_trip():
    for it in settings.ITEMS:
        if it.unit and it.kind == "float":
            raw = settings.DEFAULTS[it.key]
            assert it.unit.from_ui(it.unit.to_ui(raw)) == pytest.approx(raw, rel=1e-9), it.key
            lo = it.unit.from_ui(it.unit.lo)
            hi = it.unit.from_ui(it.unit.hi)
            settings.check({it.key: lo}); settings.check({it.key: hi})          # slider ends are valid values


def test_human_units_say_what_the_tests_measured():
    s = settings.fill_seconds(settings.DEFAULTS)
    assert s["oncoming"] == pytest.approx(5.0, rel=0.05) and s["drift"] == pytest.approx(4.0, rel=0.05)
    items = {it.key: it for it in settings.ITEMS}
    assert settings.shown(items["w_near_miss"], settings.DEFAULTS) == "2.9"            # ~3 near misses
    assert settings.shown(items["w_oncoming"], settings.DEFAULTS) == "4.8 s"
    assert settings.shown(items["arrows_slam"], settings.DEFAULTS) == "6.0"
    assert settings.shown(items["slow_speed"], settings.DEFAULTS) == "97 km/h"
    assert settings.shown(items["fill_mult"], settings.DEFAULTS) == "115 %"


def test_cli_lists_and_exports(tmp_path, capsys):
    assert cli.main(["settings"]) == 0
    out = capsys.readouterr().out
    assert "Race and Grand Prix" in out and "fill_w_oncoming" in out
    assert cli.main(["settings", "--raw"]) == 0
    assert "arrow_gain" in capsys.readouterr().out
    assert cli.main(["presets"]) == 0
    assert "Dominator rules" in capsys.readouterr().out
    p = tmp_path / "easy.json"
    assert cli.main(["export", "--preset", "Easy", str(p)]) == 0
    assert settings.preset_of(settings.load(str(p))) == "Easy"
    assert cli.main(["export", "--preset", "Nope", str(p)]) == 2
    assert cli.main(["build", "--iso", str(tmp_path / "missing.iso")]) == 2
    assert "not found" in capsys.readouterr().err


def test_cli_set_parsing():
    assert cli._parse_set(["fill_mult=2", "modes=0x7f", "lit_rgba=0.1,0.2,0.3,1"]) == {
        "fill_mult": 2.0, "modes": 0x7F, "lit_rgba": "0.1,0.2,0.3,1"}
    with pytest.raises(Exception, match="unknown"):
        cli._parse_set(["nope=1"])
    with pytest.raises(Exception, match="not a number"):
        cli._parse_set(["fill_mult=fast"])
