"""ImGui + moderngl 渲染后端（自实现，绕开 moderngl-window 的版本不兼容）。

为什么不用 `moderngl_window.integrations.imgui_bundle`：
v3.1.1 的 `ModernGLRenderer.refresh_font_texture()` 调用
`io.fonts.get_tex_data_as_rgba32()`。Dear ImGui 1.91 重构字体系统后
该 API 已删除，imgui-bundle 1.93 走的是新的 `ImTextureData` +
`BackendFlags_RendererHasTextures` 协议：后端不再一次性上传字体图集，
而是在每帧检查 `platform_io.textures` 里各纹理的 status
（want_create / want_updates / want_destroy）按需创建与增量更新。

本文件实现这套协议的 moderngl 版本，并保留 moderngl-window 的
事件转发逻辑（鼠标/键盘 → io），这样 `Panel` 与事件过滤都能复用。
"""
from __future__ import annotations

import ctypes
import os

import moderngl
import numpy as np
from imgui_bundle import imgui

VERTEX_SHADER = """
#version 330
uniform mat4 ProjMtx;
in vec2 Position;
in vec2 UV;
in vec4 Color;
out vec2 Frag_UV;
out vec4 Frag_Color;
void main() {
    Frag_UV = UV;
    Frag_Color = Color;
    gl_Position = ProjMtx * vec4(Position.xy, 0.0, 1.0);
}
"""

# ImDrawVert 的宿主内存布局：pos(vec2) + uv(vec2) + col(4×ubyte, 归一化)。
# "4f1" 是 moderngl 的"4 个归一化无符号字节"，用错成 "4f" 会 stride 错位。
VERTEX_FORMAT = "2f 2f 4f1"

FRAGMENT_SHADER = """
#version 330
uniform sampler2D Texture;
in vec2 Frag_UV;
in vec4 Frag_Color;
out vec4 Out_Color;
void main() {
    Out_Color = Frag_Color * texture(Texture, Frag_UV.st);
}
"""


