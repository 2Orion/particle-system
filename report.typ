#import "@local/tplt:0.3.0": *

#show: chap-num

#let ymd = "2026-11-4"
#let course = "计算机动画"
#let teacher = []
#let proj-name = [粒子系统]


#zju-cover(
  course: course,
  teacher: teacher,
  student-count: 1,
  students: ([2Orion -- 324010xxxx]),
  ymd: ymd,
)

#show: BL
#show: RP.with(
  course: course,
  proj-name: proj-name,
)

#exp-info-chart(
  teacher: teacher,
  course: course,
  student-count: 1,
  students: (
    ([2Orion], [324010xxxx], [计算机科学与技术]),
  ),
  ymd: ymd,
  exp-cate: [],
  exp-name: "粒子系统",
  where:[],
)

#outline()

#pagebreak()

#let codebox(body, size: 0.82em) = align(left)[
  #set text(size: size)
  #block(
    width: 100%,
    stroke: 0.5pt + luma(150),
    radius: 4pt,
    inset: 8pt,
    above: 0.6em,
    below: 0.6em,
    body,
  )
]

= 项目介绍

== 项目简介

本作业实现了一个*基于 GPU 点精灵的实时 3D 粒子系统*，用 Python + NumPy 完成
物理计算、用 ModernGL（OpenGL 3.3）完成绘制，并以 Dear ImGui 提供运行时参数面板。
程序启动即进入一个可自由旋转/缩放的 3D 场景，内含五个可以随时切换的粒子特效：
*喷泉、雪、火焰、烟花、文字*。所有效果都由课堂中讲到的粒子系统和算法实现。
粒子系统模型直接驱动，没有使用任何商业软件或预制素材——粒子纹理、地面网格、
文字点云全部在运行时程序化生成。

与之配套的一套离线脚本可以把画面导出为 PNG 与 MP4，五个特效的物理内核都
可以在没有窗口的环境下独立运行，因此本作业的 238 个单元测试全部可在纯 CPU
上复现（详见 @sec-test）。

=== 输入与输出

#figure(
  table(
    columns: 2,
    align: (left, left),
    table.header([类别], [内容]),
    [输入], [键盘/鼠标事件（相机、场景切换、参数调节）、面板滑块数值、文字内容字符串],
    [中间产物], [每帧一个粒子池（位置/速度/加速度/寿命/颜色/尺寸的 SoA 数组）],
    [输出], [实时渲染窗口（GL 3.3，默认 1280×720）、可选 MP4 录制、PNG 截图],
  ),
  caption: [输入、中间产物与输出],
)

主要功能：

+ *五个场景*，各自有独立的发射器组合、力场与着色规则，可按键 `1`–`5` 即时切换；
+ *实时参数面板*，积分器、固定步长、发射率、重力、阻力、湍流、约束刚度、
  粒子尺寸、文字内容全部可拖动修改，*改动即时生效*；
+ *运行时切换积分器*，四种数值方法（显式 Euler / Verlet / Leap-Frog /
  Velocity Verlet）可在算法运行中途互换；
+ *文字粒子*，把任意文本采样成 3D 目标点云，粒子在软约束下汇聚成字形，
  换字时连续流动成新字形（morph），鼠标划过可直接扰动；
+ *MP4 录制*与*PNG 截图*，所见即所得（含面板）。

=== 预期动画效果

- *喷泉*：三股水柱（中间主喷 + 两侧斜抛）受重力与线性阻力下落，落地弹起小水花，
  颜色随寿命从亮白转天蓝再淡出；
- *雪*：约 7000 片雪花从高空体积源缓缓飘落，受弱重力、双项阻力与多频正弦湍流风，
  落地即消失，前后遮挡由 alpha 混合给出；
- *火焰*：贴地扁体积源向上喷出，浮力随剩余生命衰减，被横向伪湍流撕开，
  颜色由亮黄经橙、暗红过渡到灰烬，尺寸收至 20% 形成火舌；
- *烟花*：火箭按解析弹道升空（带上升光尾），到顶点爆炸成 1100 颗球面均匀分布
  的火星，火星受重力与平方阻力下坠并逐渐熄灭，五组配色轮换；
- *文字*：8000 颗粒子从中心球状爆散出发，被软约束拉成"粒子系统"四个字，
  越靠拢越亮；换字时整体流动变形；鼠标位置作为排斥源把笔画推开，松开后自动复位。

== 动画实现

动画实现具体包含以下过程：

+ *生成新粒子*：发射器按 `n = (m + v·Rand())·A` 决定这一帧发几个；
+ *赋予属性*：位置、速度、寿命、尺寸按 `Value = mean + Rand()·variance` 抽样；
+ *删除过期粒子*：寿命耗尽、淡出完毕或飞出剔除框的粒子被压缩删除；
+ *移动变换*：在固定步长下对力与速度积分，再处理碰撞响应；
+ *绘制*：把活粒子打包成顶点数据，用带纹理的点精灵混合绘制。

每个场景都是这五步的一个配置：换掉发射器、力场组合与着色函数，就换了一个效果。
下面的三个小节把上述五个特效归为三组来说明（喷泉/火焰/雪共用"持续发射 + 力场"，
烟花是"一次性爆发 + 池外弹道"，文字是"软约束汇聚"）。

=== 喷泉、火焰、雪花

三者区别只在*力的配方*和*混合模式*，引擎部分是同一份代码。

*喷泉*由三个 `PointEmitter` 组成（主喷竖直、两侧的副喷向中心倾斜 0.45 rad），
每个发射器在方向锥 `±angle_var` 内取初速，因此水柱自然散开。物理只有重力与
线性阻力 `a = g − k_1 v`，落地时按 `v_new = −ε·v_n + (1−μ)·v_t`（ε = 0.30,
μ = 0.10）弹起并拉回接触点。

