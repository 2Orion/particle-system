"""复现：面板参数拖不动 —— PostMessage 走真实消息路径（坐标已修正）。

坐标系结论（本版修正了上一版的错误）：
  Windows WM_* 消息 lParam 是左上原点；pyglet 翻一次成左下原点；
  moderngl-window 再翻一次回到左上原点。两次翻转 = 恒等。
  所以直接用 ImGui 坐标（左上原点）投递即可，不需要任何翻转。

同时记录所有 drag_float 的值与矩形，点完打印"点中了谁"。

运行：python -X utf8 tools/smoke_drag.py
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

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001

_user32 = ctypes.windll.user32

S = {"frame": 0, "values": {}}


def _log(tag, **kw):
    io = imgui.get_io()
    print("[drag]", f"f{S['frame']}", tag,
          f"mp=({io.mouse_pos.x:.0f},{io.mouse_pos.y:.0f})",
          f"dn0={int(io.mouse_down[0])}",
          f"want_mouse={int(io.want_capture_mouse)}",
          *(f"{k}={v}" for k, v in kw.items()), flush=True)


def _make():
    class Smoke(ParticleApp):
        def _patch(self):
            if getattr(imgui.drag_float, "_rec", False):
                return
            orig = imgui.drag_float

            def wrap(*a, **kw):
                out = orig(*a, **kw)
                mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
                S.setdefault("rects", {})[a[0]] = (
                    (mn.x, mn.y), (mx.x, mx.y))
                S["values"][a[0]] = a[1]          # 该控件当前值
                return out
            wrap._rec = True
            imgui.drag_float = wrap

        def _post(self, msg, x, y, wparam):
            """投递 Win32 鼠标消息（坐标=ImGui 左上原点，直接用）。"""
            hwnd = self.wnd._window._view_hwnd
            lparam = (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)
            _user32.PostMessageW(hwnd, msg, wparam, lparam)

        def on_render(self, time_value, frame_time):
            self._patch()
            super().on_render(time_value, frame_time)
            S["frame"] += 1
            f = S["frame"]
            try:
                self._script(f)
            except Exception as exc:                 # noqa: BLE001
                print(f"[drag] EXCEPTION f{f}: {exc!r}", flush=True)
                self.wnd.close()

        def _script(self, f):
            label = "固定步长 (ms)"
            rects = S.get("rects", {})
            if label not in rects:
                return
            (x0, y0), (x1, y1) = rects[label]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if f == 10:
                S["before"] = self.scene.system.fixed_step * 1000
                S["before_values"] = dict(S["values"])
                _log("before", target=f"({cx:.0f},{cy:.0f})",
                     value=f"{S['before']:.3f}")
            elif f == 11:
                self._post(WM_MOUSEMOVE, cx, cy, 0)
                _log("hover(post)")
            elif f == 12:
                self._post(WM_LBUTTONDOWN, cx, cy, MK_LBUTTON)
                _log("press(post)")
            elif 13 <= f <= 17:
                cx += (f - 12) * 20
                self._post(WM_MOUSEMOVE, cx, cy, MK_LBUTTON)
                _log("drag+20px(post)")
            elif f == 18:
                cx += 100
                self._post(WM_LBUTTONUP, cx, cy, 0)
                _log("release(post)")
            elif f == 24:
                after = self.scene.system.fixed_step * 1000
                moved = abs(after - S["before"])
                # 哪些控件的值变了？
                changed = {k: (S["before_values"].get(k), v)
                           for k, v in S["values"].items()
                           if abs(v - S["before_values"].get(k, v)) > 1e-6}
                _log("after", value=f"{after:.3f}")
                print(f"[drag] fixed_step: {S['before']:.3f} → {after:.3f}",
                      flush=True)
                print(f"[drag] 变化的控件: "
                      f"{ {k: (round(a,4), round(b,4)) for k,(a,b) in changed.items()} }",
                      flush=True)
                _write_png(OUT / "drag_probe_real2.png", self._read_fbo_rgb())
                verdict = "能动" if moved > 0.5 else "不动（与用户报告一致）"
                print(f"[drag] === 真实消息路径：滑条{verdict}", flush=True)
                self.wnd.close()

    return Smoke


if __name__ == "__main__":
    run_window_config(_make())
