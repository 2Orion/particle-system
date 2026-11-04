## 2026-11-04 修复：面板参数无法手动修改（拖动塌缩 + 事件下标崩溃）

用户报告：控制面板显示正常、按钮能点，但 drag_float 类参数拖不动。

### 根因（两个独立缺陷叠加）

**1. `mouse_states` 用了下标访问**（`ui/imgui_backend.py`、`main.py`）

`wnd.mouse_states` 是 `MouseButtonStates` 属性对象（`.left/.right/.middle`），
不可下标。原代码 `states["left"]` 在每次 `mouse_drag_event` 都抛
`TypeError`；异常穿透到 pyglet WndProc 的 ctypes 回调被吞，程序不崩，
只往 stderr 打回溯——但 `main.on_mouse_drag_event` 里排在后面的相机
分支被一并跳过。改为属性访问（与 moderngl-window 官方集成一致）。

**2. 同帧"按下+移动"令 drag 手势整体失效**（时序缺陷，用户所见的主因）

ImGui 激活 drag 控件需要"按下"与"按住状态下的位置变化"落在**两个
时间步**（两次 new_frame）里。用无 GL 探针钉死的语义：

- 跨帧序列 hover→press→move：值正常更新（10.0→40.0）
- 同一批次内投 down→move（事件队列 API 按序投也不行）：值不变，
  且该手势**后续所有移动帧**都 changed=False——active 的建立时机
  已错过，整个手势被毒死
- 同批次内拆成两个 ImGui 时间步（先 down 后 move）：恢复工作

60 fps 帧间隔仅 16 ms，鼠标按下瞬间的微小移动与 press 挤进同一批
并不罕见（合成/自动化事件必然如此）。这就是"参数改不了"。

### 修复（泵步机制）

- `imgui_backend.mouse_press_event`：左键按下记录进 `_btn_batch`
- `imgui_backend.mouse_drag_event`：检测到批内已有 press 时置
  `_pump_armed`
- `imgui_backend.mouse_release_event`：与 press 同批的 release 延后
  一帧（立刻置 False 会让主帧看不到按住，探针验证不更新）
- `panel.draw`：主 new_frame 之前调 `take_press_pump()`，有积压则
  把 io 倒回按下瞬间（位置=按下点、左键=True）跑一个迷你 ImGui 步，
  再恢复终态跑主帧；帧末 `end_batch()` 处理延后的释放

真实窗口（Win32 PostMessage 走完整 WndProc 路径）2×2 验证：
窗口化/全屏 × 同帧/跨帧，修复前同帧两格 FAIL，修复后全 PASS。
六类控件回归全 PASS：固定步长（drag）、慢放（slider）、暂停
（checkbox）、积分器（combo）、发射率（drag）、g_y（折叠头内 drag）。

### 测试

新增 6 个用例：`mouse_states` 属性访问回归、批内 press+move 触发泵、
同批 release 延后、跨批释放即时生效、Panel 泵步在主帧前执行、
无积压时不补步。

```
238 passed in 36.23s        # 232 → 236 → 238
```

冒烟脚本：`tools/smoke_panel_edit.py`（真实消息路径逐控件回归）、
`tools/smoke_drag.py`（根因定位，PostMessage 完整链路）。

# 更新日志

## 2026-11-04 报告：`report.typ` 成稿（17 页）+ 两处实测数据修正

### `core/integrators.py`：Verlet / Leap-Frog 首步漏掉 ½a·h²

写报告的实验数据时发现：`verlet` 与 `leapfrog` 的 2 s 自由落体误差是
**0.0817 m**，与显式 Euler 一模一样。根因是首步历史初始化只用了
`x₋₁ = x₀ − v₀h`（Leap-Frog 同理取 `v₋ₕ/₂ = v₀`），单步多出 ½a·h²；
这一项是**常量偏移**，之后每步原样保留，于是二阶方法退化成 O(h)。

- `verlet()`：首步初始化移到 `accumulate()` 之后，改为
  `x₋₁ = x₀ − v₀h + ½a₀h²`；
- `leapfrog()`：改为 `v₋ₕ/₂ = v₀ − ½a₀h`。

修复后两者 2 s 自由落体误差 1.1e-13 / 3.9e-14。原有用例断言过松
（只要 < 5 cm 即可，0.0817 m 恰好通过），已收紧为对标解析首步，
并新增 `test_second_order_methods_have_no_first_step_offset`（参数化三种二阶方法）
与 `test_verlet_initial_guess_includes_half_acceleration`。

```
232 passed in 18.29s        # 228 → 232
```

### 报告

`report.typ`：封面、目录 + 五章（项目介绍 / 算法与原理 / 程序实现 / 程序运行 /
结果与分析），9 组插图、12 张表，**17 页**。