*火焰*用贴地的扁盒子体积源向上喷出，关键在于浮力*随剩余生命衰减*：

$
a_y = g_"buoy" dot f_"life", quad f_"life" = "life" / "max_life"
$

粒子刚出生时浮力最大、上升最快，燃尽后浮力消失，于是火焰自然形成"根部宽、
尖端收细并散开"的火舌形状。再叠加一个横向多频正弦风场把火舌撕开、并把尺寸
按生命收缩到 20%，配合加法混合就得到分层的黄—橙—红—灰。

*雪*用 18×9×18 的高空大盒体积源，让雪花在出生时就铺满整个下落区间；重力很弱
（1.6 m/s²），阻力取线性 + 平方两项，使下落速度很快饱和在 1.5 m/s 左右
（"慢慢飘"），再叠加定常侧风与湍流产生横向游走。它是唯一使用 *alpha 混合*的
场景——雪花之间要正确处理前后遮挡，而加法混合会把重叠区叠亮成一团白。

=== 烟花

烟花是唯一有"调度状态"的场景：火箭不能当普通粒子对待。原因是粒子池在删除粒子时
会把所有活粒子*压缩重排*，用索引去跟踪"哪一颗是火箭"会在重排后失效。因此火箭
被实现为池外的一个轻量对象，按解析弹道逐步推进：

$
v arrow.l v + g dif t, quad x arrow.l x + v dif t
$

每帧计时器到期就发射一发火箭（随机起点、随机初速、轮换配色），升空途中每帧在
火箭位置补 14 颗短命小火星形成光尾；当竖直速度 `v_y <= 0`（或 10 s 的保险引信
到期）即判定到达顶点，在该位置调用 `SphereBurstEmitter` 一次性喷出 1100 颗粒子。

爆炸方向的均匀性有个容易踩的坑：直接对球坐标的极角 θ 均匀取样会让两极堆积，
正确做法是用*三维正态向量归一化* `d = n/‖n‖, n ~ N(0,I)`，这在球面上严格均匀。
火星随后受重力与平方阻力 `a = g − k_2 |v| v` 下坠，透明度随剩余寿命衰减。

=== 文字动画

文字场景的物理内核是*软约束 / 能量函数*。给每个粒子指定一个目标点
$x_"target"$，定义约束能量与对应的力：

$
E = 1/2 k norm(x - x_"target")^2, quad
f = -(partial E)/(partial x) = -k (x - x_"target") - c v
$

其中 $-c v$ 是额外加入的线性阻尼，用来抑制弹簧振荡（若无阻尼，粒子会在目标点
附近来回摆动）。粒子因此不是"被摆放"到目标上，而是被物理*拉*过去，汇聚过程本身
就是动画。

目标点云由文字生成：用 Pillow 把文字渲染成灰度位图 → 阈值化取笔画像素 →
按字形*实际包围盒*归一化到世界坐标（高 3 单位，另设 9 单位的宽度上限，
防止长句子横向冲出视野）→ 重采样成恰好 8000 个点。采样用*系统抽样*（等间隔）
而不是随机抽，同一段文字每次都得到同一组目标点，morph 才稳定。

换字（morph）时只改写约束的目标数组，粒子在软约束作用下整体流动到新字形。
由于粒子在池内保持稳定顺序、目标点也按确定性顺序生成，重排表现为整体流动
而不是相互穿越乱窜（实测新旧目标点平均位移 3.2 个世界单位）。

鼠标交互是把屏幕像素位置反投影到过相机目标点、朝向相机的平面上，得到世界坐标，
再在这个位置挂一个负强度的 `Attractor`（排斥源，$f = s d / (|d|^2 + epsilon)$，
$s < 0$）。移开鼠标即撤掉该力，粒子被软约束拉回原位。

= 算法与原理

== 粒子系统的通用模型

粒子系统把"没有明确边界的自然现象"（水、火、烟、雪）看作大量简单粒子的集合，
每个粒子只遵循少数几条局部规则。课件 P11 给出了三条基本假设，本项目全部遵守：
粒子之间*互不碰撞*、*不投射阴影*、都有*有限生命周期*。这使整个系统退化为
"对每个粒子独立积分同一个常微分方程"，可以用数组运算一次算完所有粒子。

课件中的粒子系统属性在这里一一对应：

#figure(
  table(
    columns: 2,
    align: (left, left),
    table.header([课件中的属性], [本项目中的载体]),
    [Particle List（粒子列表）], [`ParticlePool` 的 SoA 数组，活粒子压缩在 `[0, count)`],
    [Position / Velocity / Acceleration], [`pos` / `vel` / `acc`，形状 `(n, 3)`],
    [Emission Rate（发射率）], [`Emitter.rate_mean` / `rate_var`],
    [Forces（外力）], [`forces` 列表，每项实现 `apply(pool)`],
    [Current State（当前状态）], [`life` / `max_life` / `color` / `size`],
    [Blending（混合方式）], [场景声明的 `blend`，映射到 `glBlendFunc`],
    [Representation（表现形式）], [带纹理的点精灵，三种程序化纹理],
  ),
  caption: [课件中的粒子系统属性与本项目实现的对应关系],
)

== 力的模型

课件把力分为一元力、n 元力与环境力，本项目按同一分类实现（`core/forces.py`）。
所有力只做一件事：把加速度*累加*到 `pool.acc`（质量按 1 处理），最后统一积分。

*一元力*（每个粒子自变量的函数）：

