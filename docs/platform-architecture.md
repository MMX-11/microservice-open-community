# 平台架构设计（微服务容器化）

## 目标

平台面向专利领域任务评测与开源社区建设，统一承载：

- 开源代码、Issue、PR 协作
- 数据集与模型资源发布
- 评测任务、基线与提交
- 大模型辅助与工作流自动化

## 微服务划分

1. `api-gateway`  
统一 API 入口、前端托管、跨服务聚合。

2. `community-service`  
对接 GitHub API，聚合仓库指标、Issue 状态、社区看板。

3. `benchmark-service`  
管理任务配置，执行评测逻辑，输出标准分数。

4. `llm-service`  
接入 OpenAI 兼容推理接口（可替换为华为云推理服务）。

5. `resource-service`  
管理平台资源目录（数据集、任务、贡献规范、外部平台入口）。

## 数据与流程

1. 前端发起请求到 `api-gateway`。
2. 网关转发到对应微服务。
3. `community-service` 从 GitHub 拉取最新社区数据。
4. `benchmark-service` 根据任务定义执行评分。
5. `llm-service` 调用模型接口，返回辅助分析结果。
6. `resource-service` 返回标准化资源目录。

## 规范化建议（对齐 OpenKG / HF 经验）

- 数据集条目必须包含许可证、版本、来源、切分信息
- 评测任务必须包含 metric、baseline、复现实验说明
- 新贡献必须通过 Issue 模板和 PR 模板进入审核流程
- 每次任务或数据变更必须更新 Changelog

