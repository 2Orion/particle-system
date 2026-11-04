"""报告配图：离屏渲染五个场景在指定时刻的画面（不入库，配合 report.typ）。

不依赖窗口系统：`moderngl.create_context(standalone=True)` 起离屏上下文，
按 `main.py` 的相机参数逐场景推进仿真，在若干仿真时刻截图。
好处是同一场景的"起始 / 中间 / 结束"三帧取的是**同一相机、同一参数**，
画面可比；也不会被面板挡住。

运行：python -X utf8 tools/report_figs.py
输出：output/fig/<key>_t<time>.png
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import moderngl
import numpy as np

from main import _VIEWS, _write_png
from render.camera import OrbitCamera
from render.ground import GridRenderer
from render.particles import ParticleRenderer
from render.textures import gaussian_spot, ring, soft_disc
from scenes import SCENES

OUT = pathlib.Path(__file__).resolve().parents[1] / "output" / "fig"
SIZE = (1280, 720)
DT = 1.0 / 60.0
TEXTURES = {"gaussian_spot": gaussian_spot, "soft_disc": soft_disc, "ring": ring}

# 每个场景要截图的仿真时刻（秒）
SHOTS = {
    "fountain": [0.9, 2.4, 6.0],
    "snow": [2.0, 6.0, 12.0],
    "fire": [0.7, 2.2, 5.0],
    "fireworks": [0.45, 1.15, 2.9],
    "text": [0.25, 0.85, 3.0, 6.0],
}


def _render(ctx, fbo, scene, renderer, grid, cam, path) -> None:
    fbo.use()
    ctx.clear(0.04, 0.05, 0.08, 1.0)
    grid.render(cam, SIZE)
    renderer.render(scene.system.pool, cam, SIZE)
    raw = np.frombuffer(fbo.read(components=3), dtype=np.uint8)
    img = raw.reshape(SIZE[1], SIZE[0], 3)[::-1]
    _write_png(path, img)
    bright = int((img.mean(axis=2) > 60).sum())
    print(f"  {path.name:34s} n={scene.count:6d} bright={bright:7d}",
          flush=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ctx = moderngl.create_context(standalone=True)
    fbo = ctx.simple_framebuffer(SIZE, components=3)   # 自带深度附件

    for key, shots in SHOTS.items():
        scene = SCENES[key]()
        target, distance, yaw, pitch, extent = _VIEWS[key]
        cam = OrbitCamera(target=target, distance=distance, yaw=yaw, pitch=pitch)
        grid = GridRenderer(ctx, extent=extent)
        renderer = ParticleRenderer(ctx, scene.capacity, blend=scene.blend)
        renderer.set_texture(TEXTURES[scene.texture]())

        print(f"[{key}]", flush=True)
        elapsed = 0.0
        for t in shots:
            while elapsed < t - 1e-9:
                scene.update(DT)
                elapsed += DT
            _render(ctx, fbo, scene, renderer, grid, cam,
                    OUT / f"{key}_t{t:04.2f}.png".replace(" ", "0"))

        renderer.release()
        grid.release()

    # 额外：雪场景 additive / alpha 混合对比（同一堆粒子，只换混合模式）
    print("[blend]", flush=True)
    scene = SCENES["snow"]()
    target, distance, yaw, pitch, extent = _VIEWS["snow"]
    cam = OrbitCamera(target=target, distance=distance, yaw=yaw, pitch=pitch)
    grid = GridRenderer(ctx, extent=extent)
    for _ in range(int(4.0 / DT)):
        scene.update(DT)
    for blend in ("additive", "alpha"):
        renderer = ParticleRenderer(ctx, scene.capacity, blend=blend)
        renderer.set_texture(soft_disc())
        fbo.use()
        ctx.clear(0.04, 0.05, 0.08, 1.0)
        grid.render(cam, SIZE)
        renderer.render(scene.system.pool, cam, SIZE)
        img = np.frombuffer(fbo.read(components=3), dtype=np.uint8)
        img = img.reshape(SIZE[1], SIZE[0], 3)[::-1]
        _write_png(OUT / f"blend_{blend}.png", img)
        lum = img.mean(axis=2)
        print(f"  blend_{blend:9s} mean_lum={lum.mean():6.2f} "
              f"bright={int((lum > 60).sum()):7d} "
              f"saturated={int((lum > 250).sum()):6d}", flush=True)
        renderer.release()

    grid.release()
    fbo.release()
    ctx.release()


if __name__ == "__main__":
    main()
