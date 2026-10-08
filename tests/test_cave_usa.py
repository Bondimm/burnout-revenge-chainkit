"""Every cave-code test again, with the code and the fake game memory built for the USA executable (SLUS_212.42).

test_cave.py / test_cave_settings.py are loaded a second time with REGION_KEY = "USA"; their tests appear here with
the suffix _usa.
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


_core = _load("test_cave__usa", "test_cave.py", REGION_KEY="USA")
_settings = _load("test_cave_settings__usa", "test_cave_settings.py", BASE_MODULE=_core)
assert _core.REGION["key"] == "USA" and _settings.LAY.region["key"] == "USA"

for _mod in (_core, _settings):
    for _name, _fn in list(vars(_mod).items()):
        if _name.startswith("test_") and callable(_fn):
            globals()[_name + "_usa"] = _fn
