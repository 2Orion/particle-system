# 项目说明

本项目为2026秋冬学期jxg老师的计算机动画课程的课程作业，选择粒子系统作为主题。

# 当前进度

- 第一轮（引擎核心）：`core/` 六模块（粒子池/积分器/力场/发射器/碰撞/系统调度）
- 第二轮（渲染 + 首场景）：`render/` 四模块（相机/纹理/点精灵/网格）、
  `scenes/fountain.py` 喷泉、`main.py` 入口 —— 85 个 pytest 测试全部通过，
  真实窗口冒烟 250+ FPS

详见 [CHANGELOG.md](./CHANGELOG.md) 与 [plan.md](./plan.md)。

# 运行

```bash
python main.py
```

操作：左键拖拽旋转 / 右键平移 / 滚轮缩放 / Space 暂停 / F 截图 / Esc 退出。

# 运行测试

```bash
pip install -r requirements-dev.txt
python -m pytest
```

# 参考资料
1. [粒子系统实现与原理](https://zhuanlan.zhihu.com/p/630778848)
2. [计算机动画原理与技术（三）粒子系统](https://zhuanlan.zhihu.com/p/483273489)
3. [jxg老师PPT](./docs/Lecture6(5).pdf)
4. [课程作业要求](./docs/project_needs.pdf)