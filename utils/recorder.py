"""逐帧抓取 → MP4（plan §6 录制）。

设计：录制器只负责"收帧 + 编码"，不碰窗口/GL 上下文——
调用方每帧把已读出的 RGB 数组喂给 `add_frame()`。

编码走 imageio-ffmpeg 的 `write_frames` 生成器（内部即 ffmpeg 管道），
不引入 imageio 主包。依赖缺失时构造即报错并给出安装提示，
而不是让用户在录到一半时才发现。

固定 fps 输出（默认 60）：录制时的实时帧率波动不影响成片的时长与节奏，
这也是课件里"逐帧录制"的常规做法。
"""
from __future__ import annotations

import pathlib
import time

import numpy as np

DEFAULT_FPS = 60


class Recorder:
    """MP4 录制器：add_frame() 收集，close() 落盘。"""

    def __init__(self, path: str | pathlib.Path, size: tuple[int, int],
                 fps: int = DEFAULT_FPS, quality: int = 7) -> None:
        """
        :param path: 输出文件路径（.mp4）
        :param size: (width, height)，必须与 add_frame 传入的帧一致
        :param fps: 输出帧率
        :param quality: ffmpeg 质量（0-10，越大越好越大）
        """
        try:
            import imageio_ffmpeg
        except ImportError as exc:                # pragma: no cover - 环境相关
            raise ImportError(
                "录制需要 imageio-ffmpeg：pip install imageio-ffmpeg"
            ) from exc

        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.size = (int(size[0]), int(size[1]))
        self.fps = int(fps)
        self.frames = 0
        # macro_block_size=16：视频宽高须为 16 的倍数，否则 ffmpeg 报错
        self._gen = imageio_ffmpeg.write_frames(
            str(self.path), self.size, fps=self.fps, quality=quality,
            macro_block_size=16, ffmpeg_log_level="error")
        self._gen.send(None)                      # seed 生成器
        self._t0 = time.perf_counter()

    def add_frame(self, rgb: np.ndarray) -> None:
        """写入一帧。rgb 形状 (h, w, 3) uint8，自顶向下（图像坐标）。"""
        arr = np.ascontiguousarray(rgb, dtype=np.uint8)
        h, w = arr.shape[:2]
        if (w, h) != self.size:
            raise ValueError(f"frame size {(w, h)} != recorder size {self.size}")
        if arr.ndim != 3 or arr.shape[2] != 3:
            raise ValueError(f"expected (h,w,3) RGB, got {arr.shape}")
        self._gen.send(arr)
        self.frames += 1

    @property
    def duration(self) -> float:
        """已录制时长（按 fps 换算的成片时长）。"""
        return self.frames / self.fps

    @property
    def real_elapsed(self) -> float:
        return time.perf_counter() - self._t0

    def close(self) -> pathlib.Path:
        """结束录制并落盘，返回文件路径。"""
        if self._gen is not None:
            self._gen.close()
            self._gen = None
        return self.path

    def __enter__(self) -> "Recorder":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
