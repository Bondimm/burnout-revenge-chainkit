"""Every cave-code test again with the PCSX2-cheat build (pop-up texts from the cave), for PAL and USA.

The cheat's memory image equals this build exactly (tests/test_pnach.py checks that against your executable).
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _load(name, filename, **inject):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    mod.__dict__.update(inject)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


for _key, _tex in (("PAL", True), ("USA", False)):      # PAL with Dominator art copied from the cave, USA without
    _core = _load("test_cave__cheat_" + _key, "test_cave.py", REGION_KEY=_key, INLINE=True, TEXCOPY=_tex)
    _settings = _load("test_cave_settings__cheat_" + _key, "test_cave_settings.py", BASE_MODULE=_core)
    assert _core.LAY.inline and _core.REGION["key"] == _key
    for _mod in (_core, _settings):
        for _name, _fn in list(vars(_mod).items()):
            if _name.startswith("test_") and callable(_fn):
                globals()["%s_cheat_%s" % (_name, _key.lower())] = _fn
