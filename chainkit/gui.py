"""ChainKit window: 1) select the Burnout Revenge ISO, 2) optional: your Burnout Dominator ISO for the arrow art,
3) save a new ISO. The settings panel on the right changes every rule of the mod; an ISO that already has the mod
opens with its own settings, which can be changed and saved again without starting over.

Launch: ChainKit.bat (Windows) / ChainKit.command (macOS) in the project folder, or `python -m chainkit gui`.
GLFW + OpenGL 3.3 core + Dear ImGui (imgui-bundle). Long operations run on a worker thread; messages go to the
log panel and to gui.log in the settings folder (app_dir). Your ISOs are only read; the result is always a new file.
"""
from __future__ import annotations

import collections
import json
import os
import sys
import threading
import time
import traceback
from types import SimpleNamespace

from . import core, settings

TITLE = "ChainKit - Burnout Chain for Burnout Revenge"
RED = (1.0, 0.45, 0.45, 1.0)
YELLOW = (1.0, 0.85, 0.35, 1.0)
GREEN = (0.45, 0.9, 0.5, 1.0)
GREY = (0.62, 0.62, 0.66, 1.0)
ACCENT = (0.3, 0.8, 1.0, 1.0)
CHANGED = (1.0, 0.78, 0.4, 1.0)
ISO_FILTERS = ["PS2 DVD image", "*.iso", "All files", "*"]
JSON_FILTERS = ["ChainKit settings", "*.json", "All files", "*"]


def app_dir():
    """Settings + log folder: %APPDATA%\\chainkit (Windows), ~/Library/Application Support/chainkit (macOS),
    ~/.config/chainkit (Linux). CHAINKIT_HOME overrides it (tests)."""
    d = os.environ.get("CHAINKIT_HOME")
    if not d:
        if os.name == "nt":
            base = os.environ.get("APPDATA") or os.path.expanduser("~")
        elif sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Application Support")
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        d = os.path.join(base, "chainkit")
    os.makedirs(d, exist_ok=True)
    return d


