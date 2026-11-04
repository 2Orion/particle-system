"""数值积分器：课件 P44–58 的四种方法，接口统一可切换。

约定：
- 入口状态为 ``[t, t+h]`` 的步进；pool 的 ``aux`` 字段缓存积分器附加状态；
- ``aux`` 为 NaN 的粒子（新出生或碰撞重置）由积分器做首步初始化；
- 所有方法整体向量化操作活粒子区间 ``[0, count)``。
"""
from __future__ import annotations

import numpy as np

from .pool import ParticlePool


def _init_aux(pool: ParticlePool) -> np.ndarray:
    """返回活粒子中 aux 为 NaN 的掩码，并对这些粒子做默认初始化。"""
    fresh = np.isnan(pool.aux[:pool.count, 0])
    if fresh.any():
        pool.aux[:pool.count][fresh] = 0.0
    return fresh


def euler(pool: ParticlePool, h: float, accumulate: callable) -> None:
    """显式欧拉法（一阶精度）：x_{n+1} = x_n + h·v_n；v_{n+1} = v_n + h·a(x_n)。

    纯显式：位置用旧速度推进（先暂存）—— 保守系统能量单调发散（课件 P50）。
    """
    _init_aux(pool)
    n = pool.count
    pos, vel, acc = pool.pos[:n], pool.vel[:n], pool.acc[:n]
    accumulate(pool, h)                              # a(x_n)
    vel_old = vel.copy()
    np.add(vel, acc * h, out=vel)                    # v_{n+1} ← v_n + h·a
    np.add(pos, vel_old * h, out=pos)                # x_{n+1} ← x_n + h·v_n（旧速度）


def verlet(pool: ParticlePool, h: float, accumulate: callable) -> None:
    """标准 Verlet（无显式速度）。

    x_{n+1} = 2·x_n − x_{n−1} + a_n·h²

    aux 缓存 x_{n−1}。新粒子首步用 x_{−1} = x_0 − v_0·h 初始化。
    pool.vel 不参与更新，仅由 compute_vel 估算（滞后一步）。

    注意：aux 里的旧值是否可信**不在这里判断** —— verlet 本身不维护 vel，
    没有可靠的量纲基准。这项校验放在 `ParticleSystem.step_physics`（那里
    vel 每步都会被 compute_vel 刷新），见 `repair_verlet_history`。
    """
    n = pool.count
    fresh = _init_aux(pool)
    pos, prev, acc, vel = pool.pos[:n], pool.aux[:n], pool.acc[:n], pool.vel[:n]
    accumulate(pool, h)                          # a(x_n)
    if fresh.any():
        # 首步历史要带上 ½a·h²：设 x_{n−1} = x_n − v_n·h + ½a·h²，代入
        # x_{n+1} = 2x_n − x_{n−1} + a·h² 得 x_n + v_n·h + ½a·h²，
        # 与 Velocity Verlet 的首步一致（二阶）。若按 x_{n−1} = x_n − v·h
        # 初始化，首步会多出 ½a·h² 的**常量偏移**，之后每步原样保留，
        # 相当于把误差从 O(h²) 退化成 O(h)（实测 2 s 自由落体与显式 Euler
        # 一模一样的 0.0817 m）。必须放到 accumulate 之后才能拿到 a。
        prev[fresh] = pos[fresh] - vel[fresh] * h + 0.5 * acc[fresh] * (h * h)
    new_pos = 2.0 * pos - prev + acc * (h * h)
    np.copyto(prev, pos)                         # aux ← x_n（成为下一步的 x_{n-1}）
    np.copyto(pos, new_pos)