- 所有数字都由脚本离线复现，不手填：
  `tools/report_figs.py` 在离屏 GL 上下文里渲染五场景的起始/中间/结束帧
  （同一相机、同一参数，只改仿真时刻），另出 `blend_additive/alpha` 对照图；
  `tools/report_metrics.py` 复算积分器精度、步长收敛阶、文字收敛曲线、
  阻尼扫描、场景扩展性、每帧耗时分解。
- 排版全部在 `report.typ` 里用 Typst 表格完成（早期试过生成 matplotlib
  PNG 再嵌入，已删除该脚本，图表不用图片）。
- 修正：表 5.4 的 5 千粒子吞吐量原写 242 µs 而正文写 224 µs（同一指标两处
  不一致），统一为表值；`pytest` 耗时由"约 50 s"改为"单机 20–50 s"
  （实测 18–47 s 波动，原值是单次抽样）。
- 版面：键盘表合并为 4 行使 4.2 节与下一章同页；测试策略段提到表 5.6 之前，
  避免页尾孤行；压缩表 5.6 描述，末页不再只挂一条改进项。

### 文档同步

`README.md`、`textbook.md` 的用例数 228 → 232；`textbook.md` 中
"Verlet 按 `x₋₁ = x₀ − v₀h` 重建历史"的表述改为带 ½a·h² 的正确版本。

## 2026-11-04 修复：切换积分器导致文字粒子被删光

用户报告：文字场景下切到 `verlet` 后只剩零散残粒、显示不出完整文字，
再切回其他积分器也救不回来，只能重置场景。

### 根因

`pool.aux` 是四种积分器**共用**的一格附加状态，但语义互不兼容：

| 积分器 | aux 里装的是 |
|---|---|
| `verlet` | 上一步位置 xₙ₋₁ |
| `leapfrog` | 半步速度 vₜ₋ₕ/₂ |
| `euler` | 恒被初始化成 0 |
| `velocity_verlet` | 不写（保留旧值） |

`verlet` 的推进公式是 `xₙ₊₁ = 2xₙ − xₙ₋₁ + a·h²`。从 `euler`/`velocity_verlet`
切过来时 aux 是 **0**，于是位置瞬间翻倍（`2x − 0`）。这等价于注入了一个
`x/h` 的伪速度——文字稳态 x≈4.4、h=1/120 时约 **530 m/s**，与实测的
`|v|max = 509.6` 吻合。粒子随后几步内飞出 `KillBox(±30)`，被 `compact()`
**永久删除**，所以切回别的积分器也没用，只有重置能恢复。

遍历 12 种积分器切换组合确认：只有切到 `verlet` 的 3 组会失效，其余正常；
喷泉/雪/火焰/烟花场景因粒子速度大、位置离原点近，恰好掩盖了问题。
另外发现 `verlet` 本身**不检查** aux 的内容（只要不是 NaN 就直接用），
而新粒子有 `fresh` 分支做初始化——所以"从第一帧就用 verlet"是正常的，
问题只出在"中途切换"。

### 修复（A + D）

- **A. 唯一切换入口** `ParticleSystem.set_integrator(name)`：切换时
  `pool.aux[:count] = NaN`，复用 `spawn()` 已有的哨兵约定，让新积分器
  在下一步对全部粒子做首步初始化。同名重复设置是 no-op（不作废历史）。
  面板 `ui/panel.py` 不再直接改两个字段。
- **D. 兜底校验** `integrators.repair_verlet_history(pool, h)`：在
  `step_physics` 里、`compute_vel` **之前**调用，检查 `|xₙ − aux|` 是否
  超出 `|v|·h` 的合理量级（100 倍容差），超了就按 `x − v·h` 重建。
  防的是绕过 `set_integrator` 直接改字段的路径。

  兜底放在系统层而不是积分器函数里，是因为 `verlet` 自己不维护 `vel`
  （只有 `compute_vel` 会刷新它），函数内部拿不到可信的量纲基准——
  第一版写在 `verlet()` 内部，直接把合法历史误判成脏数据，
  `test_symplectic_energy_bounded[verlet]` 与 `test_verlet_velocity_estimate`
  立刻失败，据此改到系统层。

顺带：`ParticleSystem.__init__` 对未知积分器名改为抛 `ValueError`
（原先直接 `KeyError`）。

### 验证

文字场景稳态后遍历全部 12 种切换组合（走 `set_integrator`）：

```
euler           -> verlet           n 8000->8000  err 0.00 -> 0.00
velocity_verlet -> verlet           n 8000->8000  err 0.00 -> 0.00
leapfrog        -> verlet           n 8000->8000  err 0.00 -> 0.00
（其余 9 组同样 8000->8000，全部 ALL OK）
```

其余四场景 `velocity_verlet -> verlet` 后粒子数均稳定在
`706~100%`（喷泉 9050→8949、雪 3978→6262、火焰 1787→1827、烟花 4529→4147）。

### 测试

```
228 passed in 28.05s
```

