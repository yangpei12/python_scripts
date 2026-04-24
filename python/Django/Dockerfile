# syntax=docker/dockerfile:1.6
# 多阶段构建：第一阶段装依赖 + 预编译静态资源，第二阶段只拷运行时所需产物。

# =========== Stage 1: 构建依赖 ===========
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 基础工具：sqlite3 客户端留作备份/手动排障用
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# =========== Stage 2: 运行镜像 ===========
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DJANGO_SETTINGS_MODULE=workorder.settings \
    WORKORDER_DB_PATH=/data/db/db.sqlite3 \
    WORKORDER_STATIC_ROOT=/app/staticfiles \
    WORKORDER_MEDIA_ROOT=/data/media

RUN apt-get update \
    && apt-get install -y --no-install-recommends sqlite3 tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 app \
    && useradd  --system --uid 1000 --gid app --home /app app

COPY --from=builder /install /usr/local
WORKDIR /app
COPY --chown=app:app . /app

# 准备数据目录（volume 会挂载覆盖）。镜像内先建好，避免首次启动缺目录
RUN mkdir -p /data/db /data/media /app/staticfiles \
    && chown -R app:app /data /app/staticfiles

# 构建阶段预先 collectstatic，把 hash 化后的静态资源烘进镜像；
# 运行期不需要再跑 collectstatic（除非改了模板/静态文件重新 build）。
# SECRET_KEY 只是 collectstatic 需要能加载 settings，随便给个值即可。
RUN WORKORDER_SECRET_KEY=build-only WORKORDER_DEBUG=0 \
    python manage.py collectstatic --noinput

USER app

EXPOSE 8000

# tini 做 init，干净处理 SIGTERM
ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker/entrypoint.sh"]
CMD ["gunicorn", "-c", "deploy/gunicorn.conf.py", "workorder.wsgi:application"]
