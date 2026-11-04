"""系统级测试：五步循环调度、固定步长解耦、端到端物理行为。"""
import numpy as np
import pytest

from core.collisions import KillBox, PlaneCollider
from core.emitters import PointEmitter, VolumeEmitter
from core.forces import Drag, Gravity, Wind
from core.integrators import INTEGRATORS
from core.system import ParticleSystem


def test_fountain_particles_fall_and_die():
    """端到端：喷泉发射 → 重力下落 → 出界/寿命尽死亡，系统达到动态平衡。"""
    sys = ParticleSystem(capacity=5000, integrator="velocity_verlet")
    sys.emitters.append(PointEmitter(
        origin=(0, 0, 0), direction=(0, 1, 0),
        speed_mean=8.0, speed_var=1.0, angle_var=0.3,
        rate_mean=500, rate_var=0, life_mean=3.0, life_var=0.2))
    sys.forces.extend([Gravity(), Drag(k1=0.1)])
    sys.kill_boxes.append(KillBox(lo=(-50, -20, -50), hi=(50, 50, 50)))

    dt = 1 / 60
    for _ in range(600):  # 10 秒
        stats = sys.update(dt)
    # 动态平衡：发射率×寿命 ≈ 500×3 = 1500，允许宽范围
    assert 300 < sys.pool.count < 5000
    assert stats["alive"] == sys.pool.count
    assert stats["died"] > 0  # 确实有粒子走完生命周期


@pytest.mark.parametrize("integrator", list(INTEGRATORS))
def test_system_runs_all_integrators(integrator):
    """四种积分器都能在系统级跑通且不产生 NaN。"""
    sys = ParticleSystem(capacity=2000, integrator=integrator, fixed_step=1/120)
    sys.emitters.append(VolumeEmitter(
        center=(0, 5, 0), half_extents=(5, 1, 5),
        rate_mean=200, rate_var=0, life_mean=2.0))
    sys.forces.append(Gravity())
    sys.colliders.append(PlaneCollider(point=(0, 0, 0), normal=(0, 1, 0)))
    sys.kill_boxes.append(KillBox(lo=(-100, -10, -100), hi=(100, 100, 100)))
    for _ in range(120):
        sys.update(1 / 60)
    n = sys.pool.count
    assert n > 0
    assert np.isfinite(sys.pool.pos[:n]).all()
    assert np.isfinite(sys.pool.vel[:n]).all()


def test_fixed_step_decoupling():
    """渲染帧率变化（30/60/120fps）不影响物理结果（固定步长累积器）。"""
    results = []
    for fps in (30, 60, 120):
        sys = ParticleSystem(capacity=1000, integrator="velocity_verlet",
                             fixed_step=1 / 120, max_substeps=500)
        sys.emitters.append(PointEmitter(rate_mean=0, rate_var=0))  # 不发射
        # 手动放一个粒子
        s, e = sys.pool.spawn(1)
        sys.pool.pos[0] = (0, 10, 0)
        sys.pool.vel[0] = (1.0, 0, 0)
        sys.pool.life[0] = 100.0
        sys.pool.max_life[0] = 100.0
        sys.forces.append(Gravity())
        for _ in range(round(2.0 * fps)):  # 都模拟 2 秒
            sys.update(1 / fps)
        results.append(sys.pool.pos[0].copy())
    # 自由落体 2s：y ≈ 10 − ½·9.8·4 = −9.6（未设 kill_box，粒子不删除）
    for r in results:
        assert r[0] == pytest.approx(2.0, abs=1e-6)  # 水平匀速 1m/s×2s
        assert r[1] == pytest.approx(10 - 0.5 * 9.8 * 4, abs=1e-3)


def test_wind_time_advances():
    sys = ParticleSystem(capacity=100, fixed_step=1 / 120, max_substeps=200)
    wind = Wind(base=(1, 0, 0), amplitude=1.0)
    sys.forces.append(wind)
    sys.pool.spawn(1)
    sys.pool.life[0] = 10.0
    sys.pool.max_life[0] = 10.0
    # 固定步长 1/120：update(0.5) 执行 60 个物理步 = 0.5s
    sys.update(0.5)
    assert sys.time == pytest.approx(60 / 120, abs=1e-9)
    # 风场在步初求值：最后一次求值时刻 = 第 60 步开始 = 59/120
    assert wind.time == pytest.approx(59 / 120, abs=1e-9)


