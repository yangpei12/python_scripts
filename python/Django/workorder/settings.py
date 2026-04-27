"""Django settings for workorder project.

开发环境：直接 `python manage.py runserver`，使用默认值即可。
生产环境：在进程环境里设置以下变量（见 deploy/env.example）：
  WORKORDER_SECRET_KEY
  WORKORDER_DEBUG=0
  WORKORDER_ALLOWED_HOSTS=工单.example.com,10.0.0.5
  WORKORDER_DB_PATH=/var/lib/workorder/db.sqlite3
  WORKORDER_MEDIA_ROOT=/mnt/nfs/workorder/media
  WORKORDER_STATIC_ROOT=/var/lib/workorder/static
"""

import os
from pathlib import Path

from django.urls import reverse_lazy


def _env_bool(name, default=False):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "y", "on")


def _env_list(name, default=None):
    v = os.environ.get(name)
    if not v:
        return list(default or [])
    return [x.strip() for x in v.split(",") if x.strip()]


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "WORKORDER_SECRET_KEY",
    "django-insecure-g!wn))**cxglo(k+n2n#m1opt_1%47(bphfald*g254mw06y@3",
)

DEBUG = _env_bool("WORKORDER_DEBUG", default=True)

ALLOWED_HOSTS = _env_list(
    "WORKORDER_ALLOWED_HOSTS",
    default=["localhost", "127.0.0.1"] if DEBUG else [],
)

# 内网 HTTP 部署，关闭 HTTPS 相关强制跳转
CSRF_TRUSTED_ORIGINS = _env_list("WORKORDER_CSRF_TRUSTED_ORIGINS", default=[])
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tickets",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise 紧跟在 SecurityMiddleware 之后，负责生产环境直接发布静态文件
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "workorder.middleware.SplitSessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "workorder.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "tickets.context_processors.role_flags",
            ],
        },
    },
]

WSGI_APPLICATION = "workorder.wsgi.application"

# SQLite 数据库文件必须放在本地盘（NFS 上锁机制不兼容，会损坏数据）
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("WORKORDER_DB_PATH", str(BASE_DIR / "db.sqlite3")),
        # 连接获取锁的等待时间，14 人并发足够。WAL 模式在部署时一次性开启（见 deploy 文档）
        "OPTIONS": {"timeout": 20},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

# 静态文件：开发时从 app 的 static 目录直接读；
# 生产环境跑 collectstatic 汇总到 STATIC_ROOT，由 WhiteNoise 直接对外发布（带强缓存 + gzip/br 压缩）
STATIC_URL = "static/"
STATIC_ROOT = os.environ.get("WORKORDER_STATIC_ROOT", str(BASE_DIR / "staticfiles"))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# 附件媒体文件：可以指向 NFS 挂载点
MEDIA_URL = "media/"
MEDIA_ROOT = Path(os.environ.get("WORKORDER_MEDIA_ROOT", str(BASE_DIR / "media")))

LOGIN_URL = reverse_lazy("login")
LOGIN_REDIRECT_URL = reverse_lazy("tickets:home")
LOGOUT_REDIRECT_URL = reverse_lazy("login")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# 我们使用自定义的 SplitSessionMiddleware 来替代默认 SessionMiddleware。
# admin 的系统检查只按字符串判断，故静默该项检查。
SILENCED_SYSTEM_CHECKS = ["admin.E410"]

# 简单日志配置：生产环境把 WARNING 以上写到 stderr，由 systemd journal 统一收集
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "INFO" if DEBUG else "WARNING"},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