class Log:
    def __init__(self, path):
        self.lines = collections.deque(maxlen=3000)
        self.lock = threading.Lock()
        try:
            self.file = open(path, "a", encoding="utf-8", buffering=1)
            self.file.write("\n===== chainkit gui %s =====\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        except OSError:
            self.file = None

    def __call__(self, text, level="info"):
        for line in str(text).splitlines() or [""]:
            with self.lock:
                self.lines.append((level, time.strftime("%H:%M:%S"), line))
            if self.file:
                try:
                    self.file.write(line + "\n")
                except Exception:
                    pass

    def error(self, text):
        self(text, "error")

    def errors(self):
        with self.lock:
            return [line for lv, _, line in self.lines if lv == "error"]


class Job:
    def __init__(self, title, fn, log):
        self.title = title
        self.progress = 0.0
        self.message = title
        self.done = False
        self.ok = False
        self.result = None
        self.log = log
        self.thread = threading.Thread(target=self._run, args=(fn,), daemon=True)
        self.thread.start()

    def update(self, frac, msg):
        self.progress = max(0.0, min(1.0, frac))
        self.message = msg

    def _run(self, fn):
        try:
            self.result = fn(self)
            self.ok = True
        except core.KitError as exc:
            self.log.error(str(exc)[0].upper() + str(exc)[1:])
        except Exception as exc:
            self.log.error("%s failed: %s" % (self.title, exc))
            self.log(traceback.format_exc(), "error")
        finally:
            self.done = True


def disc_info(path):
    """Everything the window shows about an ISO (read once; the file is closed again)."""
    with core.Disc(path) as d:
        return SimpleNamespace(path=path, summary=d.summary(), applied=d.applied, values=d.values,
                               problems=d.problems(), arrow_art=d.arrow_art, musickit=d.musickit, carkit=d.carkit,
                               songs=d.songs, crc=d.crc, langs=d.langs)


class ChainKitGui:
    """Window state and actions (no drawing): the GUI flow test drives this class directly."""

    def __init__(self, log, saved=None):
        self.log = log
        self.saved = dict(saved or {})
        self.iso_path = self.saved.get("iso") or ""
        self.dom_path = self.saved.get("dominator") or ""
        self.out_path = self.saved.get("out") or ""
        try:
            self.values = settings.check(self.saved.get("values") or {})
        except ValueError:
            self.values = dict(settings.DEFAULTS)
        self.disc = None
        self.disc_error = None
        self.dom_ok = False
        self.dom_error = None
        self.job = None
        self.dialog = None
        self.last_save = None          # {"out", "ok"} of the last save in this session
        self.open_groups = set(self.saved.get("open_groups") or [settings.GROUPS[0][0]])
        demo = self.saved.get("demo")
        if demo:                       # screenshots: a pretend disc, no file is read
            self.disc = SimpleNamespace(**demo["disc"]) if demo.get("disc") else None
            if self.disc and self.disc.values:
                self.disc.values = settings.check(self.disc.values)
            self.disc_values = dict(self.disc.values) if self.disc and self.disc.values else None
            self.dom_ok = bool(demo.get("dominator_ok"))
            self.last_save = demo.get("last_save")
            for line in demo.get("log", []):
                self.log(line)
            return
        self.disc_values = None
        if self.dom_path:
            self.set_dominator(self.dom_path, wait=True)
        if self.iso_path:
            self.load_disc(self.iso_path)

    # ------------------------------------------------------------------ state
    def save_settings(self):
        self.saved.update({"iso": self.iso_path, "dominator": self.dom_path, "out": self.out_path,
                           "values": settings.to_json(self.values)["settings"],
                           "open_groups": sorted(self.open_groups)})
        self.saved.pop("demo", None)
        try:
            with open(os.path.join(app_dir(), "settings.json"), "w", encoding="utf-8") as f:
                json.dump(self.saved, f, indent=1)
        except OSError:
            pass

    def busy(self):
        return self.job is not None and not self.job.done

    def start_job(self, title, fn):
        if self.busy():
            self.log.error("'%s' is still running" % self.job.title)
            return
        self.log("--- " + title)
        self.job = Job(title, fn, self.log)

    def changed_settings(self):
        """Settings that differ from what the selected ISO has (or from the defaults for an ISO without the mod)."""
        base = self.disc_values or settings.DEFAULTS
        return [n for n in settings.changed(self.values, base) if n != "arrow_tex_slot"]

    def adds_arrow(self):
        """A Dominator ISO is chosen and the selected modded ISO still uses Revenge's chevron."""
        return bool(self.dom_ok and self.disc and self.disc.applied and self.disc.arrow_art != "dominator")

    def save_problem(self):
        """Why "Save new ISO" cannot be pressed now (None when it can)."""
        if self.busy():
            return "wait until '%s' has finished" % self.job.title
        if self.disc is None:
            return "select your Burnout Revenge ISO first"
        if self.disc.problems:
            return self.disc.problems[0]
        if self.dom_path and not self.dom_ok:
            return "the Burnout Dominator ISO cannot be used (%s) - clear it to use Revenge's chevron" % (
                self.dom_error or "not checked yet")
        if self.disc.applied and not self.changed_settings() and not self.adds_arrow():
            return "this ISO already has the mod with these settings: change a setting first"
        out = self.out_path.strip()
        if not out:
            return "choose where to save the new ISO"
        if os.path.abspath(out) == os.path.abspath(self.disc.path):
            return "choose a different file - your ISO is never overwritten"
        if not os.path.isdir(os.path.dirname(os.path.abspath(out))):
            return "the folder of the new ISO does not exist"
        return None

    # ------------------------------------------------------------------ ISO / Dominator
    def load_disc(self, path):
        if self.busy():
            self.log.error("'%s' is still running - open the ISO again when it has finished" % self.job.title)
            return
        self.iso_path = path
        self.disc = None
        self.disc_values = None
        self.disc_error = None
        self.last_save = None
        if not path:
            self.disc_error = "Choose your Burnout Revenge ISO (Europe SLES-53507 or USA SLUS-21242) with Browse..."
            return
        if not os.path.isfile(path):
            self.disc_error = "ISO not found"
            return

        def run(job):
            job.update(0.3, "reading " + os.path.basename(path))
            try:
                info = disc_info(path)
            except Exception as exc:
                self.disc_error = str(exc)
                raise
            self.disc = info
            for p in info.problems:
                self.log.error(p[0].upper() + p[1:])
            if info.values:
                self.values = dict(info.values)
                self.disc_values = dict(info.values)
                self.log("%s: %s - its settings are loaded (%s); change them and save a new ISO" % (
                    os.path.basename(path), info.summary, settings.preset_of(info.values) or "custom"))
            else:
                self.log("%s: %s" % (os.path.basename(path), info.summary))
            if info.musickit:
                self.log("MusicKit songs found - good: MusicKit has to come before ChainKit")
            if not self.out_path or os.path.abspath(self.out_path) == os.path.abspath(path):
                self.out_path = core.default_output(path, "Burnout Chain settings" if info.applied else "Burnout Chain")
            return info

        self.start_job("open ISO", run)

    def set_dominator(self, path, wait=False):
        if self.busy():
            self.log.error("'%s' is still running" % self.job.title)
            return
        self.dom_path = path or ""
        self.dom_ok = False
        self.dom_error = None
        if not path:
            return
        if not os.path.isfile(path):
            self.dom_error = "file not found"
            return

        def run(job):
            job.update(0.3, "reading " + os.path.basename(path))
            try:
                core.dominator_txd(path)
            except Exception as exc:
                self.dom_error = str(exc)
                raise
            self.dom_ok = True
            self.log("Burnout Dominator ISO: arrow art found")

        self.start_job("check Dominator ISO", run)
        if wait and self.job:
            self.job.thread.join()

    def drop(self, paths):
        """Drag and drop: a Revenge ISO goes to step 1, a Dominator ISO to step 2, a .json loads settings."""
        for p in paths:
            low = p.lower()
            if low.endswith(".json"):
                self.import_settings(p)
            elif low.endswith(".iso"):
                if self.busy():
                    self.log.error("'%s' is still running" % self.job.title)
                    continue
                if self._is_dominator(p):
                    self.set_dominator(p)
                else:
                    self.load_disc(p)
            else:
                self.log.error("%s: drop an .iso or a ChainKit settings .json" % os.path.basename(p))

    @staticmethod
    def _is_dominator(path):
        try:
            with open(path, "rb"):
                pass
            from . import iso
            img = iso.IsoImage(path)
            try:
                return core.boot_elf(img) not in core.REVENGE_ELFS
            finally:
                img.f.close()
        except Exception:
            return False

    # ------------------------------------------------------------------ settings
    def apply_preset(self, name):
        keep = self.values.get("arrow_tex_slot")
        self.values = dict(settings.PRESETS[name])
        self.values["arrow_tex_slot"] = keep
        self.log("preset: %s" % name)

    def reset_defaults(self):
        self.apply_preset("Default (tested)")

    def set_value(self, key, value):
        lo, hi = settings.LIMITS.get(key, (None, None))
        if lo is not None and settings.TYPES[key] != "c":
            value = min(max(value, lo), hi)
        self.values = settings.check(dict(self.values, **{key: value}))

    def set_bit(self, key, bit, on):
        self.set_value(key, (self.values[key] | bit) if on else (self.values[key] & ~bit))

    def import_settings(self, path):
        try:
            v = settings.load(path)
        except (OSError, ValueError) as exc:
            self.log.error("could not load %s: %s" % (os.path.basename(path), exc))
            return False
        v["arrow_tex_slot"] = self.values.get("arrow_tex_slot")
        self.values = settings.check(v)
        self.log("settings loaded from %s" % path)
        return True

    def export_settings(self, path):
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            settings.save(path, self.values)
        except OSError as exc:
            self.log.error("could not save %s: %s" % (path, exc))
            return False
        self.log("settings saved to %s" % path)
        return True

    # ------------------------------------------------------------------ save
    def build(self):
        problem = self.save_problem()
        if problem:
            self.log.error(problem[0].upper() + problem[1:])
            return
        src, out, values = self.disc.path, self.out_path.strip(), dict(self.values)
        dom = self.dom_path if self.dom_ok else None

        def run(job):
            def progress(f, m):
                job.update(0.6 * f, m)
            done = core.save(src, out, values, dom, self.log, progress)
            job.update(0.6, "checking the new ISO")
            self.log("checking the new ISO (compares every file with your ISO) ...")
            ok = core.validate(src, out, dom, self.log)
            self.last_save = {"out": out, "ok": ok, "values": done}
            if not ok:
                raise core.KitError("the check of the new ISO FAILED - see the log above")
            self.log("Done. Play %s in PCSX2 or on your PS2. Open it here again to change its settings later."
                     % os.path.basename(out))
            return out

        self.start_job("save new ISO", run)

    def open_saved(self):
        if self.last_save:
            self.load_disc(self.last_save["out"])

    # ------------------------------------------------------------------ dialogs
    def open_dialog(self, dlg, cb):
        if self.dialog is None:
            self.dialog = (dlg, cb)

    def poll_dialog(self):
        if self.dialog is None:
            return
        dlg, cb = self.dialog
        try:
            if dlg.ready(0):
                self.dialog = None
                cb(dlg.result())
        except Exception as exc:
            self.dialog = None
            self.log.error("file dialog failed: %s" % exc)

    def _start(self, p):
        return os.path.dirname(p) if p else ""

    def pick_iso(self):
        from imgui_bundle import portable_file_dialogs as pfd
        self.open_dialog(pfd.open_file("Select your Burnout Revenge ISO", self._start(self.iso_path),
                                       ISO_FILTERS), lambda r: r and self.load_disc(r[0]))

    def pick_dominator(self):
        from imgui_bundle import portable_file_dialogs as pfd
        self.open_dialog(pfd.open_file("Select your Burnout Dominator ISO", self._start(self.dom_path), ISO_FILTERS),
                         lambda r: r and self.set_dominator(r[0]))

    def pick_out(self):
        from imgui_bundle import portable_file_dialogs as pfd
        self.open_dialog(pfd.save_file("Save the new ISO as", self.out_path, ["PS2 DVD image", "*.iso"]),
                         lambda r: r and self._set_out(r))

    def _set_out(self, path):
        if not path.lower().endswith(".iso"):
            path += ".iso"
        self.out_path = path

    def pick_import(self):
        from imgui_bundle import portable_file_dialogs as pfd
        self.open_dialog(pfd.open_file("Load ChainKit settings", "", JSON_FILTERS),
                         lambda r: r and self.import_settings(r[0]))

    def pick_export(self):
        from imgui_bundle import portable_file_dialogs as pfd
        start = os.path.join(self._start(self.out_path) or os.path.expanduser("~"), "chainkit-settings.json")
        self.open_dialog(pfd.save_file("Save ChainKit settings as", start, JSON_FILTERS),
                         lambda r: r and self.export_settings(r))

    # ------------------------------------------------------------------ UI
    def ui(self):
        from imgui_bundle import imgui
        U = _Ui(imgui)
        self.poll_dialog()
        vp = imgui.get_main_viewport()
        imgui.set_next_window_pos(vp.work_pos)
        imgui.set_next_window_size(vp.work_size)
        flags = (imgui.WindowFlags_.no_decoration | imgui.WindowFlags_.no_move | imgui.WindowFlags_.no_saved_settings
                 | imgui.WindowFlags_.no_bring_to_front_on_focus)
        imgui.begin("main", None, flags)
        U.text(ACCENT, "ChainKit")
        imgui.same_line()
        U.text(GREY, "Burnout Dominator's supercharge and Burnout chain for Burnout Revenge (PS2, Europe and USA)")
        imgui.separator()
        avail = imgui.get_content_region_avail()
        imgui.begin_child("left", imgui.ImVec2(avail.x * 0.42, avail.y - 4))
        self.ui_steps(U, imgui)
        imgui.end_child()
        imgui.same_line()
        imgui.begin_child("right", imgui.ImVec2(0, avail.y - 4))
        self.ui_settings(U, imgui)
        imgui.end_child()
        imgui.end()

    def ui_steps(self, U, imgui):
        busy = self.busy()
        # ---- 1
        U.step(1, "Select your Burnout Revenge ISO", self.disc is not None)
        imgui.begin_disabled(busy)
        imgui.set_next_item_width(-U.bw("Browse..."))
        changed, v = imgui.input_text("##iso", self.iso_path, imgui.InputTextFlags_.enter_returns_true)
        if changed:
            self.load_disc(v)
        imgui.same_line()
        if imgui.button("Browse...##iso"):
            self.pick_iso()
        imgui.end_disabled()
        if self.disc:
            d = self.disc
            U.text(GREEN, d.summary)
            for p in d.problems:
                U.text(RED, "! " + p[0].upper() + p[1:])
            if d.applied and d.values:
                U.text(GREY, "Its settings are shown on the right: change them and save a new ISO - no need to "
                             "start again from the original.")
            if d.applied and not d.musickit:
                U.text(GREY, "Want MusicKit songs too? MusicKit cannot open an ISO that already has ChainKit: run "
                             "MusicKit on your ISO without the mod first, then ChainKit on MusicKit's new ISO.")
            U.text(GREY, "Your ISO is only read; it is never changed. PCSX2 still recognises the game "
                         "(CRC %08X kept), so widescreen and other patches keep working." % d.crc)
        elif self.disc_error and not (busy and self.job.title == "open ISO"):
            U.text(RED if os.path.exists(self.iso_path or "") or self.iso_path else GREY, self.disc_error)
        U.text(GREY, "Europe (SLES-53507) or USA (SLUS-21242). With MusicKit: run MusicKit first, then ChainKit "
                     "on its new ISO.")
        # ---- 2
        U.step(2, "Arrow art: your Burnout Dominator ISO (optional)", self.dom_ok)
        imgui.begin_disabled(busy)
        imgui.set_next_item_width(-U.bw("Browse...", "Clear"))
        changed, v = imgui.input_text("##dom", self.dom_path, imgui.InputTextFlags_.enter_returns_true)
        if changed:
            self.set_dominator(v)
        imgui.same_line()
        if imgui.button("Browse...##dom"):
            self.pick_dominator()
        imgui.same_line()
        if imgui.button("Clear##dom"):
            self.set_dominator("")
        imgui.end_disabled()
        if self.dom_ok:
            U.text(GREEN, "Dominator's arrow will be used.")
        elif self.dom_path and self.dom_error:
            U.text(RED, "! " + self.dom_error)
        elif not self.dom_path:
            if self.disc and self.disc.applied:
                U.text(GREY, "This ISO uses %s." % ("Dominator's arrow" if self.disc.arrow_art == "dominator"
                                                   else "Revenge's chevron for the arrows"))
            else:
                U.text(GREY, "Without it the arrows use Revenge's own chevron. ChainKit includes no game data: the "
                             "arrow image is taken from your own Burnout Dominator disc image.")
        # ---- 3
        U.step(3, "Save the new ISO", bool(self.last_save and self.last_save["ok"]))
        imgui.begin_disabled(busy)
        imgui.set_next_item_width(-U.bw("Browse..."))
        _, self.out_path = imgui.input_text("##out", self.out_path)
        imgui.same_line()
        if imgui.button("Browse...##out"):
            self.pick_out()
        imgui.end_disabled()
        if self.out_path and os.path.exists(self.out_path) and self.disc and \
                os.path.abspath(self.out_path) != os.path.abspath(self.disc.path):
            U.text(YELLOW, "This file exists and will be replaced.")
        problem = self.save_problem()
        imgui.begin_disabled(problem is not None)
        imgui.push_style_color(imgui.Col_.button, U.col((0.1, 0.45, 0.75, 1.0)))
        if imgui.button("Save new ISO", imgui.ImVec2(U.bw("  Save new ISO  "), imgui.get_frame_height() * 1.6)):
            self.build()
        imgui.pop_style_color()
        imgui.end_disabled()
        if problem:
            U.tip(problem[0].upper() + problem[1:])
            imgui.same_line()
            U.text(GREY, problem[0].upper() + problem[1:])
        elif self.disc and self.disc.applied:
            n = len(self.changed_settings())
            U.text(GREY, "%d setting%s changed%s" % (n, "" if n == 1 else "s",
                                                    ", adds Dominator's arrow" if self.adds_arrow() else ""))
        if self.job and (not self.job.done or self.job.title == "save new ISO"):
            imgui.progress_bar(self.job.progress if not self.job.done else 1.0, imgui.ImVec2(-1, 0),
                               self.job.message if not self.job.done else ("done" if self.job.ok else "failed"))
        if self.last_save and not busy:
            if self.last_save["ok"]:
                U.text(GREEN, "Saved and checked: %s" % self.last_save["out"])
                if imgui.button("Open the new ISO here (to change its settings)"):
                    self.open_saved()
            else:
                U.text(RED, "The check of %s failed - see the log." % self.last_save["out"])
        imgui.spacing()
        if imgui.collapsing_header("Log", imgui.TreeNodeFlags_.default_open):
            imgui.begin_child("log", imgui.ImVec2(0, 0))
            with self.log.lock:
                lines = list(self.log.lines)[-400:]
            for lv, t, line in lines:
                U.text(RED if lv == "error" else GREY, "%s  %s" % (t, line))
            if imgui.get_scroll_y() >= imgui.get_scroll_max_y() - 4:
                imgui.set_scroll_here_y(1.0)
            imgui.end_child()

    def ui_settings(self, U, imgui):
        busy = self.busy()
        imgui.begin_disabled(busy)
        U.text(None, "Settings")
        imgui.same_line()
        cur = settings.preset_of(self.values)
        imgui.set_next_item_width(U.bw("Default (tested)") + imgui.get_frame_height())
        if imgui.begin_combo("##preset", cur or "Custom"):
            for name in settings.PRESETS:
                clicked, _ = imgui.selectable(name, name == cur)
                U.tip(settings.PRESET_INFO[name])
                if clicked:
                    self.apply_preset(name)
            imgui.end_combo()
        U.tip("Presets. Pick one, then change single settings if you like.")
        imgui.same_line()
        if imgui.button("Reset to defaults"):
            self.reset_defaults()
        U.tip("Back to the tested default settings.")
        if self.disc_values:
            imgui.same_line()
            if imgui.button("Undo changes"):
                self.values = dict(self.disc_values)
            U.tip("Back to the settings the selected ISO has.")
        U.text(GREY, "Settings file:")
        imgui.same_line()
        if imgui.button("Load..."):
            self.pick_import()
        U.tip("Load settings from a .json file (saved with Save... or 'chainkit export').")
        imgui.same_line()
        if imgui.button("Save..."):
            self.pick_export()
        U.tip("Save these settings to a .json file, to keep or share them, or to use them with the command line "
              "(--settings FILE.json).")
        U.text(GREY, "Hover over a setting for an explanation. Orange = changed from the default. "
                     "Ctrl+click a slider to type a value.")
        imgui.separator()
        imgui.begin_child("settings_scroll", imgui.ImVec2(0, 0))
        for title, intro, items in settings.GROUPS:
            imgui.set_next_item_open(title in self.open_groups, imgui.Cond_.always)
            is_open = imgui.collapsing_header(title)
            (self.open_groups.add if is_open else self.open_groups.discard)(title)
            if not is_open:
                continue
            if intro:
                U.text(GREY, intro)
            if imgui.begin_table("t_" + title, 2, imgui.TableFlags_.sizing_stretch_prop):
                imgui.table_setup_column("label", imgui.TableColumnFlags_.width_stretch, 0.55)
                imgui.table_setup_column("value", imgui.TableColumnFlags_.width_stretch, 0.45)
                for it in items:
                    self.ui_item(U, imgui, it)
                imgui.end_table()
            if title.startswith("Normal bar"):
                s = settings.fill_seconds(self.values)
                U.text(GREY, "An empty bar fills in about %.1f s of oncoming (250 km/h) or %.1f s of drifting "
                             "(200 km/h)." % (s["oncoming"], s["drift"]))
            imgui.spacing()
        imgui.end_child()
        imgui.end_disabled()

    def ui_item(self, U, imgui, it):
        v = self.values[it.key]
        if it.kind in ("flag", "mode"):
            dflt = bool(settings.DEFAULTS[it.key] & it.bit)
            cur = bool(v & it.bit)
            changed_ = cur != dflt
        else:
            changed_ = not settings.same(v, settings.DEFAULTS[it.key])
        imgui.table_next_row()
        imgui.table_set_column_index(0)
        imgui.align_text_to_frame_padding()
        U.text(CHANGED if changed_ else None, it.label)
        U.tip(self._help(it))
        imgui.table_set_column_index(1)
        imgui.set_next_item_width(-1)
        wid = "##" + it.key + ("_%x" % it.bit if it.bit else "")
        if it.kind in ("flag", "mode"):
            ch, nv = imgui.checkbox(wid, cur)
            if ch:
                self.set_bit(it.key, it.bit, nv)
        elif it.kind == "colour":
            ch, nv = imgui.color_edit4(wid, list(v), imgui.ColorEditFlags_.alpha_preview_half)
            if ch:
                self.set_value(it.key, tuple(min(1.0, max(0.0, float(x))) for x in nv))
        elif it.unit:
            u = it.unit
            if it.kind == "int":
                ch, nv = imgui.slider_int(wid, int(u.to_ui(v)), int(u.lo), int(u.hi))
            else:
                ch, nv = imgui.slider_float(wid, float(u.to_ui(v)), float(u.lo), float(u.hi), u.fmt)
            if ch:
                raw = u.from_ui(nv)
                self.set_value(it.key, int(raw) if it.kind == "int" else float(raw))
        U.tip(self._help(it))

    def _help(self, it):
        txt = it.help or it.label
        dflt = settings.shown(it, settings.DEFAULTS)
        return "%s\n\nDefault: %s   (setting name: %s)" % (txt, dflt, it.key if it.kind not in ("flag", "mode") else
                                                         "%s bit %#x" % (it.key, it.bit))


class _Ui:
    """Small drawing helpers (imgui passed in so the module imports without a display)."""

    def __init__(self, imgui):
        self.imgui = imgui

    def bw(self, *labels):
        """Width of a row of buttons with these labels (incl. the spacing before each)."""
        st = self.imgui.get_style()
        return sum(self.imgui.calc_text_size(t).x + 2 * st.frame_padding.x + st.item_spacing.x for t in labels)

    def col(self, c):
        return self.imgui.ImVec4(*c)

    def tip(self, text):
        imgui = self.imgui
        if text and imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled | imgui.HoveredFlags_.delay_short):
            imgui.begin_tooltip()
            imgui.push_text_wrap_pos(imgui.get_font_size() * 40)
            imgui.text_unformatted(text)
            imgui.pop_text_wrap_pos()
            imgui.end_tooltip()

    def text(self, color, text):
        imgui = self.imgui
        imgui.push_text_wrap_pos(0)
        if color is None:
            imgui.text_unformatted(text)
        else:
            imgui.push_style_color(imgui.Col_.text, self.col(color))
            imgui.text_unformatted(text)
            imgui.pop_style_color()
        imgui.pop_text_wrap_pos()

    def step(self, n, text, done):
        imgui = self.imgui
        imgui.spacing()
        self.text(GREEN if done else ACCENT, "%d" % n)
        imgui.same_line()
        self.text(None, text)
        imgui.separator()


