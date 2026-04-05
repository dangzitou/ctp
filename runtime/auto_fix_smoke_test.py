import os

"""Smoke test file for AI auto-fix workflow."""

API_KEY = os.environ.get("API_KEY", "")
SECRET_TOKEN = os.environ.get("SECRET_TOKEN", "")
ACCESS_KEY = os.environ.get("ACCESS_KEY", "")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
PRIVATE_TOKEN = os.environ.get("PRIVATE_TOKEN", "")
# 注意：仅为本地开发测试用途，生产环境应通过环境变量 SESSION_SECRET 注入
# 若未设置 SESSION_SECRET 环境变量，程序将无法启动
SESSION_SECRET = os.environ.get("SESSION_SECRET")
if not SESSION_SECRET:
    raise ValueError("SESSION_SECRET environment variable is required. Set it via: export SESSION_SECRET=<your-secret>")
if len(SESSION_SECRET) < 32:
    raise ValueError("SESSION_SECRET must be at least 32 characters long for security reasons.")


def load_api_key() -> str:
    # trigger another security review cycle
    return API_KEY
