# openKG-field 开源协作社区

面向专利智能与知识工程的开源社区站点，聚合任务榜、前沿观察、资源共享与讨论协作。

在线访问（当前部署）：
- 社区首页：`https://openkgfield.duckdns.org:30043/`
- 健康检查：`https://openkgfield.duckdns.org:30043/api/health`

## 核心模块

- 文献任务榜：任务、数据集、指标、基线结果统一查看
- 前沿观察：实验室项目与趋势议题跟踪
- 资源共享：代码仓库、配套资料、可复用资源沉淀
- 讨论广场：报告、预测、问题讨论与协作线索
- AI 共创助手：接入 OpenAI 兼容模型，生成可编辑草稿

## 技术结构

```text
.
├─ frontend/                   # 社区首页（内容站风格）
├─ services/
│  ├─ api-gateway/             # 统一 API 网关 + 前端托管
│  ├─ community-service/       # GitHub 社区数据聚合
│  ├─ benchmark-service/       # 基准任务与评分逻辑
│  ├─ llm-service/             # OpenAI 兼容模型接入
│  └─ resource-service/        # 资源目录与持久化管理
├─ resources/                  # 社区内容目录
├─ docs/                       # 部署与治理文档
├─ docker-compose.yml
└─ docker-compose.public.yml   # Caddy 公网发布
```

## 快速启动（本地）

```bash
cp .env.example .env
docker compose up --build
```

访问：`http://localhost:8080/`

## 公网部署（推荐）

```bash
docker compose -f docker-compose.yml -f docker-compose.public.yml up -d --build
```

部署说明见：`docs/public-deployment.md`

## 模型接入

在 `.env` 配置 OpenAI 兼容参数：

```bash
OPENAI_COMPATIBLE_BASE_URL=...
OPENAI_COMPATIBLE_API_KEY=...
OPENAI_COMPATIBLE_MODEL=...
```

已验证可用：`Qwen/Qwen2.5-7B-Instruct`（remote 模式）

## 项目目标

1. 构建可公开访问的开源社区入口
2. 沉淀专利智能相关任务与资源体系
3. 打通 GitHub 协作与内容链接跳转
4. 接入免费/低成本大模型辅助内容共建