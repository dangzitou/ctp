#!/usr/bin/env python3
from __future__ import annotations

import fnmatch
import os
from functools import lru_cache
from pathlib import Path

from .common import REPO_ROOT, read_json


DEFAULT_POLICY_PATH = "tools/ai_review/policy.json"


@lru_cache(maxsize=1)
def load_policy() -> dict:
    policy_path = os.getenv("AI_REVIEW_POLICY_FILE", "").strip() or DEFAULT_POLICY_PATH
    full_path = REPO_ROOT / policy_path
    payload = read_json(full_path)
    rules = payload.get("rules")
    if not isinstance(rules, list) or not rules:
        raise RuntimeError(f"AI review policy is invalid: {policy_path}")
    return payload


def _normalize(path: str) -> str:
    return path.replace("\\", "/").strip()


def _default_decision() -> dict:
    policy = load_policy()
    default_risk = str(policy.get("default_risk", "medium_risk"))
    return {
        "rule": "default",
        "risk": default_risk,
        "review_allowed": True,
        "auto_fix_allowed": False,
        "auto_merge_allowed": False,
        "gates": [],
    }


def decision_for_path(path: str) -> dict:
    normalized = _normalize(path)
    decision = _default_decision()
    for rule in load_policy()["rules"]:
        patterns = [str(item) for item in rule.get("patterns", [])]
        if not any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns):
            continue
        decision = {
            "rule": str(rule.get("name", "unnamed")),
            "risk": str(rule.get("risk", decision["risk"])),
            "review_allowed": bool(rule.get("review_allowed", True)),
            "auto_fix_allowed": bool(rule.get("auto_fix_allowed", False)),
            "auto_merge_allowed": bool(rule.get("auto_merge_allowed", False)),
            "gates": [str(item) for item in rule.get("gates", [])],
        }
        break
    return {"path": normalized, **decision}


def assess_paths(paths: list[str]) -> dict:
    normalized_paths = [_normalize(path) for path in paths if _normalize(path)]
    path_decisions = [decision_for_path(path) for path in normalized_paths]
    priority = {str(key): int(value) for key, value in load_policy().get("risk_priority", {}).items()}
    highest = "low_risk"
    highest_score = -1
    for item in path_decisions:
        score = priority.get(item["risk"], 0)
        if score > highest_score:
            highest = item["risk"]
            highest_score = score
    blocked_auto_fix = [item["path"] for item in path_decisions if not item["auto_fix_allowed"]]
    blocked_auto_merge = [item["path"] for item in path_decisions if not item["auto_merge_allowed"]]
    gates: list[str] = []
    for item in path_decisions:
        for gate in item.get("gates", []):
            if gate not in gates:
                gates.append(gate)
    return {
        "paths": path_decisions,
        "risk_level": highest if path_decisions else load_policy().get("default_risk", "medium_risk"),
        "review_allowed": all(item["review_allowed"] for item in path_decisions) if path_decisions else True,
        "auto_fix_allowed": all(item["auto_fix_allowed"] for item in path_decisions) if path_decisions else False,
        "auto_merge_allowed": all(item["auto_merge_allowed"] for item in path_decisions) if path_decisions else False,
        "blocked_auto_fix_paths": blocked_auto_fix,
        "blocked_auto_merge_paths": blocked_auto_merge,
        "gates": gates,
    }


def should_auto_fix_path(path: str) -> bool:
    return bool(decision_for_path(path)["auto_fix_allowed"])


def should_review_path(path: str) -> bool:
    return bool(decision_for_path(path)["review_allowed"])
