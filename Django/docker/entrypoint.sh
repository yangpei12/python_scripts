#!/bin/sh
# 容器入口：先迁库、灌基础数据，再 exec 启动主进程。
set -eu

echo "[entrypoint] python $(python --version 2>&1) · Django $(python -c 'import django;print(django.get_version())')"

# 1) 数据目录兜底（首次启动 volume 是空的）
mkdir -p "$(dirname "${WORKORDER_DB_PATH}")" "${WORKORDER_MEDIA_ROOT}"

# 2) 数据迁移（幂等）
echo "[entrypoint] migrate ..."
python manage.py migrate --noinput

# 3) 角色分组（frontend / backend / manager），幂等
echo "[entrypoint] seed groups ..."
python manage.py seed_groups

# 4) 可选：用环境变量一次性把超级管理员建出来（仅当用户名不存在时）
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] \
   && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  echo "[entrypoint] ensure superuser ${DJANGO_SUPERUSER_USERNAME} ..."
  python manage.py shell -c "
import os
from django.contrib.auth import get_user_model
U = get_user_model()
u = os.environ['DJANGO_SUPERUSER_USERNAME']
p = os.environ['DJANGO_SUPERUSER_PASSWORD']
e = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')
if not U.objects.filter(username=u).exists():
    U.objects.create_superuser(username=u, email=e, password=p)
    print('superuser created')
else:
    print('superuser already exists, skip')
"
fi

# 5) 一次性给 SQLite 打开 WAL（小并发下更稳，幂等）
python - <<'PY'
import os, sqlite3
p = os.environ["WORKORDER_DB_PATH"]
if os.path.exists(p):
    con = sqlite3.connect(p)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.close()
    print("[entrypoint] sqlite WAL enabled on", p)
PY

# 6) 交棒给 CMD（gunicorn）
echo "[entrypoint] exec:" "$@"
exec "$@"