class ImGuiModernGLRenderer:
    """Dear ImGui 的 moderngl 渲染后端（含新版多纹理协议 + 事件转发）。"""

    def __init__(self, window) -> None:
        if not imgui.get_current_context():
            raise RuntimeError("需要先 imgui.create_context()")
        self.wnd = window
        self.ctx: moderngl.Context = window.ctx
        self.io = imgui.get_io()
        self.io.delta_time = 1.0 / 60.0
        self.io.display_size = window.size
        self.io.display_framebuffer_scale = (window.pixel_ratio,
                                             window.pixel_ratio)

        # 新协议：告诉 ImGui 后端自己管纹理，ImGui 会把待处理纹理放进 platform_io
        self.io.backend_flags |= imgui.BackendFlags_.renderer_has_textures
        max_tex = int(self.ctx.info.get("GL_MAX_TEXTURE_SIZE", 4096))
        platform_io = imgui.get_platform_io()
        platform_io.renderer_texture_max_width = max_tex
        platform_io.renderer_texture_max_height = max_tex

        self._prog = self.ctx.program(vertex_shader=VERTEX_SHADER,
                                      fragment_shader=FRAGMENT_SHADER)
        self._proj = self._prog["ProjMtx"]

        # ImDrawIdx 宽度由 imgui 编译选项决定（官方默认 32 位 = 4 字节）
        self._index_size = imgui.INDEX_SIZE
        # 每帧最大顶点/索引数据量：按 ImGui 常见规模预留，超出则扩容
        self._vbo = self.ctx.buffer(reserve=1 << 16)     # 64 KiB
        self._ibo = self.ctx.buffer(reserve=1 << 16)
        self._vao = self._make_vao()
        # 按下/释放的批内去重：drag 需要"按住状态下位置变化"跨两个
        # ImGui 时间步才激活，同一批内的 down+move 必须拆成两步喂
        self._btn_batch: list[tuple[float, float, bool]] = []
        self._pump_armed = False
        # GL 纹理句柄 → moderngl.Texture
        self._textures: dict[int, moderngl.Texture] = {}
        self._init_key_map()
        self._setup_font()

    # -------------------------------------------------- 字体

    # Dear ImGui 1.92+ 改成按需动态光栅化，ImFontConfig 里不再有
    # glyph_ranges —— 加一个含 CJK 的 TTF 就能显示任意汉字。
    FONT_CANDIDATES = (
        "C:/Windows/Fonts/msyh.ttc",            # 微软雅黑
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simhei.ttf",          # 黑体
        "C:/Windows/Fonts/Deng.ttf",            # 等线
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    )
    FONT_SIZE = 16.0

    def _setup_font(self) -> None:
        atlas = self.io.fonts
        cfg = imgui.ImFontConfig()
        cfg.oversample_h = 2
        cfg.oversample_v = 2
        for path in self.FONT_CANDIDATES:
            if not os.path.exists(path):
                continue
            try:
                atlas.add_font_from_file_ttf(path, self.FONT_SIZE, cfg)
                self.font_path = path
                return
            except Exception:                   # noqa: BLE001 - 换下一个候选
                continue
        self.font_path = None                   # 退回内置默认字体（无 CJK）

    # -------------------------------------------------- 事件转发

    def _make_vao(self):
        return self.ctx.vertex_array(
            self._prog, [(self._vbo, VERTEX_FORMAT,
                          "Position", "UV", "Color")],
            index_buffer=self._ibo, index_element_size=self._index_size)

    def _init_key_map(self) -> None:
        keys = self.wnd.keys
        self._keymap = {
            keys.TAB: imgui.Key.tab, keys.LEFT: imgui.Key.left_arrow,
            keys.RIGHT: imgui.Key.right_arrow, keys.UP: imgui.Key.up_arrow,
            keys.DOWN: imgui.Key.down_arrow, keys.PAGE_UP: imgui.Key.page_up,
            keys.PAGE_DOWN: imgui.Key.page_down, keys.HOME: imgui.Key.home,
            keys.END: imgui.Key.end, keys.DELETE: imgui.Key.delete,
            keys.SPACE: imgui.Key.space, keys.BACKSPACE: imgui.Key.backspace,
            keys.ENTER: imgui.Key.enter, keys.ESCAPE: imgui.Key.escape,
        }

    def _viewport_pos(self, x, y):
        """窗口坐标 → ImGui 显示坐标（处理高 DPI 黑边偏移）。"""
        ox = (self.wnd.width - self.wnd.viewport_width / self.wnd.pixel_ratio) / 2
        oy = (self.wnd.height - self.wnd.viewport_height / self.wnd.pixel_ratio) / 2
        return int(x - ox), int(y - oy)

    def key_event(self, key, action, modifiers) -> None:
        if key in self._keymap:
            down = action == self.wnd.keys.ACTION_PRESS
            self.io.add_key_event(self._keymap[key], down)

    def mouse_position_event(self, x, y, dx, dy) -> None:
        self.io.mouse_pos = self._viewport_pos(x, y)

    def mouse_drag_event(self, x, y, dx, dy) -> None:
        self.io.mouse_pos = self._viewport_pos(x, y)
        # MouseButtonStates 只有属性（left/right/middle），不可下标——
        # 原来的 states["left"] 每次拖动都抛 TypeError，异常穿透到
        # pyglet 的 WndProc 回调被吞，只在 stderr 打回溯；更糟的是
        # main.on_mouse_drag_event 里排在它后面的相机分支也一起被跳过。
        states = self.wnd.mouse_states
        self.io.mouse_down[0] = bool(states.left)
        self.io.mouse_down[2] = bool(states.middle)
        self.io.mouse_down[1] = bool(states.right)
        # 按住状态下的位置更新与按下落在同一批时，标记待拆步；
        # Panel.draw 会调用 take_press_pump 补一个迷你 ImGui 时间步
        if self._btn_batch:
            self._pump_armed = True

    def take_press_pump(self):
        """若本批内"左键按下"与"按住移动"同时到达，返回按下位置。

        Panel.draw 每帧开头询问一次；返回 (x, y) 表示需要拆步，
        返回 None 表示无积压。按下/释放各取一个，剩余释放留到下一帧。
        """
        if not self._pump_armed:
            return None
        self._pump_armed = False
        if not self._btn_batch:
            return None
        x, y, down = self._btn_batch.pop(0)
        return self._viewport_pos(x, y) if down else None

    def end_batch(self) -> None:
        """渲染帧结束时调用：处理延后的释放。

        release 在批内被延后（见 mouse_release_event）的，下一帧开始时
        才真正把 io.mouse_down 置 False——本帧主步已按"按住"消费完。
        """
        if self._btn_batch:
            _, _, down = self._btn_batch.pop(0)
            self.io.mouse_down[0] = bool(down)

    def mouse_press_event(self, x, y, button) -> None:
        self.io.mouse_pos = self._viewport_pos(x, y)
        idx = self._button_index(button)
        if idx is not None:
            self.io.mouse_down[idx] = True
            if idx == 0:
                self._btn_batch.append((x, y, True))

    def mouse_release_event(self, x, y, button) -> None:
        self.io.mouse_pos = self._viewport_pos(x, y)
        idx = self._button_index(button)
        if idx is not None:
            if idx == 0 and self._btn_batch:
                # 左键释放与按下同批：延后到下一帧再置 False。立刻置位
                # 会让"按住+移动"的主帧看不到按键，drag 值不更新
                #（探针验证：pump 后主帧 down=False → 值不动）。
                self._btn_batch.append((x, y, False))
            else:
                self.io.mouse_down[idx] = False

    def _button_index(self, button):
        mouse = self.wnd.mouse
        if button == mouse.left:
            return 0
        if button == mouse.right:
            return 1
        if button == mouse.middle:
            return 2
        return None

    def mouse_scroll_event(self, x_offset, y_offset) -> None:
        self.io.mouse_wheel_h = x_offset
        self.io.mouse_wheel = y_offset

    def unicode_char_entered(self, char) -> None:
        # 不能用 ord(char)：中文输入法提交时 pyglet 一次给整串
        # （例如提交"测试"给 2 个字符），ord() 只接受单字符会抛 TypeError，
        # 异常还会穿透到 pyglet 的事件分发里，直接把程序打挂。
        self.io.add_input_characters_utf8(char)

    def resize(self, width, height) -> None:
        self._sync_display_size()

    def _sync_display_size(self) -> None:
        """每帧从窗口重新读取尺寸。

        不能只靠 on_resize 回调：`WindowConfig` 只有在子类实现了
        `on_resize` 时才把它绑给窗口，否则绑的是 `dummy_func`——
        进入全屏/最大化时窗口尺寸变了，这里却收不到通知。
        每帧同步一次最省事，也顺手覆盖了 DPI 缩放变化（buffer_size
        与 size 的比例可能同时改变）。
        """
        win_w, win_h = self.wnd.size
        if win_w <= 0 or win_h <= 0:        # 最小化时可能是 0
            return
        self.io.display_size = (float(win_w), float(win_h))
        buf_w, buf_h = self.wnd.buffer_size
        self.io.display_framebuffer_scale = (buf_w / win_w, buf_h / win_h)

    # -------------------------------------------------- 纹理（新协议）

    def _update_textures(self) -> None:
        """按 ImTextureData.status 创建/更新/销毁纹理（对应官方 OpenGL3 后端）。"""
        status_enum = imgui.ImTextureStatus
        for tex in list(imgui.get_platform_io().textures):
            status = tex.status
            if status == status_enum.want_create:
                self._create_texture(tex)
            elif status == status_enum.want_updates:
                self._update_texture(tex)
            elif status == status_enum.want_destroy:
                self._destroy_texture(tex)

    def _create_texture(self, tex) -> None:
        w, h = int(tex.width), int(tex.height)
        pixels = np.asarray(tex.get_pixels_array(), dtype=np.uint8)
        gl_tex = self.ctx.texture((w, h), 4, pixels.tobytes())
        gl_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        gl_tex.repeat_x = gl_tex.repeat_y = False
        tex.set_tex_id(gl_tex.glo)
        tex.status = imgui.ImTextureStatus.ok
        self._textures[gl_tex.glo] = gl_tex

    def _update_texture(self, tex) -> None:
        """增量更新 ImGui 标记的矩形块。

        `get_pixels_array()` 返回 (h*w*4,) 的扁平 uint8 缓冲（行优先），
        所以矩形块要靠手动切片换算，不能直接二维索引。
        """
        gl_tex = self._textures.get(int(tex.tex_id))
        if gl_tex is None:
            self._create_texture(tex)
            return
        tw, th = int(tex.width), int(tex.height)
        full = np.asarray(tex.get_pixels_array(), dtype=np.uint8).reshape(th, tw, 4)
        count = len(tex.updates)
        if count == 0:
            # 没有增量矩形：整块重传（字体图集重建时走这条）
            gl_tex.write(np.ascontiguousarray(full).tobytes())
        else:
            for i in range(count):
                rect = tex.updates[i]
                x, y = int(rect.x), int(rect.y)
                w, h = int(rect.w), int(rect.h)
                block = np.ascontiguousarray(full[y:y + h, x:x + w])
                gl_tex.write(block.tobytes(), viewport=(x, y, w, h))
        tex.status = imgui.ImTextureStatus.ok

    def _destroy_texture(self, tex) -> None:
        gl_tex = self._textures.pop(int(tex.tex_id), None)
        if gl_tex is not None:
            gl_tex.release()
        tex.set_tex_id(0)
        tex.status = imgui.ImTextureStatus.ok

    # -------------------------------------------------- 绘制

    def _rebase_indices(self, cmd_list, base_vertex: int) -> bytes:
        """把一块 DrawList 的索引整体加上 `base_vertex`，返回可直接上传的字节。"""
        n_idx = cmd_list.idx_buffer.size()
        if n_idx == 0:
            return b""
        dt = np.uint32 if self._index_size == 4 else np.uint16
        raw = (ctypes.c_ubyte * (n_idx * self._index_size)).from_address(
            cmd_list.idx_buffer.data_address())
        idx = np.frombuffer(raw, dtype=dt)
        if base_vertex:
            idx = idx + dt(base_vertex)
        return np.ascontiguousarray(idx).tobytes()

    def render(self, draw_data) -> None:
        if draw_data is None:
            return
        self._sync_display_size()
        self._update_textures()

        w, h = self.io.display_size
        fb_w = int(w * self.io.display_framebuffer_scale[0])
        fb_h = int(h * self.io.display_framebuffer_scale[1])
        if fb_w <= 0 or fb_h <= 0:
            return
        # 显式铺满整个帧缓冲（与官方 OpenGL3 后端一致）：不能指望粒子
        # 渲染器留下的那个视口，窗口尺寸变化后两者会不一致。
        # 下面的 scissor 也是按整个帧缓冲的高度做 y 翻转的，两者必须同基准。
        self.ctx.viewport = (0, 0, fb_w, fb_h)

        self._proj.write(np.array([
            2.0 / w, 0.0, 0.0, 0.0,
            0.0, -2.0 / h, 0.0, 0.0,
            0.0, 0.0, -1.0, 0.0,
            -1.0, 1.0, 0.0, 1.0,
        ], dtype="f4").tobytes())
        draw_data.scale_clip_rects(imgui.ImVec2(*self.io.display_framebuffer_scale))

        self.ctx.enable_only(moderngl.BLEND)
        self.ctx.blend_equation = moderngl.FUNC_ADD
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.ctx.disable(moderngl.DEPTH_TEST)
        self.ctx.disable(moderngl.CULL_FACE)

        # 与官方 OpenGL3 后端一致：所有 cmd_list 拼进同一块顶点/索引缓冲。
        # 鼠标拖出窗口等情况下会同时存在多个 DrawList，逐块从 0 写会互相覆盖。
        need_vtx = sum(cl.vtx_buffer.size() for cl in draw_data.cmd_lists) \
            * imgui.VERTEX_SIZE
        need_idx = sum(cl.idx_buffer.size() for cl in draw_data.cmd_lists) \
            * imgui.INDEX_SIZE
        if need_vtx > self._vbo.size or need_idx > self._ibo.size:
            self._vao.release()
            if need_vtx > self._vbo.size:
                self._vbo.release()
                self._vbo = self.ctx.buffer(reserve=need_vtx * 2)
            if need_idx > self._ibo.size:
                self._ibo.release()
                self._ibo = self.ctx.buffer(reserve=need_idx * 2)
            self._vao = self._make_vao()

        vtx_offset = idx_offset = 0
        for cmd_list in draw_data.cmd_lists:
            n_vtx = cmd_list.vtx_buffer.size()
            n_idx = cmd_list.idx_buffer.size()
            vtx_bytes = n_vtx * imgui.VERTEX_SIZE
            idx_bytes = n_idx * imgui.INDEX_SIZE
            vtx_type = ctypes.c_byte * vtx_bytes
            self._vbo.write(vtx_type.from_address(cmd_list.vtx_buffer.data_address()),
                            offset=vtx_offset)
            # 索引要重定基：每个 ImDrawList 的索引都从 0 开始编号（指向它
            # 自己的顶点），但顶点是**追加**到共享 VBO 的。不加重定基的话，
            # 第二块 DrawList（下拉框弹出层、悬浮提示等）会去索引第一块的
            # 顶点，屏幕上就是面板上糊着一块被拉长的三角形。
            # moderngl 的 vao.render() 没有 base-vertex 参数，只能改索引本身
            # （官方 OpenGL3 后端也是这么做的）。
            base_vertex = vtx_offset // imgui.VERTEX_SIZE
            self._ibo.write(self._rebase_indices(cmd_list, base_vertex),
                            offset=idx_offset)

            elem_offset = idx_offset // imgui.INDEX_SIZE
            for cmd in cmd_list.cmd_buffer:
                # 1.91+ 用 ImTextureRef 取代了裸 texture_id
                gl_tex = self._textures.get(int(cmd.get_tex_id()))
                if gl_tex is not None:
                    gl_tex.use(0)
                x, y, z, w_ = cmd.clip_rect
                self.ctx.scissor = (int(x), int(fb_h - w_),
                                    int(z - x), int(w_ - y))
                self._vao.render(moderngl.TRIANGLES,
                                 vertices=cmd.elem_count, first=elem_offset)
                elem_offset += cmd.elem_count
            vtx_offset += vtx_bytes
            idx_offset += idx_bytes
        self.ctx.scissor = None
        self.ctx.disable(moderngl.BLEND)

    def shutdown(self) -> None:
        for tex in self._textures.values():
            tex.release()
        self._textures.clear()
        self._vbo.release()
        self._ibo.release()
        self._vao.release()
        self._prog.release()


def build_imgui_renderer(window):
    """创建 ImGui 渲染器；任何失败都返回 None（降级为无面板，plan §10 兜底）。

    失败时把刚创建的上下文销毁，避免留下半初始化的全局状态
    （否则后续再建上下文会拿到脏数据）。
    """
    created = not imgui.get_current_context()
    try:
        if created:
            imgui.create_context()
        return ImGuiModernGLRenderer(window)
    except Exception as exc:                    # noqa: BLE001
        if created:
            imgui.destroy_context()
        print(f"[ui] ImGui 后端不可用，降级为快捷键模式: {exc!r}")
        return None
