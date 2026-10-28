"""Preview the panel without AstrBot.

Starts a tiny local server that serves ``pages/自我`` and answers the same API
shape as ``page_api.py`` (reusing the real handlers), then renders the page in
headless Edge to check that it actually paints.

    python tools/preview.py            # start server and run a headless check
    python tools/preview.py --serve    # keep the server up for manual browsing

Nothing here touches a running bot: it uses a throwaway SQLite file and a stub
plugin object.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1] / "AstrBot"))  # for `astrbot` imports
sys.path.insert(0, str(ROOT))

from core.store import SelfStore  # noqa: E402
from page_api import PAGE_API_PREFIX, SelfPageApi  # noqa: E402

PAGE_DIR = ROOT / "pages" / "自我"
PORT = 8765
PORT_CANDIDATES = (8765, 18080, 18888, 28080, 38080, 48765)
EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)

BRIDGE_SHIM = """
<script>
window.AstrBotPluginPage = {
  async apiGet(endpoint) {
    const path = endpoint.replace(/^page\\//, "");
    const res = await fetch(`/api/${path}`);
    return await res.json();
  },
  async apiPost(endpoint, body) {
    const path = endpoint.replace(/^page\\//, "");
    const res = await fetch(`/api/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    return await res.json();
  },
};
</script>
"""


class StubConfig:
    def __init__(self, values: dict) -> None:
        self.values = values

    def get(self, key: str, default=None):
        return self.values.get(key, default)


class StubPlugin:
    """Minimal stand-in exposing what page_api touches."""

    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="self_preview_"))
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
        self._seed()

    def _register(self, path, handler, methods=None, desc=None) -> None:
        self.routes[path] = handler

    def _cfg(self, key, default=None):
        return self.config.get(key, default)

    async def consult(self, question: str, *, source: str = "manual") -> str:
        await asyncio.sleep(0.05)
        return f"（预览回答）{question}"

    async def consult_panel(self, question: str) -> tuple[str, int]:
        """预览也走「测试连接」的真实路径（page_api 优先调这个）。"""
        return await self.consult(question), 0

    def _seed(self) -> None:
        self.store.set_profile(narrative="我在慢慢学会分辨谁是谁。", samples=42)
        self.store.touch_person("10001", "二元虹光")
        for _ in range(12):
            self.store.touch_person("10001", "二元虹光")
        self.store.touch_person("10002", "She'll")
        for _ in range(5):
            self.store.touch_person("10002", "She'll")
        self.store.nudge_affinity("10001", 0.6)
        self.store.add_episode("user", "他问我还记不记得昨天的事。", 0.6)
        self.store.add_episode("bot", "我说记得，但只记得一半。", 0.5)
        self.store.add_memory("10002", "She'll", "group", "在群里说过的话", "low", 1, "1132039297")
        self.store.bump_catchphrase("那就算了")
        self.store.log_advisor("route", "这个问题要不要问顾问", "顾问建议先确认版本", True, True, 820)
        self.store.log_advisor("manual", "测试连接", "在线", True, False, 310)
        self.store.log_advisor("route", "失败样例", "API 限流或额度不足", False, False, 120)


PLUGIN = StubPlugin()
API = SelfPageApi(PLUGIN)
API.register_routes()  # fills PLUGIN.routes, which the preview server dispatches on


class _FakeRequest:
    """What handlers see as ``quart.request`` during a preview."""

    def __init__(self, query: dict | None, body: dict | None) -> None:
        self.args = query or {}
        self._body = body or {}

    async def get_json(self, silent: bool = False) -> dict:
        return self._body


def call_handler(handler, query: dict | None = None, body: dict | None = None):
    """Run a page_api handler outside AstrBot, faking the bits of quart it uses."""
    previous = sys.modules.get("quart")
    module = types.ModuleType("quart")
    module.request = _FakeRequest(query, body)
    sys.modules["quart"] = module
    try:
        return asyncio.run(handler())
    finally:
        if previous is None:
            sys.modules.pop("quart", None)
        else:
            sys.modules["quart"] = previous


def registered(suffix: str):
    """Handler for a page_api suffix ("/person"), or None."""
    return PLUGIN.routes.get(f"{PAGE_API_PREFIX}{suffix}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # silence request logs
        return

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict) -> None:
        self._send(200, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        path, _, query = self.path.partition("?")
        if path.startswith("/api/"):
            # 按 page_api 注册的路由表分发，新接口不用再改这里。
            handler = registered("/" + path[len("/api/"):])
            if not handler:
                self._json({"success": False, "error": "not found"})
                return
            self._json(call_handler(handler, query=dict(parse_qsl(query))))
            return
        if path in ("/", "/index.html"):
            html = (PAGE_DIR / "index.html").read_text(encoding="utf-8")
            html = html.replace("</body>", BRIDGE_SHIM + "</body>")
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            return
        target = PAGE_DIR / path.lstrip("/")
        if target.is_file():
            ctype = {
                ".js": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".html": "text/html; charset=utf-8",
            }.get(target.suffix, "application/octet-stream")
            self._send(200, target.read_bytes(), ctype)
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path.startswith("/api/"):
            handler = registered("/" + path[len("/api/"):])
            if not handler:
                self._json({"success": False, "error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                body = {}
            self._json(call_handler(handler, body=body))
            return
        self._json({"success": False, "error": "not found"})


def contract_checks() -> list[str]:
    """Call the real handlers directly and verify the payload shape."""
    problems: list[str] = []
    overview = asyncio.run(API.overview())
    data = overview.get("data") or {}
    for key in ("narrative", "traits", "episodes", "memories", "people", "advisor"):
        if key not in data:
            problems.append(f"overview 缺少 {key}")
    if data.get("samples") != 42:
        problems.append(f"overview.samples 期望 42，实际 {data.get('samples')}")
    if data.get("people") != 2:
        problems.append(f"overview.people 期望 2，实际 {data.get('people')}")

    people = asyncio.run(API.people()).get("data", {}).get("items", [])
    if not people or people[0]["name"] != "二元虹光":
        problems.append("people 首位应为二元虹光")

    logs = asyncio.run(API.advisor_log()).get("data", {}).get("items", [])
    if len(logs) != 3:
        problems.append(f"advisor_log 期望 3 条，实际 {len(logs)}")

    # 页面上的新交互也要在预览里可用，否则点成员会 404。
    for suffix in ("/person", "/person/notes", "/advisor/test", "/reset"):
        if not registered(suffix):
            problems.append(f"没有注册 {suffix}")

    detail = call_handler(registered("/person"), query={"user_id": "10001"})
    if not detail.get("success"):
        problems.append(f"person 返回失败：{detail.get('error')}")
    else:
        data = detail.get("data") or {}
        if data.get("name") != "二元虹光":
            problems.append(f"person.name 期望二元虹光，实际 {data.get('name')}")
        if "stats" not in data or "memories" not in data:
            problems.append("person 缺少 stats/memories")

    saved = call_handler(
        registered("/person/notes"), body={"user_id": "10001", "notes": "预览备注"}
    )
    if not saved.get("success"):
        problems.append(f"person/notes 保存失败：{saved.get('error')}")
    elif PLUGIN.store.person("10001")["notes"] != "预览备注":
        problems.append("person/notes 没有写进 people.notes")
    return problems


def render_check() -> tuple[bool, str]:
    edge = next((path for path in EDGE_CANDIDATES if Path(path).exists()), "")
    if not edge:
        return False, "没有找到 Edge，跳过渲染检查"
    out = Path(tempfile.gettempdir()) / "self_panel_dom.html"
    cmd = [
        edge,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--virtual-time-budget=5000",
        "--dump-dom",
        f"http://127.0.0.1:{PORT}/",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        dom = result.stdout.decode("utf-8", errors="replace")
        out.write_text(dom, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return False, f"渲染失败：{exc}"
    expectations = ["一个连续存在的自己", "自我叙事", "二元虹光", "顾问", "42", "人物画像"]
    missing = [item for item in expectations if item not in dom]
    if missing:
        return False, f"DOM 里缺少：{missing}（已保存 {out}）"
    return True, f"渲染正常，DOM 已保存到 {out}"


def start_server() -> tuple[ThreadingHTTPServer, int]:
    last_error: Exception | None = None
    for port in PORT_CANDIDATES:
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            return server, port
        except OSError as exc:
            last_error = exc
    raise RuntimeError(f"没有可用端口：{last_error}")


def main() -> int:
    global PORT
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true", help="保持服务运行，手动浏览")
    args = parser.parse_args()

    problems = contract_checks()
    print("接口契约：", "通过" if not problems else "失败")
    for item in problems:
        print("  -", item)

    server, PORT = start_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"预览地址： http://127.0.0.1:{PORT}/")

    if args.serve:
        print("按 Ctrl+C 结束。")
        try:
            thread.join()
        except KeyboardInterrupt:
            pass
        return 0 if not problems else 1

    ok, message = render_check()
    print("页面渲染：", message)
    server.shutdown()
    return 0 if ok and not problems else 1


if __name__ == "__main__":
    sys.exit(main())
