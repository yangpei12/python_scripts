"""Gunicorn 配置。systemd 会用 `gunicorn -c deploy/gunicorn.conf.py workorder.wsgi` 启动。"""

import multiprocessing
import os

# 默认绑定 0.0.0.0:8000（容器场景）；裸机 + nginx 场景请通过 WORKORDER_BIND=127.0.0.1:8001 覆盖
bind = os.environ.get("WORKORDER_BIND", "0.0.0.0:8000")

# 工作进程数：推荐 2*CPU+1，14 人内部工具通常 2~4 即可
workers = int(os.environ.get("WORKORDER_WORKERS", max(2, multiprocessing.cpu_count())))

# 使用同步 worker（默认）。附件上传可能耗时，单次请求超时适当放宽。
timeout = int(os.environ.get("WORKORDER_TIMEOUT", "120"))
graceful_timeout = 30
keepalive = 5

# 日志写 stdout/stderr，由 systemd journal 收集
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("WORKORDER_LOGLEVEL", "info")

# 避免单个进程过大时泄漏内存：每处理 1000 个请求重启 worker
max_requests = 1000
max_requests_jitter = 50
