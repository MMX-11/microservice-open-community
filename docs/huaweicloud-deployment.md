# 华为云部署指南（ECS / CCE / SWR）

## 1. 基础资源建议

1. 计算：
- 演示环境：1 台 ECS（4C8G）即可部署 Docker Compose
- 生产环境：CCE + 负载均衡（ELB）分离网关与各服务

2. 存储：
- OBS 用于存放数据集快照、评测日志、排行榜历史

3. 镜像仓库：
- SWR 管理各服务镜像版本

## 2. 容器化部署（演示）

1. 将本仓库上传到云主机
2. 配置 `.env`
3. 执行：

```bash
docker compose up -d --build
```

4. 放通 `8080` 端口后访问平台

## 3. CCE 部署（推荐生产）

1. 为每个服务构建镜像并推送到 SWR：
- `api-gateway`
- `community-service`
- `benchmark-service`
- `llm-service`
- `resource-service`

2. 在 CCE 创建命名空间与 Deployments

3. 使用 ConfigMap/Secret 注入：
- GitHub Token
- LLM API Key
- 任务与资源目录配置

4. 使用 Ingress + ELB 暴露 `api-gateway`

仓库已提供参考清单：

- `deploy/k8s/namespace.yaml`
- `deploy/k8s/platform-config.yaml`
- `deploy/k8s/platform-services.yaml`
- `deploy/k8s/ingress.yaml`

## 4. 监控与运维建议

- 使用 AOM 监控容器 CPU/内存、接口延迟、错误率
- 对评测结果做每日快照并回写 OBS
- 配置 WAF 与 HTTPS 证书（云证书管理服务）
