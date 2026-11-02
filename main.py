"""程序入口：moderngl-window WindowConfig 模式。

WindowConfig 是渲染回调协议：库创建窗口并注入 ctx/wnd/timer，
每帧调用 config.render(time, frame_time)。相机输入通过 wnd 的事件转发。

操作：
  左键拖拽   旋转相机          右键拖拽   平移
  滚轮       缩放              Space      暂停/继续
  F          保存截图到 output/
  Esc        退出

运行：python main.py
"""
from __future__ import annotations

import pathlib
import struct
import time
import zlib

import numpy as np
from moderngl_window import WindowConfig, run_window_config

from render.camera import OrbitCamera
from render.ground import GridRenderer
from render.particles import ParticleRenderer
from scenes import FountainScene

SCREENSHOT_DIR = pathlib.Path(__file__).parent / "output"


class ParticleApp(WindowConfig):
    """渲染循环（第二轮：喷泉场景，场景切换待后续轮次）。"""
    gl_version = (3, 3)
    title = "Particle System — 计算机动画课程作业"
    window_size = (1280, 720)
    aspect_ratio = None                  # 允许任意窗口比例
    resizable = True
    vsync = False
    clear_color = (0.04, 0.05, 0.08, 1.0)

    def __init__(self, ctx=None, wnd=None, timer=None, **kwargs) -> None:
        super().__init__(ctx=ctx, wnd=wnd, timer=timer, **kwargs)
        self.camera = OrbitCamera(target=(0.0, 3.0, 0.0), distance=16.0,
                                  yaw=0.7, pitch=0.30)
        self.scene = FountainScene()
        self.renderer = ParticleRenderer(self.ctx, self.scene.capacity,
                                         blend="additive")
        self.grid = GridRenderer(self.ctx, extent=25.0)
        self.paused = False
        self._fps_t = time.perf_counter()
        self._fps_frames = 0
        self.fps = 0.0

    # -------------------------------------------------- 输入（wnd 事件）

    def on_mouse_drag_event(self, x, y, dx, dy) -> None:
        if self.wnd.mouse_states["left"]:
            self.camera.rotate(dx, dy)
        elif self.wnd.mouse_states["right"]:
            self.camera.pan(dx, dy)

    def on_mouse_scroll_event(self, x_offset, y_offset) -> None:
        self.camera.zoom(1.1 ** y_offset)

    def on_key_event(self, key, action, modifiers) -> None:
        if action != self.wnd.keys.ACTION_PRESS:
            return
        keys = self.wnd.keys
        if key == keys.SPACE:
            self.paused = not self.paused
        elif key == keys.F:
            self.save_screenshot()

    def save_screenshot(self) -> None:
        """当前帧 fbo → PNG（zlib + 手工 chunk，免图像库依赖）。"""
        SCREENSHOT_DIR.mkdir(exist_ok=True)
        data = np.frombuffer(self.wnd.fbo.read(components=3),
                             dtype=np.uint8).reshape(self.wnd.fbo.height,
                                                     self.wnd.fbo.width, 3)
        data = data[::-1, :, :]  # GL 自底向上 → 图像自顶向下
        out = SCREENSHOT_DIR / f"frame_{int(self.timer.time * 1000)}.png"
        _write_png(out, data)
        print(f"截图已保存: {out}")

    # -------------------------------------------------- 渲染循环

    def on_render(self, time_value: float, frame_time: float) -> None:
        dt = min(frame_time, 1.0 / 20.0)  # 帧间隔上限防大步长
        if not self.paused:
            self.scene.update(dt)
        self.wnd.use()
        self.ctx.clear(*self.clear_color)

        self.grid.render(self.camera, self.wnd.buffer_size)
        self.renderer.render(self.scene.system.pool, self.camera,
                             self.wnd.buffer_size)

        # FPS 统计（每 0.5s 更新，写标题栏）
        self._fps_frames += 1
        now = time.perf_counter()
        if now - self._fps_t >= 0.5:
            self.fps = self._fps_frames / (now - self._fps_t)
            self._fps_t, self._fps_frames = now, 0
            n = self.scene.system.pool.count
            self.wnd.title = (f"Particle System — {n} 粒子 | "
                              f"{self.fps:.0f} FPS | Space=暂停 F=截图")


def _write_png(path: pathlib.Path, rgb: np.ndarray) -> None:
    """最小 PNG 写出（zlib + 手工 chunk），免图像库依赖。"""
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[row].tobytes() for row in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    path.write_bytes(png)


def main() -> None:
    run_window_config(ParticleApp)


if __name__ == "__main__":
    main()