新增 27 个用例：`set_integrator` 拒绝未知名称 / 同名 no-op / 切换后 aux 为
NaN；**12 种积分器互切 × 系统不塌陷**（粒子数不变、无 NaN）；
3 种来源切到 verlet 时速度不突变；`repair_verlet_history` 识别三种脏
aux（0 / ±1e6）并能修复、不误伤合法历史、空池安全。

## 2026-11-03 新增 `textbook.md` 项目说明

按现有文件架构写了一份代码导读（821 行），覆盖 13 章：项目概览、目录与文件
职责、分层架构与一帧的数据流、`core/` `render/` `scenes/` `ui/` `utils/`
逐模块讲解（含关键 API、公式、参数）、五场景物理配方、201 个测试的分文件
索引与测试策略取向、关键设计决策与踩坑记录、性能画像、扩展指南，附录给出
模块↔课件页码对照。

写作过程中逐个核对实现细节，顺手修正了若干与代码不符的描述（粒子源码行数
3025、顶点着色器的 `u_point_scale`、`soft_disc` 的 smoothstep 方向、
`prefill` 只在测试里生效、文字场景 `life_mean=1e6` 的原因、`_load_scene`
重建条件等），确保文档与代码一致。README 加了指向 `textbook.md` 的链接。

`201 passed` 未受影响。

## 2026-11-03 修复面板缩放 / 下拉框贴图 / 文字输入

用户报告三个问题：全屏后面板仍然很小、点开下拉框会在面板上糊一块奇怪
贴图、文字改不动永远显示"粒子系统"。三处互相独立，逐个定位修复。

### 1. 全屏后面板不放大

面板位置已经跟上了窗口（上一轮修的），但**字号和间距还是 1 倍**，在
2560×1600 下只占左上角一小块。新增 `Panel.scale_for(w, h)`：按窗口相对
基准 1280×720 的**宽高比例几何平均**算倍数，夹在 `[1, 2.5]`。

- 用几何平均而不是长边：只取宽度在 16:10 全屏下偏小，只取高度在超宽屏
  下偏大，几何平均两端都温和（2560×1600 → 2.11 倍，1920×1080 → 1.5 倍）。
- 下限 1 倍：窗口比基准还小时不缩，否则字看不清。
- 上限 2.5 倍：4K/8K 下不让面板吃掉半个屏幕。
- 落地方式是 `style.font_scale_main`（字号）+ `style.scale_all_sizes()`
  （间距/圆角/滚动条）。注意 `scale_all_sizes()` 明确**不缩放字体**，
  两者必须分别设；而且它是**累乘**的，所以按"新倍数/上次倍数"增量应用，
  否则全屏再还原会叠成 4 倍。
- 面板初始位置/宽度也乘同一个倍数，只在其变化时写一次，用户拖动过的
  位置不会被每帧重置。

### 2. 下拉框弹出层糊出奇怪的三角形

这是**多 DrawList 的索引没有重定基**。Dear ImGui 的每个 `ImDrawList`
（主窗口一块、下拉框弹出层一块）的索引都从 **0** 开始编号、指向**自己**
的顶点数组；而我们的后端把所有 DrawList 的顶点**追加**到同一块 VBO 的
不同偏移处。第二块的索引 `0..119` 于是被解释成"整块 VBO 的第 0..119 个
顶点"——也就是主窗口的顶点，屏幕上的表现就是面板上拉出来一块三角形。

诊断时打印出来正好印证：

```
L0 nvtx=1318 nidx=2178 idx_min=0 idx_max=1317
L1 nvtx=120  nidx=192  idx_min=0 idx_max=119   ← 从 0 重新编号
```

修复：上传每块索引前整体加上该块的顶点基址（`vtx_offset / VERTEX_SIZE`）。
moderngl 的 `vao.render()` 没有 base-vertex 参数（只有 `first`），所以只能
改索引本身——官方 OpenGL3 后端也是这么做的。新增 `_rebase_indices()`。

顺带修掉一个**会上崩**的问题：`unicode_char_entered` 用的是
`io.add_input_character(ord(char))`，而中文输入法提交时 pyglet 一次给
整串（例如"测试"两个字符），`ord()` 抛 `TypeError`，异常穿透 pyglet 的
事件分发直接把程序打死。改为 `add_input_characters_utf8(char)`，
顺带也支持了 emoji 这类需要代理对的字符。

### 3. 文字改不动，永远显示"粒子系统"

`_draw_scene` 里每帧做 `if not self._editing_text: self._text_buffer =
scene.text`，而 `_editing_text` 取的是 `io.want_text_input`。点"应用文字"
那一帧输入框已经失焦（`want_text_input == False`），**同步先于按钮判断
执行**，缓冲被恢复成旧文字，于是 `set_text()` 收到的永远是原文。

反向也有坑：点输入框的下一帧 `want_text_input` 还是 `False`（焦点差一帧
到），这一帧的同步会把用户刚敲进去的字擦掉。

