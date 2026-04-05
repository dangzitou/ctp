import os

"""Smoke test file for AI auto-fix workflow."""

API_KEY = os.environ.get("API_KEY", "")
SECRET_TOKEN = os.environ.get("SECRET_TOKEN", "")
ACCESS_KEY = os.environ.get("ACCESS_KEY", "")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
PRIVATE_TOKEN = os.environ.get("PRIVATE_TOKEN", "")
# 注意：仅为本地开发测试用途，生产环境应通过环境变量 SESSION_SECRET 注入
SESSION_SECRET = os.environ.get("SESSION_SECRET", "test-secret-placeholder")
PRIVATE_TOKEN = os.environ.get("PRIVATE_TOKEN", "")


def load_api_key() -> str:
    # trigger another security review cycle
    return API_KEY
