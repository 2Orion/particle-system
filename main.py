"""程序入口：moderngl-window WindowConfig 模式。

WindowConfig 是渲染回调协议：库创建窗口并注入 ctx/wnd/timer，
每帧调用 config.on_render(time, frame_time)。相机输入通过 wnd 的事件转发。

操作：
  左键拖拽   旋转相机          右键拖拽   平移
  滚轮       缩放              1-4        切换场景
  R          重置当前场景       Space      暂停/继续
  F          保存截图到 output/             Esc        退出

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
from render.textures import gaussian_spot, ring, soft_disc
from scenes import SCENE_ORDER, SCENES

SCREENSHOT_DIR = pathlib.Path(__file__).parent / "output"

_TEXTURES = {
    "gaussian_spot": gaussian_spot,
    "soft_disc": soft_disc,
    "ring": ring,
}

# 每个场景的相机与地面配置：(target, distance, yaw, pitch, grid_extent)
_VIEWS = {
    "fountain": ((0.0, 3.2, 0.0), 13.0, 0.7, 0.26, 25.0),
    "snow": ((0.0, 9.0, 0.0), 34.0, 0.7, 0.22, 40.0),
    "fire": ((0.0, 2.6, 0.0), 11.0, 0.7, 0.18, 25.0),
    "fireworks": ((0.0, 9.0, 0.0), 30.0, 0.6, 0.12, 40.0),
}


class ParticleApp(WindowConfig):
    """渲染循环 + 场景切换。"""
    gl_version = (3, 3)
    title = "Particle System — 计算机动画课程作业"
    window_size = (1280, 720)
    aspect_ratio = None                  # 允许任意窗口比例
    resizable = True
    vsync = False
    clear_color = (0.04, 0.05, 0.08, 1.0)

    def __init__(self, ctx=None, wnd=None, timer=None, **kwargs) -> None:
        super().__init__(ctx=ctx, wnd=wnd, timer=timer, **kwargs)
        # 先初始化 _load_scene 会读到的状态（FPS），再装载首个场景
        self.fps = 0.0
        self._fps_t = time.perf_counter()
        self._fps_frames = 0
        self.paused = False
        self.camera = OrbitCamera()
        self.grid = None
        self.renderer = None
        self.scene = None
        self.scene_key = ""
        self._load_scene(SCENE_ORDER[0])

    # -------------------------------------------------- 场景

    def _load_scene(self, key: str) -> None:
        """切换场景：重建场景 + 渲染器（混合模式/纹理由场景声明）。"""
        self.scene = SCENES[key]()
        self.scene_key = key
        target, distance, yaw, pitch, extent = _VIEWS[key]
        self.camera = OrbitCamera(target=target, distance=distance,
                                  yaw=yaw, pitch=pitch)
        blend = self.scene.blend
        if self.renderer is None:
            self.renderer = ParticleRenderer(self.ctx, self.scene.capacity,
                                             blend=blend)
        else:
            # 混合模式在构造时固定；变化时重建
            if self.renderer.blend != blend:
                self.renderer.release()
                self.renderer = ParticleRenderer(self.ctx, self.scene.capacity,
                                                 blend=blend)
            elif self.renderer.max_particles != self.scene.capacity:
                self.renderer = ParticleRenderer(self.ctx, self.scene.capacity,
                                                 blend=blend)
        self.renderer.set_texture(_TEXTURES[self.scene.texture]())
        if self.grid is None or abs(self.grid.extent - extent) > 1e-6:
            self.grid = GridRenderer(self.ctx, extent=extent)
        self._update_title()

    def switch_scene(self, index: int) -> None:
        if 0 <= index < len(SCENE_ORDER):
            self._load_scene(SCENE_ORDER[index])

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
        elif key == keys.R:
            self.scene.reset()
        else:
            # 键常量在不同后端是字符串/整数，统一走查找表（NUMBER_1..4 切场景）
            for i in range(len(SCENE_ORDER)):
                if key == getattr(keys, f"NUMBER_{i + 1}", None):
                    self.switch_scene(i)
                    break

    def save_screenshot(self) -> None:
        """当前帧 fbo → PNG（zlib + 手工 chunk，免图像库依赖）。"""
        SCREENSHOT_DIR.mkdir(exist_ok=True)
        data = np.frombuffer(self.wnd.fbo.read(components=3),
                             dtype=np.uint8).reshape(self.wnd.fbo.height,
                                                     self.wnd.fbo.width, 3)
        data = data[::-1, :, :]  # GL 自底向上 → 图像自顶向下
        out = SCREENSHOT_DIR / f"{self.scene_key}_{int(self.timer.time * 1000)}.png"
        _write_png(out, data)
        print(f"截图已保存: {out}")

    # -------------------------------------------------- 渲染循环

    def _update_title(self) -> None:
        self.wnd.title = (f"Particle System — {self.scene.name} | "
                          f"{self.scene.count} 粒子 | {self.fps:.0f} FPS | "
                          f"1-4 切场景 Space=暂停 F=截图 R=重置")

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
            self._update_title()


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