+ 重力：$a = g$
+ 粘性阻力：$a = -(k_1 + k_2 norm(v)) v$，线性项适合水花，平方项适合高速下落
+ 风场：$w(x,t) = w_0 + sum_i A_i sin(omega_i t + k_i x + phi_i) d_i$，用两组不同
  频率与相位的正弦叠加，在空间上连续、时间上不规则，作为 curl noise 的廉价替代

*n 元力*在这里被简化为"粒子—固定锚点"的弹簧阻尼
$f = -k_s (norm(d) - l_0) hat(d) - k_d v$，避免了 $O(n^2)$ 的粒子对计算。

*环境力与约束*：吸引子 $a = s d / (norm(d)^2 + epsilon)$（$s<0$ 即排斥子），
以及文字场景用的软约束 $f = -k(x - x_"target") - c v$。

其中两个参数对画面的影响最直接：

- *阻力系数*决定"速度上限"。喷泉的 $k_1 = 0.28$ 让水花在 1 m/s 量级饱和、
  保持水感；火焰用 $k_1 = 1.5, k_2 = 0.35$ 把上升速度封顶在 6 m/s 左右，
  否则火舌会窜出画面；雪用较重阻力让下落速度饱和在 1.5 m/s。
- *软约束刚度 k 与阻尼 c* 决定汇聚的"手感"。$k$ 越大收敛越快但越容易振荡，
  $c$ 决定是否过冲（见 @sec-text-tuning 的实测）。

== 数值积分

粒子运动方程 $dot(x) = v, thin quad dot(v) = f(x, v)/m$ 是常微分方程，
数值解是一条折线而非真实积分曲线。项目实现课件中提到的四种方法：

#figure(
  table(
    columns: 4,
    align: (left, left, left, left),
    table.header([方法], [更新公式], [精度], [特点]),
    [显式 Euler], [$x arrow.r x + h v$, $v arrow.r v + h a$], [1 阶],
    [位置用*旧*速度推进，保守系统能量单调发散],
    [Verlet], [$x_{n+1} = 2x_n - x_(n-1) + a h^2$], [2 阶],
    [无显式速度，需由位置差分估算],
    [Leap-Frog], [$v_(t+h/2) = v_(t-h/2) + a h$, $x arrow.r x + v_(t+h/2) h$], [2 阶],
    [速度半步步进，位置与速度不同步],
    [Velocity Verlet], [$v arrow.r v + 1/2(a_n + a_(n+1)) h$], [2 阶],
    [位置速度同步，本项目默认],
  ),
  caption: [四种积分器（对应课件 P51–58）],
)

== 积分器的两条性质

*辛性（symplecticity）*是这里最重要的概念。Verlet 家族的三种方法都是辛积分器，
它们在保守系统上不会像显式 Euler 那样持续注入或耗散能量，而是让能量在一个
有界的区间内振荡。这正是课件 P50 "误差把圆变成了螺旋线"所要避免的现象。
@tab-integrator 用简谐振子 $a = -omega^2 x$（$omega = 2$，$h = 1/120$，
跑 12 秒 ≈ 3.8 个周期）实测，显式 Euler 的能量在 12 秒内涨到初值的 1.49 倍，
而三种辛积分器的相对漂移始终低于 1.7%。

#figure(
  table(
    columns: 4,
    align: (left, center, center, center),
    table.header([积分器], [自由落体 2 s 位置误差], [简谐振动 $E(12" s") / E(0)$], [期间最大 $E/E_0$]),
    [euler], [$8.17 times 10^(-2)$ m], [1.4917], [1.4917],
    [verlet], [$1.1 times 10^(-13)$ m], [1.0064], [1.0083],
    [leapfrog], [$3.9 times 10^(-14)$ m], [1.0126], [1.0166],
    [velocity_verlet], [$3.9 times 10^(-14)$ m], [0.9999], [1.0000],
  ),
  caption: [四种积分器的精度与能量行为（$h = 1/120$，"自由落体"为从静止下落 2 s 的位置误差）],
)<tab-integrator>

*首步初始化*是 Verlet 家族特有的麻烦：递推式需要"上一步位置" $x_(n-1)$，
而新出生的粒子没有历史。项目用 `aux` 字段的 `NaN` 作哨兵标记"待初始化"，
并在首步按 $x_(n-1) = x_n - v_n h + 1/2 a h^2$ 构造历史（Leap-Frog 同理取
$v_(-h/2) = v_0 - 1/2 a h$）。

这里踩过一个值得记的坑：最初按 $x_(n-1) = x_n - v_n h$ 初始化（漏掉
$1/2 a h^2$），首步就多出 $1/2 a h^2$ 的*常量偏移*，之后每步原样保留。
结果 Verlet 与 Leap-Frog 在 2 s 自由落体上的误差与本应最差的显式 Euler
完全一样（都是 0.0817 m），二阶精度名存实亡（@tab-integrator 已含修正）。
修正后二者在常加速度下精确到机器精度。这个 bug 是在为本题准备数据时
才被发现的——单元测试原来只断言"误差小于 5 cm"，正好放过了它。

== 固定步长与帧率解耦

渲染帧率会抖动（60/120/144 Hz 甚至卡顿），如果用帧间隔直接积分的，物理行为
会随帧率变化。项目采用*固定步长累加器*：

#codebox(
  ```python
  self._accumulator += dt
  steps = min(int(self._accumulator / h), self.max_substeps)  # 步数一次算出
  for _ in range(steps):
      self.step_physics(h)
  self._accumulator -= steps * h
  if steps == self.max_substeps:
      self._accumulator = 0.0          # 防螺旋：丢弃积压时间
  ```,
  size: 0.82em,
)

