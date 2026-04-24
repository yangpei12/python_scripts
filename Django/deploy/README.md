# 工单系统 · Docker 部署指南

适用：小团队（10~50 人）内部工具。单容器 = Django + Gunicorn + WhiteNoise + SQLite。
数据持久化通过 docker named volume：`workorder_db`（SQLite 主库）+ `workorder_media`（附件）。

---

## 0. 依赖

- 目标服务器：Linux + Docker ≥ 24 + docker compose v2
- 首次联网拉取 `python:3.12-slim` 基底镜像

## 1. 首次部署（从零到上线，约 5 分钟）

```bash
# 1) 把代码拷到服务器（git / scp / rsync 均可）
cd /opt && git clone <your-repo> workorder && cd workorder

# 2) 准备 .env
cp deploy/docker.env.example .env
# 用编辑器修改：
#   - WORKORDER_SECRET_KEY        （必改，随机长串）
#   - WORKORDER_ALLOWED_HOSTS     （改成你对外的域名/IP）
#   - DJANGO_SUPERUSER_USERNAME/PASSWORD（首次自动建管理员用；启动后进 /admin 改密）
vim .env

# 3) 构建 + 启动（后台）
docker compose up -d --build

# 4) 查看日志确认 migrate/seed_groups/superuser 都成功
docker compose logs -f web
```

启动后浏览器访问 `http://<服务器IP>:8080/`（compose 默认映射 8080→容器 8000；如冲突可在 `docker-compose.yml` 里改）。

## 2. 账号初始化

登录 `/admin/`（用 `.env` 里配置的超管账号）：

1. 创建 14 个业务账号（前端 + 后端 + 必要的管理员）。
2. 给每个账号勾选 `Groups`：`frontend` / `backend` / `manager`（`seed_groups` 已在首启时自动建好这 3 个分组）。
3. 管理员账号无需再入组，`is_staff` / `is_superuser` 即视为 manager。

## 3. 日常运维

```bash
# 查看状态
docker compose ps
docker compose logs --tail 200 web

# 停 / 启
docker compose stop
docker compose start

# 代码更新后重新部署（保留数据）
git pull
docker compose up -d --build

# 进容器排障
docker compose exec web bash
docker compose exec web python manage.py shell
docker compose exec web sqlite3 $WORKORDER_DB_PATH ".tables"
```

## 4. 数据备份（重要！）

SQLite 文件在 named volume 里，**不会随容器删除而消失**，但仍需周期备份：

```bash
# 备份（热备，期间服务不中断；WAL 模式下安全）
mkdir -p /backup/workorder
docker compose exec -T web sqlite3 $WORKORDER_DB_PATH ".backup /data/db/backup.sqlite3"
docker cp workorder:/data/db/backup.sqlite3 \
  /backup/workorder/workorder-$(date +%F-%H%M).sqlite3

# 附件备份（按需增量；1~50 人用量不大）
docker run --rm \
  -v workorder_media:/src -v /backup/workorder:/dst \
  alpine tar czf /dst/media-$(date +%F).tgz -C /src .
```

建议加 cron：每日备 SQLite，每周备 media。

## 5. 数据恢复

```bash
docker compose stop web
docker run --rm -v workorder_db:/dst -v /backup/workorder:/src \
  alpine sh -c 'cp /src/workorder-YYYY-MM-DD-HHMM.sqlite3 /dst/db.sqlite3'
docker compose start web
```

## 6. 要不要加 HTTPS / Nginx？

- 内网 HTTP 直接用：无需改。
- 要 HTTPS：推荐在宿主机上装 Caddy 或 Nginx 做反代到 `127.0.0.1:8080`，证书走 Let's Encrypt。
  - 使用反代时在 `.env` 中补 `WORKORDER_CSRF_TRUSTED_ORIGINS=https://你的域名`。

## 7. 性能 / 并发

SQLite 已开 WAL（entrypoint 自动），读并发几乎无上限，写串行但实测 <100 人/天 的工单系统毫无压力。
如果未来接入需要千级并发 / 多实例集群，再考虑切换 PostgreSQL（改 `DATABASES`，其余逻辑无需改）。

## 8. 常见问题

| 现象 | 排查 |
|---|---|
| `Invalid HTTP_HOST header` | `.env` 的 `WORKORDER_ALLOWED_HOSTS` 没写你访问用的域名/IP |
| `CSRF verification failed` | 走反代 HTTPS 时忘了配 `WORKORDER_CSRF_TRUSTED_ORIGINS` |
| 静态资源 404 | 改过静态资源没 rebuild；`docker compose up -d --build` |
| 想改端口 | `docker-compose.yml` 里的 `ports: - "8080:8000"` 左侧 |
| 想暴露给外网 | 前面加 Caddy/Nginx + HTTPS + 账号强制策略；不要让 `:8000` 直接对公网 |
