"""ImGui 参数面板（plan §6）：场景切换 + 全局参数 + 场景参数 + 统计。

设计原则：面板**不持有状态**，每次 `draw()` 都读写外部传入的对象
（app / scene），所以"实时生效"是自然的——改完参数下一帧就作用于物理。

控件按作用域分三层：
  全局：积分器、时间步长、暂停、慢放、混合模式、纹理
  场景：按场景类型探测可用参数（重力/风力/阻力/发射率/刚度/文字）
  统计：粒子数 / FPS / 录制状态（只读）

imgui-bundle 缺失时 `Panel.available == False`，main.py 自动退回快捷键模式
（plan §10 的兜底方案）。
"""
from __future__ import annotations

import numpy as np

try:                                        # imgui-bundle 是可选依赖
    from imgui_bundle import imgui
    HAVE_IMGUI = True
except ImportError:                         # pragma: no cover - 环境相关
    imgui = None
    HAVE_IMGUI = False


class Panel:
    """Dear ImGui 面板。"""

    available = HAVE_IMGUI

    # 可选纹理（与 render/textures 对应）
    TEXTURES = ("gaussian_spot", "soft_disc", "ring")
    INTEGRATORS = ("euler", "verlet", "leapfrog", "velocity_verlet")
    SCENE_LABELS = {
        "fountain": "喷泉 Fountain",
        "snow": "雪 Snow",
        "fire": "火焰 Fire",
        "fireworks": "烟花 Fireworks",
        "text": "文字 Text",
    }

    TITLE = "粒子系统控制台"
    # 面板在缩放 1 倍时的摆放（像素）；其余控件由 style 统一缩放
    BASE_POS = 12.0
    BASE_WIDTH = 300.0
    BASE_LABEL_WIDTH = 90.0

    def __init__(self) -> None:
        self.visible = True
        self._text_buffer = ""              # 文字场景输入框缓冲
        self._text_synced = None            # 缓冲最后一次与场景对齐时的值
        self._editing_text = False          # 用户正在输入时不覆盖缓冲
        self._focus_text_next = False       # 冒烟脚本用：下一帧抢键盘焦点
        self._last_draw_data = None          # 上一帧 ImGui 绘制数据
        self._applied_scale = None          # 已应用到 ImGui style 的缩放倍数
        self._last_layout_scale = None      # 上次写入窗口位置/尺寸时的缩放倍数
        self.ui_scale = 1.0                 # 本次绘制使用的缩放倍数
        # 上一帧结束时面板是否想吃键鼠。imgui 的 want_capture_* 只在
        # new_frame() 之后有效，而事件回调在本帧 new_frame() 之前触发，
        # 所以这里缓存上一帧的值供事件过滤使用（差一帧，用户无感知）。
        self.wants_mouse = False
        self.wants_keyboard = False

    # -------------------------------------------------- 调试钩子

    def focus_text_input(self) -> None:
        """下一次 draw 时把键盘焦点放到文字输入框（供冒烟脚本用）。"""
        self._focus_text_next = True

    # -------------------------------------------------- 公共入口

    def toggle(self) -> None:
        self.visible = not self.visible

    # -------------------------------------------------- 缩放

    @staticmethod
    def scale_for(width: int, height: int,
                  base=(1280, 720), max_scale: float = 2.5) -> float:
        """按窗口相对基准窗口的缩放倍数算 UI 缩放。

        取宽高比例的几何平均：单独用宽度会在 16:10 全屏（2560×1600）
        下偏小，单独用高度则在超宽屏下偏大，几何平均两端都温和。
        结果夹在 [1, max_scale]：缩到比 1 倍小会让字看不清，无上限则
        超大屏上面板会占掉半个屏幕。
        """
        if width <= 0 or height <= 0:
            return 1.0
        ratio = ((width / base[0]) * (height / base[1])) ** 0.5
        return min(max(ratio, 1.0), max_scale)

    def _apply_scale(self, scale: float) -> None:
        """把缩放写进 ImGui style（字号 + 间距/圆角/滚动条等尺寸）。"""
        if scale == self._applied_scale:
            return
        style = imgui.get_style()
        # scale_all_sizes 是**累乘**的，所以每次都从 1 倍重新算：
        # 按上次的倍数反向还原，再乘新倍数。
        previous = self._applied_scale or 1.0
        style.scale_all_sizes(scale / previous)
        # scale_all_sizes 明确说明"不缩放字体"，字号要单独给
        style.font_scale_main = scale
        self._applied_scale = scale

    def draw(self, app, renderer, scale: float = 1.0):
        """构建一帧面板并返回 ImGui 绘制数据（供后端 render 上传）。

        app 为 main.ParticleApp，renderer 为 ParticleRenderer，
        scale 为 UI 缩放倍数（全屏时跟着窗口放大，见 `scale_for`）。
        面板不可用时返回 None，调用方据此跳过渲染。
        隐藏时仍走完整帧流程（new_frame/render），这样 ImGui 状态机
        不会因为跳过帧而错乱，同时清掉捕获标志。
        """
        if not self.available:
            return None
        self._apply_scale(max(scale, 0.5))
        # 泵步必须在主 new_frame 之前：ImGui 不允许嵌套时间步
        self._pump_coalesced_press(app, renderer)
        imgui.new_frame()
        if self.visible:
            # 窗口位置/尺寸只在首帧（或缩放变化时）定一次，之后交给
            # ImGui 记住用户的拖拽结果。
            if scale != self._last_layout_scale:
                self._last_layout_scale = scale
                imgui.set_next_window_pos((self.BASE_POS * scale,
                                           self.BASE_POS * scale))
                imgui.set_next_window_size((self.BASE_WIDTH * scale, 0))
            self._draw_body(app, renderer)
        imgui.render()
        self.ui_scale = max(scale, 0.5)
        self._last_draw_data = imgui.get_draw_data()
        # 记录本帧捕获状态，供下一帧的事件回调过滤
        io = imgui.get_io()
        self.wants_mouse = self.visible and bool(io.want_capture_mouse)
        self.wants_keyboard = self.visible and bool(io.want_capture_keyboard)
        # 批内延后的左键释放，在主步消费完"按住"状态后再生效
        backend = getattr(app, "_imgui", None)
        if callable(getattr(backend, "end_batch", None)):
            backend.end_batch()
        return self._last_draw_data

    @property
    def first_frame(self) -> bool:
        return self._last_draw_data is None

    def _draw_body(self, app, renderer) -> None:
        """面板窗口内容（不含 set_next_window_* 布局，可重复调用）。"""
        imgui.begin(self.TITLE)
        self._draw_global(app, renderer)
        imgui.separator()
        self._draw_scene(app)
        imgui.separator()
        self._draw_stats(app)
        imgui.end()

    def _pump_coalesced_press(self, app, renderer) -> None:
        """批内"按下+移动"的拆步（修复滑条在低帧率下拖不动）。

        ImGui 激活 drag 控件需要"按下"与"按住下的位置变化"落在**两个
        时间步**（两次 new_frame）里：同一批次内即使按顺序投 down→move，
        ImGui 也只记录终态，且该手势后续所有移动都不再生效（active 的
        建立时机已错过）。帧率低/事件合并时 press 与首批 move 会挤进
        同一批——真人拖动 16 ms 帧间隔内也偶发。

        解法（探针验证）：在正式帧之前补一个"迷你步"，把 io 倒回按下
        瞬间的状态（位置=按下点、左键=按下）跑一遍 UI，让 ImGui 建立
        active；再恢复到当前（已移动）状态跑正式帧，delta 就被正确计入。
        """
        backend = getattr(app, "_imgui", None)
        take = getattr(backend, "take_press_pump", None)
        press = take() if callable(take) else None
        if press is None or not self.visible:
            return
        io = imgui.get_io()
        final_pos = (io.mouse_pos.x, io.mouse_pos.y)
        final_down = bool(io.mouse_down[0])
        io.mouse_pos = press
        io.mouse_down[0] = True
        imgui.new_frame()
        self._draw_body(app, renderer)
        imgui.render()
        io.mouse_pos = final_pos
        io.mouse_down[0] = final_down

    def draw_data(self):
        """返回最近一次 draw() 产生的绘制数据（同一帧，不重开 new_frame）。"""
        return self._last_draw_data

    # -------------------------------------------------- 全局

    def _draw_global(self, app, renderer) -> None:
        imgui.text("场景")
        for i, key in enumerate(app.scene_order):
            if i % 3:                       # 300px 宽面板一排 3 个正好
                imgui.same_line()
            if imgui.button(f"{i + 1}. {self.SCENE_LABELS.get(key, key)}"):
                app.switch_scene(i)
        if imgui.button("重置当前场景 (R)"):
            app.scene.reset()

        imgui.separator()
        imgui.text("物理")
        system = app.scene.system
        # 积分器切换：走 set_integrator —— 它负责作废 aux（各积分器对 aux 的
        # 语义不同，直接换函数引用会让新积分器拿旧状态当自己的用）
        cur = self.INTEGRATORS.index(system.integrator_name) \
            if system.integrator_name in self.INTEGRATORS else 3
        changed, sel = imgui.combo("积分器", cur, list(self.INTEGRATORS))
        if changed:
            system.set_integrator(self.INTEGRATORS[sel])

        changed, h = imgui.drag_float("固定步长 (ms)", system.fixed_step * 1000.0,
                                      0.2, 1.0, 33.0, "%.2f")
        if changed:
            system.fixed_step = max(1e-4, h / 1000.0)

        changed, app.paused = imgui.checkbox("暂停 (Space)", app.paused)
        changed, app.time_scale = imgui.slider_float("慢放", app.time_scale,
                                                     0.05, 3.0, "%.2fx")

        imgui.separator()
        imgui.text("渲染")
        cur_tex = self.TEXTURES.index(app.scene.texture) \
            if app.scene.texture in self.TEXTURES else 0
        changed, sel = imgui.combo("粒子纹理", cur_tex, list(self.TEXTURES))
        if changed:
            app.set_texture(self.TEXTURES[sel])
        changed, app.show_grid = imgui.checkbox("显示地面网格", app.show_grid)

    # -------------------------------------------------- 场景参数

    def _draw_scene(self, app) -> None:
        scene = app.scene
        imgui.text(f"场景参数 — {scene.name}")
        # 发射率：持续发射器才有 rate_mean，一次性爆发器没有
        for e in scene.system.emitters:
            rate = getattr(e, "rate_mean", None)
            if rate is None:
                continue
            changed, v = imgui.drag_float(
                f"发射率 {type(e).__name__}##{id(e)}", float(rate), 10.0,
                0.0, 20000.0, "%.0f /s")
            if changed:
                e.rate_mean = v
        for f in scene.system.forces:
            self._draw_force(f)

        # 粒子尺寸：直接改所有活粒子的 size0 基准
        pool = scene.system.pool
        n = pool.count
        if n:
            base = float(pool.size0[:n].mean())
            changed, v = imgui.drag_float("粒子尺寸", base, 0.001, 0.005, 1.0,
                                          "%.3f")
            if changed and base > 1e-6:
                pool.size0[:n] *= v / base
                pool.size[:n] *= v / base

        # 文字场景特有
        if hasattr(scene, "set_text"):
            # 场景文字与输入框只在"两者不一致且用户没在输入"时对齐一次。
            # 不用 `if not self._editing_text` 每帧硬覆盖：点输入框的下一帧
            # want_text_input 还是 False（焦点差一帧到），覆盖会把用户刚
            # 敲进去的字擦掉；反过来点"应用文字"时输入框失焦，又会在读按钮
            # 之前把缓冲恢复成旧文字，于是按钮拿到的还是原文。
            # 用"记下上次对齐时的值"代替猜测，两边都能自愈。
            if not self._editing_text and \
                    self._text_buffer != scene.text and \
                    self._text_synced != scene.text:
                self._text_buffer = scene.text
            imgui.separator()
            # 注意：input_text 的签名是 (label, text[, flags]) —— 没有"最大
            # 长度"参数，第三位是 flags，别照 pyimgui 的旧习惯传长度。
            imgui.push_item_width(-self.BASE_LABEL_WIDTH * self.ui_scale)
            if self._focus_text_next:
                imgui.set_keyboard_focus_here()
                self._focus_text_next = False
            changed, buf = imgui.input_text("文字内容", self._text_buffer)
            imgui.pop_item_width()
            if changed:
                self._text_buffer = buf
            self._editing_text = imgui.get_io().want_text_input
            # 回车直接提交（EnterReturnsTrue 那种体验），再配一个按钮给鼠标用户
            submitted = imgui.is_item_deactivated_after_edit()
            if imgui.button("应用文字"):
                submitted = True
            if submitted and self._text_buffer:
                scene.set_text(self._text_buffer)
                self._text_synced = scene.text

    def _draw_force(self, force) -> None:
        """按力场类型给出可调参数（未来新增力场只需加一个分支）。"""
        name = type(force).__name__
        label = f"{name}##{id(force)}"
        if imgui.collapsing_header(label, imgui.TreeNodeFlags_.default_open.value):
            if name == "Gravity":
                changed, y = imgui.drag_float("g_y",
                                              float(force.g[1]), 0.05,
                                              -30.0, 10.0, "%.2f")
                if changed:
                    force.g = np.array([0.0, y, 0.0])
            elif name == "Drag":
                changed, k1 = imgui.drag_float("k1 线性", float(force.k1), 0.01,
                                               0.0, 20.0, "%.3f")
                if changed:
                    force.k1 = k1
                changed, k2 = imgui.drag_float("k2 平方", float(force.k2), 0.01,
                                               0.0, 20.0, "%.3f")
                if changed:
                    force.k2 = k2
            elif name == "Wind":
                changed, amp = imgui.drag_float("湍流幅度", float(force.amplitude),
                                                0.02, 0.0, 8.0, "%.3f")
                if changed:
                    force.amplitude = amp
                    force._basis = None     # 幅度变了不影响基，但保持一致性
                changed, freq = imgui.drag_float("时间频率", float(force.frequency),
                                                 0.02, 0.0, 10.0, "%.3f")
                if changed:
                    force.frequency = freq
            elif name == "Buoyancy":
                changed, acc = imgui.drag_float("浮力加速度",
                                                float(force.acceleration), 0.1,
                                                -5.0, 40.0, "%.2f")
                if changed:
                    force.acceleration = acc
            elif name == "TargetConstraint":
                changed, k = imgui.drag_float("约束刚度 k", float(force.k), 0.1,
                                              0.0, 60.0, "%.2f")
                if changed:
                    force.k = k
                changed, c = imgui.drag_float("阻尼 c", float(force.damping),
                                              0.05, 0.0, 30.0, "%.3f")
                if changed:
                    force.damping = c
            elif name == "Attractor":
                changed, s = imgui.drag_float("强度 (负=排斥)", float(force.strength),
                                              0.5, -80.0, 80.0, "%.2f")
                if changed:
                    force.strength = s

    # -------------------------------------------------- 统计

    def _draw_stats(self, app) -> None:
        imgui.text("统计")
        imgui.text(f"粒子数  {app.scene.count} / {app.scene.capacity}")
        imgui.text(f"FPS     {app.fps:.1f}")
        imgui.text(f"物理时间 {app.scene.system.time:.1f}s")
        rec = getattr(app, "recorder", None)
        if rec is not None:
            imgui.text_colored((1.0, 0.3, 0.3, 1.0),
                               f"● 录制中 {rec.frames} 帧 / {rec.duration:.1f}s")
        else:
            imgui.text("录制：R 开始（输出 MP4）")
