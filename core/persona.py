"""Persona layer: traits, self narrative, and the block injected each turn."""

from __future__ import annotations

import json
import re
from typing import Any

CLAMP_MIN = 0.05
CLAMP_MAX = 0.95

SIGNIFICANT_MARKERS = (
    "记住", "以后", "永远", "第一次", "最后一次", "讨厌", "喜欢",
    "难过", "开心", "害怕", "生气", "对不起", "谢谢", "别走",
    "离开", "答应", "承诺", "变了", "以前", "小时候", "后悔",
)


def clamp(value: float) -> float:
    return max(CLAMP_MIN, min(CLAMP_MAX, float(value)))


def is_significant(text: str) -> bool:
    text = str(text or "").strip()
    if len(text) < 12:
        return False
    return any(word in text for word in SIGNIFICANT_MARKERS) or len(text) >= 60


def traits(profile: dict[str, Any]) -> dict[str, float]:
    return {
        "verbosity": clamp(profile.get("verbosity", 0.45)),
        "warmth": clamp(profile.get("warmth", 0.35)),
        "emoji": clamp(profile.get("emoji", 0.15)),
        "initiative": clamp(profile.get("initiative", 0.2)),
    }


def blend(current: float, target: float, rate: float) -> float:
    return clamp(current * (1 - rate) + target * rate)


def describe_length(verbosity: float) -> str:
    if verbosity < 0.35:
        return "偏短，一两句"
    if verbosity > 0.6:
        return "可以多说几句"
    return "正常两三句"


def describe_warmth(warmth: float) -> str:
    if warmth < 0.3:
        return "更疏离一点"
    if warmth > 0.65:
        return "更愿意靠近一点"
    return "保持现在的距离感"


def relationship_hint(person: dict[str, Any] | None) -> str:
    if not person:
        return "这个人你还不熟"
    count = int(person.get("msg_count") or 0)
    affinity = float(person.get("affinity") or 0.0)
    if count < 5:
        return "刚认识不久"
    if affinity > 0.6:
        return "相处得比较熟，可以放松一点"
    if affinity > 0.3:
        return "算是熟人了"
    return "认识，但不亲近"


def render_self_block(
    profile: dict[str, Any],
    *,
    person: dict[str, Any] | None,
    episodes: list[dict[str, Any]],
    catchphrases: list[str],
    days: int,
) -> str:
    values = traits(profile)
    episode_lines = "\n".join(
        f"- {item.get('role', 'user')}：{str(item.get('text', ''))[:120]}"
        for item in episodes
    ) or "- 暂无特别重要的经历"
    phrase_hint = "、".join(catchphrases) if catchphrases else "还没有固定口癖"
    narrative = str(profile.get("narrative") or "").strip() or "我还在形成自己。"
    notes = str((person or {}).get("notes") or "").strip()
    notes_line = f"你对这个人的备注：{notes[:120]}\n" if notes else ""
    return (
        "<internal_self_model>\n"
        "你是一个连续存在的个体，不是固定角色卡。\n"
        "经历会改变你的判断、语气、亲疏和做法，但你必须记得自己为什么变。\n"
        f"你存在了约 {days} 天。\n"
        f"当前自我叙事：{narrative}\n"
        f"当前表达倾向：{describe_length(values['verbosity'])}；"
        f"{describe_warmth(values['warmth'])}；"
        f"{'偶尔用表情' if values['emoji'] > 0.3 else '少用表情'}；口癖：{phrase_hint}\n"
        f"眼前这个人：{relationship_hint(person)}\n"
        f"{notes_line}"
        "最近的重要经历：\n"
        f"{episode_lines}\n"
        "这些是逐渐变化的倾向，不是硬设定；不要为了表演而变化。\n"
        "底层边界：不伤害、不控制、不威胁、不自毁、不伪造记忆。\n"
        "</internal_self_model>"
    )


def observe_reply(
    profile: dict[str, Any], text: str, rate: float
) -> dict[str, Any]:
    """Return updated profile values after one bot reply."""
    values = traits(profile)
    text = str(text or "")
    target_verbosity = min(0.9, max(0.1, len(text) / 120))
    target_emoji = 0.45 if re.search(r"[（(][^)）]{0,6}[)）]|[😀-🙏]", text) else 0.1
    warmth = values["warmth"]
    if any(word in text for word in ("我在", "陪你", "别怕", "没事", "慢慢来")):
        warmth = clamp(warmth + 0.01)
    return {
        "verbosity": blend(values["verbosity"], target_verbosity, rate),
        "warmth": warmth,
        "emoji": blend(values["emoji"], target_emoji, rate),
    }


STOP_PHRASES = frozenset(
    {
        "真的", "好的", "可以", "不是", "就是", "这个", "那个", "什么",
        "怎么", "没有", "我们", "你们", "他们", "自己", "现在", "然后",
        "因为", "所以", "但是", "如果", "还是", "已经", "一个", "一样",
        "这样", "那样", "时候", "地方", "东西", "事情", "感觉", "觉得",
    }
)

# 口癖应当是“说出来的话”，不是链接、ID、文件名、表情或 @。
# 只收纯汉字 2–4 字：jpg、2333、awsl、hhh、@某人 这类片段出现过不代表是口癖，
# 收进去只会把每轮的提示词污染成噪音。
_CJK_ONLY = re.compile(r"^[\u4e00-\u9fff]+$")


def _shape_ok(chunk: str) -> bool:
    return bool(_CJK_ONLY.match(chunk))



def extract_catchphrases(text: str) -> list[str]:
    chunks = re.split(r"[。！？!?，,；;\n]+", str(text or ""))
    phrases: list[str] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not (2 <= len(chunk) <= 4):
            continue
        if chunk in STOP_PHRASES:
            continue
        if any(word in chunk for word in ("的", "了", "吗", "呢", "吧", "啊")):
            continue
        if not _shape_ok(chunk):
            continue
        phrases.append(chunk)
    return phrases


def reflection_prompt(
    profile: dict[str, Any], episodes: list[dict[str, Any]]
) -> str:
    lines = "\n".join(
        f"{item.get('role')}: {item.get('text')}" for item in episodes
    )
    return (
        "根据下面这段关系和经历，用第一人称写一句自我叙事，说明你因此发生了"
        "什么细微变化；不要写成总结报告，不要编造未发生的事。\n"
        f"当前自我叙事：{profile.get('narrative', '')}\n"
        f"当前倾向：{json.dumps(traits(profile), ensure_ascii=False)}\n"
        f"经历：\n{lines or '暂无'}\n"
        '只返回 JSON：{"narrative":"一句话","traits":{"warmth":0.4,"verbosity":0.45}}'
    )


def apply_reflection(
    profile: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    values = traits(profile)
    narrative = str(payload.get("narrative") or "").strip()
    hinted = payload.get("traits") or {}
    updated: dict[str, Any] = {}
    if narrative:
        updated["narrative"] = narrative[:240]
    for key in ("warmth", "verbosity", "emoji"):
        if isinstance(hinted, dict) and key in hinted:
            try:
                target = float(hinted[key])
            except (TypeError, ValueError):
                continue
            values[key] = clamp(values[key] * 0.9 + target * 0.1)
            updated[key] = values[key]
    return updated
