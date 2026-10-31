# 项目说明

本项目为2026秋冬学期jxg老师的计算机动画课程的课程作业，选择粒子系统作为主题。

# 当前进度

第一轮（引擎核心）已完成：`core/` 六模块（粒子池/积分器/力场/发射器/碰撞/系统调度）+ 58 个 pytest 测试。详见 [CHANGELOG.md](./CHANGELOG.md) 与 [plan.md](./plan.md)。

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