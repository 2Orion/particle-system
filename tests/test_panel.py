"""ImGui 面板测试：无 GL 的逻辑层（imgui 上下文需 GL，这里只测纯数据部分）。

面板的红线是"不持有状态"——参数改完直接写回外部对象。
这里用假的 app/scene 验证这条路走得通，不依赖窗口。
"""
import numpy as np
import pytest

from ui.panel import Panel


def test_panel_module_imports_and_reports_availability():
    assert isinstance(Panel.available, bool)


def test_scene_labels_cover_all_scenes():
    """面板能显示每个场景的中文名，包括新加的文字场景。"""
    from scenes import SCENE_ORDER
    for key in SCENE_ORDER:
        assert key in Panel.SCENE_LABELS, f"面板缺少场景 {key} 的中文名"


def test_panel_options_match_engine():
    """面板下拉框的选项必须与引擎里真实存在的实现一致。"""
    from core.integrators import INTEGRATORS
    from scenes.base import VALID_TEXTURE
    assert set(Panel.INTEGRATORS) == set(INTEGRATORS)
    assert set(Panel.TEXTURES) == set(VALID_TEXTURE)


class _FakeScene:
    name = "fake"
    texture = "gaussian_spot"
    count = 0
    capacity = 1000

    class _System:
        integrator_name = "velocity_verlet"
        fixed_step = 1 / 120
        time = 0.0
        forces = []
        emitters = []

        class _Pool:
            count = 0

        pool = _Pool()

    system = _System()


class _FakeApp:
    scene = _FakeScene()
    scene_order = ("fake",)
    paused = False
    time_scale = 1.0
    show_grid = True
    fps = 60.0

    def switch_scene(self, index):
        self.switched = index

    def set_texture(self, name):
        self.texture_set = name


def test_panel_toggle():
    p = Panel()
    assert p.visible
    p.toggle()
    assert not p.visible
    p.toggle()
    assert p.visible


def test_panel_without_imgui_draws_nothing(monkeypatch):
    """imgui 不可用时 draw 返回 None（main.py 据此跳过渲染）。"""
    p = Panel()
    monkeypatch.setattr(Panel, "available", False)
    assert p.draw(_FakeApp(), None) is None


@pytest.mark.skipif(not Panel.available, reason="imgui-bundle 未安装")
def test_panel_without_imgui_context_raises():
    """没有 ImGui 上下文时 draw 应抛错（尽早暴露集成问题，而非静默画错）。"""
    p = Panel()
    with pytest.raises(Exception):
        p.draw(_FakeApp(), None)


# ---------------------------------------------------------------- 真实上下文

@pytest.fixture
def imgui_ctx():
    """建一个不接 GL 的 ImGui 上下文。

    新版 imgui 要求后端声明 `RendererHasTextures`，否则 new_frame() 会因
    字体图集未构建而断言失败。这里只测控件逻辑，不需要真的上传纹理。
    """
    from imgui_bundle import imgui
    imgui.create_context()
    io = imgui.get_io()
    io.display_size = (1280, 720)
    io.backend_flags |= imgui.BackendFlags_.renderer_has_textures
    try:
        yield imgui
    finally:
        imgui.destroy_context()


def _type_into_field(imgui, flags=None, frames=4):
    """每帧按键后跑一帧 input_text，返回最终缓冲。

    键盘焦点在 set_keyboard_focus_here() 之后要再过一帧才生效，
    所以至少跑三帧才能看到第一个字符——两帧会误判成"输入被吞"。
    """
    buf = ""
    for frame in range(frames):
        if frame:
            imgui.get_io().add_input_characters_utf8("粒")
        imgui.new_frame()
        imgui.begin("t")
        imgui.set_keyboard_focus_here()
        if flags is None:
            _, buf = imgui.input_text("文字", buf)
        else:
            _, buf = imgui.input_text("文字", buf, flags)
        imgui.end()
        imgui.render()                 # 每帧必须 render()，否则下帧会断言
    return buf


