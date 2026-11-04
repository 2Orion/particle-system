"""程序入口：moderngl-window WindowConfig 模式 + ImGui 面板 + MP4 录制。

操作：
  左键拖拽   旋转相机          右键拖拽   平移
  滚轮       缩放              1-5        切换场景
  R          开始/停止录制      T          重置当前场景
  G          显隐 ImGui 面板    Space      暂停/继续
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
from ui import Panel
from utils import Recorder

OUTPUT_DIR = pathlib.Path(__file__).parent / "output"

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
    "text": ((0.0, 2.2, 0.0), 13.0, 0.0, 0.06, 25.0),
}

RECORD_FPS = 60


class ParticleApp(WindowConfig):
    """渲染循环 + 场景切换 + 面板 + 录制。"""
    gl_version = (3, 3)
    title = "Particle System — 计算机动画课程作业"
    window_size = (1280, 720)
    aspect_ratio = None                  # 允许任意窗口比例
    resizable = True
    vsync = False
    clear_color = (0.04, 0.05, 0.08, 1.0)

    # 供面板与快捷键共用
    scene_order = SCENE_ORDER

    def __init__(self, ctx=None, wnd=None, timer=None, **kwargs) -> None:
        super().__init__(ctx=ctx, wnd=wnd, timer=timer, **kwargs)
        # 先初始化 _load_scene 会读到的状态（FPS），再装载首个场景
        self.fps = 0.0
        self._fps_t = time.perf_counter()
        self._fps_frames = 0
        self.paused = False
        self.time_scale = 1.0
        self.show_grid = True
        self.camera = OrbitCamera()
        self.grid = None
        self.renderer = None
        self.scene = None
        self.scene_key = ""
        self.recorder: Recorder | None = None
        self._load_scene(SCENE_ORDER[0])

        # ImGui（imgui-bundle 缺失时 Panel.available=False，自动降级）
        self.panel = Panel()
        self._imgui = None
        self._setup_imgui()

    # -------------------------------------------------- ImGui

    def _setup_imgui(self) -> None:
        if not Panel.available:
            print("[ui] 未安装 imgui-bundle，使用快捷键模式")
            return
        from ui.imgui_backend import build_imgui_renderer
        # 面板是增强功能：任何集成失败都降级而非崩溃（plan §10 兜底）
        self._imgui = build_imgui_renderer(self.wnd)
        if self._imgui is not None:
            print("[ui] ImGui 面板已启用（G 键显隐）")

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
        elif self.renderer.blend != blend or \
                self.renderer.max_particles != self.scene.capacity:
            self.renderer.release()
            self.renderer = ParticleRenderer(self.ctx, self.scene.capacity,
                                             blend=blend)
        self.renderer.set_texture(_TEXTURES[self.scene.texture]())
        if self.grid is None or abs(self.grid.extent - extent) > 1e-6:
            self.grid = GridRenderer(self.ctx, extent=extent)
        self._update_title()

    def switch_scene(self, index: int) -> None:
        if 0 <= index < len(SCENE_ORDER):
            self._load_scene(SCENE_ORDER[index])

    def set_texture(self, name: str) -> None:
        """面板切换粒子纹理（覆盖场景默认纹理）。"""
        if name in _TEXTURES:
            self.scene.texture = name
            self.renderer.set_texture(_TEXTURES[name]())

    # -------------------------------------------------- 输入（wnd 事件）

    def on_mouse_drag_event(self, x, y, dx, dy) -> None:
        if self._imgui is not None:
            self._imgui.mouse_drag_event(x, y, dx, dy)
            if self.panel.wants_mouse:
                return                              # 面板在拖拽时不转相机
        # mouse_states 是属性对象（.left/.right），不是字典（见后端同类修复）
        if self.wnd.mouse_states.left:
            self.camera.rotate(dx, dy)
        elif self.wnd.mouse_states.right:
            self.camera.pan(dx, dy)

    def on_mouse_position_event(self, x, y, dx, dy) -> None:
        if self._imgui is not None:
            self._imgui.mouse_position_event(x, y, dx, dy)
            if self.panel.wants_mouse:
                return
        # 文字场景：鼠标在世界平面上的位置作为排斥源（扰动文字）
        scene = self.scene
        if hasattr(scene, "set_mouse_world"):
            p = self.camera.project_to_plane(x, y, self.wnd.buffer_size)
            scene.set_mouse_world(p)

    def on_mouse_press_event(self, x, y, button) -> None:
        if self._imgui is not None:
            self._imgui.mouse_press_event(x, y, button)

    def on_mouse_release_event(self, x, y, button) -> None:
        if self._imgui is not None:
            self._imgui.mouse_release_event(x, y, button)

    def on_mouse_scroll_event(self, x_offset, y_offset) -> None:
        if self._imgui is not None:
            self._imgui.mouse_scroll_event(x_offset, y_offset)
            if self.panel.wants_mouse:
                return
        self.camera.zoom(1.1 ** y_offset)

    def on_unicode_char_entered(self, char) -> None:
        if self._imgui is not None:
            self._imgui.unicode_char_entered(char)

    def on_key_event(self, key, action, modifiers) -> None:
        if self._imgui is not None:
            self._imgui.key_event(key, action, modifiers)
            # 注意：面板自己也要靠这些键（输入框），所以只拦"按下的普通键"；
            # Space/F/G/T/R/数字等单键快捷键在面板聚焦时不响应，避免打字误触。
            if self.panel.wants_keyboard:
                return
        if action != self.wnd.keys.ACTION_PRESS:
            return
        keys = self.wnd.keys
        if key == keys.SPACE:
            self.paused = not self.paused
        elif key == keys.F:
            self.save_screenshot()
        elif key == keys.T:
            self.scene.reset()
        elif key == keys.R:
            self.toggle_recording()
        elif key == keys.G:
            self.panel.toggle()
        else:
            # 键常量在不同后端是字符串/整数，统一走查找表（NUMBER_1..5 切场景）
            for i in range(len(SCENE_ORDER)):
                if key == getattr(keys, f"NUMBER_{i + 1}", None):
                    self.switch_scene(i)
                    break

    def on_close(self) -> None:
        if self.recorder is not None:
            path = self.recorder.close()
            print(f"录制已保存（窗口关闭）: {path}")

    # -------------------------------------------------- 录制 / 截图

    def toggle_recording(self) -> None:
        if self.recorder is None:
            try:
                w, h = self.wnd.buffer_size
                path = OUTPUT_DIR / f"demo_{self.scene_key}_{int(time.time())}.mp4"
                self.recorder = Recorder(path, (w, h), fps=RECORD_FPS)
                print(f"开始录制 → {path}")
            except Exception as exc:              # noqa: BLE001
                print(f"录制启动失败: {exc}")
                self.recorder = None
        else:
            path = self.recorder.close()
            print(f"录制已保存: {path}（{self.recorder.frames} 帧）")
            self.recorder = None
        self._update_title()

    def _read_fbo_rgb(self) -> np.ndarray:
        """当前帧 fbo → (h,w,3) uint8，自顶向下。

        必须显式传 viewport：`ctx.screen` 是创建时缓存的 Framebuffer
        对象，窗口切全屏后它的内部 `_size` 仍是旧值，`read()` 不带
        viewport 就只会读回原来那块 1280×720 区域。
        """
        w, h = self.wnd.buffer_size
        data = np.frombuffer(
            self.wnd.fbo.read(components=3, viewport=(0, 0, w, h)),
            dtype=np.uint8).reshape(h, w, 3)
        return np.ascontiguousarray(data[::-1, :, :])

    def save_screenshot(self) -> None:
        """当前帧 fbo → PNG（zlib + 手工 chunk，免图像库依赖）。"""
        OUTPUT_DIR.mkdir(exist_ok=True)
        out = OUTPUT_DIR / f"{self.scene_key}_{int(self.timer.time * 1000)}.png"
        _write_png(out, self._read_fbo_rgb())
        print(f"截图已保存: {out}")

    # -------------------------------------------------- 渲染循环

    def _update_title(self) -> None:
        rec = " | ●录制中" if self.recorder is not None else ""
        self.wnd.title = (f"Particle System — {self.scene.name} | "
                          f"{self.scene.count} 粒子 | {self.fps:.0f} FPS{rec} | "
                          f"1-5 切场景 G=面板 Space=暂停 F=截图 R=录制 T=重置")

    def on_render(self, time_value: float, frame_time: float) -> None:
        dt = min(frame_time, 1.0 / 20.0)  # 帧间隔上限防大步长
        if not self.paused:
            self.scene.update(dt * self.time_scale)
        self.wnd.use()
        # 尺寸一律取 buffer_size，并把 viewport 显式传下去：全屏后
        # `ctx.screen` 缓存的尺寸还是旧的，不传就只清理/绘制左上角一块。
        size = self.wnd.buffer_size
        self.ctx.clear(*self.clear_color, viewport=(0, 0, *size))

        if self.show_grid:
            self.grid.render(self.camera, size)
        self.renderer.render(self.scene.system.pool, self.camera, size)

        # ImGui 面板（必须在本帧粒子之后绘制）
        if self._imgui is not None:
            # 面板字号/间距跟着窗口放大：全屏（2560×1600）下 1 倍 UI 只占
            # 左上角一小块，看着像坏了。用窗口逻辑尺寸算倍数，高 DPI 由
            # display_framebuffer_scale 单独处理，两者不重复叠加。
            self.panel.draw(self, self.renderer,
                            scale=Panel.scale_for(*self.wnd.size))
            self._imgui.render(self.panel.draw_data())

        # 录制：读回本帧像素（含面板，成片与所见一致）
        if self.recorder is not None:
            self.recorder.add_frame(self._read_fbo_rgb())

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