def test_area_factor_passes_to_emitter():
    sys = ParticleSystem(capacity=500)
    em = PointEmitter(rate_mean=100, rate_var=0, area_adaptive=True)
    sys.emitters.append(em)
    stats = sys.update(1.0, area_factor=2.0)
    assert stats["emitted"] == 200
    stats2 = sys.update(1.0)  # 默认 A=1
    assert stats2["emitted"] == 100


# ---------------------------------------------------------------- 积分器切换

def _spring_system(integrator):
    """一个简谐振子 + 阻力的小系统，用于观察切换积分器后的稳定性。"""
    sys = ParticleSystem(capacity=2000, integrator=integrator, fixed_step=1 / 120)
    sys.emitters.append(PointEmitter(rate_mean=0, rate_var=0))   # 不发射
    start, end = sys.pool.spawn(200)
    rng = np.random.default_rng(0)
    sys.pool.pos[start:end] = rng.uniform(-1.0, 1.0, (end - start, 3))
    sys.pool.vel[start:end] = rng.uniform(-1.0, 1.0, (end - start, 3)) * 0.5
    sys.pool.life[start:end] = 1e6
    sys.pool.max_life[start:end] = 1e6
    sys.forces.append(Gravity())
    sys.kill_boxes.append(KillBox(lo=(-1e4, -1e4, -1e4), hi=(1e4, 1e4, 1e4)))
    return sys


def test_set_integrator_rejects_unknown():
    sys = ParticleSystem(capacity=10)
    with pytest.raises(ValueError, match="unknown integrator"):
        sys.set_integrator("runge_kutta")
    # 报错后状态不变
    assert sys.integrator_name == "velocity_verlet"


def test_set_integrator_is_noop_for_same_name():
    """同名的重复设置不应作废 aux（否则会无谓地重置历史）。"""
    sys = _spring_system("velocity_verlet")
    sys.update(1 / 60)
    before = sys.pool.aux[:sys.pool.count].copy()
    sys.set_integrator("velocity_verlet")
    assert np.array_equal(sys.pool.aux[:sys.pool.count], before)


@pytest.mark.parametrize("source", list(INTEGRATORS))
@pytest.mark.parametrize("target", list(INTEGRATORS))
def test_integrator_switch_keeps_system_stable(source, target):
    """任意两种积分器互切后，系统不能塌陷 / 出 NaN / 损失粒子。

    回归：verlet 把 ``aux`` 当作「上一步位置 xₙ₋₁」，而 euler 恒把它写成 0、
    leapfrog 写的是半步速度。切到 verlet 后 ``2x − aux`` 使位置瞬间翻倍，
    等于注入 ``x/h`` 的伪速度，粒子飞出 KillBox 被 compact() 永久删除。
    """
    sys = _spring_system(source)
    for _ in range(120):               # 先跑 2 秒进入稳态
        sys.update(1 / 60)
    count_before = sys.pool.count
    assert count_before == 200

    sys.set_integrator(target)
    for _ in range(120):               # 切换后再跑 2 秒
        sys.update(1 / 60)

    n = sys.pool.count
    assert n == count_before, f"{source}→{target} 丢了 {count_before - n} 个粒子"
    assert np.isfinite(sys.pool.pos[:n]).all(), f"{source}→{target} 位置出现 NaN"
    assert np.isfinite(sys.pool.vel[:n]).all(), f"{source}→{target} 速度出现 NaN"


@pytest.mark.parametrize("source", ["euler", "leapfrog", "velocity_verlet"])
def test_switch_to_verlet_does_not_inject_fake_velocity(source):
    """切到 verlet 时速度不能突变——突变就说明 aux 被当成了位置历史。

    判据：切换后第一步的速度与切换前同量级（允许 soft 的减速，不允许放大）。
    """
    sys = _spring_system(source)
    for _ in range(120):
        sys.update(1 / 60)
    v_before = np.abs(sys.pool.vel[:sys.pool.count]).max()

    sys.set_integrator("verlet")
    sys.update(1 / 60)
    v_after = np.abs(sys.pool.vel[:sys.pool.count]).max()

    assert v_after < max(v_before * 10.0, 1.0), \
        f"{source}→verlet 速度从 {v_before:.3f} 突变到 {v_after:.3f}"


def test_set_integrator_invalidates_aux():
    """切换后 aux 必须是 NaN 哨兵，由新积分器做首步初始化。"""
    sys = _spring_system("euler")
    sys.update(1 / 60)
    assert np.isfinite(sys.pool.aux[:sys.pool.count]).all()   # euler 写 0
    sys.set_integrator("verlet")
    assert np.isnan(sys.pool.aux[:sys.pool.count]).all()