改为"记录上次对齐时的值"：只在**用户没在输入** 且 缓冲与场景文字不一致
且 **上次对齐以来场景文字没变过** 时才对一次。两边都能自愈，不再靠猜。
同时把"回车结束编辑"（`is_item_deactivated_after_edit`）也接上，作为
按钮之外的第二种提交方式。

### 验证（`tools/smoke_ui_bugs.py`，数值断言 + 截图目检）

```
[bug] windowed input_h=22.0
[bug] PASS panel scales with fullscreen windowed=22px fullscreen=46px
[bug] typed buffer='粒子系统新文字'
[bug] PASS typing reaches the input box buffer='粒子系统新文字'
[bug] PASS apply button updates the scene scene='粒子系统新文字' typed='粒子系统新文字'
[bug] PASS combo popup uses its own vertices drawlists=2 越界=[]
[bug] === ALL PASS
```

判据都是可量化的：全屏后输入框高度必须涨到 1.5 倍以上；弹出层出现时
DrawList 数必须 ≥2 且索引不越界；点"应用文字"后 `scene.text` 必须
等于输入框内容。另跑通过 `smoke_w2b.py`（文字收敛 + morph + 录制）与
`smoke_fullscreen.py`（三段尺寸往返），五场景截图像素统计正常。

### 测试

```
201 passed in 14.72s
```

新增 11 个用例：`scale_for` 的基准/全屏/下限/上限/最小化五个边界、
缩放同时作用于字号与间距且从 2 倍退回 1 倍不叠成 4 倍、
`unicode_char_entered` 收多字符串不乱、
索引重定基（整体加基址 / 基址 0 原样 / 空块）、
输入框缓冲在失焦后不被回滚、场景文字被外部改动后输入框能跟上。

## 2026-11-03 修复全屏下面板尺寸不更新

全屏（或最大化）后 ImGui 面板只画在左上角一小块、截图与录制也只覆盖
原窗口区域。这是三个独立的尺寸缓存同时失效，逐个修掉。

### 根因与修复

- **后端收不到 resize 事件**：`WindowConfig.assign_event_callbacks()` 只在
  子类**实现了** `on_resize` 时才把它绑给窗口，否则绑 `dummy_func`。
  `ParticleApp` 没有实现它，后端 `resize()` 从未被调用，`io.display_size`
  永远停在启动时的 1280×720。改为**每帧**在 `render()` 开头从窗口重新读取
  尺寸（`_sync_display_size()`），顺带覆盖 DPI 变化与最小化（0 尺寸时跳过，
  避免把 `display_size` 写成 0 后除零）。
- **`ctx.screen` 的尺寸是创建时缓存的**：`moderngl` 的默认帧缓冲对象在
  窗口全屏后 `fbo.size` 仍是旧值，因此 `fbo.read(components=3)` 只读回
  原来那块区域，`reshape` 到新尺寸直接 `ValueError`。改为显式传
  `viewport`：`fbo.read(components=3, viewport=(0, 0, w, h))`。
  `ctx.clear()` 同理，一并显式传 viewport。
- **绘制视口靠"上一帧残留"**：粒子渲染器会设置视口，ImGui 之前直接沿用，
  窗口尺寸一变就错位。改为绘制前显式设置成整个帧缓冲（与官方 OpenGL3
  后端一致，scissor 的 y 翻转也按同一基准算）。
- **多处尺寸来源不统一**：`main.py` 里 `buffer_size` / `fbo.size` 混用。
  统一为 `wnd.buffer_size`（它是 GL 真实的帧缓冲尺寸，高 DPI 下正确），
  涉及清屏、粒子/网格渲染、录制尺寸、鼠标拾取。

### 顺带修掉的多 DrawList 问题

`ImDrawData` 可能包含多个 `ImDrawList`（窗口被拖出主视口等）。原实现每块
都从缓冲偏移 0 写入，会互相覆盖。改为按官方后端的做法：所有 DrawList 拼进
同一块顶点/索引缓冲，各自按累加偏移写入，索引渲染的 `first` 也相应偏移。

### 验证（`tools/smoke_fullscreen.py`）

```
windowed        window=(1280, 720)  io.display_size=(1280.0, 720.0)
fullscreen      window=(2560, 1600) io.display_size=(2560.0, 1600.0)
windowed again  window=(1280, 720)  io.display_size=(1280.0, 720.0)
```

三张截图尺寸分别为 1280×720 / 2560×1600 / 1280×720，面板位置与字号正常；
全屏下录制经 ffmpeg 解码确认输出 2560×1600 / 60 fps。

### 测试

```
190 passed in 16.84s
```

新增 3 个用例：进入全屏后 `display_size` 跟上、HiDPI 下缩放因子为
buffer/size 之比、最小化（0 尺寸）时不污染 `display_size`。

## 2026-11-02 第四轮：文字粒子 + ImGui 面板 + 录制

