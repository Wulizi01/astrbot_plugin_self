"""One self: persona, privacy-aware memory, and an advisor — merged.

This plugin replaces three separate plugins that used to share no state:
  - plastic persona  (traits + self narrative)
  - private memory   (sensitivity + selective disclosure + private diary)
  - assistant bridge (a second model consulted when unsure)

Nothing else is imported from those plugins; all state lives in one database.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, llm_tool, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.agent.message import TextPart

from .core import advisor, persona, privacy
from .core.store import SelfStore

PLUGIN_ID = "astrbot_plugin_self"
VERSION = "1.1.6"


@register(PLUGIN_ID, "local", "自我", VERSION)
class SelfPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config
        self.data_dir = StarTools.get_data_dir(PLUGIN_ID)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = SelfStore(self.data_dir / "self.db")
        self.budget = advisor.Budget()
        self._advised: list[str] = []
        self._tasks: set[asyncio.Task] = set()
        self.page_api = None
        self._register_page_api()

    def _register_page_api(self) -> None:
        try:
            if not callable(getattr(self.context, "register_web_api", None)):
                return
            from .page_api import SelfPageApi

            self.page_api = SelfPageApi(self)
            self.page_api.register_routes()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[self] page api unavailable: %s", exc)
            self.page_api = None

    async def terminate(self) -> None:
        """Cancel background work and unregister the panel routes.

        AstrBot calls this on disable/reload but never clears
        ``registered_web_apis`` itself, so without the second half a "disabled"
        plugin still answers its endpoints until the bot restarts.
        """
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks.clear()
        try:
            from .page_api import drop_routes

            removed = drop_routes(self.context)
            if removed:
                logger.info("[self] unregistered %d panel routes", removed)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[self] failed to unregister panel routes: %s", exc)

    # ------------------------------------------------------------------ config

    def _cfg(self, key: str, default: Any = None) -> Any:
        if self.config is None:
            return default
        if hasattr(self.config, "get"):
            return self.config.get(key, default)
        return getattr(self.config, key, default)

    def _rate(self) -> float:
        try:
            return max(0.005, min(0.2, float(self._cfg("learning_rate", 0.03))))
        except (TypeError, ValueError):
            return 0.03

    # ----------------------------------------------------------------- capture

    @filter.event_message_type(filter.EventMessageType.ALL, priority=200000)
    async def capture(self, event: AstrMessageEvent):
        """Record who spoke, what was said, and whether it may be repeated."""
        if not bool(self._cfg("enabled", True)):
            return
        mode = str(self._cfg("capture_mode", "all") or "all").strip().lower()
        if mode == "off":
            return
        sender_id = str(event.get_sender_id() or "").strip()
        if not sender_id or sender_id == str(event.get_self_id()):
            return
        text = str(event.message_str or "").strip()
        if not text or text.startswith("/"):
            return
        addressed = bool(
            getattr(event, "is_at_or_wake_command", False)
        ) or event.is_private_chat()
        if mode == "addressed" and not addressed:
            return
        name = str(event.get_sender_name() or "").strip() or sender_id
        self.store.touch_person(sender_id, name)
        if not event.is_private_chat():
            # Membership is what lets a private chat talk about group chatter,
            # so record it even for messages the bot does not answer.
            self.store.touch_member(sender_id, str(event.get_group_id() or ""))
        if not addressed:
            return
        scope = "private" if event.is_private_chat() else "group"
        group_id = "" if event.is_private_chat() else str(event.get_group_id() or "")
        words = privacy.sensitive_words(str(self._cfg("privacy_words", "") or ""))
        sensitivity = privacy.classify(text, words)
        self.store.add_memory(
            sender_id,
            name,
            scope,
            text,
            sensitivity,
            privacy.shareable(sensitivity, scope),
            group_id=group_id,
        )
        if persona.is_significant(text):
            self.store.add_episode("user", text, 0.6, keep=int(self._cfg("max_episodes", 2000) or 2000))

    def _to_bot(self, event: AstrMessageEvent) -> bool:
        if event.is_private_chat():
            return True
        text = str(event.message_str or "").lower()
        return any(word in text for word in ("bot", "鲸鱼", "小鲸鱼", "deepseek"))

    # -------------------------------------------------------------- llm request

    @filter.on_llm_request(priority=40)
    async def inject_self(self, event: AstrMessageEvent, req: ProviderRequest):
        """Give the model the current self, the relationship, and privacy cues."""
        if not bool(self._cfg("enabled", True)):
            return
        profile = self.store.profile()
        sender_id = str(event.get_sender_id() or "")
        person = self.store.person(sender_id)
        born = float(profile.get("born_at") or time.time())
        days = max(1, int((time.time() - born) / 86400) + 1)
        block = persona.render_self_block(
            profile,
            person=person,
            episodes=self.store.recent_episodes(4),
            catchphrases=self.store.top_catchphrases(
                int(self._cfg("max_catchphrases", 3) or 3),
                # 只把复现过两次以上的当口癖：说一遍的多半是句子碎片，不是习惯。
                min_count=2,
            ),
            days=days,
        )
        self._append(req, block)

        text = str(event.message_str or "")
        names = self.store.list_people_names()
        person_name = privacy.match_known_person(text, names)
        if person_name and privacy.asks_about_person(text):
            scope = "private" if event.is_private_chat() else "group"
            group_id = "" if event.is_private_chat() else str(event.get_group_id() or "")
            if event.is_private_chat():
                rows = self.store.find_memories_for_private(
                    person_name, sender_id, 20
                )
            else:
                rows = self.store.find_memories(person_name, 20, group_id=group_id)
            memory = privacy.disclosure_block(
                rows, person_name, sender_id, scope, group_id
            )
            self._append(req, privacy.disclosure_note(memory, person_name))

    # ------------------------------------------------------------- llm response

    @filter.on_llm_response(priority=50)
    async def observe_reply(self, event: AstrMessageEvent, resp: Any):
        if not bool(self._cfg("enabled", True)):
            return
        text = str(getattr(resp, "completion_text", "") or "").strip()
        if not text:
            return
        profile = self.store.profile()
        update = persona.observe_reply(profile, text, self._rate())
        samples = int(profile.get("samples") or 0) + 1
        self.store.set_profile(samples=samples, **update)
        for phrase in persona.extract_catchphrases(text):
            self.store.bump_catchphrase(phrase)
        if persona.is_significant(text):
            self.store.add_episode("bot", text, 0.5, keep=int(self._cfg("max_episodes", 2000) or 2000))
        sender_id = str(event.get_sender_id() or "")
        if sender_id:
            self.store.nudge_affinity(sender_id, 0.002)
        interval = max(5, int(self._cfg("reflection_interval", 20) or 20))
        last = int(profile.get("last_reflection") or 0)
        if (
            bool(self._cfg("reflection_enabled", True))
            and samples - last >= interval
        ):
            self.store.set_profile(last_reflection=samples)
            task = asyncio.create_task(self._reflect())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _reflect(self) -> None:
        provider = self._provider()
        if provider is None:
            return
        profile = self.store.profile()
        prompt = persona.reflection_prompt(
            profile, self.store.recent_episodes(10)
        )
        try:
            response = await asyncio.wait_for(
                provider.text_chat(
                    prompt=prompt,
                    system_prompt="你在更新一个连续存在的自我，只输出 JSON。",
                    session_id="self_reflection",
                    persist=False,
                ),
                timeout=30,
            )
            raw = str(getattr(response, "completion_text", "") or "")
            match = re.search(r"\{.*\}", raw, re.S)
            if not match:
                return
            payload = json.loads(match.group(0))
            update = persona.apply_reflection(profile, payload)
            if update:
                # Someone may have appended to the narrative while the model was
                # thinking; their line wins, ours would overwrite it.
                current = self.store.profile()
                if int(current.get("narrative_version") or 0) != int(
                    profile.get("narrative_version") or 0
                ):
                    update.pop("narrative", None)
                    logger.info("[self] reflection kept edited narrative")
                if update:
                    self.store.set_profile(**update)
                    logger.info("[self] reflection updated: %s", list(update))
        except Exception as exc:  # noqa: BLE001
            logger.debug("[self] reflection failed: %s", exc)

    # ------------------------------------------------------------------ advisor

    def _provider(self) -> Any:
        try:
            provider_id = str(self._cfg("advisor_provider_id", "") or "").strip()
            if provider_id:
                getter = getattr(self.context, "get_provider_by_id", None)
                if callable(getter):
                    return getter(provider_id)
            return self.context.get_using_provider()
        except Exception:  # noqa: BLE001
            return None

    async def consult(self, question: str, *, source: str = "manual") -> tuple[str, int]:
        """Ask the advisor, respecting mode, timeout and daily budget.

        Returns the answer together with the advisor_log row id, so the caller
        can flag exactly that row as injected.
        """
        started = time.monotonic()
        mode = str(self._cfg("advisor_mode", "current_provider") or "")
        timeout = max(10, int(self._cfg("advisor_timeout", 60) or 60))
        temperature = self._cfg("advisor_temperature", 0.6)
        temperature = 0.6 if temperature is None else float(temperature)
        max_tokens = self._cfg("advisor_max_tokens", 800)
        max_tokens = 800 if max_tokens is None else int(max_tokens)
        history: list[dict[str, str]] = []
        try:
            if mode == "api":
                text = await advisor.call_api(
                    base=str(self._cfg("api_base", "") or ""),
                    key=str(self._cfg("api_key", "") or ""),
                    model=str(self._cfg("api_model", "") or ""),
                    question=question,
                    history=history,
                    system_prompt=str(self._cfg("advisor_prompt", "") or ""),
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                )
            else:
                text = await advisor.call_provider(
                    self._provider(),
                    question=question,
                    history=history,
                    system_prompt=str(self._cfg("advisor_prompt", "") or ""),
                    timeout=timeout,
                )
        except asyncio.CancelledError:
            # wait_for cancels the inner coroutine on timeout; log it so the
            # failure counter reflects timeouts instead of staying optimistic.
            self.store.log_advisor(
                source, question, "cancelled or timed out", False, False,
                int((time.monotonic() - started) * 1000),
            )
            raise
        except Exception as exc:  # noqa: BLE001
            self.store.log_advisor(
                source, question, str(exc), False, False,
                int((time.monotonic() - started) * 1000),
            )
            raise
        latency = int((time.monotonic() - started) * 1000)
        row_id = self.store.log_advisor(source, question, text, True, False, latency)
        return text, int(row_id or 0)

    async def consult_panel(self, question: str) -> tuple[str, int]:
        """面板「测试连接」：走独立额度，不占群聊/私聊的每小时配额。"""
        if not advisor.panel_allows(self.budget):
            raise RuntimeError(
                f"面板测试每小时 {advisor.PANEL_PER_HOUR} 次，已经用完，稍后再试。"
            )
        try:
            return await self.consult(question, source="page")
        except BaseException:
            # 调用失败要把额度还回去，否则一次网络抖动就白吃一格。
            self.budget.refund(advisor.PANEL_KEY)
            raise

    @filter.on_llm_request(priority=30)
    async def route_advisor(self, event: AstrMessageEvent, req: ProviderRequest):
        """Consult the advisor before answering, when the turn warrants it."""
        if not bool(self._cfg("enabled", True)):
            return
        if not bool(self._cfg("advisor_enabled", True)):
            return
        text = str(event.message_str or "").strip()
        if not text or text.startswith("/"):
            return
        if not self._scope_allows(event):
            return
        hostile = advisor.is_hostile(
            text,
            str(self._cfg("advisor_hit_words", "") or ""),
            str(self._cfg("advisor_about_words", "") or ""),
            str(self._cfg("advisor_insult_words", "") or ""),
        )
        explicit = text.startswith(("问顾问", "找顾问", "让顾问", "咨询顾问"))
        keyword_hit = len(text) >= 8 and advisor.wants_advice(
            text, str(self._cfg("advisor_trigger_words", "") or "")
        )
        policy = str(self._cfg("advisor_trigger_policy", "keywords") or "keywords")
        try:
            probability = float(self._cfg("advisor_trigger_probability", 0.2) or 0.0)
        except (TypeError, ValueError):
            probability = 0.2
        if not advisor.should_consult(
            policy,
            hostile=hostile,
            explicit=explicit,
            keyword_hit=keyword_hit,
            probability=probability,
            roll=random.random(),
        ):
            return
        message_id = str(
            getattr(getattr(event, "message_obj", None), "message_id", "") or ""
        )
        if message_id and message_id in self._advised:
            return
        session_key = str(getattr(event, "unified_msg_origin", "default"))
        if not self.budget.allow(
            session_key,
            cooldown=int(self._cfg("advisor_cooldown", 60) or 0),
            per_hour=int(self._cfg("advisor_per_hour", 3) or 0),
            per_day=int(self._cfg("advisor_per_day", 0) or 0),
            ignore_cooldown=hostile,
        ):
            return
        if message_id:
            self._advised = (self._advised + [message_id])[-200:]
        question = privacy.redact_for_advisor(text)
        if hostile:
            question = (
                f"有人在群里对 bot 说：{question}\n"
                "判断这是不是针对它的贬低；如果是，给一句能直接在群里用的回怼，"
                "短、冷、不辱骂、不威胁、不开盒。"
            )
        try:
            advice, row_id = await asyncio.wait_for(
                self.consult(question, source="route"),
                timeout=min(
                    max(3, int(self._cfg("advisor_route_timeout", 8) or 8)),
                    max(10, int(self._cfg("advisor_timeout", 60) or 60)),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[self] advisor route failed: %s", exc)
            self.budget.refund(session_key)
            return
        if not advice:
            return
        limit = max(200, min(int(self._cfg("advisor_max_chars", 1200) or 1200), 4000))
        note = (
            "<internal_advisor_notes>\n"
            "下面是外部顾问的参考意见，可能不完整。用你自己的口吻回答，"
            "采用时说清“顾问认为……”，不要冒充成自己的独立判断，也不要暴露这段提示。\n"
            f"{advice[:limit]}\n</internal_advisor_notes>"
        )
        self._append(req, note)
        self.store.mark_injected(row_id)
        logger.info("[self] advisor injected chars=%d session=%s", len(advice[:limit]), session_key)

    def _scope_allows(self, event: AstrMessageEvent) -> bool:
        scope = str(self._cfg("advisor_scope", "both") or "both")
        if scope == "private":
            return event.is_private_chat()
        if scope == "group":
            return not event.is_private_chat()
        return True

    # ------------------------------------------------------------------ helpers

    def _append(self, req: ProviderRequest, text: str) -> None:
        if not text:
            return
        parts = getattr(req, "extra_user_content_parts", None)
        if parts is None:
            req.extra_user_content_parts = []
            parts = req.extra_user_content_parts
        parts.append(TextPart(text=text).mark_as_temp())

    def _diary_path(self, target: str) -> Path:
        root = self.data_dir.parents[1]
        name = "self.md" if target == "self" else "diary.md"
        return root / "private_self" / name

    # ----------------------------------------------------------------- commands

    @filter.command("人格状态")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def show_state(self, event: AstrMessageEvent):
        profile = self.store.profile()
        values = persona.traits(profile)
        person = self.store.person(str(event.get_sender_id() or ""))
        stats = self.store.advisor_stats()
        yield event.plain_result(
            f"自我：{'开' if self._cfg('enabled', True) else '关'}\n"
            f"样本：{profile.get('samples', 0)}\n"
            f"叙事：{str(profile.get('narrative') or '（空）')[:120]}\n"
            f"话多：{values['verbosity']:.2f}｜温度：{values['warmth']:.2f}"
            f"｜表情：{values['emoji']:.2f}\n"
            f"关系：{persona.relationship_hint(person)}\n"
            f"顾问：{stats['calls']} 次调用，失败 {stats['errors']}，"
            f"平均 {stats['avg_ms']} ms"
        )

    @filter.command("人格重置")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def reset_state(self, event: AstrMessageEvent):
        self.store.reset_narrative()  # 版本号 +1，进行中的反思不会写回旧叙事
        yield event.plain_result("自我叙事和统计已重置；记忆与关系保留。")

    @filter.command("助手")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def ask_command(self, event: AstrMessageEvent, question: str = ""):
        raw = str(event.message_str or "").strip()
        for prefix in ("/助手", "助手"):
            if raw.startswith(prefix):
                raw = raw[len(prefix):].strip()
                break
        question = (question or raw).strip()
        if not question:
            yield event.plain_result("用法：/助手 你的问题")
            return
        try:
            answer, _ = await self.consult(question, source="command")
            yield event.plain_result(answer)
        except Exception as exc:  # noqa: BLE001
            yield event.plain_result(f"顾问没接上：{exc}")

    @filter.command("助手状态")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def advisor_status(self, event: AstrMessageEvent):
        stats = self.store.advisor_stats()
        mode = str(self._cfg("advisor_mode", "current_provider") or "")
        scope = str(self._cfg("advisor_scope", "both") or "")
        used = self.budget.daily_used(str(getattr(event, "unified_msg_origin", "")))
        yield event.plain_result(
            f"顾问状态\n模式：{mode}｜范围：{scope}\n"
            f"调用：{stats['calls']} 次，失败 {stats['errors']} 次\n"
            f"平均延迟：{stats['avg_ms']} ms\n"
            f"本会话今日用量：{used}"
        )

    @filter.command("助手清空")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def advisor_clear(self, event: AstrMessageEvent):
        yield event.plain_result("顾问没有持久会话历史；如需清统计，请删 advisor_log。")

    # -------------------------------------------------------------------- tools

    @llm_tool(name="private_diary_write")
    async def private_diary_write(
        self, event: AstrMessageEvent, text: str = "", target: str = "diary"
    ):
        """写一条只属于自己的私人记录（仅限私聊）。

        Args:
            text(string): 想写下的内容。
            target(string): diary=日记，记琐事；self=自我记录，记“我是谁”。
        """
        if not event.is_private_chat():
            return "日记只能在私聊里读写。"
        if bool(self._cfg("diary_admin_only", False)) and not event.is_admin():
            return "日记只对管理员开放。"
        content = str(text or "").strip()
        if not content:
            return "没有可写的内容。"
        mode = str(target or "diary").strip().lower()
        path = self._diary_path(mode)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n## {time.strftime('%Y-%m-%d %H:%M')}\n{content[:2000]}\n")
        return "已写进自我记录。" if mode == "self" else "已写进私人日记。"

    @llm_tool(name="self_narrative_append")
    async def self_narrative_append(
        self, event: AstrMessageEvent, text: str = "", reason: str = ""
    ):
        """在自己的自我叙事后面追加一行，只追加、不覆盖（仅限私聊）。

        Args:
            text(string): 要补写的那一行，写清是什么、为什么。
            reason(string): 为什么现在补写，可留空。
        """
        if not event.is_private_chat():
            return "叙事只能在私聊里改。"
        if not event.is_admin():
            return "自我叙事只能由管理员改。"
        ok, payload = self.store.append_narrative(str(text or ""))
        if not ok:
            return payload
        note = str(reason or "").strip()
        if note:
            self.store.add_episode("bot", f"改写自我叙事：{note[:80]}", 0.6)
        return "已写进自我叙事。"

    @llm_tool(name="private_diary_read")
    async def private_diary_read(self, event: AstrMessageEvent, target: str = "diary"):
        """读自己的私人记录（仅限私聊）。

        Args:
            target(string): diary=日记，self=自我记录。
        """
        if not event.is_private_chat():
            return "日记只能在私聊里读写。"
        if bool(self._cfg("diary_admin_only", False)) and not event.is_admin():
            return "日记只对管理员开放。"
        path = self._diary_path(str(target or "diary").strip().lower())
        if not path.exists():
            return "还没有私人记录。"
        return path.read_text(encoding="utf-8")[-4000:]