两处细节：步数用除法*一次算出*而不是循环减 `h`（浮点下 0.5 s ÷ 1/120 循环减
只剩 59 步，长期会让物理变慢）；步数上限防止"卡帧 → 补步 → 更卡"的正反馈。

固定步长的取值直接影响精度。@tab-stepsize 用简谐振动（有解析解
$x(t) = cos 2t$）测位置误差，步长每减半误差约降到 1/4，即 *2 阶收敛*。

#figure(
  table(
    columns: 3,
    align: (center, center, center),
    table.header([步长 $h$], [$t = 1$ s 时位置误差], [步长减半后误差比]),
    [33.3 ms], [$3.36 times 10^(-4)$], [--],
    [16.7 ms], [$8.46 times 10^(-5)$], [3.98],
    [8.3 ms], [$2.09 times 10^(-5)$], [4.05],
    [4.2 ms], [$5.35 times 10^(-6)$], [3.90],
    [2.1 ms], [$1.34 times 10^(-6)$], [4.00],
  ),
  caption: [Velocity Verlet 的步长收敛性（简谐振动，$h$ 减半误差降至 1/4 ⇒ 二阶）],
)<tab-stepsize>

项目默认 $h = 1/120$（8.3 ms），每帧最多补 8 个子步，60 fps 下正好每帧 2 步。

== 粒子绘制与混合

粒子被绘制成始终朝向相机的*带纹理点精灵*。顶点着色器按透视做尺寸缩放：

$
"gl_PointSize" = "clamp"(("size" dot "pixels_per_unit" dot 2) / "dist", 1, "max_point_size")
$

其中 `pixels_per_unit = 0.5H / tan(fovy/2)` 是视口高度上的世界单位→像素比，
乘 2 是因为 `size` 存的是半径而 `gl_PointSize` 是直径，最后 clamp 到驱动支持的上限
（否则近距离粒子会被裁成方角）。

纹理只贡献 alpha，颜色完全由粒子自身的 RGBA 决定。两种混合模式对应课件的两类用法
：

#figure(
  table(
    columns: 4,
    align: (left, left, left, left),
    table.header([模式], [`glBlendFunc`], [合成结果], [使用场景]),
    [加法 additive], [`SRC_ALPHA, ONE`], [
      $C = C_"src" dot alpha + C_"dst"$，越叠越亮
    ], [喷泉、火焰、烟花、文字],
    [常规 alpha], [`SRC_ALPHA, ONE_MINUS_SRC_ALPHA`], [
      $C = C_"src" dot alpha + C_"dst" dot (1 - alpha)$，正确遮挡
    ], [雪],
  ),
  caption: [两种混合模式（对应课件 P40 的 Alpha Blending 公式）],
)<tab-blend>

加法混合下颜色需要预乘自身的 alpha，这样"渐隐"表现为*变暗*而不是变成半透明，
叠加起来才有真实的光感。@fig-blend 是同一堆雪花分别用两种模式绘制的结果，
可以观察到加法混合下密集区被叠成一团白（像素饱和度 8935 vs 990）。

#figure(
  grid(
    columns: 2,
    gutter: 6pt,
    image("output/fig/blend_additive.png", width: 100%),
    image("output/fig/blend_alpha.png", width: 100%),
  ),
  caption: [同一堆雪花：左为加法混合（重叠区叠亮），右为 alpha 混合（正确遮挡）],
)<fig-blend>

== 颜色与生命周期的关系

课件指出颜色与透明度应当是*剩余生命周期的函数*。项目把它做成关键帧插值
`lerp_stops()`：给定若干 `(生命分数, RGBA)` 关键点，按当前生命分数线性插值。
例如喷泉的关键帧是"出生近白 → 天蓝 → 深蓝 → 暗蓝淡出"。这样改配色只需改一张表，不必写任何分支。尺寸同理，用 `size0`（出生尺寸）作基准按生命分数缩放，
火焰因此能收到 20% 形成尖端。

= 程序实现

== 模块结构

依赖方向严格单向，这是整个工程最重要的约束：

#codebox(
  ```text
  main.py  ──►  ui/        面板：只读 app / scene 对象
     │
     ├──►  scenes/  ──►  core/          物理：发射器 / 力 / 积分 / 碰撞 / 调度
     │         └─────►  utils/sampling  文字 → 点云
     │
     └──►  render/  ──►  core/pool.py   只读，取粒子数据上传 GPU
  ```,
  size: 0.82em,
)

`core/` 不 import `render/`、`scenes/`、`ui/`；`render/` 不认识 `scenes/`。
好处是*物理逻辑可以脱离窗口在 pytest 里直接跑*，渲染逻辑可以用离屏 GL 上下文
做像素级断言。整个项目的源码规模如下：

#figure(
  table(
    columns: 4,
    align: (left, center, center, left),
    table.header([目录], [文件], [行数], [职责]),
    [`core/`], [6], [800], [粒子池、系统调度、积分器、力场、发射器、碰撞],
    [`render/`], [4], [429], [相机、点精灵渲染器、程序化纹理、地面网格],
    [`scenes/`], [7], [613], [场景协议 + 五个场景的配方与着色],
    [`ui/`], [2], [705], [ImGui 参数面板 + 自实现的 moderngl 渲染后端],
    [`utils/`], [2], [219], [文字→点云采样、MP4 录制],
    [`main.py`], [1], [306], [入口：窗口、渲染循环、输入分发、截图/录制],
  ),
  caption: [源码规模（不含测试）],
)

== 执行流程

一帧的完整路径（事件回调与渲染循环是两个阶段，moderngl-window 先派发完本帧
所有输入事件，再调用 `on_render`）：