对标 `plan.md` W2 后半，交付文字粒子（采样 + 软约束 + morph）、ImGui 参数面板、
MP4 录制，五场景全交互；+56 个新测试（131 → 187），全部通过。

### 新增

- **`utils/sampling.py`** — 文字 → 3D 点云：Pillow 渲染灰度位图 → 阈值化 →
  取亮像素 → **按字形包围盒**归一化到世界坐标。采样用系统抽样（等间隔）而非
  随机抽，同一段文字每次得到同一组目标点，morph 才稳定；点不够时整除复制
  并加亚像素抖动，避免多个粒子重叠成一个点。
- **`scenes/text_particles.py`** — 文字粒子场景，物理直接用课件 P25 的软约束
  `f = −k(x−x_target) − c·v`（`core.forces.TargetConstraint`）。
  `build()` 一次性布好 8000 粒子（`prefill = True`），从球状爆散出发被拉成文字；
  `set_text()` 重采样目标点，粒子顺势流到新字形（morph）；
  `set_mouse_world()` 挂/摘一个负强度 `Attractor`（排斥源），鼠标划过即可扰动文字。
- **`ui/panel.py`** — ImGui 控制台：全局（场景按钮/积分器/固定步长/暂停/慢放/
  纹理/网格）、场景参数（按 `type(force).__name__` 分派，Gravity/Drag/Wind/
  Buoyancy/TargetConstraint/Attractor 各有滑块）、统计数据。面板**不持有状态**，
  改完直接写回 `app` / `scene` 对象，所以"即时生效"是自然结果。
- **`ui/imgui_backend.py`** — 自实现的 moderngl ImGui 渲染后端。`moderngl-window`
  3.1.1 的集成调用 `get_tex_data_as_rgba32()`，该 API 在 Dear ImGui 1.91 已被
  移除，故按新的 `ImTextureData` + `BackendFlags_RendererHasTextures` 协议重写：
  每帧检查 `platform_io.textures` 里各纹理的 status（want_create / want_updates /
  want_destroy）按需创建与增量更新，并保留鼠标键盘事件转发。
- **`utils/recorder.py`** — 基于 `imageio-ffmpeg.write_frames()` 的 MP4 录制，
  按 `R` 开/关，成片含面板（所见即所得）。
- **`main.py`** — 接入第五个场景、面板、录制；`1-5` 切场景、`G` 显隐面板、
  `R` 录制、`T` 重置；文字场景下做屏幕→世界平面射线求交，把鼠标位置喂给排斥源。
- **`render/camera.py`** — `screen_ray()` / `project_to_plane()`：像素坐标 → 世界射线 →
  与文字所在平面求交。

### 修复（开发中发现的问题）

- **面板顶点格式写错**：颜色用了 `4f`（4×float=16 字节），而 `ImDrawVert` 的颜色是
  4×ubyte，导致 stride 24 而非 20 —— 面板被画成一片斜线。改为 moderngl 的归一化
  写法 `4f1`，并把这条格式串提为 `VERTEX_FORMAT` 常量加断言守住。
- **索引宽度硬编码 2**：`ImDrawIdx` 实际是 32 位（`imgui.INDEX_SIZE == 4`），
  改为跟随库的常量。
- **`ImDrawCmd.texture_id` 已不存在**：1.91+ 换成 `ImTextureRef`，取 id 要走
  `cmd.get_tex_id()`。
- **`get_pixels_array()` 是一维扁平缓冲**：`(h·w·4,)` 而非 `(h,w,4)`，矩形增量更新
  前必须 reshape；且 `tex.updates` 是 `ImVector_ImTextureRect`，只支持整数下标、
  不能切片。
- **文字输入框永远是空的**：`imgui.input_text` 的第三参数是 **flags 不是缓冲长度**，
  照 pyimgui 旧习惯传 `64` 会命中 `InputTextFlags_EnterReturnsTrue`（回车前不回传）。
  已去掉该参数，并在测试里模拟键入中文验证。
- **长句子横向冲出视野**：`mask_to_points` 只按高度归一化，"Computer Animation"
  这种长文本宽度能到 14 个世界单位。新增 `world_width` 上限，缩放取
  `min(高度尺度, 宽度尺度)`，两目标冲突时整体等比缩小。
- **文字压在地面网格上**：字形中心原本在 y=0，下半截与网格重叠。引入
  `center_y = 2.2`，采样点与爆散中心一起抬高，相机 target 同步。
- **`build_imgui_renderer` 失败时残留上下文**：降级返回 None 前先销毁刚创建的
  ImGui 上下文，避免全局脏状态。
- **冒烟脚本按帧数计拍错时**：本机帧率 50~540 FPS 波动，"第 420 帧"可能只模拟了
  0.8~1.5s，拍到的是没收敛的散点。改为按 `system.time` 推进检查点。

### 中文显示

