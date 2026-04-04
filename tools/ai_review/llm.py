#!/usr/bin/env python3
from __future__ import annotations

import os


def model_for(var_name: str, default: str) -> str:
    return os.getenv(var_name, "").strip() or default


def create_client():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("`OPENAI_API_KEY` is missing. Configure `MINIMAX_API_KEY` in GitHub secrets.")

    from openai import OpenAI

    base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def request_markdown(system_prompt: str, user_prompt: str, model: str) -> str:
    client = create_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )
    message = response.choices[0].message.content if response.choices else ""
    content = (message or "").strip()
    if not content:
        raise RuntimeError("The model response was empty.")
    return content


def request_text(system_prompt: str, user_prompt: str, model: str, temperature: float = 0.2) -> str:
    client = create_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    message = response.choices[0].message.content if response.choices else ""
    content = (message or "").strip()
    if not content:
        raise RuntimeError("The model response was empty.")
    return content