#codebox(
  ```text
  on_render(time, dt):
      scene.update(dt * time_scale)          ← 场景推进（下面展开）
      ctx.clear(viewport = 窗口尺寸)
      grid.render(camera, size)              ← 地面网格
      renderer.render(pool, camera, size)    ← 点精灵 + 混合
      panel.draw(app, renderer, scale)       ← ImGui 顶点
      imgui.render(panel.draw_data())
      recorder.add_frame(fbo.read())         ← 录制（可选）

  scene.update(dt) 展开为：
      system.update(dt):
          emitters.emit(pool, dt)            ← 步骤 1+2：生成 + 赋属性
          life -= dt                         ← 步骤 3a：寿命衰减
          for _ in range(steps): step_physics(h)
              accumulate(pool)  →  a = Σ forces
              integrator(pool, h, accumulate)  ← 步骤 4：积分
              colliders.resolve(pool)          ← 碰撞响应
          compact(alive)                     ← 步骤 3b：删除
      shade()                                ← 按生命分数改颜色/尺寸
  ```,
  size: 0.78em,
)

== 关键数据结构：SoA 粒子池

课件中的 `ParticleSystem` 用一个 `Particle` 结构体数组存粒子。本项目改成
*结构体数组的转置*（Structure of Arrays）：每个属性单独一条 NumPy 数组。

#codebox(
  ```python
  self.pos    = np.zeros((n, 3))   # 位置
  self.vel    = np.zeros((n, 3))   # 速度
  self.acc    = np.zeros((n, 3))   # 加速度（力累加）
  self.aux    = np.full((n, 3), np.nan)  # 积分器附加状态；NaN = 待初始化
  self.life   = np.zeros(n)        # 剩余寿命
  self.size   = np.ones(n)         # 绘制尺寸
  self.color  = np.zeros((n, 4))   # RGBA
  ```,
  size: 0.82em,
)

好处是所有运算都能对活粒子区间 `[0, count)` 整体切片，一次算完。代价是删除粒子时
必须重排：`compact(alive)` 用布尔掩码把活粒子挑到前段。这比环形空闲链表实现简单
得多，且稳态下有一条"全活快路径"，只有真有死亡时才触发重排。

== 关键函数

*发射器*（`core/emitters.py`）。三个子类只实现 `_fill()`（填属性），计数与
切片由基类统一处理：

#codebox(
  ```python
  def emission_count(self, dt, area_factor=1.0):
      """课件 P13：n = (m + v·rand())·A"""
      n = (self.rate_mean * dt + self.rate_var * dt * np.random.uniform(-1, 1))
      return max(0, int(n * (area_factor if self.area_adaptive else 1.0)))

  def emit(self, pool, dt, area_factor=1.0):
      start, end = pool.spawn(self.emission_count(dt, area_factor))
      if end > start:
          self._fill(pool, start, end)   # 子类：位置/速度/寿命/尺寸/颜色
      return end - start
  ```,
  size: 0.82em,
)

*Velocity Verlet 积分器*（`core/integrators.py`）。注意新粒子首步需要先求一次
$a(t_0)$，因为池里的 `acc` 此时还是 0：

#codebox(
  ```python
  def velocity_verlet(pool, h, accumulate):
      fresh = _init_aux(pool)                 # NaN → 0，返回新粒子掩码
      n = pool.count
      pos, vel, acc = pool.pos[:n], pool.vel[:n], pool.acc[:n]
      if fresh.any():
          accumulate(pool, h)                 # 为新粒子求 a(t_n)
      old_acc = acc.copy()
      pos += vel * h + 0.5 * old_acc * (h * h)  # x_{n+1}
      accumulate(pool, h)                     # a(x_{n+1})
      vel += 0.5 * (old_acc + acc) * h        # v_{n+1}
  ```,
  size: 0.82em,
)

*平面碰撞*（`core/collisions.py`）。只修改位置与速度，并把 `aux` 置为 NaN
作废积分器历史（速度被改写过，Verlet 的"上一步位置"不再有效）：

#codebox(
  ```python
  s = (pos - self.point) @ self.normal          # 有符号距离
  hit = (s < 0.0) & (vel @ self.normal < 0.0)   # 已穿入且仍在靠近
  vn = (vel[hit] @ self.normal)[:, None] * self.normal
  vt = vel[hit] - vn
  vel[hit] = -self.restitution * vn + (1 - self.friction) * vt
  pos[hit] -= s[hit][:, None] * self.normal     # 拉回接触点
  aux[hit] = np.nan                             # 历史作废
  ```,
  size: 0.82em,
)

*软约束*（`core/forces.py`）与*文字采样*（`utils/sampling.py`）是文字场景的全部物理与素材来源，两者都很短：

#codebox(
  ```python
  def apply(self, pool):     # TargetConstraint（课件 P25）
      n = pool.count
      pool.acc[:n] += (-self.k * (pool.pos[:n] - self.targets[:n])
                       - self.damping * pool.vel[:n])

  def mask_to_points(mask, world_height, z_spread=0.0, world_width=None):
      rows, cols = np.nonzero(mask)          # 行优先，结果确定
      r0, r1, c0, c1 = rows.min(), rows.max(), cols.min(), cols.max()
      scale = world_height / max(r1 - r0 + 1, 1)    # 按字形包围盒缩放
      if world_width is not None:                   # 长句子按宽度封顶
          scale = min(scale, world_width / max(c1 - c0 + 1, 1))
      x = (cols - (c0 + c1) / 2) * scale
      y = ((r0 + r1) / 2 - rows) * scale            # 图像 y 向下 → 世界 y 向上
      return np.column_stack([x, y, np.zeros(len(x))])
  ```,
  size: 0.82em,
)

