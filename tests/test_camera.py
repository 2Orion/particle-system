"""相机与矩阵测试：lookAt/透视投影的几何性质。"""
import numpy as np
import pytest

from render.camera import OrbitCamera, look_at, perspective


def test_look_at_maps_eye_to_origin():
    """相机位置应变换到原点（视图空间）。矩阵为 float32，精度 ~1e-6。"""
    eye = np.array([3.0, 4.0, 5.0])
    target = np.array([0.0, 0.0, 0.0])
    v = look_at(eye, target, np.array([0.0, 1.0, 0.0]))
    p = v @ np.append(eye, 1.0)
    assert np.allclose(p[:3], [0, 0, 0], atol=1e-5)


def test_look_at_target_on_negative_z():
    """视线方向映射到 −z（右手 OpenGL 约定）。"""
    eye = np.array([0.0, 0.0, 5.0])
    target = np.array([1.0, 0.0, 0.0])
    v = look_at(eye, target, np.array([0.0, 1.0, 0.0]))
    p = v @ np.append(target, 1.0)
    assert p[0] == pytest.approx(0.0, abs=1e-5)
    assert p[1] == pytest.approx(0.0, abs=1e-5)
    assert p[2] < 0


def test_look_at_preserves_distance():
    """刚体变换：‖eye−target‖ 在视图空间不变。"""
    eye = np.array([1.0, 2.0, 3.0])
    target = np.array([-2.0, 0.5, 1.0])
    v = look_at(eye, target, np.array([0.0, 1.0, 0.0]))
    pe = (v @ np.append(eye, 1.0))[:3]
    pt = (v @ np.append(target, 1.0))[:3]
    assert abs(np.linalg.norm(pe - pt) - np.linalg.norm(eye - target)) < 1e-5


def test_perspective_maps_near_far():
    """near 平面 → NDC z=−1，far 平面 → z=+1。"""
    p = perspective(np.radians(60), 1.0, near=0.1, far=100.0)
    near_pt = p @ np.array([0, 0, -0.1, 1.0])
    far_pt = p @ np.array([0, 0, -100.0, 1.0])
    assert (near_pt[:3] / near_pt[3])[2] == pytest.approx(-1.0)
    assert (far_pt[:3] / far_pt[3])[2] == pytest.approx(1.0)


def test_perspective_fov_extent():
    """fovy=90° 时，z=−d 处的可见半高 = d（tan45°=1）。"""
    p = perspective(np.radians(90), 1.0, near=0.1, far=100.0)
    corner = p @ np.array([0, 1.0, -1.0, 1.0])  # 视锥上边缘
    ndc = corner[:3] / corner[3]
    assert ndc[1] == pytest.approx(1.0, abs=1e-12)


def test_orbit_camera_eye_distance():
    cam = OrbitCamera(distance=10.0)
    assert np.linalg.norm(cam.eye - cam.target) == pytest.approx(10.0)


def test_orbit_camera_rotate_clamps_pitch():
    cam = OrbitCamera(pitch=0.0)
    for _ in range(500):
        cam.rotate(0.0, 0.1)   # 持续向上
    assert cam.pitch <= cam.max_pitch + 1e-12
    for _ in range(1000):
        cam.rotate(0.0, -0.1)
    assert cam.pitch >= cam.min_pitch - 1e-12


def test_orbit_camera_zoom_clamps():
    cam = OrbitCamera(distance=50)
    for _ in range(100):
        cam.zoom(2.0)         # 持续拉近
    assert cam.distance >= cam.min_distance
    for _ in range(200):
        cam.zoom(0.5)
    assert cam.distance <= cam.max_distance


def test_pixels_per_unit_formula():
    """pixels_per_unit = 0.5·H / tan(fovy/2)：fovy=90° 时 = H/2。"""
    cam = OrbitCamera(fovy_deg=90.0)
    assert cam.pixels_per_unit(720) == pytest.approx(360.0)
    cam2 = OrbitCamera(fovy_deg=60.0)
    assert cam2.pixels_per_unit(720) == pytest.approx(0.5 * 720 / np.tan(np.radians(30)))
