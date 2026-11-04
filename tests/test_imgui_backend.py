"""ImGui 后端测试：只测不依赖 GL 上下文的部分。

渲染本身需要真实窗口（tools/smoke_w2b.py 覆盖），但有两个容易出错的
静态约定值得钉死：
1. 顶点布局必须与 ImDrawVert 的内存布局一致（20 字节/顶点，颜色是
   归一化的 4×ubyte 而不是 4×float）—— 写错会画出斜线状乱码；
2. 索引宽度必须跟随 imgui.INDEX_SIZE（1.91+ 默认 32 位）。
这两处一旦与库脱节，只有肉眼才能发现，所以用断言守住。
"""
import struct

import pytest

pytest.importorskip("imgui_bundle")
pytest.importorskip("moderngl")

from imgui_bundle import imgui

from ui import imgui_backend


def test_vertex_layout_matches_imdrawvert():
    """顶点布局必须 8+8+4=20 字节，且颜色是 4 个归一化 ubyte。

    写成 "4f" 会让 stride 变成 24、颜色也读错——表现是面板画成一片
    斜线。单元测试看不出斜线，所以这里钉住那条格式串本身。
    """
    assert imgui.VERTEX_SIZE == 20
    fmt = imgui_backend.VERTEX_FORMAT
    assert fmt == "2f 2f 4f1"
    assert sum(8 if t == "2f" else 4 for t in fmt.split()) == 20



def test_index_size_is_followed():
    """ImDrawIdx 宽度由库决定，后端必须读它而不是硬编码 2。"""
    assert imgui.INDEX_SIZE in (2, 4)


def test_font_candidates_are_paths():
    assert imgui_backend.ImGuiModernGLRenderer.FONT_CANDIDATES
    for path in imgui_backend.ImGuiModernGLRenderer.FONT_CANDIDATES:
        assert isinstance(path, str) and path


def test_texture_status_enum_exists():
    """新纹理协议依赖这四个状态，改名要立刻暴露。"""
    status = imgui.ImTextureStatus
    for name in ("ok", "destroyed", "want_create", "want_updates",
                 "want_destroy"):
        assert hasattr(status, name), f"ImTextureStatus 缺少 {name}"


def test_draw_cmd_exposes_tex_id():
    """1.91+ 用 ImTextureRef，取 id 得走 get_tex_id()。"""
    assert hasattr(imgui.ImDrawCmd, "get_tex_id")


def test_build_returns_none_without_window():
    """没有窗口时 build_imgui_renderer 必须降级返回 None 而不是抛错。"""
    assert imgui_backend.build_imgui_renderer(None) is None


# ---------------------------------------------------------------- 尺寸同步

class _FakeWindow:
    """只提供 `_sync_display_size` 需要的两个属性。"""

    def __init__(self, size, buffer_size):
        self.size = size
        self.buffer_size = buffer_size


def _renderer_with(window):
    """绕过 GL 构造，只挂上尺寸同步需要的属性。"""
    r = imgui_backend.ImGuiModernGLRenderer.__new__(
        imgui_backend.ImGuiModernGLRenderer)
    r.wnd = window
    r.io = _FakeIO()
    return r


class _FakeIO:
    display_size = (0.0, 0.0)
    display_framebuffer_scale = (1.0, 1.0)


def test_display_size_follows_fullscreen():
    """窗口进全屏后 display_size 必须跟上。

    回归：`WindowConfig` 只在子类实现了 `on_resize` 时才绑定它，否则
    绑的是 dummy —— 后端收不到 resize 回调，面板就停留在启动尺寸，
    全屏下只画在左上角一小块。
    """
    win = _FakeWindow((1280, 720), (1280, 720))
    r = _renderer_with(win)
    r._sync_display_size()
    assert r.io.display_size == (1280.0, 720.0)

    win.size = win.buffer_size = (2560, 1600)          # 切全屏
    r._sync_display_size()
    assert r.io.display_size == (2560.0, 1600.0)
    assert r.io.display_framebuffer_scale == (1.0, 1.0)