Dear ImGui 1.92+ 改为按需动态光栅化，`ImFontConfig` 里已无 `glyph_ranges` ——
直接挂一个含 CJK 的 TTF 即可显示任意汉字。后端按
`msyh.ttc → msyhbd.ttc → simhei.ttf → Deng.ttf → PingFang → NotoSansCJK`
顺序探测，全都没有则退回内置字体（无中文，其余功能正常）。

### 冒烟测试（真实窗口，`tools/smoke_w2b.py`）

```
[smoke] switched to text, count=8000
[smoke] t=6.00s 收敛截图 bright=62362
[smoke] mp4 105 帧, 101697 字节
[smoke] morph -> 'Computer Animation'
[smoke] t=12.01s morph 截图 bright=56631
```

截图目检：文字居中成形、面板中文正常、输入框显示当前文字、morph 后改为
"Computer Animation" 且收在 9 单位宽度内。录制文件经 ffmpeg 解码验证：
h264 / yuv420p / 1280×720 / 60 fps / 1.75 s，画面正常。

### 性能

文字场景 8000 粒子：纯物理（发射+积分+约束+着色）1.10 ms/帧
（10 秒仿真 0.66 s，合 909 FPS 的物理预算）。真实窗口 1280×720 含面板与录制
读回，实测 50~540 FPS 波动（读回 fbo 与 ffmpeg 编码是主要开销，非粒子本身）。

### 测试

```
187 passed in 45.67s
```

新增覆盖：文字采样（掩膜包围盒归一化/系统抽样确定性/宽度上限）、文字场景
（软约束收敛到目标/字形包围盒/morph 换目标/抬离地面/鼠标排斥的挂摘与推离/
着色随汇聚变亮）、录制器（帧计数/尺寸校验/关闭后再写报错）、面板
（无上下文降级/真实上下文跑两帧拿到绘制数据/输入框收得下中文）、
ImGui 后端静态约定（顶点 stride=20、索引宽度跟随库、纹理状态枚举、
`get_tex_id` 存在、无窗口时降级）。

## 2026-11-02 第三轮：三新场景 + 场景切换

对标 `plan.md` W2 前半，交付 烟花/火焰/雪 三场景、场景协议基类、引擎两处增强
+ 46 个新测试（85 → 131），全部通过；四个场景真实窗口截图目检通过。

### 新增

- **`scenes/base.py`** — `Scene` 基类，把"一个场景"抽象成
  `name / capacity / blend / texture / build() / shade() / update() / reset()`。
  `blend` 与 `texture` 由场景自己声明，`main.py` 据此重建渲染器——
  雪用 alpha+soft_disc，其余用 additive，无需在入口写分支。
  附 `lerp_stops()`：按生命分数对关键帧颜色做线性插值（含越界夹紧）。
- **`scenes/fireworks.py`** — 烟花：`Rocket` 走**解析弹道**（池外对象，
  不受 `compact()` 重排影响），到顶点（`v_y≤0` 或引信到期）在其位置
  调用 `SphereBurstEmitter` 球面炸开 1100 颗火星；每帧沿火箭轨迹补 14 颗
  短命火星作上升光尾；5 组配色轮换，粒子数按剩余槽位截断。
- **`scenes/fire.py`** — 火焰：贴地扁体积源 + `Buoyancy`（浮力∝剩余生命）
  + 强阻力 + 横向伪湍流；颜色 亮黄→橙→暗红→灰烬，尺寸随生命收到 20%，
  形成上窄下散的火舌。
- **`scenes/snow.py`** — 雪：9000 粒子量级的大盒体积源 + 弱重力 + 线性/平方
  阻力（终端速度 ≈1 m/s）+ 定常侧风与湍流；落地即剔除（不弹跳）；
  alpha 混合软圆盘，尺寸随下落略微增大。
- **`main.py`** — 数字键 `1-4` 切场景（切场景时重建相机/渲染器/网格并重置
  标题栏）、`R` 重置当前场景。
- **引擎增强**：
  - `core/forces.py` `Buoyancy`：`a_y = g · life_fraction`（火焰/烟雾上升）。
  - `core/pool.py` `size0`：记录出生尺寸，供场景做"随生命缩放"的基准。
  - `core/system.py` 判死**快路径**：全活时跳过 `compact()` 的全字段重排。
  - `core/forces.py` `Wind`：垂直基 `(d1,d2)` 构造时算一次并缓存
    （原实现每物理子步重算 `norm`/`cross`，占掉约 1/3 帧时间）；
    并修掉 `base` 沿 z 时 `(−b1,b0,0)` 退化为零向量导致的除零隐患。
- **`tools/smoke_scenes.py`** — 开发期辅助脚本：逐场景跑 300 帧、读 fbo、
  存截图并统计亮度/粒子数（不入库交付范围，仅用于画面回归）。

### 渲染调参（第一版截图全部不合格，靠截图-分析-改参迭代）

