# GitHub 集成清单

## 仓库级设置

1. 开启 Issues、Discussions、Projects
2. 配置默认分支保护规则（至少包含 PR Review + CI）
3. 启用 GitHub Actions（当前仓库包含 `benchmark-ci.yml`）

## 社区模板

- 已提供 Bug / Benchmark / Dataset 三类 Issue 模板
- 已提供 PR 模板，要求提交评测结果与数据治理信息

## 统一管理建议

1. 使用 GitHub Project 字段：
- `Type`（Bug / Feature / Dataset / Benchmark）
- `TaskID`（如 `patent_semantic_matching_zh`）
- `Status`（Backlog / In Progress / Review / Done）
- `BenchmarkScore`（可选）

2. 使用 Label 规范：
- `benchmark`
- `dataset`
- `governance`
- `infra`
- `good-first-issue`

3. 每月发布社区报告：
- 新增任务数量
- 数据集更新次数
- PR 合并与评测提交统计

