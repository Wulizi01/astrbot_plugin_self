"""Tests for the panel API and the migration tool.

Both used to be untested; the migration one only blew up on ``--apply``.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.store import SelfStore  # noqa: E402
from page_api import SelfPageApi  # noqa: E402


class StubConfig:
    def __init__(self, values: dict) -> None:
        self.values = values

    def get(self, key: str, default=None):
        return self.values.get(key, default)


class StubPlugin:
    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.store = SelfStore(self.dir / "self.db")
        self.config = StubConfig(
            {
                "enabled": True,
                "advisor_mode": "current_provider",
                "advisor_scope": "both",
                "advisor_enabled": True,
            }
        )
        self.routes: dict[str, object] = {}
        self.context = SimpleNamespace(register_web_api=self._register)
        self.asked: list[str] = []

    def _register(self, path, handler, methods=None, desc=None) -> None:
        self.routes[path] = handler

    def _cfg(self, key, default=None):
        return self.config.get(key, default)

    async def consult(self, question: str, *, source: str = "manual") -> str:
        self.asked.append(question)
        return f"回答：{question}"


class PageApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = StubPlugin()
        self.api = SelfPageApi(self.plugin)
        self.plugin.store.set_profile(narrative="测试叙事", samples=7)
        self.plugin.store.touch_person("1", "甲")
        self.plugin.store.touch_person("2", "乙")
        self.plugin.store.log_advisor("route", "q", "a", True, True, 120)

    def run_async(self, coro):
        return asyncio.run(coro)

    def test_routes_are_registered(self):
        self.api.register_routes()
        for name in ("overview", "people", "advisor/log", "advisor/test", "reset"):
            self.assertIn(f"/astrbot_plugin_self/page/{name}", self.plugin.routes)

    def test_overview_shape(self):
        payload = self.run_async(self.api.overview())
        self.assertTrue(payload["success"])
        data = payload["data"]
        for key in ("narrative", "traits", "episodes", "memories", "people", "advisor"):
            self.assertIn(key, data)
        self.assertEqual(data["samples"], 7)
        self.assertEqual(data["people"], 2)
        self.assertEqual(data["advisor"]["calls"], 1)

    def test_people_list(self):
        payload = self.run_async(self.api.people())
        self.assertEqual(len(payload["data"]["items"]), 2)

    def test_advisor_log(self):
        payload = self.run_async(self.api.advisor_log())
        self.assertEqual(len(payload["data"]["items"]), 1)

    def test_people_count_is_not_capped(self):
        for index in range(250):
            self.plugin.store.touch_person(str(1000 + index), f"人{index}")
        payload = self.run_async(self.api.overview())
        self.assertEqual(payload["data"]["people"], 252)

    def test_reset_clears_narrative_only(self):
        self.plugin.store.add_memory("1", "甲", "group", "你好", "low", 1, group_id="9")
        payload = self.run_async(self.api.reset())
        self.assertTrue(payload["success"])
        profile = self.plugin.store.profile()
        self.assertEqual(profile["narrative"], "")
        self.assertEqual(profile["samples"], 0)
        self.assertEqual(self.plugin.store.memory_count(), 1)


class MigrateTests(unittest.TestCase):
    """Exercise tools/migrate.py against a fake AstrBot data tree."""

    def build_tree(self) -> tuple[Path, Path]:
        base = Path(tempfile.mkdtemp())
        data = base / "AstrBot" / "data"
        plugin_data = data / "plugin_data"
        (plugin_data / "astrbot_plugin_plastic_persona").mkdir(parents=True)
        (plugin_data / "astrbot_plugin_private_memory").mkdir(parents=True)
        profile = {
            "__self__": {
                "created_at": 1793040238.0,
                "samples": 147,
                "traits": {"verbosity": 0.29, "warmth": 0.38, "emoji": 0.1},
                "self_narrative": "被指出记错之后，我学会了先对一遍再开口。",
                "episodes": [
                    {"at": 1793040300.0, "role": "bot", "text": "第一段经历"},
                    {"at": 1793040400.0, "role": "user", "text": "第二段经历"},
                ],
            }
        }
        (plugin_data / "astrbot_plugin_plastic_persona" / "profiles.json").write_text(
            json.dumps(profile, ensure_ascii=False), encoding="utf-8"
        )
        db = plugin_data / "astrbot_plugin_private_memory" / "private_memory.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE memories(id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "speaker_id TEXT,speaker_name TEXT,scope TEXT,text TEXT,"
            "sensitivity TEXT,shareable INTEGER,created_at REAL)"
        )
        conn.execute(
            "INSERT INTO memories(speaker_id,speaker_name,scope,text,sensitivity,shareable,created_at)"
            " VALUES('1','甲','group','旧记忆','low',1,1793000000.0)"
        )
        conn.commit()
        conn.close()
        return base, plugin_data

    def load_module(self, plugin_data: Path):
        import importlib.util

        source = ROOT / "tools" / "migrate.py"
        spec = importlib.util.spec_from_file_location("migrate_mod", source)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        module.PLUGIN_DATA = plugin_data
        return module

    def test_apply_imports_narrative_and_sets_reflection_marker(self):
        _, plugin_data = self.build_tree()
        module = self.load_module(plugin_data)
        profile = module.plan_profile()
        db_path = plugin_data / "astrbot_plugin_self" / "self.db"
        db_path.parent.mkdir(parents=True)
        SelfStore(db_path)
        module.apply(profile, [], db_path, with_memories=False)

        store = SelfStore(db_path)
        values = store.profile()
        self.assertEqual(values["samples"], 147)
        # Without this, the first reply would rewrite the imported narrative.
        self.assertEqual(values["last_reflection"], 147)
        self.assertEqual(values["born_at"], 1793040238.0)
        self.assertIn("学会了先对一遍", values["narrative"])
        self.assertEqual(store.episode_count(), 2)

    def test_apply_is_idempotent_for_episodes(self):
        _, plugin_data = self.build_tree()
        module = self.load_module(plugin_data)
        profile = module.plan_profile()
        db_path = plugin_data / "astrbot_plugin_self" / "self.db"
        db_path.parent.mkdir(parents=True)
        SelfStore(db_path)
        module.apply(profile, [], db_path, with_memories=False)
        module.apply(profile, [], db_path, with_memories=False)
        self.assertEqual(SelfStore(db_path).episode_count(), 2)

    def test_memories_are_skipped_by_default(self):
        _, plugin_data = self.build_tree()
        module = self.load_module(plugin_data)
        profile = module.plan_profile()
        memories = module.plan_memories()
        db_path = plugin_data / "astrbot_plugin_self" / "self.db"
        db_path.parent.mkdir(parents=True)
        SelfStore(db_path)
        result = module.apply(profile, memories, db_path, with_memories=False)
        self.assertEqual(result["memories"], 0)
        self.assertEqual(SelfStore(db_path).memory_count(), 0)

    def test_memories_are_marked_legacy_when_requested(self):
        _, plugin_data = self.build_tree()
        module = self.load_module(plugin_data)
        profile = module.plan_profile()
        memories = module.plan_memories()
        db_path = plugin_data / "astrbot_plugin_self" / "self.db"
        db_path.parent.mkdir(parents=True)
        SelfStore(db_path)
        result = module.apply(profile, memories, db_path, with_memories=True)
        self.assertEqual(result["memories"], 1)
        store = SelfStore(db_path)
        rows = store.find_memories("甲", 10)
        self.assertEqual(rows[0]["scope"], "legacy")
        self.assertEqual(rows[0]["shareable"], 0)


class TriggerPolicyTests(unittest.TestCase):
    def test_off_never(self):
        from core import advisor

        self.assertFalse(
            advisor.should_consult(
                "off", hostile=True, explicit=True, keyword_hit=True
            )
        )

    def test_hostile_only(self):
        from core import advisor

        self.assertTrue(
            advisor.should_consult(
                "hostile_only", hostile=True, explicit=False, keyword_hit=False
            )
        )
        self.assertFalse(
            advisor.should_consult(
                "hostile_only", hostile=False, explicit=True, keyword_hit=True
            )
        )

    def test_addressed_is_legacy_alias_of_explicit(self):
        from core import advisor

        self.assertTrue(
            advisor.should_consult(
                "addressed", hostile=False, explicit=True, keyword_hit=False
            )
        )
        self.assertFalse(
            advisor.should_consult(
                "addressed", hostile=False, explicit=False, keyword_hit=True
            )
        )

    def test_explicit_policy(self):
        from core import advisor

        self.assertTrue(
            advisor.should_consult(
                "explicit", hostile=True, explicit=False, keyword_hit=False
            )
        )
        self.assertFalse(
            advisor.should_consult(
                "explicit", hostile=False, explicit=False, keyword_hit=True
            )
        )

    def test_keywords_default(self):
        from core import advisor

        self.assertTrue(
            advisor.should_consult(
                "keywords", hostile=False, explicit=False, keyword_hit=True
            )
        )
        self.assertFalse(
            advisor.should_consult(
                "keywords", hostile=False, explicit=False, keyword_hit=False
            )
        )

    def test_always(self):
        from core import advisor

        self.assertTrue(
            advisor.should_consult(
                "always", hostile=False, explicit=False, keyword_hit=False
            )
        )

    def test_probabilistic(self):
        from core import advisor

        self.assertTrue(
            advisor.should_consult(
                "probabilistic", hostile=False, explicit=False, keyword_hit=False,
                probability=0.5, roll=0.2,
            )
        )
        self.assertFalse(
            advisor.should_consult(
                "probabilistic", hostile=False, explicit=False, keyword_hit=False,
                probability=0.5, roll=0.9,
            )
        )
        # Explicit requests always go through, regardless of the dice.
        self.assertTrue(
            advisor.should_consult(
                "probabilistic", hostile=False, explicit=True, keyword_hit=False,
                probability=0.1, roll=0.99,
            )
        )


class PrivateScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SelfStore(Path(tempfile.mkdtemp()) / "self.db")

    def test_private_query_includes_group_rows_from_shared_group(self):
        self.store.add_memory("B", "B", "group", "群里的公开话", "low", 1, "100")
        self.store.add_memory("A", "A", "group", "我也在群里", "low", 1, "100")
        rows = self.store.find_memories_for_private("B", "A")
        self.assertTrue(any(row["text"] == "群里的公开话" for row in rows))

    def test_private_query_excludes_group_rows_from_other_groups(self):
        self.store.add_memory("B", "B", "group", "别群的话", "low", 1, "999")
        self.store.add_memory("A", "A", "group", "我在 100 群", "low", 1, "100")
        rows = self.store.find_memories_for_private("B", "A")
        self.assertFalse(any(row["text"] == "别群的话" for row in rows))

    def test_private_query_keeps_private_rows(self):
        self.store.add_memory("B", "B", "private", "私聊的话", "low", 0)
        rows = self.store.find_memories_for_private("B", "C")
        self.assertTrue(any(row["text"] == "私聊的话" for row in rows))

    def test_private_query_drops_non_shareable_group_rows(self):
        self.store.add_memory("B", "B", "group", "敏感的话", "high", 0, "100")
        self.store.add_memory("A", "A", "group", "我在群里", "low", 1, "100")
        rows = self.store.find_memories_for_private("B", "A")
        self.assertFalse(any(row["text"] == "敏感的话" for row in rows))


class AdvisorSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = StubPlugin()
        self.api = SelfPageApi(self.plugin)

    def run_async(self, coro):
        return asyncio.run(coro)

    def test_settings_masks_api_key(self):
        self.plugin.config.values["api_key"] = "sk-secret"
        payload = self.run_async(self.api.advisor_settings())
        self.assertEqual(payload["data"]["values"]["api_key"], "")
        self.assertTrue(payload["data"]["has_key"])

    def test_settings_shape(self):
        payload = self.run_async(self.api.advisor_settings())
        for key in ("advisor_mode", "advisor_scope", "advisor_trigger_policy"):
            self.assertIn(key, payload["data"]["values"])

    def test_settings_fall_back_to_schema_defaults(self):
        # StubConfig only holds four keys; the rest must come from the schema,
        # otherwise the form renders empty in a fresh install.
        payload = self.run_async(self.api.advisor_settings())
        values = payload["data"]["values"]
        self.assertEqual(values["advisor_temperature"], 0.6)
        self.assertEqual(values["advisor_trigger_policy"], "keywords")
        self.assertEqual(values["advisor_max_tokens"], 800)

    def test_settings_exposes_ranges_for_the_form(self):
        payload = self.run_async(self.api.advisor_settings())
        data = payload["data"]
        self.assertIn("ranges", data)
        self.assertIn("types", data)
        low, high = data["ranges"]["advisor_per_hour"]
        self.assertLess(low, high)
        self.assertEqual(data["types"]["advisor_per_hour"], "int")

    def test_settings_normalises_addressed(self):
        self.plugin.config.values["advisor_trigger_policy"] = "addressed"
        payload = self.run_async(self.api.advisor_settings())
        self.assertEqual(payload["data"]["values"]["advisor_trigger_policy"], "explicit")

    def test_coerce_accepts_normal_values(self):
        applied, error = self.api._coerce_settings(
            {"advisor_temperature": 0.8, "advisor_per_hour": 5, "advisor_scope": "group"}
        )
        self.assertEqual(error, "")
        self.assertEqual(applied["advisor_temperature"], 0.8)
        self.assertEqual(applied["advisor_per_hour"], 5)

    def test_coerce_skips_empty_numbers(self):
        # Clearing a numeric field must keep the old value, not write 0.
        applied, error = self.api._coerce_settings(
            {"advisor_per_hour": "", "advisor_temperature": "  "}
        )
        self.assertEqual(error, "")
        self.assertEqual(applied, {})

    def test_coerce_rejects_garbage(self):
        applied, error = self.api._coerce_settings({"advisor_timeout": "abc"})
        self.assertEqual(applied, {})
        self.assertIn("不合法", error)

    def test_coerce_clamps_ranges(self):
        applied, _ = self.api._coerce_settings(
            {"advisor_per_hour": -1, "advisor_temperature": 99}
        )
        self.assertEqual(applied["advisor_per_hour"], 0)
        self.assertEqual(applied["advisor_temperature"], 2.0)

    def test_coerce_keeps_key_only_when_provided(self):
        applied, _ = self.api._coerce_settings({"api_key": ""})
        self.assertNotIn("api_key", applied)
        applied, _ = self.api._coerce_settings({"api_key": "sk-new"})
        self.assertEqual(applied["api_key"], "sk-new")


if __name__ == "__main__":
    unittest.main(verbosity=2)
