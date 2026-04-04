from __future__ import annotations

import os
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

try:
    import redis
except ImportError:  # pragma: no cover - optional dependency for local scripts
    redis = None


DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_FRONT_SET_KEY = "ctp_collect_url"
DEFAULT_AUTH_HASH_KEY = "ctp_collect_auth"


def _clean(value: Optional[str]) -> str:
    return str(value or "").strip()


def _clean_fronts(fronts) -> List[str]:
    cleaned: List[str] = []
    seen = set()
    for front in fronts or []:
        value = _clean(front)
        if value and value not in seen:
            seen.add(value)
            cleaned.append(value)
    return cleaned


def _parse_front_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return _clean_fronts(value.replace(";", ",").replace("\n", ",").split(","))


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}***{value[-2:]}"


def _build_redis_client():
    if redis is None:
        return None

    redis_url = _clean(os.environ.get("REDIS_URL"))
    if redis_url:
        return redis.Redis.from_url(redis_url, decode_responses=True)

    host = _clean(os.environ.get("REDIS_HOST")) or "127.0.0.1"
    port = int(_clean(os.environ.get("REDIS_PORT")) or "6379")
    db = int(_clean(os.environ.get("REDIS_DB")) or "0")
    password = _clean(os.environ.get("REDIS_PASSWORD")) or None
    return redis.Redis(host=host, port=port, db=db, password=password, decode_responses=True)


@dataclass
class CtpConnectionSettings:
    front: str
    front_source: str
    front_candidates: List[str]
    broker_id: str
    user_id: str
    password: str
    app_id: str
    auth_code: str
    user_product_info: str
    auth_source: str
    redis_error: str = ""

    @property
    def requires_auth(self) -> bool:
        return bool(self.app_id or self.auth_code)

    def masked_summary(self) -> Dict[str, object]:
        return {
            "front": self.front,
            "front_source": self.front_source,
            "front_candidates": self.front_candidates,
            "broker_id": self.broker_id,
            "user_id": self.user_id,
            "password": _mask_secret(self.password),
            "app_id": self.app_id,
            "auth_code": _mask_secret(self.auth_code),
            "user_product_info": self.user_product_info,
            "auth_source": self.auth_source,
            "redis_error": self.redis_error,
        }


def resolve_ctp_connection(
    default_front: str,
    default_broker_id: str = "9999",
    default_user_id: str = "9999",
    default_password: str = "9999",
    default_app_id: str = "",
    default_auth_code: str = "",
    default_user_product_info: str = "ctp-runtime",
) -> CtpConnectionSettings:
    front_env = _clean_fronts(
        _parse_front_list(os.environ.get("CTP_FRONT"))
        + _parse_front_list(os.environ.get("CTP_FRONTS"))
    )
    auth_env = {
        "broker_id": _clean(os.environ.get("CTP_BROKER_ID")),
        "user_id": _clean(os.environ.get("CTP_USER_ID")),
        "password": _clean(os.environ.get("CTP_PASSWORD")),
        "app_id": _clean(os.environ.get("CTP_APP_ID")),
        "auth_code": _clean(os.environ.get("CTP_AUTH_CODE")),
        "user_product_info": _clean(os.environ.get("CTP_USER_PRODUCT_INFO")),
    }

    front_key = _clean(os.environ.get("CTP_FRONT_REDIS_KEY")) or DEFAULT_FRONT_SET_KEY
    auth_key = _clean(os.environ.get("CTP_AUTH_REDIS_KEY")) or DEFAULT_AUTH_HASH_KEY
    use_redis = _clean(os.environ.get("CTP_USE_REDIS")).lower() not in {"0", "false", "no", "off"}
    redis_fronts: List[str] = []
    redis_auth: Dict[str, str] = {}
    redis_error = ""

    if use_redis:
        try:
            client = _build_redis_client()
            if client is not None:
                redis_fronts = sorted(_clean_fronts(client.smembers(front_key)))
                redis_auth = {str(k).lower(): _clean(v) for k, v in client.hgetall(auth_key).items()}
            else:
                redis_error = "python redis package not installed"
        except Exception as exc:  # pragma: no cover - integration path
            redis_error = str(exc)

    if front_env:
        front_candidates = front_env
        front_source = "env:CTP_FRONT/CTP_FRONTS"
    elif redis_fronts:
        front_candidates = redis_fronts
        front_source = f"redis-set:{front_key}"
    else:
        front_candidates = [default_front]
        front_source = "default"

    pick_mode = _clean(os.environ.get("CTP_FRONT_PICK")).lower() or "sorted-first"
    front_index = _clean(os.environ.get("CTP_FRONT_INDEX"))
    if front_index:
        try:
            front = front_candidates[int(front_index) % len(front_candidates)]
            front_source = f"{front_source}#index={front_index}"
        except ValueError:
            front = front_candidates[0]
    elif pick_mode == "random" and len(front_candidates) > 1:
        front = random.choice(front_candidates)
        front_source = f"{front_source}#random"
    else:
        front = front_candidates[0]

    resolved_auth = {}
    auth_source = "default"
    defaults = {
        "broker_id": default_broker_id,
        "user_id": default_user_id,
        "password": default_password,
        "app_id": default_app_id,
        "auth_code": default_auth_code,
        "user_product_info": default_user_product_info,
    }
    for key, default_value in defaults.items():
        if auth_env.get(key):
            resolved_auth[key] = auth_env[key]
            auth_source = "env"
        elif redis_auth.get(key):
            resolved_auth[key] = redis_auth[key]
            if auth_source != "env":
                auth_source = f"redis-hash:{auth_key}"
        else:
            resolved_auth[key] = default_value

    return CtpConnectionSettings(
        front=front,
        front_source=front_source,
        front_candidates=front_candidates,
        broker_id=resolved_auth["broker_id"],
        user_id=resolved_auth["user_id"],
        password=resolved_auth["password"],
        app_id=resolved_auth["app_id"],
        auth_code=resolved_auth["auth_code"],
        user_product_info=resolved_auth["user_product_info"],
        auth_source=auth_source,
        redis_error=redis_error,
    )


def resolve_ctp_front(default_front: str) -> Tuple[str, str, List[str]]:
    settings = resolve_ctp_connection(default_front)
    return settings.front, settings.front_source, settings.front_candidates