def test_display_size_handles_hidpi_scale():
    """高 DPI 下 buffer 比窗口大，缩放因子要按两者之比算。"""
    r = _renderer_with(_FakeWindow((1280, 720), (2560, 1440)))
    r._sync_display_size()
    assert r.io.display_size == (1280.0, 720.0)
    assert r.io.display_framebuffer_scale == (2.0, 2.0)


def test_display_size_ignores_zero_sized_window():
    """最小化时尺寸可能为 0，不能把 display_size 写成 0（会除零）。"""
    r = _renderer_with(_FakeWindow((1280, 720), (1280, 720)))
    r._sync_display_size()
    before = r.io.display_size

    r.wnd = _FakeWindow((0, 0), (0, 0))
    r._sync_display_size()
    assert r.io.display_size == before


# ---------------------------------------------------------------- 索引重定基

def _make_backend():
    """无 GL 构造一个后端实例（只挂事件转发需要的属性）。"""
    r = imgui_backend.ImGuiModernGLRenderer.__new__(
        imgui_backend.ImGuiModernGLRenderer)
    r.wnd = _MouseWindow()
    r.io = _MouseIO()
    r._btn_batch = []
    r._pump_armed = False
    return r


class _MouseWindow:
    """模拟 moderngl-window：mouse 常量、mouse_states 属性对象、viewport。"""

    class _Keys:
        ACTION_PRESS = 1

    keys = _Keys()

    class _Mouse:
        left = 1
        right = 3
        middle = 2

    mouse = _Mouse()

    class _States:
        """真实MouseButtonStates 只有属性，不可下标——回归的对象形态。"""
        left = False
        right = False
        middle = False

    mouse_states = _States()

    # _viewport_pos 需要的尺寸字段（无黑边）
    width, height = 1280, 720
    viewport_width, viewport_height = 1280, 720
    pixel_ratio = 1.0


class _MouseIO:
    """记录 mouse_down / mouse_pos 写入序列的假 io。"""

    def __init__(self):
        self.__dict__["written"] = []
        self.mouse_down = [False, False, False]
        self.mouse_pos = (0.0, 0.0)


def test_mouse_drag_event_uses_attribute_access(monkeypatch):
    """mouse_states 必须用属性访问（.left），不能下标（["left"]）。

    回归：原实现 `states["left"]` 每次拖动都抛 TypeError。异常穿透到
    pyglet 的 WndProc ctypes 回调被吞，程序不崩但相机拖拽永远失效，
    stderr 里堆满回溯。
    """
    r = _make_backend()
    r.wnd.mouse_states.left = True
    r.mouse_drag_event(100, 200, 5, 5)          # 修复前：TypeError
    assert r.io.mouse_down[0] is True
    r.wnd.mouse_states.left = False
    r.wnd.mouse_states.right = True
    r.mouse_drag_event(100, 200, 5, 5)
    assert r.io.mouse_down[0] is False
    assert r.io.mouse_down[1] is True


def test_press_then_drag_same_batch_arms_pump():
    """同批内"按下"与"按住移动"必须触发拆步（否则 drag 手势整体失效）。

    ImGui 激活 drag 控件需要 down 与 move-held 落在两个时间步；同批到达
    时若不拆步，后续所有移动都不会改变控件值——用户表现即"参数拖不动"。
    """
    r = _make_backend()
    assert r.take_press_pump() is None          # 平时无积压
    r.mouse_press_event(100, 200, r.wnd.mouse.left)
    r.mouse_drag_event(160, 200, 60, 0)         # 同批移动
    pump = r.take_press_pump()
    assert pump == (100, 200)                   # 返回按下位置供 Panel 拆步
    assert r.take_press_pump() is None          # 只补一步