# ---------------------------------------------------------------------------------------------- window
def _fatal(msg):
    try:
        sys.stderr.write(msg + "\n")   # under pythonw there is no console (sys.stderr is None)
    except Exception:
        pass
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg[-3000:], "ChainKit error", 0x10)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["osascript", "-e", 'display alert "ChainKit error" message '
                            '(system attribute "CHAINKIT_MSG") as critical'],
                           env=dict(os.environ, CHAINKIT_MSG=msg[-3000:]), timeout=3600)
    except Exception:
        pass


def main(shot=None, demo=None, size=None):
    try:
        with open(os.path.join(app_dir(), "settings.json"), encoding="utf-8") as f:
            saved = json.load(f)
    except Exception:
        saved = {}
    if demo:
        saved = {"demo": demo, **{k: demo[k] for k in ("iso", "dominator", "out", "values", "open_groups")
                                  if k in demo}}
    log = Log(os.path.join(app_dir(), "gui.log"))
    try:
        return _run(saved, log, shot, size)
    except Exception:
        tb = traceback.format_exc()
        log(tb, "error")
        if not shot:
            _fatal("ChainKit crashed:\n\n%s\n\nLog: %s" % (tb, os.path.join(app_dir(), "gui.log")))
        else:
            print(tb)
        return 1


