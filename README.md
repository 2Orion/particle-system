# 项目说明

本项目为2026秋冬学期jxg老师的计算机动画课程的课程作业，选择粒子系统作为主题。

# 当前进度

- 第一轮（引擎核心）：`core/` 六模块（粒子池/积分器/力场/发射器/碰撞/系统调度）
- 第二轮（渲染 + 首场景）：`render/` 四模块（相机/纹理/点精灵/网格）、
  `scenes/fountain.py` 喷泉、`main.py` 入口
- 第三轮（三新场景 + 切换）：`scenes/` 场景基类与协议、烟花/火焰/雪三场景、
  数字键切换 —— 131 个 pytest 测试全部通过

详见 [CHANGELOG.md](./CHANGELOG.md) 与 [plan.md](./plan.md)。

# 运行

```bash
python main.py
```

| 操作 | 按键 |
|---|---|
| 旋转相机 | 左键拖拽 |
| 平移 / 缩放 | 右键拖拽 / 滚轮 |
| 切换场景 | `1` 喷泉 / `2` 雪 / `3` 火焰 / `4` 烟花 |
| 重置当前场景 | `R` |
| 暂停 / 继续 | `Space` |
| 截图到 `output/` | `F` |
| 退出 | `Esc` |

# 场景

| 场景 | 混合 | 纹理 | 要点 |
|---|---|---|---|
| 喷泉 Fountain | additive | 高斯光斑 | 主喷+双侧水拱，地面弹性碰撞 |
| 雪 Snow | alpha | 软圆盘 | 大范围体积源，弱重力+阻力+侧风，落地即消 |
| 火焰 Fire | additive | 软圆盘 | 浮力（∝剩余生命）+ 伪湍流，黄→橙→红→灰 |
| 烟花 Fireworks | additive | 高斯光斑 | 解析弹道火箭 + 顶点球面爆发 + 上升光尾 |

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