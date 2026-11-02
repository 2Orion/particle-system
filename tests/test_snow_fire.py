"""雪 / 火焰场景测试：各自的物理特征。"""
import numpy as np
import pytest

from core.emitters import VolumeEmitter
from core.forces import Buoyancy
from core.pool import ParticlePool
from scenes.fire import FireScene
from scenes.snow import SnowScene


# ---------------------------------------------------------------- 浮力力场

def _pool_with_life(lives, max_lives=1.0):
    """构造指定生命分数的粒子（默认 max_life=1 → life_fraction 数值上等于 life）。"""
    pool = ParticlePool(len(lives))
    s, e = pool.spawn(len(lives))
    pool.life[s:e] = lives
    pool.max_life[s:e] = max_lives
    return pool


def test_buoyancy_lifts_proportional_to_life_fraction():
    pool = _pool_with_life([1.0, 0.5, 0.0])
    Buoyancy(acceleration=10.0).apply(pool)
    acc = pool.acc[:3]
    assert acc[0, 1] == pytest.approx(10.0)     # 满生命 → 全浮力
    assert acc[1, 1] == pytest.approx(5.0)      # 半生命 → 半浮力
    assert acc[2, 1] == pytest.approx(0.0)      # 生命耗尽 → 无浮力
    assert np.allclose(acc[:, 0], 0.0)          # 只沿 +y


def test_buoyancy_zero_is_noop():
    pool = _pool_with_life([1.0])
    Buoyancy(acceleration=0.0).apply(pool)
    assert np.allclose(pool.acc[:1], 0.0)


def test_buoyancy_empty_pool_safe():
    pool = ParticlePool(4)
    Buoyancy(acceleration=5.0).apply(pool)      # 不应抛异常
    assert pool.count == 0


# ---------------------------------------------------------------- 雪

def test_snow_reaches_terminal_velocity():
    """弱重力 + 阻力 → 竖直速度饱和在个位数 m/s，不会一路加速。"""
    scene = SnowScene()
    for _ in range(300):                        # 5 秒足够达到终端速度
        scene.update(1 / 60)
    pool = scene.system.pool
    vy = pool.vel[:pool.count, 1]
    assert vy.mean() < 0                        # 整体在下落
    assert np.abs(vy).max() < 6.0               # 没有自由落体式加速
    # 自由落体 5 秒会到 −8 m/s 以上；阻力明显压住了它
    assert np.abs(vy).mean() < 3.5


def test_snow_removes_particles_below_ground():
    """KillBox 生效：直接往地面以下注入粒子，一帧后即被清除。"""
    scene = SnowScene()
    scene.system.emitters.clear()               # 关掉发射，只观察注入的这 50 个
    pool = scene.system.pool
    s, e = pool.spawn(50)
    pool.pos[s:e] = np.array([0.0, -3.0, 0.0])  # 全部在地面以下
    pool.life[s:e] = 5.0
    pool.max_life[s:e] = 5.0
    assert pool.count == 50
    scene.update(1 / 60)
    assert scene.count == 0                     # 全部出界剔除


def test_snow_fills_whole_volume():
    """雪花应铺满整个下落区域，而不是只聚在一处。"""
    scene = SnowScene()
    for _ in range(180):                        # 3 秒即可铺开
        scene.update(1 / 60)
    pos = scene.system.pool.pos[:scene.count]
    assert np.ptp(pos[:, 1]) > 6.0              # 竖直方向有分布
    assert np.ptp(pos[:, 0]) > 10.0             # 横向也铺开


def test_snow_uses_alpha_blend():
    assert SnowScene.blend == "alpha"
    assert SnowScene.texture == "soft_disc"


def test_snow_size_grows_as_it_falls():
    """着色回调：生命分数低（下落已久）→ 尺寸相对出生尺寸更大。"""
    scene = SnowScene()
    for _ in range(180):
        scene.update(1 / 60)
    pool = scene.system.pool
    n = pool.count
    frac = pool.life_fraction
    ratio = pool.size[:n] / pool.size0[:n]
    old_sel = frac < 0.3
    young_sel = frac > 0.9
    if old_sel.any() and young_sel.any():
        assert ratio[old_sel].mean() > ratio[young_sel].mean()


def test_volume_emitter_sets_size0():
    """所有发射器都应写 size0（尺寸缩放基准）。"""
    pool = ParticlePool(100)
    VolumeEmitter(center=(0, 0, 0), half_extents=(1, 1, 1)).emit(pool, 0.1)
    n = pool.count
    assert n > 0
    assert np.allclose(pool.size0[:n], pool.size[:n])


# ---------------------------------------------------------------- 火焰

def test_fire_particles_rise_against_gravity():
    """浮力 > 重力 → 火焰整体净上升。"""
    scene = FireScene()
    for _ in range(300):
        scene.update(1 / 60)
    pool = scene.system.pool
    assert pool.vel[:pool.count, 1].mean() > 0.5


def test_fire_reaches_steady_state():
    scene = FireScene()
    for _ in range(600):
        scene.update(1 / 60)
    assert 1_000 < scene.count < scene.capacity


def test_fire_tapers_with_life():
    """尺寸随生命收尖，颜色由亮黄转暗红。"""
    scene = FireScene()
    for _ in range(300):
        scene.update(1 / 60)
    pool = scene.system.pool
    n = pool.count
    frac = pool.life_fraction
    red = pool.color[:n, 0]
    green = pool.color[:n, 1]
    young = frac > 0.85
    old = frac < 0.25
    if young.any() and old.any():
        assert green[young].mean() > green[old].mean() + 0.1   # 黄 → 暗
        assert pool.size[:n][old].mean() < pool.size[:n][young].mean()
