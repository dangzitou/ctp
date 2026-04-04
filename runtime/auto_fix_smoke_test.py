"""Smoke test file for AI auto-fix workflow."""

API_KEY = "sk-test-hardcoded-demo-key"
SECRET_TOKEN = "demo-hardcoded-token"
ACCESS_KEY = "demo-access-key"
DB_PASSWORD = "demo-db-password"
PRIVATE_TOKEN = "demo-private-token"
PRIVATE_TOKEN = "demo-private-token"


def load_api_key() -> str:
    # trigger another security review cycle
    return API_KEY