- **火焰**：初版是一团纯白圆球——加法混合下 3200 粒子/s × 尺寸 0.30 使密集区
  亮度全部 clip。压暗色板 alpha（0.42 上限）、缩体积源到 1.1 宽、
  降发射率到 1100/s、浮力提到 9.5 拉出火舌，才得到分层火焰。
- **烟花**：初版整屏几乎全黑——相机 target y=18 俯视空洞区，且粒子尺寸 0.075
  太小。相机降到 y=9 距离 30、火星尺寸 0.24、爆发数 1100 后画面正常。
- **喷泉**：初版水柱极细极暗——发射率 900/s、尺寸 0.055。提到 2200/s、
  尺寸 0.105、相机距离 16→13，三条水拱才清晰。
- **雪**：初版 30k 粒子 72ms/帧（≈14 FPS）。降发射率并放大雪花后
  稳定在 ~9.5k 粒子 18ms/帧（≈55 FPS）。

### 修复（开发中发现的问题）

- `main.py._load_scene()` 调 `_update_title()` 时读 `self.fps`，
  而 `fps` 在其后才初始化 → 构造窗口必崩。改为先初始化 FPS 状态再装场景。
- `ParticleRenderer` 缺 `release()`、`GridRenderer` 缺 `extent` 属性，
  切场景的重建逻辑无从判断 → 补上。
- `lerp_stops()` 对 `frac` 越界未夹紧，`i0` 索引在边界处取到越界行
  → 先 `np.clip` 再插值。

### 性能（稳态，含发射+物理+着色，60fps 预算 16.7ms）

| 场景 | 稳态粒子数 | 每帧耗时 |
|---|---|---|
| 喷泉 | ~9.0k | 6.2 ms |
| 雪 | ~9.5k | 17.7 ms |
| 火焰 | ~1.8k | 3.9 ms |
| 烟花 | ~4.2k | 3.8 ms |

雪场景仍是最重的（粒子多 + 三个力场逐粒子求值），如实记录。

### 测试

```
131 passed in 36.36s
```

新增覆盖：场景协议一致性（4 场景参数化：能构造/推进/重置/无 NaN/颜色合法）、
`lerp_stops` 端点与越界、`Buoyancy` 与生命分数的正比关系、风场垂直基缓存
与退化方向、烟花的火箭弹道真值对比/顶点判定/引信/球面速度分布/容量保护/配色保持、
雪的终端速度与出界剔除、火焰净上升与随生命变暗变细。

## 2026-10-31 第二轮：渲染层 + 喷泉场景

对标 `plan.md` W1 后半，交付 `render/` 四模块、`scenes/fountain.py`、`main.py`
入口 + 27 个新测试（58 → 85），全部通过。

### 新增

- **`render/camera.py`** — 手写 lookAt / 透视投影矩阵（float32，右手 OpenGL 约定）；
  `OrbitCamera` 轨道相机（yaw/pitch 旋转、滚轮缩放、右键平移），
  `pixels_per_unit = 0.5·H / tan(fovy/2)` 供点精灵透视缩放。
- **`render/textures.py`** — 程序化粒子纹理（课件 P26–30）：`gaussian_spot`
  （高斯光斑，默认）、`soft_disc`（smoothstep 软圆盘，雪花/烟）、`ring`
  （r=0.7 环，火花）。全 RGBA float32，RGB=白（着色靠粒子色）。
- **`render/particles.py`** — GPU 点精灵渲染器（GL 3.3，课件 P26/P40）：
  交错缓冲（pos3+color4+size1，8 float），`gl_PointSize` 透视缩放并 clamp
  到驱动上限；两种混合模式——additive `glBlendFunc(SRC_ALPHA, ONE)`
  叠加越叠越亮（点光源模型）、alpha 常规透明（前后遮挡）；
  颜色预乘自身 alpha 作为加法混合亮度；粒子不写深度按绘制顺序混合。
- **`render/ground.py`** — 地面网格 + RGB 坐标轴（LINES）。
- **`scenes/fountain.py`** — 喷泉场景：3 个锥形点源（主直立 + 2 侧倾 ∓0.45rad）、
  重力 + 线性阻力、地面碰撞（ε=0.30, μ=0.10）、KillBox 剔除；
  寿命关键帧渐变 白→天蓝→深蓝→暗淡。
- **`main.py`** — `WindowConfig` 模式入口：轨道相机输入（左键旋转/右键平移/
  滚轮缩放）、Space 暂停、F 截图（手工 PNG 编码，zlib chunk，免图像库依赖）、
  标题栏 FPS 统计。
- **`tests/`** — 新增 4 个测试文件 27 个用例：lookAt 几何性质（eye→原点、
  目标→−z、保距）、透视 near/far 映射、纹理径向对称/单调性/环峰位置、
  独立 GL 上下文像素级断言（加法混合叠加更亮、alpha 混合饱和、
  非法 blend 拒绝）、喷泉动态平衡（粒子数收敛、颜色随寿命变暗）。