@pytest.mark.skipif(not Panel.available, reason="imgui-bundle 未安装")
def test_text_input_accepts_cjk(imgui_ctx):
    """确认"两参数"调用能收下汉字（面板用的就是这种）。"""
    assert "粒" in _type_into_field(imgui_ctx)


@pytest.mark.skipif(not Panel.available, reason="imgui-bundle 未安装")
def test_input_text_third_arg_is_flags():
    """`input_text` 没有"最大长度"参数，第三位是 flags。

    这个签名容易被当成 pyimgui 的 `(label, value, max_len)` 而误传 64，
    所以把"该函数只接受 (label, text[, flags])"钉在文档上：
    误传长度不会报错，只会静默改变行为。
    """
    from imgui_bundle import imgui as im
    doc = im.input_text.__doc__
    assert "flags: int = 0" in doc
    assert "max" not in doc.split("->")[0].lower()


# ---------------------------------------------------------------- UI 缩放

def test_scale_for_is_one_at_base_size():
    assert Panel.scale_for(1280, 720) == 1.0


def test_scale_for_grows_with_fullscreen():
    """2560×1600 全屏下约 2.1 倍（宽高比例的几何平均）。"""
    assert Panel.scale_for(2560, 1600) == pytest.approx(2.11, abs=0.02)
    assert Panel.scale_for(2560, 1600) > 2.0
    assert Panel.scale_for(1920, 1080) == pytest.approx(1.5, abs=0.02)


def test_scale_for_clamps_to_unit_minimum():
    """窗口比基准还小时不缩小——字小了看不清。"""
    assert Panel.scale_for(640, 360) == 1.0


def test_scale_for_has_upper_bound():
    """超大屏（5K/8K）不无限放大，否则面板占掉半个屏幕。"""
    assert Panel.scale_for(8000, 4500) == pytest.approx(2.5)


def test_scale_for_ignores_minimized_window():
    """最小化为 0 时不能算出 0 或负数（会除零/负尺寸）。"""
    assert Panel.scale_for(0, 0) == 1.0


@pytest.mark.skipif(not Panel.available, reason="imgui-bundle 未安装")
def test_panel_applies_scale_to_font_and_sizes(imgui_ctx):
    """全屏缩放必须同时放大字号和间距（scale_all_sizes 不缩放字体）。"""
    p = Panel()
    app = _FakeApp()
    p.draw(app, None, scale=2.0)
    style = imgui_ctx.get_style()
    assert style.font_scale_main == pytest.approx(2.0)
    assert style.window_padding.x > 8.0          # 默认 8，缩放后应更大

    # 再退回 1 倍：累乘的 scale_all_sizes 不能被叠成 4 倍
    p.draw(app, None, scale=1.0)
    assert style.font_scale_main == pytest.approx(1.0)
    assert style.window_padding.x == pytest.approx(8.0)


# ---------------------------------------------------------------- 文字输入

class _TextScene(_FakeScene):
    text = "初始"

    def __init__(self):
        self.applied = []

    def set_text(self, t):
        self.applied.append(t)
        self.text = t


class _TextApp(_FakeApp):
    scene = _TextScene()


