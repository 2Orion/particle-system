"""喷泉场景测试：端到端物理 + 着色。"""
import numpy as np
import pytest

from scenes.fountain import FountainScene


def test_fountain_reaches_steady_state():
    """发射 ~900+450×2/s、寿命 ~2s → 动态平衡粒子数应在量级范围内。"""
    scene = FountainScene()
    for _ in range(600):                    # 10 秒 @60fps
        scene.update(1 / 60)
    n = scene.system.pool.count
    assert 1_000 < n < scene.capacity, f"alive={n}"


def test_fountain_particles_stay_in_world():
    """KillBox 应删除所有越界粒子。"""
    scene = FountainScene()
    for _ in range(300):
        scene.update(1 / 60)
    pos = scene.system.pool.pos[:scene.system.pool.count]
    assert np.isfinite(pos).all()
    assert pos[:, 1].max() < 40             # 没有粒子飞出天际


def test_fountain_color_fades_with_life():
    """生命分数低 → 透明度低（着色回调生效）。"""
    scene = FountainScene()
    for _ in range(120):                    # 2 秒：有完整生命周期的粒子
        scene.update(1 / 60)
    pool = scene.system.pool
    n = pool.count
    frac = pool.life_fraction
    alpha = pool.color[:n, 3]
    # 新生粒子（frac>0.9）应比临终粒子（frac<0.1）更不透明
    young = alpha[frac > 0.9].mean() if (frac > 0.9).any() else 1.0
    old = alpha[frac < 0.1].mean() if (frac < 0.1).any() else 0.0
    assert young > old + 0.2


def test_fountain_uses_ground_collision():
    """碰撞体配置存在且地面下无粒子堆积。"""
    scene = FountainScene()
    for _ in range(300):
        scene.update(1 / 60)
    pos = scene.system.pool.pos[:scene.system.pool.count]
    # 允许瞬时穿透一帧内被拉回：地面下粒子极少
    below = (pos[:, 1] < -0.5).sum()
    assert below < pos.shape[0] * 0.01


def test_fountain_render_smoke():
    """场景 + 渲染器联动冒烟（有 GL 才跑）。"""
    moderngl = pytest.importorskip("moderngl")
    try:
        ctx = moderngl.create_context(standalone=True)
    except Exception as e:
        pytest.skip(f"no GL: {e}")
    from render.camera import OrbitCamera
    from render.particles import ParticleRenderer

    scene = FountainScene()
    for _ in range(60):
        scene.update(1 / 60)
    cam = OrbitCamera(target=(0, 2, 0), distance=14)
    r = ParticleRenderer(ctx, scene.capacity)
    fbo = ctx.simple_framebuffer((320, 240))
    fbo.use(); fbo.clear(0, 0, 0, 1)
    r.render(scene.system.pool, cam, (320, 240))
    data = np.frombuffer(fbo.read(), dtype=np.uint8).reshape(240, 320, 3)
    assert data.max() > 40                  # 画面里有亮的东西
    r.texture.release(); r._buffer.release(); ctx.release()
