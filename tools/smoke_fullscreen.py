"""全屏/还原/缩放下 ImGui 面板尺寸同步冒烟。

运行：python -X utf8 tools/smoke_fullscreen.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from moderngl_window import run_window_config

from main import ParticleApp, _write_png

OUT = pathlib.Path(__file__).resolve().parents[1] / "output"

CHECKPOINTS = [(60, "windowed"), (61, "-> fullscreen"),
               (120, "fullscreen"), (121, "-> windowed"),
               (180, "windowed again")]


def _make():
    class Smoke(ParticleApp):
        def _report(self, tag: str, shot: str | None = None) -> None:
            win = tuple(self.wnd.size)
            buf = tuple(self.wnd.buffer_size)
            msg = f"[fs] {tag:16s} window={win} buffer={buf}"
            if self._imgui is not None:
                io = self._imgui.io
                msg += (f" io.display_size={tuple(io.display_size)}"
                        f" scale={tuple(io.display_framebuffer_scale)}")
            print(msg, flush=True)
            if shot:
                img = self._read_fbo_rgb()
                _write_png(OUT / f"{shot}.png", img)
                print(f"[fs]   saved {shot}.png {img.shape}", flush=True)

        def on_render(self, time_value, frame_time):
            super().on_render(time_value, frame_time)
            self._frame = getattr(self, "_frame", 0) + 1
            f = self._frame
            if f == 60:
                self._report("windowed", "fs_before")
                self.wnd.fullscreen = True
            elif f == 120:
                self._report("fullscreen", "fs_after")
                self.wnd.fullscreen = False
            elif f == 180:
                self._report("windowed again", "fs_restored")
                print("[fs] DONE", flush=True)
                self.wnd.close()

    return Smoke


if __name__ == "__main__":
    run_window_config(_make())