@pytest.mark.skipif(Panel.available is False, reason="imgui-bundle 未安装")
def test_apply_button_uses_typed_buffer(imgui_ctx):
    """点"应用文字"时缓冲不能被 scene.text 覆盖回旧值。

    回归：原实现每帧 `if not self._editing_text: self._text_buffer =
    scene.text`。点按钮那一帧输入框已失焦（want_text_input=False），
    同步先于按钮判断执行，缓冲被恢复成旧文字，于是 set_text 永远收到
    原文——"只能显示粒子系统"。
    """
    from imgui_bundle import imgui
    p = Panel()
    scene = _TextScene()
    app = _TextApp()
    app.scene = scene
    for _ in range(3):
        p.draw(app, None)
    assert p._text_buffer == "初始"

    # 用户输入：set_keyboard_focus_here 抢到的焦点会全选原有内容，
    # 所以敲的字替换掉"初始"——这是 ImGui 的既定行为。
    p.focus_text_input()
    for frame in range(4):
        if frame >= 3:
            imgui.get_io().add_input_characters_utf8("改")
        p.draw(app, None)
    typed = p._text_buffer
    assert "改" in typed and typed != "初始"

    # 点按钮那一帧：输入框已失焦。缓冲必须仍是用户输入的内容，
    # 不能被 scene.text 覆盖回"初始"，否则 set_text 收到的是旧文字。
    imgui.get_io().want_text_input = False
    p.draw(app, None)
    assert p._text_buffer == typed, "缓冲被 scene.text 覆盖了"


@pytest.mark.skipif(Panel.available is False, reason="imgui-bundle 未安装")
def test_text_buffer_resyncs_when_scene_changes(imgui_ctx):
    """场景文字被外部改掉时（切场景/脚本），输入框要跟上。"""
    p = Panel()
    scene = _TextScene()
    app = _TextApp()
    app.scene = scene
    p.draw(app, None)
    p.draw(app, None)
    assert p._text_buffer == "初始"

    scene.text = "外部改的"              # 例如 scene.set_text() 被别处调用
    p.draw(app, None)
    assert p._text_buffer == "外部改的"


@pytest.mark.skipif(not Panel.available, reason="imgui-bundle 未安装")
def test_panel_draws_after_two_frames(imgui_ctx):
    """完整走两帧：new_frame → 控件 → render → 拿到绘制数据。

    首帧 ImGui 只做布局、不产出绘制列表（cmd_lists 为空），
    第二帧起才有顶点数据——所以断言放在第二帧。
    """
    p = Panel()
    assert p.first_frame
    p.draw(_FakeApp(), None)
    assert not p.first_frame
    data = p.draw(_FakeApp(), None)
    assert data is not None
    assert len(data.cmd_lists) >= 1
    assert data.total_vtx_count > 0
    assert p.draw_data() is data


# ---------------------------------------------------------------- drag 泵步

class _PumpBackend:
    """模拟后端：按脚本依次返回/清空 pump 请求。"""

    def __init__(self, script):
        self.script = list(script)          # [(调用, 返回值), ...]
        self.calls = []

    def take_press_pump(self):
        self.calls.append("take")
        return self.script.pop(0)[1] if self.script else None

    def end_batch(self):
        self.calls.append("end")


@pytest.mark.skipif(not Panel.available, reason="imgui-bundle 未安装")
def test_pump_step_runs_before_main_frame(imgui_ctx):
    """同批 press+move 时，Panel.draw 要在主帧前补一个迷你 ImGui 步。

    回归：ImGui 激活 drag 需要按下与按住移动分处两个时间步。同批到达
    而不拆步时，整段手势失效——用户看到的就是"滑条拖不动、参数改不了"。
    """
    p = Panel()
    app = _FakeApp()
    app._imgui = _PumpBackend([("take", (100.0, 200.0))])
    p.draw(app, None)                       # 泵步 + 主帧各走一遍
    assert app._imgui.calls[0] == "take"    # 主 new_frame 之前询问
    assert app._imgui.calls[-1] == "end"    # 帧末处理延后的释放


@pytest.mark.skipif(not Panel.available, reason="imgui-bundle 未安装")
def test_no_pump_when_no_backlog(imgui_ctx):
    """无积压时（绝大多数帧）不补步，行为与原来完全一致。"""
    p = Panel()
    app = _FakeApp()
    app._imgui = _PumpBackend([])
    data = p.draw(app, None)
    assert data is not None                 # 正常产出绘制数据
    assert app._imgui.calls == ["take", "end"]
