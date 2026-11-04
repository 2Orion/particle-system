"""回归：面板所有可编辑控件（真实消息路径 + 同帧投递）。

修复后四类控件全部应可编辑：
  全局区  固定步长（drag_float）、慢放（slider）、暂停（checkbox）
  场景区  发射率（drag_float）、力场参数（折叠头内 drag_float）
  下拉    积分器（combo）
全用同帧投递（最难路径：press+move+release 挤一批）——这是修复的核心
目标；跨帧路径已由 smoke_panel_edit 的 A/B 案例覆盖。

运行：python -X utf8 tools/smoke_panel_edit.py
"""
from __future__ import annotations

import ctypes
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from moderngl_window import run_window_config

from main import ParticleApp, _write_png
from imgui_bundle import imgui

OUT = pathlib.Path(__file__).resolve().parents[1] / "output"

WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
MK_LBUTTON = 0x0001
_user32 = ctypes.windll.user32

S = {"frame": 0, "results": []}


def _make():
    class Smoke(ParticleApp):
        def _patch(self):
            if getattr(imgui.drag_float, "_rec", False):
                return
            for fname in ("drag_float", "slider_float", "checkbox", "combo"):
                orig = getattr(imgui, fname)
                recs = S.setdefault("rects", {})

                def wrap(*a, _o=orig, _n=fname, _r=recs, **kw):
                    out = _o(*a, **kw)
                    mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
                    _r[f"{_n}:{a[0]}"] = ((mn.x, mn.y), (mx.x, mx.y))
                    return out
                wrap._rec = True
                setattr(imgui, fname, wrap)

        def _post(self, msg, x, y, wparam=0):
            hwnd = self.wnd._window._view_hwnd
            lparam = (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)
            _user32.PostMessageW(hwnd, msg, wparam, lparam)

        def _drag(self, label, dx=60):
            """同帧完整手势：press+move+release 一批投递。"""
            (x0, y0), (x1, y1) = S["rects"][label]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            self._post(WM_MOUSEMOVE, cx, cy)
            self._post(WM_LBUTTONDOWN, cx, cy, MK_LBUTTON)
            self._post(WM_MOUSEMOVE, cx + dx, cy, MK_LBUTTON)
            self._post(WM_LBUTTONUP, cx + dx, cy)

        def _click(self, label, off_x=0):
            (x0, y0), (x1, y1) = S["rects"][label]
            cx, cy = (x0 + x1) / 2 + off_x, (y0 + y1) / 2
            self._post(WM_MOUSEMOVE, cx, cy)
            self._post(WM_LBUTTONDOWN, cx, cy, MK_LBUTTON)
            self._post(WM_LBUTTONUP, cx, cy)

        def _check(self, name, before, after, ok=None):
            ok = (before != after) if ok is None else ok
            S["results"].append((name, ok))
            print(f"[reg] {'PASS' if ok else 'FAIL'} {name}: "
                  f"{before!r} → {after!r}", flush=True)

        def on_render(self, time_value, frame_time):
            self._patch()
            super().on_render(time_value, frame_time)
            S["frame"] += 1
            try:
                self._script(S["frame"])
            except Exception as exc:                 # noqa: BLE001
                print(f"[reg] EXCEPTION f{S['frame']}: {exc!r}", flush=True)
                self.wnd.close()

        def _wait_label(self, pred):
            for k in S.get("rects", {}):
                if pred(k):
                    return k
            return None

        def _script(self, f):
            if f < 12:
                return
            rects = S.get("rects", {})
            # --- 全局区 ---
            if f == 12:
                S["h"] = self.scene.system.fixed_step * 1000
            elif f == 13:
                self._drag("drag_float:固定步长 (ms)")
            elif f == 18:
                self._check("固定步长(同帧)", round(S["h"], 2),
                            round(self.scene.system.fixed_step * 1000, 2))
            elif f == 22:
                S["s"] = self.time_scale
            elif f == 23:
                # slider：点击右侧 60px（0.05~3.0 范围）
                (x0, y0), (x1, y1) = rects["slider_float:慢放"]
                cx, cy = (x0 + x1) / 2 + 60, (y0 + y1) / 2
                self._post(WM_MOUSEMOVE, cx, cy)
                self._post(WM_LBUTTONDOWN, cx, cy, MK_LBUTTON)
                self._post(WM_LBUTTONUP, cx, cy)
            elif f == 28:
                self._check("慢放 slider(同帧)", round(S["s"], 2),
                            round(self.time_scale, 2))
            elif f == 30:
                S["p"] = self.paused
            elif f == 31:
                self._click("checkbox:暂停 (Space)")
            elif f == 36:
                self._check("暂停 checkbox", S["p"], self.paused)
            elif f == 38:
                S["i"] = self.scene.system.integrator_name
            elif f == 39:
                self._click("combo:积分器", off_x=40)   # 展开下拉
            elif f == 44:
                # 弹出层第 2 项（verlet）。第一项高亮行高 ~18px、
                # 顶部留白随字体度量浮动，试两个候选 y，点不到则重试
                (a0, b0), _ = rects["combo:积分器"]
                cx, cy = a0 + 60, b0 + 50
                self._post(WM_MOUSEMOVE, cx, cy)
                self._post(WM_LBUTTONDOWN, cx, cy, MK_LBUTTON)
                self._post(WM_LBUTTONUP, cx, cy)
            elif f == 50:
                ok = self.scene.system.integrator_name != S["i"]
                if not ok and S.get("i") == "velocity_verlet":
                    # 重试一次：弹出层几何偶发错位（与本次修复无关的
                    # 测试几何假设），第二次点击往往命中
                    self._click("combo:积分器", off_x=40)
            elif f == 56:
                if S["i"] == "velocity_verlet":
                    (a0, b0), _ = rects["combo:积分器"]
                    cx, cy = a0 + 60, b0 + 56
                    self._post(WM_MOUSEMOVE, cx, cy)
                    self._post(WM_LBUTTONDOWN, cx, cy, MK_LBUTTON)
                    self._post(WM_LBUTTONUP, cx, cy)
            elif f == 62:
                self._check("积分器 combo", S["i"],
                            self.scene.system.integrator_name,
                            ok=self.scene.system.integrator_name != S["i"])
            # --- 场景区（喷泉：发射率 + Gravity g_y 折叠头） ---
            elif f == 66:
                S["rate"] = self.scene.system.emitters[0].rate_mean
                lbl = self._wait_label(lambda k: k.startswith("drag_float:发射率"))
                S["rate_lbl"] = lbl
            elif f == 67 and S.get("rate_lbl"):
                self._drag(S["rate_lbl"])
            elif f == 72:
                self._check("发射率(同帧)", round(S["rate"]),
                            round(self.scene.system.emitters[0].rate_mean),
                            ok=abs(self.scene.system.emitters[0].rate_mean
                                   - S["rate"]) > 10)
            elif f == 76:
                S["g"] = float(self.scene.system.forces[0].g[1])
                lbl = self._wait_label(lambda k: "g_y" in k)
                S["g_lbl"] = lbl
            elif f == 77 and S.get("g_lbl"):
                self._drag(S["g_lbl"])
            elif f == 82:
                self._check("g_y(折叠头内,同帧)", round(S["g"], 2),
                            round(float(self.scene.system.forces[0].g[1]), 2))
            elif f == 88:
                _write_png(OUT / "panel_regression.png", self._read_fbo_rgb())
                fails = [n for n, ok in S["results"] if not ok]
                print(f"[reg] === {'ALL PASS' if not fails else 'FAIL: ' + ', '.join(fails)}",
                      flush=True)
                self.wnd.close()

    return Smoke


if __name__ == "__main__":
    run_window_config(_make())
