"""Re-create the README screenshots (docs/images/chainkit_*.png) from the demo files next to this script.
The demo files describe a pretend disc, so no game file is needed and no personal path appears.

    .venv/Scripts/python docs/screenshots/make_screenshots.py      (macOS: .venv/bin/python ...)
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SHOTS = {"main": "chainkit_main.png", "saved": "chainkit_saved.png", "tune": "chainkit_tune.png"}

for name, png in SHOTS.items():
    out = os.path.join(ROOT, "docs", "images", png)
    env = dict(os.environ, CHAINKIT_HOME=os.path.join(HERE, ".home"))
    subprocess.run([sys.executable, "-m", "chainkit", "gui", "--shot", out, "--demo",
                    os.path.join(HERE, name + ".json"), "--size", "1400x860"], cwd=ROOT, env=env, check=True)
    print("wrote", out)