== 自己实现的部分

- *引擎全部*：粒子池、调度器、四种积分器、七种力场、三种发射器、碰撞与剔除、
  固定步长调度均为本项目从零实现，没有使用现成物理库。
- *渲染全部*：`lookAt` 与透视投影矩阵手写（不依赖 pyglm），点精灵着色器与
  混合模式、程序化纹理、地面网格均自己实现。
- *ImGui 后端*：`moderngl-window` 自带的 ImGui 集成调用的是 Dear ImGui 1.91
  已移除的 `get_tex_data_as_rgba32()`，本项目按新的 `ImTextureData` 协议
  *重写了一个 moderngl 渲染后端*（约 390 行），并实现了多 DrawList 的索引
  重定基、事件转发与中文字体加载。
- *文字采样与录制*：文字→点云、MP4 录制、手工 PNG 编码（zlib + chunk，
  不引入图像库）均为自写。

= 程序运行

== 运行环境

#figure(
  table(
    columns: 2,
    align: (left, center),
    table.header([项目], [版本 / 说明]),
    [操作系统], [Windows 11（10.0.26200），64 位],
    [Python], [3.14.7],
    [必需依赖], [`numpy 2.5.4`、`moderngl 5.13.0`、`moderngl-window 3.1.1`、`pillow 12.3.0`],
    [可选依赖], [`imgui-bundle >= 1.90`（参数面板）、`imageio-ffmpeg 0.7.0`（MP4 录制）],
    [测试依赖], [`pytest`（238 个用例，约 20–50 s）],
  ),
  caption: [运行环境与依赖版本],
)

两个可选依赖缺失时程序*自动降级*而不会崩溃：没有 ImGui 就退回快捷键模式，
没有 ffmpeg 则录制功能给出安装提示。因此任意环境都能 `python main.py` 启动。

== 运行方式

#codebox(
  ```bash
  pip install -r requirements.txt   # 依赖
  python main.py                    # 启动

  # 测试
  pip install -r requirements-dev.txt
  python -m pytest                  # 238 passed

  # 真实窗口冒烟（截图与 MP4 落到 output/）
  python -X utf8 tools/smoke_scenes.py
  ```,
  size: 0.84em,
)

#figure(
  table(
    columns: 2,
    align: (left, center),
    table.header([操作], [按键]),
    [旋转 / 平移 / 缩放], [左键拖拽 / 右键拖拽 / 滚轮],
    [切换场景], [`1` 喷泉 · `2` 雪 · `3` 火焰 · `4` 烟花 · `5` 文字],
    [重置 / 暂停 / 截图 / 退出], [`T` / `Space` / `F` / `Esc`],
    [面板显隐 / 录制开关], [`G` / `R`],
  ),
  caption: [键盘操作],
)

面板中的积分器、固定步长、发射率、各力场参数、约束刚度、粒子尺寸、文字内容
*改动即时生效*，无需重启。文字场景下移动鼠标可直接扰动粒子。

= 结果与分析

== 场景效果

以下截图由 `tools/report_figs.py` 在*离屏 GL 上下文*中渲染：同一场景用同一个相机、
同一组参数，只改变仿真时刻，因此"起始 / 中间 / 结束"三帧可以直接对比，
也不会被参数面板遮挡。

#figure(
  grid(
    columns: 3,
    gutter: 4pt,
    image("output/fig/fountain_t0.90.png", width: 100%),
    image("output/fig/fountain_t2.40.png", width: 100%),
    image("output/fig/fountain_t6.00.png", width: 100%),
  ),
  caption: [喷泉：$t = 0.9$ s / $2.4$ s / $6.0$ s（发射率 2200+2×1100 /s，ε = 0.30，$k_1 = 0.28$）],
)<fig-fountain>

喷泉的三帧体现了"稳态而非一次性"：$t=0.9$ s 时水柱刚成形（3850 颗），
$t=2.4$ s 进入动态平衡（8952 颗），之后粒子数稳定在 9000 左右不再增长——
发射率与死亡率达到了平衡。两侧副喷的抛物线拱和落地弹起的小水花都能看清，
颜色由白转蓝的梯度对应粒子年龄。

#figure(
  grid(
    columns: 3,
    gutter: 4pt,
    image("output/fig/fire_t0.70.png", width: 100%),
    image("output/fig/fire_t2.20.png", width: 100%),
    image("output/fig/fire_t5.00.png", width: 100%),
  ),
  caption: [火焰：$t = 0.7$ s / $2.2$ s / $5.0$ s（发射率 1100 /s，浮力 9.5 m/s²，$k_1 = 1.5$）],
)<fig-fire>

火焰从 $t=0.7$ s 的一团火心长成 $t=5$ s 的稳定火舌，形态是浮力随生命衰减的
直接结果：新粒子浮力大、冲得高，烧尽的粒子浮力消失并被阻力压住，于是自然形成
上窄下散的分层结构。颜色序列（亮黄→橙→暗红→灰）与尺寸收缩（至 20%）都由
同一个生命分数驱动。

#figure(
  grid(
    columns: 3,
    gutter: 4pt,
    image("output/fig/snow_t2.00.png", width: 100%),
    image("output/fig/snow_t6.00.png", width: 100%),
    image("output/fig/snow_t12.00.png", width: 100%),
  ),
  caption: [雪：$t = 2.0$ s / $6.0$ s / $12.0$ s（发射率 820 /s，重力 1.6 m/s²，终端速度 ≈ 1.5 m/s）],
)<fig-snow>

