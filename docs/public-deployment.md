# 公网访问部署（Docker + Caddy）

这个项目不只能本地运行。部署到云服务器后，任何人都可以通过你的域名访问。

## 1. 准备一台云服务器

- 建议配置：2C4G 起步
- 系统：Ubuntu 22.04 / Debian 12
- 安装：Docker + Docker Compose
- 安全组放行端口：`80`、`443`

## 2. 配置环境变量

在项目根目录创建 `.env`（可从 `.env.example` 复制），至少补齐：

```bash
GITHUB_ORG=openKG-field
DOMAIN=your-domain.com
```

说明：
- `DOMAIN` 必须已经解析到你的云服务器公网 IP

## 3. 启动公网服务

```bash
docker compose -f docker-compose.yml -f docker-compose.public.yml up -d --build
```

启动后：
- `api-gateway` 仍在容器网络内提供服务
- `caddy` 负责对外 `80/443` 访问与 HTTPS 证书自动续期

## 4. 验证

- 打开 `https://your-domain.com`
- 访问 `https://your-domain.com/api/health` 返回 `{"status":"ok","service":"api-gateway"}`

## 5. 常见问题

1. 证书申请失败  
通常是域名未解析到服务器，或 `80/443` 未放行。

2. 页面可访问但 API 失败  
先检查容器状态：

```bash
docker compose ps
docker compose logs --tail=200 api-gateway resource-service
```

3. 更新后不生效  
重新构建并重启：

```bash
docker compose -f docker-compose.yml -f docker-compose.public.yml up -d --build
```