def _run(saved, log, shot, size=None):
    import glfw
    from OpenGL import GL as gl
    from imgui_bundle import imgui
    from imgui_bundle.python_backends.glfw_backend import GlfwRenderer

    if not glfw.init():
        raise RuntimeError("could not initialise GLFW")
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, gl.GL_TRUE)     # required on macOS
    window = glfw.create_window(*(size or (1400, 860)), TITLE, None, None)
    if not window:
        raise RuntimeError("could not create an OpenGL 3.3 window")
    glfw.make_context_current(window)
    glfw.swap_interval(1)
    imgui.create_context()
    io = imgui.get_io()
    io.config_flags |= imgui.ConfigFlags_.nav_enable_keyboard
    io.set_ini_filename("")
    sx, _ = glfw.get_window_content_scale(window)
    # Windows/Linux HiDPI: window size = framebuffer size in pixels -> scale the UI. macOS Retina: the window size
    # is in points and only the framebuffer is larger -> ImGui already draws at the right size (sharp text).
    if sx and sx > 1.01 and glfw.get_framebuffer_size(window)[0] <= glfw.get_window_size(window)[0] * 1.01:
        imgui.get_style().scale_all_sizes(sx)
        imgui.get_style().font_scale_dpi = sx
    impl = GlfwRenderer(window)
    gui = ChainKitGui(log, saved)
    if shot:
        gui.save_settings = lambda: None
    dropped = []
    glfw.set_drop_callback(window, lambda w, paths: dropped.extend(paths))
    frames = 0
    while not glfw.window_should_close(window):
        glfw.poll_events()
        if not shot and not gui.busy() and not glfw.get_window_attrib(window, glfw.FOCUSED):
            glfw.wait_events_timeout(0.1)
        impl.process_inputs()
        if dropped:
            gui.drop(list(dropped))
            dropped.clear()
        imgui.new_frame()
        fb_w, fb_h = glfw.get_framebuffer_size(window)
        if fb_w == 0 or fb_h == 0:
            imgui.end_frame()
            glfw.wait_events_timeout(0.2)
            continue
        idle = not gui.busy()
        gui.ui()
        gl.glViewport(0, 0, fb_w, fb_h)
        gl.glClearColor(0.1, 0.1, 0.12, 1)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        imgui.render()
        impl.render(imgui.get_draw_data())
        frames += 1
        if shot and frames > 30 and idle:
            import numpy as np
            from PIL import Image
            gl.glPixelStorei(gl.GL_PACK_ALIGNMENT, 1)
            px = gl.glReadPixels(0, 0, fb_w, fb_h, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
            img = np.frombuffer(px, dtype=np.uint8).reshape(fb_h, fb_w, 3)[::-1]
            Image.fromarray(img).save(shot)
            glfw.set_window_should_close(window, True)
        glfw.swap_buffers(window)
    gui.save_settings()
    impl.shutdown()
    glfw.terminate()
    return 0
