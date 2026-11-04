"""报告数据：报告里"结果与分析"一节的量化实验（不入库，配合 report.typ）。

四组实验，全部离线可复现：
  1. 积分器精度：自由落体对解析解 + 简谐振子的能量漂移（辛 vs 显式）；
  2. 固定步长精度：h 从 1/30 到 1/480，抛体落点误差；
  3. 文字软约束收敛：|x − x_target| 随时间下降 + 换字 morph 的重排距离；
  4. 每帧耗时分项：发射 / 物理 / 着色 / 打包上传（五场景稳态）。

运行：python -X utf8 tools/report_metrics.py
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import numpy as np

from core.emitters import SphereBurstEmitter
from core.forces import Gravity, TargetConstraint
from core.pool import ParticlePool
from core.system import ParticleSystem
from scenes import SCENES
from utils.sampling import text_targets

G = 9.8


# ---------------------------------------------------------------- 1. 积分器

def free_fall_error(integrator: str, h: float, T: float = 2.0) -> float:
    """自由落体：解析解 x(T) = −½gT²。返回 2 秒后的位置误差（米）。"""
    system = ParticleSystem(capacity=4, integrator=integrator, fixed_step=h)
    system.forces.append(Gravity(g=(0.0, -G, 0.0)))
    e = SphereBurstEmitter(center=(0.0, 0.0, 0.0), speed_mean=0.0, speed_var=0.0,
                           life_mean=1e6, life_var=0.0)
    e.burst(system.pool, 1)
    system.pool.vel[0] = (0.0, 0.0, 0.0)
    elapsed = 0.0
    while elapsed < T - 1e-12:
        system.step_physics(h)
        elapsed += h
    return abs(system.pool.pos[0, 1] - (-0.5 * G * T * T))


def oscillator_energy_drift(integrator: str, h: float,
                            T: float = 12.0) -> tuple[float, float]:
    """简谐振动 ẍ = −ω²x（ω=2）。返回 (末/初总能比, 过程最大能量比)。"""
    omega2 = 4.0
    system = ParticleSystem(capacity=4, integrator=integrator, fixed_step=h)
    e = SphereBurstEmitter(center=(0.0, 0.0, 0.0), speed_mean=0.0, speed_var=0.0,
                           life_mean=1e6, life_var=0.0)
    e.burst(system.pool, 1)
    pool = system.pool
    pool.pos[0] = (1.0, 0.0, 0.0)
    pool.vel[0] = (0.0, 0.0, 0.0)
    pool.aux[0] = np.nan

    def spring(p: ParticlePool, h_: float) -> None:
        p.acc[:p.count] = 0.0
        p.acc[:p.count, 0] = -omega2 * p.pos[:p.count, 0]

    def energy() -> float:
        x = pool.pos[0, 0]
        v = pool.vel[0, 0]
        return 0.5 * v * v + 0.5 * omega2 * x * x

    e0 = energy()
    worst = 1.0
    steps = int(round(T / h))
    for _ in range(steps):
        system.integrator(pool, h, spring)
        if integrator == "verlet":
            from core.integrators import compute_vel
            compute_vel(pool, h)
        worst = max(worst, energy() / e0)
    return energy() / e0, worst


# ---------------------------------------------------------------- 2. 步长

def oscillator_error(h: float, T: float = 1.0) -> float:
    """简谐振动 ẍ = −ω²x（ω=2, x(0)=1, v(0)=0）：x(T) = cos(ωT) 有解析解。

    不用抛体做步长收敛：常加速度下 Velocity Verlet 是**精确**的
    （它对二次多项式无截断误差），误差会一直停在 1e-14 的舍入噪声上，
    看不出收敛阶。简谐振动才有真正的截断误差可以测。
    """
    omega2 = 4.0
    system = ParticleSystem(capacity=4, integrator="velocity_verlet", fixed_step=h)
    e = SphereBurstEmitter(center=(0.0, 0.0, 0.0), speed_mean=0.0, speed_var=0.0,
                           life_mean=1e6, life_var=0.0)
    e.burst(system.pool, 1)
    pool = system.pool
    pool.pos[0] = (1.0, 0.0, 0.0)
    pool.vel[0] = (0.0, 0.0, 0.0)
    pool.aux[0] = np.nan

    def spring(p: ParticlePool, _h: float) -> None:
        p.acc[:p.count] = 0.0
        p.acc[:p.count, 0] = -omega2 * p.pos[:p.count, 0]

    steps = int(round(T / h))
    for _ in range(steps):
        system.integrator(pool, h, spring)
    return abs(float(pool.pos[0, 0]) - np.cos(np.sqrt(omega2) * steps * h))


# ---------------------------------------------------------------- 3. 文字

def text_convergence(interval: float = 0.25) -> list[tuple[float, float, float]]:
    """文字场景收敛过程。返回 [(t, mean|Δ|, max|Δ|)]。"""
    scene = SCENES["text"]()
    targets = scene._constraint.targets
    out = []
    t = 0.0
    next_sample = 0.0
    while t < 6.0 - 1e-9:
        scene.update(1 / 60)
        t += 1 / 60
        if t >= next_sample:
            pool = scene.system.pool
            n = pool.count
            d = np.linalg.norm(pool.pos[:n] - targets[:n], axis=1)
            out.append((t, float(d.mean()), float(d.max())))
            next_sample += interval
    return out


def morph_distance() -> tuple[float, float]:
    """换字 morph：新旧目标点之间的平均/最大位移（世界单位）。"""
    n = 8000
    a = text_targets("粒子系统", n, world_height=3.0, world_width=9.0)
    b = text_targets("Computer Animation", n, world_height=3.0, world_width=9.0)
    d = np.linalg.norm(a - b, axis=1) if len(a) == len(b) else np.zeros(1)
    return float(d.mean()), float(d.max())


# ---------------------------------------------------------------- 4. 性能

def scene_frame_cost(key: str, seconds: float = 4.0) -> dict:
    """稳态每帧耗时分解（物理 update + 着色 + 打包成 GPU 顶点）。"""
    scene = SCENES[key]()
    dt = 1 / 60
    for _ in range(int(2.0 / dt)):        # 先跑到稳态
        scene.update(dt)

    def pack() -> np.ndarray:
        pool = scene.system.pool
        n = pool.count
        data = np.empty((n, 8), dtype=np.float32)
        data[:, 0:3] = pool.pos[:n]
        data[:, 3:7] = pool.color[:n]
        data[:, 3:6] *= pool.color[:n, 3:4]
        data[:, 7] = pool.size[:n]
        return data.tobytes()

    t_full = t_shade_alone = t_pack = 0.0
    frames = int(seconds / dt)
    for _ in range(frames):
        t0 = time.perf_counter()
        scene.update(dt)                  # 场景完整一帧（含烟花火箭调度 + shade）
        t1 = time.perf_counter()
        scene.shade()                     # 单独再测一次着色成本
        t2 = time.perf_counter()
        pack()                            # 交错打包（上传前的 CPU 侧成本）
        t3 = time.perf_counter()
        t_full += t1 - t0
        t_shade_alone += t2 - t1
        t_pack += t3 - t2
    k = frames * 1e-3                     # 秒 → 毫秒，且取每帧均值
    shade_ms = t_shade_alone / k
    full_ms = t_full / k
    return {
        "count": scene.system.pool.count,
        "system": full_ms - shade_ms,     # 发射 + 物理 + 剔除（烟花含火箭调度）
        "shade": shade_ms,
        "pack": t_pack / k,
        "total": full_ms + t_pack / k,
    }


def damping_sweep(T: float = 8.0) -> list[tuple[float, float, float, float]]:
    """固定 k=14，扫阻尼 c。返回 [(c, 收敛时间, 1s 时 mean|Δ|, 8s 时 mean|Δ|)]。

    收敛判据：mean|Δ| 首次降到 0.05 世界单位以下（字高 3 单位，即 1.7%）。
    c 偏小时无阻尼振荡、拖很久；c 偏大时虽然不振荡但收敛慢（过阻尼）。
    """
    frame = 1 / 60
    sample_every = 6                      # 每 6 帧 = 0.1 s 采一次
    out = []
    for damping in (0.6, 1.8, 3.6, 7.5, 15.0):
        scene = SCENES["text"]()
        scene._constraint.damping = damping
        targets = scene._constraint.targets
        curve = []
        frames = int(T / frame)
        for i in range(frames):
            scene.update(frame)
            if i % sample_every == 0:
                n = scene.system.pool.count
                d = np.linalg.norm(scene.system.pool.pos[:n] - targets[:n], axis=1)
                curve.append(float(d.mean()))
        curve = np.asarray(curve)
        times = np.arange(len(curve)) * sample_every * frame
        below = np.nonzero(curve < 0.05)[0]
        t_conv = float(times[below[0]]) if len(below) else float("nan")
        at_1s = float(curve[min(int(1.0 / (sample_every * frame)), len(curve) - 1)])
        out.append((damping, t_conv, at_1s, float(curve[-1])))
    return out


def count_scaling() -> list[tuple[int, float, float]]:
    """粒子数 vs 每帧物理耗时（喷泉力场组合，纯 step_physics）。"""
    from core.collisions import KillBox, PlaneCollider
    from core.emitters import PointEmitter
    from core.forces import Drag

    out = []
    for n in (1_000, 5_000, 10_000, 20_000, 50_000):
        system = ParticleSystem(capacity=n, integrator="velocity_verlet",
                                fixed_step=1 / 120)
        system.emitters.append(PointEmitter(
            origin=(0, 0, 0), direction=(0, 1, 0), rate_mean=n * 4.0,
            rate_var=0.0, speed_mean=9.5, speed_var=0.8, life_mean=2.2,
            life_var=0.0))
        system.forces.extend([Gravity(g=(0, -9.8, 0)), Drag(k1=0.28)])
        system.colliders.append(PlaneCollider(point=(0, 0, 0), normal=(0, 1, 0),
                                              restitution=0.3, friction=0.1))
        system.kill_boxes.append(KillBox(lo=(-60, -5, -60), hi=(60, 40, 60)))
        for _ in range(int(1.0 / (1 / 60))):
            system.update(1 / 60)
        frames = 120
        t0 = time.perf_counter()
        for _ in range(frames):
            system.update(1 / 60)
        dt_ms = (time.perf_counter() - t0) / frames * 1e3
        out.append((system.pool.count, dt_ms, dt_ms / max(system.pool.count, 1) * 1e6))
    return out


# ---------------------------------------------------------------- 5. 场景级

def scene_under_integrator(key: str, integrator: str, h: float,
                           T: float = 3.0) -> dict:
    """同一个场景换积分器：跑 T 秒后的粒子数、最大速度、越界数。

    "越界"指飞出场景 KillBox 的粒子（已被剔除，故另记 max|pos| 作对照）。
    """
    scene = SCENES[key]()
    scene.system.set_integrator(integrator)
    scene.system.fixed_step = h
    dt = 1 / 60
    for _ in range(int(T / dt)):
        scene.update(dt)
    pool = scene.system.pool
    n = pool.count
    speed = float(np.linalg.norm(pool.vel[:n], axis=1).max()) if n else 0.0
    extent = float(np.abs(pool.pos[:n]).max()) if n else 0.0
    return {"count": n, "max_speed": speed, "max_extent": extent}


# ---------------------------------------------------------------- main

def main() -> None:
    print("== 1. 积分器 ==")
    h = 1 / 120
    print("| 方法 | 自由落体 2s 位置误差 (m) | 简谐振动 E(T)/E(0) | max E/E0 |")
    print("|---|---|---|---|")
    for name in ("euler", "verlet", "leapfrog", "velocity_verlet"):
        err = free_fall_error(name, h)
        et, worst = oscillator_energy_drift(name, h)
        print(f"| {name} | {err:.3e} | {et:.4f} | {worst:.4f} |")

    print("\n== 2. 固定步长（velocity_verlet，简谐振动 t=1s 位置误差）==")
    print("| h (ms) | 位置误差 | 误差比（步长减半后） |")
    print("|---|---|---|")
    prev = None
    for ms in (33.3, 16.7, 8.3, 4.2, 2.1):
        err = oscillator_error(ms / 1000)
        ratio = f"{prev / err:.2f}" if prev else "--"
        print(f"| {ms:.1f} | {err:.3e} | {ratio} |")
        prev = err

    print("\n== 3. 文字软约束收敛 ==")
    rows = text_convergence()
    print("| t (s) | mean |Δ| | max |Δ| |")
    print("|---|---|---|")
    for t, m, mx in rows:
        print(f"| {t:.2f} | {m:.4f} | {mx:.4f} |")
    dm, dx = morph_distance()
    print(f"\nmorph 目标点位移：mean={dm:.3f} max={dx:.3f}")

    print("\n== 6. 阻尼扫描（文字场景，k=14）==")
    print("| 阻尼 c | 收敛时间 (s) | t=1s 时 mean\\|Δ\\| | t=8s 时 mean\\|Δ\\| |")
    print("|---|---|---|---|")
    for c, tc, a1, a8 in damping_sweep():
        print(f"| {c} | {tc:.1f} | {a1:.4f} | {a8:.4f} |")

    print("\n== 7. 粒子数 vs 每帧物理耗时（喷泉力场组合）==")
    print("| 粒子数 | 每帧 (ms) | 每千粒子 (µs) |")
    print("|---|---|---|")
    for cnt, ms_, per in count_scaling():
        print(f"| {cnt} | {ms_:.2f} | {per:.1f} |")

    print("\n== 5. 场景换积分器（各跑 3 s，h=8.3 ms）==")
    print("| 场景 | 积分器 | 粒子数 | max\\|v\\| (m/s) | max\\|x\\| (m) |")
    print("|---|---|---|---|---|")
    for key in ("fountain", "text"):
        for name in ("euler", "verlet", "leapfrog", "velocity_verlet"):
            r = scene_under_integrator(key, name, 1 / 120)
            print(f"| {key} | {name} | {r['count']} | {r['max_speed']:.2f} "
                  f"| {r['max_extent']:.2f} |")

    print("\n== 4. 每帧耗时（稳态，ms）==")
    print("| 场景 | 粒子数 | 系统(发射+物理+剔除) | shade | 打包 | 合计 |")
    print("|---|---|---|---|---|---|")
    for key in ("fountain", "snow", "fire", "fireworks", "text"):
        r = scene_frame_cost(key)
        print(f"| {key} | {r['count']} | {r['system']:.2f} | {r['shade']:.2f} "
              f"| {r['pack']:.2f} | {r['total']:.2f} |")


if __name__ == "__main__":
    main()
