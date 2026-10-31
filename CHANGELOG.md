# 更新日志

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
