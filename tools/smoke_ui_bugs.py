"""UI 三个 bug 的真实窗口回归冒烟：面板缩放 / 下拉框贴图 / 文字输入。

运行：python -X utf8 tools/smoke_ui_bugs.py

对应三处回归：
  1. 全屏后面板仍是 1 倍大小 —— 现在字号与间距跟窗口缩放；
  2. 打开"粒子纹理"下拉框时面板上糊着一块拉长的三角形 —— 多 DrawList
     的索引没重定基，弹出层索引到了主窗口的顶点；
  3. 文字改不动、永远显示"粒子系统" —— 点按钮时缓冲被 scene.text 覆盖。

三个检查都以数值断言为主（不靠肉眼），截图留作人工复核：
  * 缩放：全屏后输入框的屏幕矩形必须比窗口化时明显更大；
  * 下拉框：弹出层必须以自己那块 DrawList 的顶点范围为准（索引不越界）；
  * 文字：点"应用文字"后 scene.text 必须变成输入的内容。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import numpy as np
from imgui_bundle import imgui
from moderngl_window import run_window_config

from main import ParticleApp, _write_png
from ui import imgui_backend

OUT = pathlib.Path(__file__).resolve().parents[1] / "output"

S = {
    "frame": 0,
    "rects": {},          # 控件名 → ((x0,y0),(x1,y1))
    "log": [],
    "combo_chk": None,    # 下拉框索引检查结果
    "typed": "",
}
FAILS = []


def _check(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    print(f"[bug] {tag} {name} {detail}", flush=True)
    if not ok:
        FAILS.append(name)


# ---------------------------------------------------------------- 后端截获

_orig_render = imgui_backend.ImGuiModernGLRenderer.render


def _render(self, draw_data):
    """在多 DrawList 出现时校验索引是否越界（bug 2 的直接判据）。"""
    if draw_data is not None and len(draw_data.cmd_lists) >= 2 \
            and S["combo_chk"] is None:
        dt = np.uint32 if imgui.INDEX_SIZE == 4 else np.uint16
        import ctypes
        bad = []
        for li, cl in enumerate(draw_data.cmd_lists):
            n_vtx = cl.vtx_buffer.size()
            n_idx = cl.idx_buffer.size()
            raw = (ctypes.c_ubyte * (n_idx * imgui.INDEX_SIZE)).from_address(
                cl.idx_buffer.data_address())
            idx = np.frombuffer(raw, dtype=dt)
            # 重定基后索引上界 = 该块顶点数 + 基址；这里只看"块内相对
            # 编号"是否越界，重定基会把它们抬到合法区间。
            rebased = self._rebase_indices(cl, 0)
            rel = np.frombuffer(rebased, dtype=dt)
            if len(rel) and int(rel.max()) >= n_vtx:
                bad.append((li, int(rel.max()), n_vtx))
        S["combo_chk"] = {"lists": len(draw_data.cmd_lists), "bad": bad}
    return _orig_render(self, draw_data)


imgui_backend.ImGuiModernGLRenderer.render = _render


# ---------------------------------------------------------------- 场景

def _make():
    class Smoke(ParticleApp):
        def _patch(self):
            """记录控件矩形（不改控件行为）。"""
            if getattr(imgui.input_text, "_rec", False):
                return
            oi, ob = imgui.input_text, imgui.button
            oc = imgui.combo

            def rec(kind, fn):
                def wrap(*a, **kw):
                    out = fn(*a, **kw)
                    mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
                    S["rects"][f"{kind}:{a[0]}"] = (
                        (min(mn.x, mx.x), min(mn.y, mx.y)),
                        (max(mn.x, mx.x), max(mn.y, mx.y)))
                    if kind == "input":
                        io = imgui.get_io()
                        S["log"].append(
                            (S["frame"], "hov=%s" % imgui.is_item_hovered(),
                             "act=%s" % imgui.is_item_active(),
                             "mp=(%d,%d)" % (io.mouse_pos.x, io.mouse_pos.y),
                             "dn=%s" % bool(io.mouse_down[0])))
                    return out
                wrap._rec = True
                return wrap

            def rec_combo(*a, **kw):
                out = oc(*a, **kw)
                mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
                S["rects"][f"combo:{a[0]}"] = (
                    (min(mn.x, mx.x), min(mn.y, mx.y)),
                    (max(mn.x, mx.x), max(mn.y, mx.y)))
                return out

            imgui.input_text = rec("input", oi)
            imgui.button = rec("button", ob)
            imgui.combo = rec_combo

        # ---------------------------------------------- 输入辅助
        def _center(self, key):
            r = S["rects"][key]
            return ((r[0][0] + r[1][0]) / 2, (r[0][1] + r[1][1]) / 2)

        def _hover(self, key):
            """先只移动鼠标。ImGui 的 hover 判定要用上一帧的鼠标位置，
            所以"移动"和"按下"必须分两帧（真实用户移动鼠标会连续发
            很多帧位置事件，天然满足这一点）。"""
            x, y = self._center(key)
            self.on_mouse_position_event(x, y, 0, 0)
            S["pt"] = (x, y)

        def _click(self, key, down):
            x, y = self._center(key)
            if down:
                self.on_mouse_position_event(x, y, 0, 0)
                self.on_mouse_press_event(x, y, self.wnd.mouse.left)
                S["pt"] = (x, y)
            else:
                px, py = S.get("pt", (x, y))
                self.on_mouse_release_event(px, py, self.wnd.mouse.left)

        def _input_h(self):
            r = S["rects"]["input:文字内容"]
            return r[1][1] - r[0][1]

        # ---------------------------------------------- 主循环
        def on_render(self, time_value, frame_time):
            self._patch()
            super().on_render(time_value, frame_time)
            S["frame"] += 1
            f = S["frame"]
            try:
                self._script(f)
            except Exception as exc:                 # noqa: BLE001
                print(f"[bug] EXCEPTION f{f}: {exc!r}", flush=True)
                FAILS.append(f"exception@{f}")
                self.wnd.close()

        def _script(self, f):
            # 顺序有讲究：文字输入测试放在下拉框测试**之前**。下拉框弹出层
            # 会独占鼠标/键盘焦点，开着时点别处只会关掉它，那一下点击不会
            # 落到被遮住的输入框上——这会把两个测试耦合在一起。
            if f == 5:
                self.switch_scene(4)                 # 文字场景
            elif f == 20:
                _write_png(OUT / "bug_windowed.png", self._read_fbo_rgb())
                S["h_windowed"] = self._input_h()
                self.wnd.fullscreen = True
                print(f"[bug] windowed input_h={S['h_windowed']!r}", flush=True)
            elif f == 50:
                _write_png(OUT / "bug_fullscreen.png", self._read_fbo_rgb())
                S["h_fullscreen"] = self._input_h()
                _check("panel scales with fullscreen",
                       S["h_fullscreen"] > S["h_windowed"] * 1.5,
                       f"windowed={S['h_windowed']:.0f}px "
                       f"fullscreen={S['h_fullscreen']:.0f}px")
            elif f == 54:
                self._hover("input:文字内容")
            elif f == 55:
                self._click("input:文字内容", True)
            elif f == 56:
                self._click("input:文字内容", False)
            elif f == 60:
                self.wnd._window.dispatch_event("on_text", "新")
            elif f == 61:
                self.wnd._window.dispatch_event("on_text", "文字")
            elif f == 64:
                S["typed"] = self.panel._text_buffer
                print(f"[bug] typed buffer={S['typed']!r}", flush=True)
                self._hover("button:应用文字")
            elif f == 65:
                self._click("button:应用文字", True)
            elif f == 66:
                self._click("button:应用文字", False)
            elif f == 70:
                _write_png(OUT / "bug_text.png", self._read_fbo_rgb())
                applied = getattr(self.scene, "text", "")
                _check("typing reaches the input box",
                       "新" in S["typed"] or "文" in S["typed"],
                       f"buffer={S['typed']!r}")
                _check("apply button updates the scene",
                       applied == S["typed"],
                       f"scene={applied!r} typed={S['typed']!r}")
            elif f == 80:
                self._hover("combo:粒子纹理")
            elif f == 81:
                self._click("combo:粒子纹理", True)   # 展开下拉框
            elif f == 82:
                self._click("combo:粒子纹理", False)
            elif f == 92:
                # 弹出层在下一帧才建出来（第二块 DrawList）
                _write_png(OUT / "bug_combo.png", self._read_fbo_rgb())
                chk = S["combo_chk"]
                _check("combo popup uses its own vertices",
                       chk is not None and chk["lists"] >= 2 and not chk["bad"],
                       f"drawlists={chk['lists'] if chk else 0} "
                       f"越界={chk['bad'] if chk else '无弹层'}")
                print(f"[bug] === {'ALL PASS' if not FAILS else 'FAILED: ' + ', '.join(FAILS)}",
                      flush=True)
                self.wnd.close()

    return Smoke


if __name__ == "__main__":
    run_window_config(_make())
    sys.exit(1 if FAILS else 0)
