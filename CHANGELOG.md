# 更新日志

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
