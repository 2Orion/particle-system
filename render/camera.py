"""轨道相机：拖拽旋转（yaw/pitch）、滚轮缩放、右键平移。

矩阵手写（列主序，兼容 OpenGL uniform mat4）：
- view：lookAt(eye, target, up) 的标准形式；
- projection：透视投影 fov_y / aspect / near / far。

不用 pyglm —— 手写便于课程报告展示公式，也少一个测试依赖。
"""
from __future__ import annotations

import numpy as np


def look_at(eye: np.ndarray, target: np.ndarray, up: np.ndarray) -> np.ndarray:
    """视图矩阵：世界 → 相机（右手系，相机看 −z）。

    z_axis = normalize(eye − target)（相机朝向的反向）
    x_axis = normalize(cross(up, z_axis))
    y_axis = cross(z_axis, x_axis)
    """
    z = eye - target
    z /= np.linalg.norm(z)
    x = np.cross(up, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    m = np.identity(4, dtype=np.float32)
    m[0, :3], m[1, :3], m[2, :3] = x, y, z
    m[0, 3], m[1, 3], m[2, 3] = -x @ eye, -y @ eye, -z @ eye
    return m


def perspective(fovy_rad: float, aspect: float, near: float, far: float) -> np.ndarray:
    """透视投影矩阵（OpenGL 约定，映射到 NDC [−1,1]³）。"""
    f = 1.0 / np.tan(fovy_rad / 2.0)
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2.0 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


class OrbitCamera:
    """绕目标点的轨道相机。

    eye = target + distance·(cosP·sinY, sinP, cosP·cosY)
    """

    def __init__(self, target=(0.0, 2.0, 0.0), distance: float = 14.0,
                 yaw: float = 0.6, pitch: float = 0.35,
                 fovy_deg: float = 50.0, near: float = 0.1, far: float = 500.0) -> None:
        self.target = np.asarray(target, dtype=np.float64)
        self.distance = float(distance)
        self.yaw = float(yaw)          # 绕 y 轴方位角
        self.pitch = float(pitch)      # 仰角，限制在 [min_pitch, max_pitch]
        self.fovy = np.radians(fovy_deg)
        self.near, self.far = near, far
        self.min_distance, self.max_distance = 1.0, 200.0
        self.min_pitch, self.max_pitch = -1.45, 1.45  # 不越过极点

    @property
    def eye(self) -> np.ndarray:
        cp = np.cos(self.pitch)
        offset = np.array([cp * np.sin(self.yaw), np.sin(self.pitch),
                           cp * np.cos(self.yaw)])
        return self.target + self.distance * offset

    # -------------------------------------------------- 输入处理

    def rotate(self, dx: float, dy: float, sensitivity: float = 0.005) -> None:
        """左键拖拽：dx/dy 为像素位移。"""
        self.yaw += dx * sensitivity
        self.pitch = np.clip(self.pitch + dy * sensitivity,
                             self.min_pitch, self.max_pitch)

    def zoom(self, factor: float) -> None:
        """滚轮：factor>1 拉近（每档 1.1）。"""
        self.distance = np.clip(self.distance / factor,
                                self.min_distance, self.max_distance)

    def pan(self, dx: float, dy: float) -> None:
        """右键拖拽：沿相机右/上方向平移目标点。"""
        up = np.array([0.0, 1.0, 0.0])
        z = self.eye - self.target
        z /= np.linalg.norm(z)
        x = np.cross(up, z); x /= np.linalg.norm(x)
        y = np.cross(z, x)
        scale = self.distance * 0.0016
        self.target = self.target - x * (dx * scale) + y * (dy * scale)

    # -------------------------------------------------- 矩阵

    def view_matrix(self) -> np.ndarray:
        return look_at(self.eye, self.target, np.array([0.0, 1.0, 0.0]))

    def projection_matrix(self, aspect: float) -> np.ndarray:
        return perspective(self.fovy, aspect, self.near, self.far)

    def mvp(self, aspect: float) -> np.ndarray:
        """MVP = P·V（模型为单位阵）。"""
        return self.projection_matrix(aspect) @ self.view_matrix()

    def pixels_per_unit(self, viewport_height: int) -> float:
        """世界单位 → 像素的换算因子（点精灵尺寸用）：0.5·H / tan(fovy/2)。"""
        return 0.5 * viewport_height / np.tan(self.fovy / 2.0)

    # -------------------------------------------------- 屏幕 → 世界

    def screen_ray(self, px: float, py: float,
                   viewport: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
        """像素坐标 → 世界空间射线 (origin=eye, direction 单位向量)。

        px/py 为窗口像素坐标，原点左上、y 向下（与 pyglet 一致）。
        做法：像素 → NDC → 视图空间方向 → 乘 view 的逆旋转回到世界。
        """
        w, h = viewport
        ndc_x = (2.0 * px / max(w, 1)) - 1.0
        ndc_y = 1.0 - (2.0 * py / max(h, 1))       # y 翻转
        tan_half = np.tan(self.fovy / 2.0)
        aspect = w / max(h, 1)
        # 视图空间：相机看 −z
        dir_view = np.array([ndc_x * tan_half * aspect, ndc_y * tan_half, -1.0])
        # view 是刚体变换，其逆旋转 = 转置的左上 3×3
        v = self.view_matrix()[:3, :3]
        direction = v.T @ dir_view
        direction /= np.linalg.norm(direction)
        return self.eye, direction

    def project_to_plane(self, px: float, py: float, viewport: tuple[int, int],
                         plane_point=None, plane_normal=None) -> np.ndarray | None:
        """像素 → 与给定平面（默认过 target、法向朝相机）的交点。"""
        origin, direction = self.screen_ray(px, py, viewport)
        if plane_point is None:
            plane_point = self.target
        p0 = np.asarray(plane_point, dtype=float)
        if plane_normal is None:
            n = self.eye - self.target
            n /= np.linalg.norm(n)
        else:
            n = np.asarray(plane_normal, dtype=float)
            n /= np.linalg.norm(n)
        denom = float(direction @ n)
        if abs(denom) < 1e-9:
            return None                             # 射线与平面平行
        t = float((p0 - origin) @ n) / denom
        if t <= 0.0:
            return None                             # 交点在相机背后
        return origin + direction * t
