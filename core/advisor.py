"""Advisor layer: decide when to ask, call the model, and enforce budgets."""

from __future__ import annotations

import asyncio
import time
from typing import Any

# aiohttp is imported lazily inside call_api so the module can be unit-tested
# in environments that do not ship it.

DEFAULT_HIT_WORDS = ("你不行", "你好菜", "你真菜", "你傻", "你蠢", "你闭嘴", "你滚")
DEFAULT_ABOUT_WORDS = ("bot", "机器人", "你", "这货", "人工智障")
DEFAULT_INSULT_WORDS = ("垃圾", "废物", "骗子", "傻", "蠢", "智障", "没用的东西")
DEFAULT_ASK_WORDS = ("方案", "分析", "风险", "为什么", "怎么办", "怎么", "如何", "对比")


def _split(raw: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    items = [item.strip() for item in str(raw or "").replace("，", ",").split(",")]
    items = [item for item in items if item]
    return tuple(items) if items else fallback


class Budget:
    """Per-session rate limiting for advisor calls."""

    def __init__(self) -> None:
        self._hourly: dict[str, list[float]] = {}
        self._daily: dict[str, list[float]] = {}
        self._last: dict[str, float] = {}

    def allow(
        self,
        key: str,
        *,
        cooldown: int,
        per_hour: int,
        per_day: int = 0,
        ignore_cooldown: bool = False,
    ) -> bool:
        now = time.time()
        hourly = [stamp for stamp in self._hourly.get(key, []) if now - stamp < 3600]
        daily = [stamp for stamp in self._daily.get(key, []) if now - stamp < 86400]
        last = self._last.get(key, 0.0)
        if not ignore_cooldown and cooldown and last and now - last < cooldown:
            self._hourly[key] = hourly
            self._daily[key] = daily
            return False
        if per_hour and len(hourly) >= per_hour:
            self._hourly[key] = hourly
            self._daily[key] = daily
            return False
        if per_day and len(daily) >= per_day:
            self._hourly[key] = hourly
            self._daily[key] = daily
            return False
        hourly.append(now)
        daily.append(now)
        self._hourly[key] = hourly
        self._daily[key] = daily
        self._last[key] = now
        self._prune()
        return True

    def refund(self, key: str, keep_cooldown: bool = True) -> None:
        """Give back the reserved quota after a failed call.

        The cooldown timestamp is kept by default: a failing advisor must not
        be retried on every incoming message.
        """
        for bucket in (self._hourly, self._daily):
            stamps = bucket.get(key)
            if stamps:
                stamps.pop()
                if not stamps:
                    bucket.pop(key, None)
        if keep_cooldown:
            # Push the last attempt forward so the cooldown window still runs.
            self._last[key] = time.time()
        else:
            self._last.pop(key, None)

    def _prune(self) -> None:
        now = time.time()
        for bucket, window in ((self._hourly, 3600), (self._daily, 86400)):
            stale = [
                key
                for key, stamps in bucket.items()
                if not stamps or now - stamps[-1] > window
            ]
            for key in stale:
                bucket.pop(key, None)

    def daily_used(self, key: str) -> int:
        now = time.time()
        return len([stamp for stamp in self._daily.get(key, []) if now - stamp < 86400])


def is_hostile(text: str, hit_words: str = "", about: str = "", insults: str = "") -> bool:
    text = str(text or "")
    hits = _split(hit_words, DEFAULT_HIT_WORDS)
    if any(word in text for word in hits):
        return True
    about_words = _split(about, DEFAULT_ABOUT_WORDS)
    insult_words = _split(insults, DEFAULT_INSULT_WORDS)
    return any(word in text for word in about_words) and any(
        word in text for word in insult_words
    )


def should_consult(
    policy: str,
    *,
    hostile: bool,
    explicit: bool,
    keyword_hit: bool,
    probability: float = 1.0,
    roll: float = 0.0,
) -> bool:
    """Decide whether this turn should consult the advisor.

    Policies:
        off           never consult
        hostile_only  only when the message attacks the bot
        addressed     when the bot is addressed or attacked
        keywords      attacks, explicit requests, or keyword hits
        always        every eligible message (subject to budget)
        probabilistic explicit requests and a random share of the rest
    """
    policy = str(policy or "keywords").strip().lower()
    if policy == "off":
        return False
    if policy == "hostile_only":
        return hostile
    # ``addressed`` is a legacy alias: on_llm_request only fires when the bot is
    # about to reply, so "addressed" cannot mean anything wider than "explicit".
    if policy in ("addressed", "explicit"):
        return hostile or explicit
    if policy == "always":
        return True
    if policy == "probabilistic":
        if hostile or explicit:
            return True
        return roll < max(0.0, min(1.0, probability))
    return hostile or explicit or keyword_hit


def wants_advice(text: str, ask_words: str = "") -> bool:
    """Keyword-based hint that the user wants a second opinion."""
    text = str(text or "")
    if text.startswith(("问顾问", "找顾问", "让顾问", "咨询顾问", "用顾问")):
        return True
    words = _split(ask_words, DEFAULT_ASK_WORDS)
    return any(word in text for word in words)


async def call_provider(
    provider: Any,
    *,
    question: str,
    history: list[dict[str, str]],
    system_prompt: str,
    timeout: int,
) -> str:
    """Ask through an AstrBot provider object."""
    if provider is None:
        raise RuntimeError("没有可用的文本模型")
    response = await asyncio.wait_for(
        provider.text_chat(
            prompt=question,
            contexts=history,
            system_prompt=system_prompt,
            session_id=None,
            persist=False,
        ),
        timeout=timeout,
    )
    text = str(getattr(response, "completion_text", "") or response).strip()
    if not text:
        raise RuntimeError("模型没有返回内容")
    return text


async def call_api(
    *,
    base: str,
    key: str,
    model: str,
    question: str,
    history: list[dict[str, str]],
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    retries: int = 1,
) -> str:
    """Ask through an OpenAI-compatible endpoint."""
    import aiohttp  # local import keeps this module importable without it

    base = str(base or "").rstrip("/")
    if not key or not base or not model:
        raise RuntimeError("API 模式需要 api_base、api_key、api_model")
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": question})
    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": max(64, int(max_tokens)),
        "stream": False,
    }
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as session:
                async with session.post(
                    f"{base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                ) as response:
                    body = await response.text()
                    if response.status == 401:
                        raise RuntimeError("API 鉴权失败（key 无效或过期）")
                    if response.status == 429:
                        raise RuntimeError("API 限流或额度不足")
                    if response.status >= 400:
                        raise RuntimeError(f"API {response.status}: {body[:200]}")
                    data = await response.json()
            text = str(data["choices"][0]["message"]["content"] or "").strip()
            if not text:
                raise RuntimeError("API 返回空内容")
            return text
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < retries:
                await asyncio.sleep(1.5)
    raise RuntimeError(str(last_error or "API 调用失败"))
