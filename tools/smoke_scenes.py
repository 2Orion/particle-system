"""逐场景真实窗口冒烟 + 截图（不入库，开发期辅助脚本）。

运行：python -X utf8 tools/smoke_scenes.py
对每个场景：跑 N 帧 → 读 fbo → 统计亮度/粒子数 → 存 output/smoke_<key>.png
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import numpy as np

from main import ParticleApp, _write_png
from moderngl_window import run_window_config
from scenes import SCENE_ORDER

OUT = pathlib.Path(__file__).resolve().parents[1] / "output"
FRAMES = 300
_report: list[str] = []
_index = 0


def _run_scene(app: ParticleApp) -> None:
    global _index
    key = SCENE_ORDER[_index]
    app._load_scene(key)
    for _ in range(FRAMES):
        app.scene.update(1 / 60)

    app.wnd.use()
    app.ctx.clear(*app.clear_color)
    app.grid.render(app.camera, app.wnd.buffer_size)
    app.renderer.render(app.scene.system.pool, app.camera, app.wnd.buffer_size)

    data = np.frombuffer(app.wnd.fbo.read(components=3), dtype=np.uint8)
    img = data.reshape(app.wnd.fbo.height, app.wnd.fbo.width, 3)[::-1]
    bright = int((img.mean(axis=2) > 60).sum())
    _report.append(f"{key:10s} n={app.scene.count:6d} "
                   f"max={img.max():3d} mean={img.mean():5.1f} bright={bright:6d}")
    OUT.mkdir(exist_ok=True)
    _write_png(OUT / f"smoke_{key}.png", img)

    _index += 1
    if _index >= len(SCENE_ORDER):
        _print_and_exit()


def _print_and_exit() -> None:
    print("\n===== SCENE SMOKE =====")
    for line in _report:
        print(line)
    print("=======================")
    for mod in ("pyglet",):
        try:
            __import__(mod).app.exit()
        except Exception:
            pass


def _make_subclass():
    base = ParticleApp

    class SceneSmoke(base):
        def on_render(self, time_value, frame_time):
            if _index < len(SCENE_ORDER):
                try:
                    _run_scene(self)
                except Exception as exc:      # noqa: BLE001
                    _report.append(f"ERROR at {SCENE_ORDER[_index]}: {exc!r}")
                    _print_and_exit()

    return SceneSmoke


if __name__ == "__main__":
    t0 = time.perf_counter()
    run_window_config(_make_subclass())
    print(f"elapsed {time.perf_counter() - t0:.1f}s")