def test_release_in_same_batch_is_deferred():
    """同批内的 release 延后一帧生效：主帧仍按"按住"消费 move。"""
    r = _make_backend()
    r.mouse_press_event(100, 200, r.wnd.mouse.left)
    r.mouse_release_event(100, 200, r.wnd.mouse.left)
    # 同批：down 立即置位，up 不立即清
    assert r.io.mouse_down[0] is True
    r.mouse_drag_event(160, 200, 60, 0)
    r.take_press_pump()                          # Panel 消费
    r.end_batch()                                # 帧末才处理延后的 up
    assert r.io.mouse_down[0] is False


def test_release_alone_takes_effect_immediately():
    """跨批的普通点击/释放不受延后逻辑影响。"""
    r = _make_backend()
    r.mouse_press_event(100, 200, r.wnd.mouse.left)
    assert r.io.mouse_down[0] is True
    r.end_batch()                                # 批结束，队列里只剩 press
    r.mouse_release_event(100, 200, r.wnd.mouse.left)
    assert r.io.mouse_down[0] is False           # 无同批 press，立即生效


def test_unicode_char_entered_accepts_ime_string():
    """IME 一次提交多个字符时不能崩。

    回归：原实现是 `io.add_input_character(ord(char))`，中文输入法提交
    "测试" 时 char 是长度 2 的字符串，ord() 抛 TypeError，异常穿透 pyglet
    的事件分发，整个程序挂掉。
    """
    r = _renderer_with(_FakeWindow((1280, 720), (1280, 720)))
    io = _RecordingIO()
    r.io = io
    r.unicode_char_entered("测")
    r.unicode_char_entered("试AB")          # 多字符提交
    assert io.received == ["测", "试AB"]


class _RecordingIO:
    def __init__(self):
        self.received = []

    def add_input_characters_utf8(self, text):
        self.received.append(text)


def _index_probe(indices, index_size):
    """造一个只带索引缓冲的假 DrawList，验证 _rebase_indices。"""
    import ctypes

    import numpy as np

    dt = np.uint32 if index_size == 4 else np.uint16
    arr = np.asarray(indices, dtype=dt)
    buf = (ctypes.c_ubyte * arr.nbytes).from_buffer_copy(arr.tobytes())

    class _Buf:
        @staticmethod
        def size():
            return len(indices)

        @staticmethod
        def data_address():
            return ctypes.addressof(buf)

    class _CmdList:
        idx_buffer = _Buf()

    return _CmdList()


def test_rebase_indices_offsets_second_draw_list():
    """第二块 DrawList 的索引必须整体加上顶点基址。

    回归：每个 ImDrawList 的索引都从 0 编号，但顶点是追加到共享 VBO 的。
    不加基址时下拉框弹出层（第二块 DrawList）会索引到主窗口的顶点，
    面板上糊出一块被拉长的三角形。
    """
    r = imgui_backend.ImGuiModernGLRenderer.__new__(
        imgui_backend.ImGuiModernGLRenderer)
    size = imgui.INDEX_SIZE
    r._index_size = size

    cmds = _index_probe([0, 1, 2, 5], size)
    out = r._rebase_indices(cmds, 40)
    dt = "uint32" if size == 4 else "uint16"
    import numpy as np
    assert np.frombuffer(out, dtype=dt).tolist() == [40, 41, 42, 45]

    # 基址为 0 时原样输出（第一块 DrawList 不必改）
    assert np.frombuffer(r._rebase_indices(cmds, 0), dtype=dt).tolist() \
        == [0, 1, 2, 5]


def test_rebase_indices_handles_empty_list():
    r = imgui_backend.ImGuiModernGLRenderer.__new__(
        imgui_backend.ImGuiModernGLRenderer)
    r._index_size = imgui.INDEX_SIZE
    assert r._rebase_indices(_index_probe([], imgui.INDEX_SIZE), 12) == b""
