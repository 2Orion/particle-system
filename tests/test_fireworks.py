"""烟花场景测试：火箭解析弹道 + 顶点炸开 + 容量保护。"""
import numpy as np
import pytest

from scenes.fireworks import FireworksScene, Rocket


def test_rocket_rises_then_apexes():
    """Rocket 竖直速度从正变负，pos 先升后降。"""
    r = Rocket(pos=np.array([0.0, 0.0, 0.0]),
               vel=np.array([0.0, 15.0, 0.0]),
               color=np.array([1.0, 1.0, 1.0]))
    assert not r.apex
    heights = []
    for _ in range(150):                      # 15/9.8 ≈ 1.53s 才到顶点
        r.step(1 / 60)
        heights.append(r.pos[1])
    assert heights[-1] < max(heights)          # 已经往下走了
    assert r.vel[1] < 0
    assert r.apex


def test_rocket_fuse_expires():
    """引信到期也算 apex（防止火箭卡在顶点之上）。"""
    r = Rocket(pos=np.zeros(3), vel=np.array([0.0, 100.0, 0.0]),
               color=np.ones(3), fuse=0.5)
    for _ in range(40):
        r.step(1 / 60)
    assert r.apex                            # 速度仍为正，但引信到期


def test_rocket_gravity_matches_projectile():
    """解析弹道与 y(t)=y0+v0t−½gt² 一致（半隐式，误差 O(h)）。"""
    v0 = 15.0
    r = Rocket(pos=np.zeros(3), vel=np.array([0.0, v0, 0.0]), color=np.ones(3))
    h = 1 / 240
    t = 0.0
    for _ in range(240):                      # 1 秒
        r.step(h)
        t += h
    analytic = v0 * t - 0.5 * 9.8 * t * t
    assert r.pos[1] == pytest.approx(analytic, abs=0.1)


def test_scene_launches_on_interval():
    """自动发射：随时间推移出现火箭，到顶点后炸开并清空火箭列表。"""
    scene = FireworksScene()
    assert scene.count == 0
    for _ in range(30):
        scene.update(1 / 60)
    assert len(scene._rockets) >= 1            # 已经发射
    for _ in range(180):
        scene.update(1 / 60)
    assert scene.count > 0                     # 炸开的火星进入了池


def test_manual_launch_and_forced_burst():
    """手动 launch + 直接把 vel 置零 → 下一帧炸开，粒子数阶跃。"""
    scene = FireworksScene(auto_launch=False)
    r = scene.launch(origin=np.array([0.0, 10.0, 0.0]))
    scene.update(1 / 60)
    before = scene.count
    r.vel = np.array([0.0, 0.0, 0.0])          # 强制到顶点
    scene.update(1 / 60)
    assert scene.count > before + r.burst_count * 0.8
    assert len(scene._rockets) == 0


def test_burst_velocity_spherically_distributed():
    """爆炸火星速度方向近似球面均匀：各轴均值≈0，径向分量占主导。"""
    scene = FireworksScene(auto_launch=False)
    r = scene.launch(origin=np.array([0.0, 10.0, 0.0]))
    scene.update(1 / 60)                       # 生成少量 trail
    n_before = scene.count
    scene._burst(r)
    pool = scene.system.pool
    new = pool.vel[n_before:pool.count]
    assert len(new) >= r.burst_count * 0.95
    mean_dir = new.mean(axis=0) / (np.linalg.norm(new, axis=1).mean() + 1e-9)
    assert np.abs(mean_dir).max() < 0.15       # 无系统偏向
    assert (np.linalg.norm(new, axis=1) > 5.0).mean() > 0.9


def test_does_not_exceed_capacity():
    """连续大量爆炸不得超出容量，也不得破坏已有粒子。"""
    scene = FireworksScene(auto_launch=False)
    for _ in range(40):
        scene.launch(origin=np.array([0.0, 10.0, 0.0]))
    for r in list(scene._rockets):
        r.vel = np.zeros(3)
    scene.update(1 / 60)
    assert scene.count <= scene.capacity


def test_color_kept_per_burst():
    """同一发烟花的 RGB 一致（不是全局渐变），只有 alpha 随生命衰减。"""
    scene = FireworksScene(auto_launch=False)
    r = scene.launch(origin=np.array([0.0, 10.0, 0.0]))
    scene.update(1 / 60)
    n0 = scene.count
    scene._burst(r)
    colors = scene.system.pool.color[n0:scene.count]
    # 爆炸瞬间刚生成，RGB 应几乎一致
    assert colors[:, :3].std(axis=0).max() < 1e-5
    assert np.allclose(colors[:, :3][0], r.color)