### 修复（开发中发现的问题）

- 渲染层相对导入 `from ..core.pool` 超出顶层包 → 全部改绝对导入。
- `GL_POINT_SIZE_RANGE` 在本机驱动返回 tuple `(1.0, 255.0)` 而非字符串
  → isinstance 分支处理两种格式。
- moderngl-window 3.x 回调协议是 `on_render(time, frame_time)` 而非 `render`，
  事件为 `on_key_event` / `on_mouse_drag_event` 等 → 全部重命名；
  事件返回值非 None 会触发 NotImplementedError。
- 早期直接子类化 pyglet Window 与 `run_window_config` 冲突
  （AttributeError log_level / add_arguments）→ 改为标准 WindowConfig。
- 窗口冒烟测试中 `window.close()` 后主循环仍继续触发 flip 崩溃
  → 用 `pyglet.app.exit()` 退出。

### 冒烟测试（真实窗口）

```
200 帧 @ 250–650 FPS，稳态 730 活粒子，亮像素 7699
截图 output/frame_506.png：1280×720，亮像素质心 (0.50, 0.57) 居中，
中部亮度 21.3 高于顶部 14.3 —— 水柱居中、地面网格可见
```

### 测试

```
85 passed in 7.01s
```

## 2026-10-31 第一轮：引擎核心（最小功能）

对标 `plan.md` W1 前半，交付 `core/` 六模块 + 58 个 pytest 测试，全部通过。

### 新增

- **`core/pool.py`** — 粒子数据池：SoA NumPy 布局，活粒子压缩在 `[0, count)`；
  `spawn()` O(1) 返回连续索引、`compact()` 布尔掩码批量删除；
  `aux` 字段缓存积分器历史（Verlet 的 xₙ₋₁ / Leap-Frog 的半步速度），
  NaN 标记"新粒子/碰撞后需重置"。
- **`core/integrators.py`** — 课件四种积分器（P44–58），统一接口可切换：
  显式 Euler、标准 Verlet、Leap-Frog、Velocity Verlet（默认）。
- **`core/forces.py`** — 力场（P20–25）：Gravity、Drag（线性+平方）、
  Wind（定常+多频正弦伪湍流）、Attractor（吸引/排斥）、PointSpringDamper、
  TargetConstraint（软约束，文字粒子用）；`accumulate_all` 清零叠加。
- **`core/emitters.py`** — 发射器（P13–14）：数量 `n=(m+v·rand())·A`、
  属性 `mean+variance·rand`；PointEmitter（锥形点源）、
  VolumeEmitter（盒体积源）、SphereBurstEmitter（球面一次性爆炸）。
- **`core/collisions.py`** — 平面碰撞（P42–43）：`N·(P−P0)<0` 检测、
  `v_new=−ε·v_n+(1−μ)·v_t` 响应、位置回拉接触点；KillBox AABB 出界剔除。
- **`core/system.py`** — ParticleSystem 五步循环调度（P12）：
  发射→寿命衰减→固定步长物理（accumulator 解耦渲染帧率，乘法取代循环减法避免浮点漂移）→剔除。
- **`tests/`** — 6 个测试文件 58 个用例：解析真值对比（自由落体）、
  能量守恒（Euler 发散 vs 辛积分器有界）、终端速度、公式逐项验证、
  端到端动态平衡、帧率解耦一致性。

### 修复（开发中发现的问题）

- `velocity_verlet`：新粒子首步 `acc` 为池初值 0，漏掉首步加速度 → 首步先求 a(t₀)
  （2 秒自由落体累积误差从 0.08m 消除）。
- `euler`：误写成半隐式（先位置后速度），能量有界不发散 → 改回真显式（旧速度推位置）。
- `leapfrog`：新粒子 `aux` 初始化在求力之前，首步即用被污染的加速度 → 移到求力后。
- `pool.compact`：`arr[:n] = arr[:n][alive]` 形状不匹配 → 先取 `kept` 再赋值。
- 固定步长累积器：循环减法浮点漂移（0.5s 只走 59/60 步）→ `int(acc/h)` 一次算步数。
- `PlaneCollider`：默认 friction 0.05 干涉弹性反射测试 → 默认改 0（摩擦按需开启）。

### 性能（冒烟测试，60fps 帧预算 16.7ms）

| 规模 | 每帧耗时 | 说明 |
|---|---|---|
| 1 万粒子 | 5.1 ms | 全功能（含碰撞+剔除） |
| 10 万粒子 | 47–77 ms | 纯物理 47ms；瓶颈在 NumPy 临时数组分配 |

10 万级后续可优化（float32、`out=` 原地运算、预分配缓冲），当前 1–3 万粒子的
场景规模已足够，优化记入后续轮次。

### 测试

```
58 passed in 1.59s
```