雪场景的粒子数是*缓慢爬升*的（1596 → 4747 → 8643）：雪花寿命 14 s，
而落地即被剔除，所以数量要等第一批雪从上界落到底（约 20 单位 / 1.5 m/s ≈ 13 s）
才趋于饱和。这提示"画面密度"不仅取决于发射率，还取决于粒子寿命与下落距离的比值。

#figure(
  grid(
    columns: 3,
    gutter: 4pt,
    image("output/fig/fireworks_t0.45.png", width: 100%),
    image("output/fig/fireworks_t1.15.png", width: 100%),
    image("output/fig/fireworks_t2.90.png", width: 100%),
  ),
  caption: [烟花：$t = 0.45$ s / $1.15$ s / $2.9$ s（每 0.7 s 一发，爆炸 1100 颗，初速 12.5 m/s）],
)<fig-fireworks>

烟花的三帧分别是"火箭升空带光尾"、"第一发到达顶点"和"多发放开"。
$t = 2.9$ s 时画面里有四发不同配色的烟花，球面分布均匀、没有两极密集，
验证了正态向量归一化的取方向方式。

#figure(
  grid(
    columns: 2,
    gutter: 4pt,
    image("output/fig/text_t0.85.png", width: 100%),
    image("output/fig/text_t3.00.png", width: 100%),
  ),
  caption: [文字：$t = 0.85$ s（汇聚中）/ $3.0$ s（收敛，均方误差 0.01 单位）——8000 粒子，$k = 14$，$c = 3.6$],
)<fig-text>

文字场景的收敛过程最能说明软约束的作用：$t = 0.85$ s 时"粒子系统"四字已可辨认
但笔画仍模糊（粒子还在被拉近），$t = 3$ s 时笔画锐利。颜色/亮度由"离目标多近"
驱动，所以汇聚过程同时是变亮过程。完整参数面板见 @fig-panel。

#figure(
  image("output/fig/panel.png", width: 80%),
  caption: [参数面板（文字场景）：场景切换、积分器与步长、力场参数、文字输入、实时统计],
)<fig-panel>

== 积分器对比

@tab-integrator 已经给出精度与能量两项指标。为了看场景级别的差异，我把文字场景
在四种积分器下各跑 3 s（$h = 8.3$ ms），统计粒子数与最大速度：

#figure(
  table(
    columns: 5,
    align: (left, center, center, center, center),
    table.header([场景], [积分器], [粒子数], [$max norm(v)$ (m/s)], [$max norm(x)$ (m)]),
    [喷泉], [euler], [9067], [10.06], [4.59],
    [喷泉], [verlet], [9002], [10.13], [4.54],
    [喷泉], [leapfrog], [9026], [10.18], [4.53],
    [喷泉], [velocity_verlet], [9097], [10.05], [4.56],
    [文字], [euler], [8000], [0.08], [4.52],
    [文字], [verlet], [8000], [0.06], [4.51],
    [文字], [leapfrog], [8000], [0.06], [4.51],
    [文字], [velocity_verlet], [8000], [0.06], [4.51],
  ),
  caption: [场景级换积分器对比（各跑 3 s，$h = 8.3$ ms；粒子数不变、无发散）],
)<tab-scene-integ>

四种方法在本项目的场景里都能稳定运行，粒子数与速度量级几乎一致，差异主要体现
在能量行为（@tab-integrator）而非画面。真正会暴露问题的是*切换*积分器的操作。

本项目的选择是 Velocity Verlet 作为默认：精度最高、能量漂移最小
（3.8 个周期后仅 $6 times 10^(-5)$），且位置与速度同步，无需额外的速度估算步骤。

为什么不选计算量最小的显式 Euler？实测它在 12 s 内把简谐振子的能量放大了
#h(0pt) 49%，在长时间运行（如雪场景的 14 s 寿命）会明显失真；而且它的位置用旧速度
推进，粒子对力的响应滞后一步，视觉上"发飘"。

== 文字场景的阻尼扫描 <sec-text-tuning>

软约束的阻尼 $c$ 是文字场景手感的核心参数。固定刚度 $k = 14$，扫 $c$ 从 0.6 到 15：

#figure(
  table(
    columns: 4,
    align: (center, center, center, center),
    table.header([阻尼 $c$], [收敛时间（mean\|Δ\| < 0.05）], [$t = 1$ s 时 mean\|Δ\|], [$t = 8$ s 时 mean\|Δ\|]),
    [0.6], [未收敛（8 s 仍振荡）], [1.774], [0.182],
    [1.8], [4.0 s], [1.052], [0.0019],
    [3.6], [2.3 s], [0.428], [0.0000],
    [7.5], [1.7 s], [0.314], [0.0000],
    [15.0], [4.1 s], [0.994], [0.0011],
  ),
  caption: [阻尼扫描（文字场景，$k = 14$，8000 粒子，字高 3 世界单位）],
)<tab-damping>

规律很清楚：$c$ 太小时粒子在目标点附近来回摆动甚至 8 s 仍未停
（欠阻尼，$c = 0.6$ 一列）；$c$ 太大时虽然不振荡但整体变"拖沓"，
收敛反而变慢（过阻尼，$c = 15$ 需要 4.1 s）。最优区间在 $c approx 3.6 ~ 7.5$，
对应临界阻尼 $2 sqrt(k) approx 7.5$ 附近，与理论一致。项目默认取 $c = 3.6$，
在"快速收敛"与"不振荡"之间偏保守。

== 性能分析

@tab-perf 把每帧的 CPU 成本分成三部分：系统推进（发射 + 固定步长物理 + 剔除）、
着色（按生命分数改颜色尺寸）、打包（交错成 `(n,8)` float32 上传前）。

