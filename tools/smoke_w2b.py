"""W2 后半冒烟：真实窗口跑文字场景 + ImGui 面板 + 录制几帧 MP4。

文字粒子靠软约束收敛，需要 ~4s 物理时间才成形，所以各检查点都按
**仿真时间**推进 —— 真实帧率随机器变化（本机 300~440 FPS），按帧数计
会让"第 420 帧"只跑到 1.5s，拍到的是没收敛的散点。

运行：python -X utf8 tools/smoke_w2b.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from moderngl_window import run_window_config

from main import ParticleApp, _write_png

OUT = pathlib.Path(__file__).resolve().parents[1] / "output"

# 阶段（严格单调推进，避免重复触发）：
#   0 刚启动 → 1 已切文字场景 → 2 已拍收敛图 → 3 已开始录制
#   → 4 已停止录制并换字 → 5 已拍 morph 图 → 收尾
_STAGE = {"n": 0}


def _make():
    class Smoke(ParticleApp):
        def on_render(self, time_value, frame_time):
            super().on_render(time_value, frame_time)
            frame = getattr(self, "_frame", 0) + 1
            self._frame = frame

            if _STAGE["n"] == 0 and frame >= 30:
                _STAGE["n"] = 1
                self.switch_scene(4)
                print(f"[smoke] switched to {self.scene_key}, "
                      f"count={self.scene.count}", flush=True)
                return

            t = self.scene.system.time
            stage = _STAGE["n"]

            if stage == 1 and t >= 6.0:
                _STAGE["n"] = 2
                img = self._read_fbo_rgb()
                _write_png(OUT / "w2b_text_converged.png", img)
                print(f"[smoke] t={t:.2f}s 收敛截图 bright="
                      f"{int((img.mean(axis=2) > 60).sum())}", flush=True)
            elif stage == 2 and t >= 6.5:
                _STAGE["n"] = 3
                self.toggle_recording()
                print(f"[smoke] recording -> {self.recorder.path}", flush=True)
            elif stage == 3 and t >= 8.0:
                _STAGE["n"] = 4
                rec = self.recorder
                path = rec.close()
                self.recorder = None
                print(f"[smoke] mp4 {rec.frames} 帧, "
                      f"{path.stat().st_size} 字节", flush=True)
                self.scene.set_text("Computer Animation")
                print(f"[smoke] morph -> {self.scene.text!r}", flush=True)
            elif stage == 4 and t >= 12.0:
                _STAGE["n"] = 5
                img = self._read_fbo_rgb()
                _write_png(OUT / "w2b_text_morphed.png", img)
                print(f"[smoke] t={t:.2f}s morph 截图 bright="
                      f"{int((img.mean(axis=2) > 60).sum())}", flush=True)
                print(f"[smoke] DONE ({self.fps:.0f} FPS)", flush=True)
                # run_window_config 的循环条件是 window.is_closing，
                # pyglet.app.exit() 对它无效 —— 必须走 wnd.close()
                self.wnd.close()

    return Smoke


if __name__ == "__main__":
    run_window_config(_make())
