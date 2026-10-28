"""Privacy layer: sensitivity, disclosure rules, and what may be repeated.

Scope semantics: ``private`` outranks ``group``. Content never moves toward a
more public place than where it was said, regardless of who is asking.
"""

from __future__ import annotations

import re
from typing import Any

HIGH_WORDS = (
    "秘密", "别告诉", "不要告诉", "隐私", "密码", "身份证", "银行卡",
    "住址", "开盒", "裸照", "病历",
)

MENTION_WORDS = (
    "喜欢", "暗恋", "关系", "电话", "手机号", "工资", "生病", "地址", "家里",
)

PERSON_PATTERNS = (
    r"(?:^|[^我])[\s，,。]*(?:问问|问一下|问|关于)?\s*"
    r"([A-Za-z0-9_\u4e00-\u9fa5]{1,12}?)\s*(?:跟你|和你|对你)\s*(?:说|讲|提)",
    r"(?:关于|问问|问一下)\s*([A-Za-z0-9_\u4e00-\u9fa5]{1,12}?)\s*"
    r"(?:说了什么|说过什么|的事|的事吗)",
)

SCOPE_RANK = {"private": 0, "group": 1}


def sensitive_words(raw: str) -> tuple[str, ...]:
    """Kept for config compatibility; returns the high-sensitivity word list."""
    words = [item.strip() for item in re.split(r"[,，\s]+", raw or "") if item.strip()]
    return tuple(words) if words else HIGH_WORDS


def classify(text: str, high_words: tuple[str, ...] = HIGH_WORDS) -> str:
    """Return high / mention / medium / low.

    Only ``low`` may be repeated, and only inside a group.
    """
    text = str(text or "")
    if any(word in text for word in high_words):
        return "high"
    if any(word in text for word in MENTION_WORDS):
        return "mention"
    if len(text) > 60:
        return "medium"
    return "low"


def shareable(sensitivity: str, scope: str) -> int:
    if scope == "private":
        return 0
    return 1 if sensitivity == "low" else 0


def extract_person(text: str) -> str:
    text = str(text or "").strip()
    for pattern in PERSON_PATTERNS:
        match = re.search(pattern, text)
        if not match:
            continue
        name = match.group(1).strip()
        name = re.sub(r"^(?:问问|问一下|问|关于|和|跟|对)", "", name).strip()
        if 1 <= len(name) <= 12:
            return name
    return ""


def asks_about_person(text: str) -> bool:
    return bool(extract_person(text)) and any(
        word in str(text or "") for word in ("说", "聊", "告诉", "提")
    )


def _allowed(
    row: dict[str, Any],
    requester_id: str,
    current_scope: str,
    current_group: str = "",
) -> bool:
    source_scope = str(row.get("scope") or "group")
    source_rank = SCOPE_RANK.get(source_scope, 1)
    current_rank = SCOPE_RANK.get(current_scope, 1)
    # Never move content toward a more public place (higher rank = more public).
    if current_rank > source_rank:
        return False
    # Group content never crosses groups, even for its own speaker: knowing
    # that someone also talks in another group is itself information.
    if source_scope == "group" and current_scope == "group":
        source_group = str(row.get("group_id") or "")
        if not source_group or not current_group or source_group != current_group:
            return False
    own = str(row.get("speaker_id")) == requester_id
    if own:
        return True
    if (
        source_scope == "group"
        and current_scope == "private"
        and str(row.get("sensitivity")) == "low"
        and bool(row.get("shareable"))
    ):
        # Talking about public group chatter in a private chat is fine; the
        # opposite direction is still blocked by the rank check above.
        return True
    return (
        source_scope == "group"
        and current_scope == "group"
        and str(row.get("sensitivity")) == "low"
        and bool(row.get("shareable"))
    )


def disclosure_block(
    rows: list[dict[str, Any]],
    person: str,
    requester_id: str,
    scope: str,
    group_id: str = "",
) -> str:
    """Render what may be repeated about ``person`` to ``requester_id``."""
    if not rows:
        return "没有找到这个人的相关记忆。"
    lines: list[str] = []
    for row in rows:
        if not _allowed(row, requester_id, scope, group_id):
            continue
        stamp = int(float(row.get("created_at") or 0))
        lines.append(
            f"[{row.get('scope')} {row.get('speaker_name')} {stamp}] {row.get('text')}"
        )
    if not lines:
        return (
            f"有关于 {person} 的记忆，但属于私下内容，不能转述。"
            "不要编造；可以说“这个我不方便替他说”或“你可以自己问他”。"
        )
    return "\n".join(lines[:5])


def match_known_person(text: str, names: list[str]) -> str:
    """Longest known-name match, falling back to the regex extractor."""
    text = str(text or "")
    best = ""
    for name in names:
        name = str(name or "").strip()
        if name and name in text and len(name) > len(best):
            best = name
    return best or extract_person(text)


def disclosure_note(memory: str, person: str) -> str:
    return (
        "<private_memory>\n"
        f"用户在问 {person} 和你的谈话。\n{memory}\n"
        "只根据上面的记录回答；不要编造。不能说的就明确说不方便，"
        "不要假装记得没发生的事。\n</private_memory>"
    )


def redact_for_advisor(text: str) -> str:
    """Strip obvious secrets before an external model sees the text.

    Chinese text has no word boundaries around digits, so plain ``\\b`` anchors
    never fire here; match by context instead.
    """
    text = str(text or "")
    text = re.sub(r"(?<!\d)(\d{17}[\dXx])(?!\d)", "[身份证]", text)
    text = re.sub(r"(?<!\d)(1[3-9]\d{9})(?!\d)", "[手机号]", text)
    text = re.sub(r"(?i)(sk-[a-z0-9]{6})[a-z0-9]+", r"\1***", text)
    text = re.sub(r"(?<!\d)(\d{16,19})(?!\d)", "[卡号]", text)
    return text[:1200]