#figure(
  table(
    columns: 6,
    align: (left, center, center, center, center, center),
    table.header([场景], [粒子数], [系统 (ms)], [shade (ms)], [打包 (ms)], [合计 (ms)]),
    [喷泉], [8978], [4.32], [1.24], [0.50], [6.07],
    [雪], [6903], [3.74], [0.47], [0.28], [4.49],
    [火焰], [1814], [1.29], [0.16], [0.09], [1.54],
    [烟花], [3704], [1.33], [0.02], [0.16], [1.51],
    [文字], [8000], [0.56], [0.58], [0.32], [1.45],
  ),
  caption: [稳态每帧 CPU 耗时（5 次取中位数，60 fps 预算为 16.7 ms）],
)<tab-perf>

所有场景都远低于 16.7 ms 的 60 fps 预算，最重的喷泉约 6 ms，仍有 2.7 倍余量。
两点观察：

- *文字场景的系统耗时最低（0.56 ms）*，因为它只有一个力场（软约束），
  而喷泉有重力 + 阻力 + 碰撞；但它的 shade 耗时最高（0.58 ms），因为每帧要算
  8000 个粒子到目标点的距离。
- *粒子的耗时不随数量线性增长*：@tab-scaling 显示 5 万粒子时每千粒子成本
  明显上升（435 µs vs 5 千粒子时的 242 µs），瓶颈是 NumPy 每步的临时数组分配
  与缓存失配，而非运算量本身。当前场景规模（1–3 万）仍在高效区间。

#figure(
  table(
    columns: 3,
    align: (center, center, center),
    table.header([粒子数], [每帧物理耗时], [等效吞吐（每千粒子）]),
    [1 000], [0.35 ms], [350 µs],
    [5 000], [1.21 ms], [242 µs],
    [10 000], [2.29 ms], [229 µs],
    [20 000], [6.98 ms], [349 µs],
    [50 000], [21.74 ms], [435 µs],
  ),
  caption: [粒子数扩展性（喷泉力场组合，$h = 8.3$ ms）],
)<tab-scaling>

真实窗口的帧率波动更大（50–600 FPS），主要开销来自录制时的 `fbo.read()` 读回
与 ffmpeg 编码，而不是粒子本身——这也是冒烟脚本改用*仿真时间*而非帧数做检查点
的原因。

== 测试

<sec-test>

项目共 *238 个 pytest 用例*，单机 20–50 s 跑完，按模块分文件组织（@tab-tests）。

测试策略的取向是：*能算真值就对比真值*（自由落体、抛体、终端速度都有解析解）；
*物理性质优先于具体数值*（能量守恒用"Euler 发散 / 辛积分有界"这种定性断言）；
*与库脱节的易错约定用静态断言钉死*（顶点 stride、索引宽度这类写错只会表现为
"画出来是斜线"的问题）。需要 GL 上下文的用例在没有显卡的环境自动 `skip`。

#figure(
  table(
    columns: 3,
    align: (left, left, left),
    table.header([测试文件], [用例], [覆盖内容]),
    [`test_pool.py`], [8], [spawn 区间/截断、compact 保序、掩码形状],
    [`test_integrators.py`], [22], [解析真值、能量守恒、首步初始化、脏 aux 兜底],
    [`test_forces.py`], [15], [各力逐项、终端速度、风场基缓存],
    [`test_emitters.py`], [9], [计数公式、锥形方向、球面均匀性、容量截断],
    [`test_collisions.py`], [9], [检测条件、反弹/摩擦、位置回拉、aux 作废],
    [`test_system.py`], [30], [五步循环、帧率解耦、12 种积分器互切不塌陷],
    [`test_camera.py`], [9], [lookAt 性质、透视映射、pitch/zoom 夹紧],
    [`test_textures.py`], [6], [径向对称、单调性、环峰位置],
    [`test_render.py`], [7], [离屏 GL 像素断言：越叠越亮、alpha 不饱和],
    [`test_scene_base.py`], [26], [五场景参数化：推进/重置/无 NaN/颜色合法],
    [`test_fountain.py` 等三个场景文件], [25], [动态平衡、终端速度、弹道真值、球面分布],
    [`test_sampling.py` / `test_text_scene.py`], [30], [采样确定性、软约束收敛、morph、鼠标排斥],
    [`test_recorder.py` / `test_panel.py` / `test_imgui_backend.py`], [40], [录制尺寸、UI 缩放、CJK 输入、顶点 stride],
  ),
  caption: [测试文件与覆盖内容（共 238 个用例）],
)<tab-tests>

除单元测试外，还有四个*真实窗口冒烟脚本*（`tools/`）覆盖单元测试看不到的部分：
面板缩放、下拉框弹出层、中文字符输入、全屏尺寸往返、MP4 可解码性。判据都是
可量化的数值断言而非人工看图，例如"全屏后输入框高度必须涨到 1.5 倍以上"、
"弹出层出现时 DrawList 数 ≥ 2 且索引不越界"。

== 可改进之处

+ *性能*：5 万粒子以上时 NumPy 临时数组分配成为瓶颈，可改用 `out=` 原地运算
  与 float32 存储，或把物理移到 GPU（compute shader / CUDA）。
+ *碰撞*：目前只有无限平面。加入球体/网格碰撞后可以做"瀑布冲击岩石"这类效果。
+ *粒子间作用*：n 元力目前退化为锚点弹簧。若引入空间哈希做近邻查询，
  可以实现真正的粒子间排斥（SPH 式的流体效果）。
+ *文字采样*：目前是二维字形投影到平面。若把 z 方向也赋予渐变（如按笔画粗细
  或灰度值偏移 z），可以得到有厚度的立体文字。
