"""录制器测试：帧校验、时长换算、真实 MP4 输出（依赖 ffmpeg 时）。"""
import pathlib

import numpy as np
import pytest

from utils.recorder import Recorder


def test_recorder_rejects_wrong_size(tmp_path):
    try:
        rec = Recorder(tmp_path / "a.mp4", (64, 48), fps=10)
    except ImportError:
        pytest.skip("imageio-ffmpeg 未安装")
    with pytest.raises(ValueError, match="frame size"):
        rec.add_frame(np.zeros((48, 128, 3), dtype=np.uint8))
    rec.close()


def test_recorder_rejects_wrong_channels(tmp_path):
    try:
        rec = Recorder(tmp_path / "b.mp4", (64, 48), fps=10)
    except ImportError:
        pytest.skip("imageio-ffmpeg 未安装")
    with pytest.raises(ValueError, match="RGB"):
        rec.add_frame(np.zeros((48, 64), dtype=np.uint8))
    rec.close()


def test_recorder_counts_frames_and_duration(tmp_path):
    try:
        rec = Recorder(tmp_path / "c.mp4", (64, 48), fps=30)
    except ImportError:
        pytest.skip("imageio-ffmpeg 未安装")
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    for _ in range(15):
        rec.add_frame(frame)
    assert rec.frames == 15
    assert rec.duration == pytest.approx(0.5)     # 15 帧 @30fps
    path = rec.close()
    assert path.exists() and path.stat().st_size > 0


def test_recorder_accepts_non_contiguous_frames(tmp_path):
    """fbo 读回的图经 [::-1] 翻转后不是 C 连续，录制器要能处理。"""
    try:
        rec = Recorder(tmp_path / "d.mp4", (64, 48), fps=10)
    except ImportError:
        pytest.skip("imageio-ffmpeg 未安装")
    base = np.random.randint(0, 255, (48, 64, 3), dtype=np.uint8)
    flipped = base[::-1, :, :]                   # 负步长视图
    assert not flipped.flags["C_CONTIGUOUS"]
    rec.add_frame(flipped)                       # 不应抛异常
    assert rec.frames == 1
    rec.close()


def test_recorder_context_manager(tmp_path):
    try:
        rec = Recorder(tmp_path / "e.mp4", (64, 48), fps=10)
    except ImportError:
        pytest.skip("imageio-ffmpeg 未安装")
    with rec as r:
        r.add_frame(np.zeros((48, 64, 3), dtype=np.uint8))
    assert rec._gen is None


def test_recorder_creates_parent_dir(tmp_path):
    try:
        rec = Recorder(tmp_path / "deep" / "nested" / "f.mp4", (64, 48), fps=10)
    except ImportError:
        pytest.skip("imageio-ffmpeg 未安装")
    rec.add_frame(np.zeros((48, 64, 3), dtype=np.uint8))
    path = rec.close()
    assert path.parent.is_dir()
    assert path.exists()


def test_recorder_produces_playable_mp4(tmp_path):
    """端到端：写 20 帧彩色渐变，用 ffmpeg 读回并检查尺寸。"""
    pytest.importorskip("imageio_ffmpeg")
    import imageio_ffmpeg

    path = tmp_path / "g.mp4"
    rec = Recorder(path, (64, 48), fps=20)
    for i in range(20):
        frame = np.full((48, 64, 3), i * 10, dtype=np.uint8)
        frame[:, :, 0] = i * 12
        rec.add_frame(frame)
    rec.close()

    reader = imageio_ffmpeg.read_frames(str(path))
    meta = next(reader)                          # 首个元素是元数据 dict
    assert meta["size"] == (64, 48)
    assert meta["fps"] == pytest.approx(20.0, rel=0.1)
    frames = list(reader)
    assert len(frames) == 20