def leapfrog(pool: ParticlePool, h: float, accumulate: callable) -> None:
    """Leap-Frog（蛙跳）Verlet：速度与位置交错半步。

    v_{t+h/2} = v_{t−h/2} + a_t·h
    x_{t+h}   = x_t + v_{t+h/2}·h

    aux 缓存 v_{t−h/2}（新粒子首步以 v_t 初始化）。
    同步速度估计：v(t) = v_{t+h/2} − ½·a_t·h。
    """
    n = pool.count
    fresh = _init_aux(pool)
    vh, pos, acc, vel = pool.aux[:n], pool.pos[:n], pool.acc[:n], pool.vel[:n]
    accumulate(pool, h)                          # a(x_t)
    if fresh.any():
        # 新粒子：v_{−h/2} = v_0 − ½a·h（由 v_half 与同步速度的关系反推）。
        # 取 v_{−h/2} = v_0 会让首步速度多出 ½a·h，位置多 ½a·h² —— 与 Verlet
        # 同样的 O(h) 退化，实测 2 s 自由落体误差 0.0817 m。
        vh[fresh] = vel[fresh] - 0.5 * acc[fresh] * h
    vh += acc * h                                # v_{t-h/2} → v_{t+h/2}
    np.add(pos, vh * h, out=pos)                 # x_t → x_t+h
    np.subtract(vh, 0.5 * acc * h, out=vel)      # v(t) ≈ v_{t+h/2} − a·h/2


def velocity_verlet(pool: ParticlePool, h: float, accumulate: callable) -> None:
    """Velocity Verlet：位置与速度同步，二阶精度（项目默认）。

    x_{n+1} = x_n + v_n·h + ½a_n·h²
    v_{n+1} = v_n + ½(a_n + a_{n+1})·h

    新粒子首步需先求 a(t₀)（acc 此前为池初值 0，直接用会漏掉首步加速度）。
    """
    fresh = _init_aux(pool)
    n = pool.count
    pos, vel, acc = pool.pos[:n], pool.vel[:n], pool.acc[:n]
    if fresh.any():
        accumulate(pool, h)                      # 幂等：为所有粒子求 a(t_n)
    old_acc = acc.copy()
    pos += vel * h + 0.5 * old_acc * (h * h)
    accumulate(pool, h)                          # a(x_{n+1})
    vel += 0.5 * (old_acc + acc) * h


#: 积分器注册表：名称 → 步进函数
INTEGRATORS: dict[str, callable] = {
    "euler": euler,
    "verlet": verlet,
    "leapfrog": leapfrog,
    "velocity_verlet": velocity_verlet,
}


def compute_vel(pool: ParticlePool, h: float) -> None:
    """为标准 Verlet 估算速度 v(t) ≈ (x(t) − x(t−h)) / h（其他积分器无需调用）。"""
    n = pool.count
    np.subtract(pool.pos[:n], pool.aux[:n], out=pool.vel[:n])
    pool.vel[:n] /= h


#: aux 被判为「脏数据」的容差倍数：合法的 |x_n − x_{n−1}| 只可能是 |v|·h，
#: 差出这个倍数就说明 aux 里存的不是本积分器的位置历史
_VERLET_DRIFT_TOLERANCE = 100.0


def repair_verlet_history(pool: ParticlePool, h: float) -> int:
    """校验 `aux` 是否是 Verlet 的合法位置历史，不是就按 v 重建。返回修复数。

    这是 `ParticleSystem.set_integrator` 之外的**防御性兜底**：`aux` 被写成
    别人的状态（euler 恒写 0、leapfrog 写半步速度）或切走再切回时早已过期，
    `2x_n − aux` 都会让位置瞬间翻倍，等价于注入 `x/h` 的伪速度，粒子随即飞出
    KillBox 被永久删除。

    必须在 `compute_vel` **之前**调用：判据依赖上一步的 vel（Verlet 的 vel 由
    `compute_vel` 从 `pos − aux` 估算并刷新，所以只要每步都刷新，它就是可靠的
    速度估计；如果在这里之前先算了 vel，就变成用待检验的数据检验自己）。
    """
    n = pool.count
    if n == 0:
        return 0
    pos, prev, vel = pool.pos[:n], pool.aux[:n], pool.vel[:n]
    drift = np.linalg.norm(pos - prev, axis=1)
    speed = np.linalg.norm(vel, axis=1)
    # 合理量级 |v|·h；下限兜住 v≈0 的静止粒子（此时任何非零 drift 都是脏的）
    plausible = np.maximum(speed, 1e-3) * h * _VERLET_DRIFT_TOLERANCE + 1e-6
    stale = drift > plausible
    if stale.any():
        # 布尔索引取到的是副本，不能写 out=，必须显式赋值回去
        prev[stale] = pos[stale] - vel[stale] * h
    return int(stale.sum())
