"""Panel API for the merged self plugin.

Routes are registered under ``/<plugin>/page/*`` and consumed by the bundled
page through ``AstrBotPluginPage.apiGet/apiPost``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

try:
    from astrbot.api import logger
except Exception:  # running the tests outside AstrBot (CI)
    import logging

    logger = logging.getLogger("astrbot_plugin_self")

PLUGIN_NAME = "astrbot_plugin_self"
PAGE_API_PREFIX = f"/{PLUGIN_NAME}/page"

SENSITIVE_KEYS = {"api_key"}
EDITABLE_KEYS = [
    "advisor_enabled",
    "advisor_mode",
    "api_base",
    "api_key",
    "api_model",
    "advisor_provider_id",
    "advisor_prompt",
    "advisor_temperature",
    "advisor_max_tokens",
    "advisor_timeout",
    "advisor_scope",
    "advisor_cooldown",
    "advisor_per_hour",
    "advisor_per_day",
    "advisor_trigger_policy",
    "advisor_trigger_probability",
    "advisor_route_timeout",
    "advisor_max_chars",
]
SCHEMA_TYPES = {
    "advisor_enabled": "bool",
    "advisor_mode": "string",
    "api_base": "string",
    "api_key": "string",
    "api_model": "string",
    "advisor_provider_id": "string",
    "advisor_prompt": "text",
    "advisor_temperature": "float",
    "advisor_max_tokens": "int",
    "advisor_timeout": "int",
    "advisor_scope": "string",
    "advisor_cooldown": "int",
    "advisor_per_hour": "int",
    "advisor_per_day": "int",
    "advisor_trigger_policy": "string",
    "advisor_trigger_probability": "float",
    "advisor_route_timeout": "int",
    "advisor_max_chars": "int",
}
RANGES = {
    "advisor_temperature": (0.0, 2.0),
    "advisor_max_tokens": (64, 8192),
    "advisor_timeout": (10, 600),
    "advisor_cooldown": (0, 3600),
    "advisor_per_hour": (0, 100),
    "advisor_per_day": (0, 1000),
    "advisor_trigger_probability": (0.0, 1.0),
    "advisor_route_timeout": (3, 60),
    "advisor_max_chars": (200, 4000),
}


class SelfPageApi:
    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin

    def register_routes(self) -> None:
        register = getattr(self.plugin.context, "register_web_api", None)
        if not callable(register):
            return
        routes = [
            ("/overview", self.overview, ["GET"], "自我概览"),
            ("/people", self.people, ["GET"], "认识的人"),
            ("/person", self.person_detail, ["GET"], "某个人的画像"),
            ("/person/notes", self.save_person_notes, ["POST"], "保存备注"),
            ("/advisor/log", self.advisor_log, ["GET"], "顾问调用记录"),
            ("/advisor/test", self.advisor_test, ["POST"], "测试顾问连接"),
            ("/advisor/settings", self.advisor_settings, ["GET"], "顾问设置"),
            ("/advisor/settings/save", self.save_advisor_settings, ["POST"], "保存顾问设置"),
            ("/reset", self.reset, ["POST"], "重置自我叙事"),
        ]
        for path, handler, methods, desc in routes:
            register(f"{PAGE_API_PREFIX}{path}", handler, methods, desc)

    @staticmethod
    def _ok(data: Any = None) -> dict[str, Any]:
        return {"success": True, "data": data, "ts": int(time.time())}

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return {"success": False, "error": str(message), "ts": int(time.time())}

    # ------------------------------------------------------------------ routes

    async def overview(self):
        try:
            plugin = self.plugin
            profile = plugin.store.profile()
            traits = plugin.store.profile()
            stats = plugin.store.advisor_stats()
            return self._ok(
                {
                    "enabled": bool(plugin._cfg("enabled", True)),
                    "narrative": str(profile.get("narrative") or ""),
                    "samples": int(profile.get("samples") or 0),
                    "days": max(
                        1,
                        int(
                            (time.time() - float(profile.get("born_at") or time.time()))
                            / 86400
                        )
                        + 1,
                    ),
                    "traits": {
                        "verbosity": round(float(traits.get("verbosity") or 0), 3),
                        "warmth": round(float(traits.get("warmth") or 0), 3),
                        "emoji": round(float(traits.get("emoji") or 0), 3),
                        "initiative": round(float(traits.get("initiative") or 0), 3),
                    },
                    "episodes": plugin.store.episode_count(),
                    "memories": plugin.store.memory_count(),
                    "people": plugin.store.count_people(),
                    "catchphrases": plugin.store.top_catchphrases(6),
                    "advisor": {
                        **stats,
                        "mode": str(plugin._cfg("advisor_mode", "current_provider") or ""),
                        "scope": str(plugin._cfg("advisor_scope", "both") or ""),
                        "enabled": bool(plugin._cfg("advisor_enabled", True)),
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[self] overview failed: %s", exc)
            return self._error(exc)

    async def people(self):
        try:
            rows = self.plugin.store.list_people(50)
            return self._ok({"items": rows})
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)

    async def person_detail(self):
        try:
            from quart import request

            user_id = str(request.args.get("user_id") or "").strip()
            if not user_id:
                return self._error("缺少 user_id")
            detail = self.plugin.store.person_detail(user_id)
            if not detail:
                return self._error("没有这个人")
            return self._ok(detail)
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)

    async def save_person_notes(self):
        try:
            from quart import request

            body = await request.get_json(silent=True) or {}
            user_id = str(body.get("user_id") or "").strip()
            if not user_id:
                return self._error("缺少 user_id")
            ok, payload = self.plugin.store.set_person_notes(
                user_id, str(body.get("notes") or "")
            )
            if not ok:
                return self._error(payload)
            return self._ok({"user_id": user_id, "notes": payload})
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)

    async def advisor_log(self):
        try:
            rows = self.plugin.store.recent_advisor(20)
            return self._ok({"items": rows})
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)

    async def advisor_test(self):
        try:
            from quart import request

            body = await request.get_json(silent=True) or {}
            question = str(body.get("question") or "用一个词回答：在线").strip()
            started = time.monotonic()
            answer, _ = await self.plugin.consult(question, source="page")
            return self._ok(
                {
                    "answer": answer,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                }
            )
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)

    async def advisor_settings(self):
        try:
            plugin = self.plugin
            defaults = self._schema_defaults()
            values = {}
            for key in EDITABLE_KEYS:
                if key in SENSITIVE_KEYS:
                    values[key] = ""
                    continue
                default = defaults.get(key)
                value = plugin._cfg(key)
                if value is None:
                    value = default
                if key == "advisor_trigger_policy" and value == "addressed":
                    value = "explicit"  # legacy alias, normalise for the panel
                values[key] = value
            return self._ok(
                {
                    "values": values,
                    "has_key": bool(str(plugin._cfg("api_key", "") or "").strip()),
                    "keys": EDITABLE_KEYS,
                    "ranges": {k: list(v) for k, v in RANGES.items()},
                    "types": SCHEMA_TYPES,
                }
            )
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)

    def _schema_defaults(self) -> dict[str, Any]:
        path = Path(__file__).with_name("_conf_schema.json")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[self] read schema defaults failed: %s", exc)
            return {}
        return {
            key: item.get("default")
            for key, item in data.items()
            if isinstance(item, dict)
        }

    def _coerce_settings(self, values: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """Coerce incoming settings, skipping blanks and clamping ranges.

        Args:
            values: Raw key/value pairs from the panel.

        Returns:
            A tuple of (applied values, error message). The error is empty on
            success; on failure nothing should be written.
        """
        applied: dict[str, Any] = {}
        for key, raw in values.items():
            if key not in EDITABLE_KEYS:
                continue
            if key in SENSITIVE_KEYS:
                if not str(raw or "").strip():
                    continue  # empty means "keep the current key"
                applied[key] = str(raw)
                continue
            kind = SCHEMA_TYPES.get(key, "string")
            if kind in ("int", "float"):
                text = str(raw if raw is not None else "").strip()
                if text == "":
                    continue  # empty means "keep the current value"
                try:
                    value = int(float(text)) if kind == "int" else float(text)
                except (TypeError, ValueError):
                    return {}, f"{key} 的值不合法"
                low, high = RANGES.get(key, (None, None))
                if low is not None:
                    value = max(low, value)
                if high is not None:
                    value = min(high, value)
            elif kind == "bool":
                value = bool(raw)
            else:
                value = str(raw)
            applied[key] = value
        return applied, ""

    async def save_advisor_settings(self):
        try:
            from quart import request

            body = await request.get_json(silent=True) or {}
            values = body.get("values") if isinstance(body.get("values"), dict) else body
            plugin = self.plugin
            applied, error = self._coerce_settings(values)
            if error:
                return self._error(error)
            target = getattr(plugin, "config", None)
            if target is None:
                return self._error("配置对象不可用")
            for key, value in applied.items():
                try:
                    target[key] = value
                except Exception:  # noqa: BLE001
                    setattr(target, key, value)
            saved = False
            for name in ("save_config", "save"):
                method = getattr(target, name, None)
                if callable(method):
                    try:
                        method()
                        saved = True
                        break
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[self] save config failed: %s", exc)
                        continue
            if not saved:
                logger.warning("[self] advisor settings applied but not persisted")
            public = {k: v for k, v in applied.items() if k not in SENSITIVE_KEYS}
            return self._ok({"applied": public, "saved": saved})
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)

    async def reset(self):
        try:
            self.plugin.store.reset_narrative()
            return self._ok({"ok": True})
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)
