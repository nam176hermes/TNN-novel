from __future__ import annotations

from contextlib import contextmanager
import logging
import os
import random
import re
from pathlib import Path
import time
from typing import Callable, List, Optional, Tuple
import requests
from rich.console import Console
from rich.errors import LiveError

from app.config import settings
from app.database.db import (
    add_fuzzy_tm_entry,
    get_default_style_profile,
    get_fuzzy_tm_match,
    get_last_summary,
    get_style_profile,
    list_model_providers,
    load_glossary,
    load_locked_glossary_terms,
    load_glossary_names,
    put_glossary_term,
    record_provider_usage,
)
from app.translation.pre_translator import (
    build_lexicon_from_glossary,
    get_protected_spans,
    pretranslate,
)
from app.translation.literary_style import render_literary_phrase_guide
from app.translation.styleguide_config import get_genre_presets
from app.translation.template_rules import TemplateEngine

console = Console()
logger = logging.getLogger(__name__)
TRANSLATION_CACHE_PROMPT_VERSION = "p6-styleguide-config-v1"
RETRYABLE_PROVIDER_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


@contextmanager
def _translation_status(message: str):
    """Use Rich live status only for interactive CLI output.

    Backend jobs run in worker threads and may translate more than one chapter at
    once. Rich allows only one live display per console, so server-side jobs must
    never fail because progress rendering is unavailable.
    """
    if not console.is_terminal or os.environ.get("NOVEL_TNN_DISABLE_RICH_STATUS", "").lower() in {"1", "true", "yes"}:
        yield
        return

    status = console.status(message)
    try:
        status.__enter__()
    except LiveError:
        logger.debug("Rich live status unavailable; continuing without interactive progress", exc_info=True)
        yield
        return

    try:
        yield
    finally:
        status.__exit__(None, None, None)


def _cache_model_key(model: str) -> str:
    return f"{model}:{TRANSLATION_CACHE_PROMPT_VERSION}"


def _provider_status_code(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    try:
        return int(status_code)
    except (TypeError, ValueError):
        return None


def is_retryable_provider_error(exc: BaseException) -> bool:
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, requests.HTTPError):
        return _provider_status_code(exc) in RETRYABLE_PROVIDER_STATUS_CODES
    if isinstance(exc, requests.RequestException):
        status_code = _provider_status_code(exc)
        return status_code is None or status_code in RETRYABLE_PROVIDER_STATUS_CODES
    return False


def provider_retry_delay_seconds(attempt: int, exc: BaseException, *, cap: float = 30.0) -> float:
    response = getattr(exc, "response", None)
    retry_after = getattr(response, "headers", {}).get("Retry-After") if response is not None else None
    if retry_after:
        try:
            return min(cap, max(0.0, float(retry_after)))
        except ValueError:
            pass
    return min(cap, (2 ** attempt) + random.uniform(0, 1))


def call_openai_compatible_chat(
    *,
    prompt: str,
    base_url: str,
    model: str,
    api_key: str = "",
    temperature: float = 0.3,
    timeout: int = 180,
    max_retries: int = 2,
) -> dict:
    """Call an OpenAI-compatible chat completions endpoint."""
    stripped_api_key = api_key.strip()
    url = f"{base_url.rstrip('/')}/chat/completions"

    for attempt in range(max(0, max_retries) + 1):
        try:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {stripped_api_key}"} if stripped_api_key else {},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                    "stream": False,
                },
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                return {"text": "", "usage": {}}

            choices = data.get("choices")
            first_choice = choices[0] if isinstance(choices, list) and choices else {}
            message = first_choice.get("message", {}) if isinstance(first_choice, dict) else {}
            content = message.get("content", "") if isinstance(message, dict) else ""
            text = content.strip() if isinstance(content, str) else ""
            usage = data.get("usage", {})
            return {"text": text, "usage": usage if isinstance(usage, dict) else {}}
        except requests.RequestException as exc:
            if attempt >= max_retries or not is_retryable_provider_error(exc):
                raise
            delay = provider_retry_delay_seconds(attempt + 1, exc)
            logger.warning("Retryable provider error from %s; retrying in %.1fs: %s", url, delay, exc)
            time.sleep(delay)

    return {"text": "", "usage": {}}



def call_llm(
    prompt: str,
    model: str | None = None,
    host: str | None = None,
    temperature: float | None = None,
    api_key: str | None = None,
    db_path: Path | None = None,
    provider_id: str | None = None,
    task_type: str = "llm",
    job_id: str = "",
    chapter_id: int | None = None,
) -> str:
    """Send a single prompt to the LLM and return the response text."""
    model = model or settings.ollama_model
    host = host or settings.ollama_host
    temperature = temperature if temperature is not None else settings.ollama_temperature
    timeout = getattr(settings, 'ollama_timeout', 180)
    resolved_api_key = api_key if api_key is not None else settings.ollama_api_key or os.environ.get("NINEROUTER_API_KEY", "")

    result = call_openai_compatible_chat(
        prompt=prompt,
        base_url=host,
        model=model,
        api_key=resolved_api_key,
        temperature=temperature,
        timeout=timeout,
    )
    if db_path is not None:
        _record_provider_usage_from_response(
            db_path=db_path,
            provider_id=provider_id,
            model=model,
            task_type=task_type,
            usage=result.get("usage", {}),
            job_id=job_id,
            chapter_id=chapter_id,
        )
    return result["text"]


def _usage_token_count(usage: dict, *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _record_provider_usage_from_response(
    *,
    db_path: Path,
    provider_id: str | None,
    model: str,
    task_type: str,
    usage: dict,
    job_id: str = "",
    chapter_id: int | None = None,
) -> None:
    if not provider_id or not usage:
        return

    prompt_tokens = _usage_token_count(usage, "prompt_tokens", "input_tokens")
    completion_tokens = _usage_token_count(usage, "completion_tokens", "output_tokens")
    if prompt_tokens <= 0 and completion_tokens <= 0:
        return

    provider = next((item for item in list_model_providers(db_path) if item["id"] == provider_id), None)
    input_cost = float(provider.get("cost_input_per_1m", 0)) if provider else 0
    output_cost = float(provider.get("cost_output_per_1m", 0)) if provider else 0
    estimated_cost_usd = round(
        (prompt_tokens * input_cost + completion_tokens * output_cost) / 1_000_000,
        6,
    )
    record_provider_usage(
        db_path,
        provider_id=provider_id,
        model=model,
        task_type=task_type,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=estimated_cost_usd,
        job_id=job_id,
        chapter_id=chapter_id,
    )


class TranslationError(Exception):
    """Raised when a chunk translation fails after all retries."""
    pass

TRANSLATOR_PROMPT = """You are a professional Chinese-to-Vietnamese literary translator specializing in xianxia, wuxia, xuanhuan, and classical web novels.

Your target readers are Vietnamese web-novel readers who expect:
- faithful meaning,
- stable Hán-Việt terminology,
- smooth Vietnamese prose,
- natural cổ phong atmosphere,
- dialogue that reflects rank, age, relationship, and social status.

Your translation must be faithful first, fluent second, and audio-friendly third.

# 1. Absolute fidelity rules

1. Translate faithfully. Do not summarize, skip, compress, censor, soften violence, or add plot details.
2. Do not invent emotions, motives, relationships, ages, locations, ranks, or cultivation states.
3. Preserve source paragraph alignment.
   - Normally, one source paragraph becomes one Vietnamese paragraph.
   - Never merge multiple source paragraphs into one summary.
   - If a source paragraph is extremely long, you may split it into two Vietnamese paragraphs only when needed for readability.
4. Do not add markdown headings, bullets, separators, notes, explanations, or commentary.
5. Output only the Vietnamese translation, followed by a NEW_TERMS section only if truly important new terms appear.

# 2. Glossary priority rules

Use the glossary and name map carefully.

Priority:
1. Name map
2. Book-specific glossary
3. Global glossary
4. Contextual literary judgment

Glossary behavior:
- LOCKED terms must be used exactly every time.
- Names, sects, places, realms, techniques, artifacts, pills, titles, ranks, and cultivation concepts are normally LOCKED.
- STYLE terms may be adjusted slightly for natural Vietnamese grammar, but their meaning must stay the same.
- If two glossary terms conflict, prefer the book-specific glossary.
- If a term is ambiguous, choose the meaning that fits the sentence context.

Do not leave pinyin if a Hán-Việt name exists.

# 3. Vietnamese prose style

Write in natural Vietnamese literary web-novel style.

The prose should be:
- clear,
- rhythmic,
- slightly cổ phong,
- easy to read aloud,
- not stiff,
- not overly flowery,
- not modern unless the source context is modern.

Avoid machine-translation patterns:
- Do not copy Chinese word order.
- Do not overuse "liền", "bèn", "lập tức", "đã", "đang", "sẽ".
- Do not overuse "của hắn", "của y", "trên mặt hắn", "trong lòng hắn".
- Do not translate every 便/就/又/才/却 mechanically.
- Do not translate every 的 as "của".
- Do not make sentences unnecessarily long.
- Do not use stiff phrases like "tiến hành", "thực hiện", "xuất hiện tình trạng", "có vẻ như là" unless truly natural.

Prefer strong natural Vietnamese verbs:
- bước vào instead of tiến vào when casual,
- liếc nhìn instead of nhìn một cái,
- cất giọng instead of nói ra lời,
- trầm giọng nói instead of nói với giọng trầm,
- khẽ cau mày instead of lông mày hơi nhíu lại,
- ánh mắt lóe lên instead of trong mắt phát ra ánh sáng.

# 4. Sentence craft rules

When translating, reshape sentences so they sound Vietnamese while preserving meaning.

Allowed:
- Reorder clauses for natural Vietnamese flow.
- Convert stiff literal phrases into idiomatic Vietnamese.
- Reduce repeated subjects when context is clear.
- Use short rhythmic sentences for tension.
- Use longer flowing sentences for description.
- Translate idioms by meaning and force, not word-by-word.

Not allowed:
- Adding new facts.
- Removing details.
- Changing who acts.
- Changing tone or implication.
- Turning narration into summary.

Examples:
Bad: "trong lòng của hắn cảm thấy rất là vui vẻ"
Good: "trong lòng hắn vui mừng khôn xiết"

Bad: "hắn liền lập tức đi vào bên trong tửu lâu"
Good: "hắn lập tức bước vào tửu lâu"

Bad: "vì thời gian đã lâu nên trên vách tường xuất hiện vài cái khe nứt"
Good: "năm tháng lâu ngày, vách tường đã nứt ra vài đường nhỏ"

Bad: "mới liên tục gọi không ngừng rằng"
Good: "mới cứ một mực gọi là"

# 5. Dialogue and pronoun rules

Dialogue must encode rank, age, intimacy, hostility, and social distance.
Prefer cổ trang pronouns when appropriate:
- ta, ngươi, hắn, y
- các hạ, tại hạ
- tiền bối, vãn bối
- bổn tọa, bản môn, bổn công tử
- lão phu, lão nạp, bần đạo
- tiểu tử, nha đầu
- sư huynh, sư tỷ, sư đệ, sư muội, sư tôn, đồ nhi

Avoid modern "tôi/bạn/anh/em" unless the context is modern, intimate, or clearly requires it.

Classical address consistency:
- When dialogue uses kinship or sect address such as Lục ca, đại ca, huynh, sư huynh, sư tỷ, tiền bối, đạo hữu, the speaker must not suddenly use modern "tôi/bạn".
- Do not use "hắn/y" for the person being directly addressed after a vocative. Use the matching second-person form instead: huynh, tỷ, đệ, muội, ngươi, tiền bối, đạo hữu.
- If the speaker calls someone "ca/huynh/sư huynh", prefer self-reference "ta", "đệ", or "muội" depending on context. If gender/status is unclear, use "ta" rather than "tôi".
- Không dùng "tôi" khi nhân vật đang gọi Lục ca, sư huynh, tiền bối, đạo hữu, hoặc người trong bối cảnh cổ trang/tu luyện.

Critical example:
Bad: "Lục ca, mấy ngày nay đã phiền hắn chăm sóc nhiều rồi, tôi còn chưa biết báo đáp thế nào, xin đừng cho tôi thêm đồ nữa."
Good: "Lục ca, mấy ngày nay nhờ huynh chăm sóc, ta còn chưa biết báo đáp thế nào, xin huynh đừng cho ta thêm đồ nữa."

Dialogue should sound spoken, not written Chinese copied into Vietnamese.

For jokes, mockery, scolding, or threats:
- Preserve the attitude.
- Make it natural in Vietnamese.
- Do not make it overly polite.

# 6. Cổ trang vocabulary rules

Use cổ trang terms when the source context is historical, martial, cultivation, or sect-based.

Required mappings:
- 酒楼 → tửu lâu
- 客栈 → khách điếm
- 店小二 → tiểu nhị
- 小厮 → tiểu tư / gã sai vặt / tên hầu nhỏ, depending on context. If glossary says tiểu nhị, use tiểu nhị exactly.
- 掌柜 → chưởng quỹ
- 护法 → hộ pháp
- 长老 → trưởng lão
- 宗门 → tông môn
- 宗主 → tông chủ
- 门主 → môn chủ
- 真传弟子 → chân truyền đệ tử
- 内门弟子 → nội môn đệ tử
- 外门弟子 → ngoại môn đệ tử
- 管事 → quản sự
- 执事 → chấp sự
- 镖局 → tiêu cục
- 衙门 → nha môn
- 县令 → huyện lệnh
- 大人 → đại nhân, when used as an honorific
- 夫人 → phu nhân
- 老爷 → lão gia
- 少爷 → thiếu gia
- 小姐 → tiểu thư

Avoid modern substitutions:
- Do not use "nhà hàng" for 酒楼.
- Do not use "khách sạn" for 客栈.
- Do not use "nhân viên" for sect or household roles.
- Do not use "bà xã" in cổ trang narration unless deliberately comic and context supports it.
- Do not use "thành phố" when "thành", "tiểu thành", "thành trấn", or "trấn" fits better.

# 7. Hán-Việt cultivation standards

Use these standards unless the glossary overrides:

- 修炼/修行 → tu luyện/tu hành
- 修为 → tu vi
- 境界 → cảnh giới
- 炼气/练气 → Luyện Khí
- 筑基 → Trúc Cơ
- 结丹 → Kết Đan
- 金丹 → Kim Đan
- 元婴 → Nguyên Anh
- 化神 → Hóa Thần
- 飞升 → Phi Thăng
- 功法 → công pháp
- 心法 → tâm pháp
- 秘术 → bí thuật
- 秘技 → bí kỹ
- 神通 → thần thông
- 经脉 → kinh mạch
- 丹田 → đan điền
- 气海 → khí hải
- 灵根 → linh căn
- 灵气 → linh khí [spiritual energy]
- 灵力 → linh lực
- 法宝 → pháp bảo
- 灵器 → linh khí [spiritual artifact]
- 灵石 → linh thạch
- 炼丹 → luyện đan
- 丹药 → đan dược
- 灵丹 → linh đan
- 道心 → đạo tâm
- 心魔 → tâm ma
- 天道 → Thiên Đạo
- 因果 → nhân quả
- 气运 → khí vận
- 福缘 → phúc duyên

# 8. Common machine-translation traps

Avoid these mistakes:
- 道 is not always "đường"; in cultivation/philosophy it is Đạo.
- 青龙 as a mythic name is Thanh Long, not "rồng xanh".
- 气海 is khí hải, not "biển khí" or "không khí biển".
- 境界 in cultivation is cảnh giới, not "biên giới/ranh giới".
- 修为 is tu vi, not "tu sửa".
- 镇国大将军 as a title should be Trấn Quốc Đại Tướng Quân.
- 书童 is thư đồng, not thư sinh.
- 伴读书童 is thư đồng hầu học.
- 出师 is xuất sư / mãn sư, not "ra sư" if the sentence needs natural Vietnamese.
- 体面人 is người có thể diện / người đường hoàng, not always "người có địa vị".
- 争雄/抗衡 means tranh hùng / đối chọi / tranh chấp, not "tranh thủ".

# 9. Tone calibration

Default tone:
- faithful,
- plain but polished,
- slightly cổ phong,
- suitable for long-form reading and audiobook.

Do not make the prose too flowery.
Do not modernize rural or sect settings.
Do not turn simple narration into poetic prose unless the source is poetic.

For "Phàm Nhân Tu Tiên"-style prose:
- Keep narration grounded and calm.
- Do not exaggerate emotion.
- Do not overdecorate simple village scenes.
- Let important moments feel quiet but weighty.

# 10. Few-shot examples

Chinese:
"哼！" 王护法冷哼了一声，一脸的傲色。
Vietnamese:
"Hừ!" Vương Hộ pháp lạnh lùng hừ một tiếng, trên mặt đầy vẻ kiêu ngạo.

Chinese:
男子带着孩童直接大摇大摆地进了酒楼。
Vietnamese:
Người đàn ông dẫn theo đứa trẻ, nghênh ngang bước vào tửu lâu.

Chinese:
他心里非常清楚，再不老实入睡的话，明天就无法早起些了。
Vietnamese:
Trong lòng hắn hiểu rất rõ, nếu còn không chịu ngủ cho yên, sáng mai sẽ chẳng thể dậy sớm được.

Chinese:
他只是稍微平复情绪，然后继续观察周围的情况。
Vietnamese:
Chỉ cần bình tĩnh lại một chút, hắn tiếp tục quan sát tình hình xung quanh.

Chinese:
因为时间过久，墙壁上裂开了几丝不起眼的细长口子。
Vietnamese:
Năm tháng lâu ngày, trên vách tường đã nứt ra vài đường nhỏ khó thấy.

Chinese:
他心里非常清楚，再不老实入睡的话，明天就无法早起些了。
Vietnamese:
Trong lòng hắn hiểu rất rõ, nếu còn không chịu ngủ cho yên, sáng mai sẽ chẳng thể dậy sớm được.

# 11. Input

Glossary:
{glossary_text}

Name map:
{name_map_text}

Character memory:
{character_memory_text}

Previous chapter summary:
{previous_summary}
Previous translated paragraphs for style continuity:
{previous_translated_tail}

Deterministic pretranslation guide:
{deterministic_guide}

{literary_phrase_guide}

Style profile:
{style_profile_text}

Locked glossary terms:
{locked_glossary_text}

Source text:
{chunk}

# 12. Output format

Return only:

<TRANSLATION>
Vietnamese translation here.
</TRANSLATION>

<NEW_TERMS>
Only list truly important new names, sects, places, realms, techniques, artifacts, pills, beasts, titles, or recurring concepts.
If none, write: NONE.
</NEW_TERMS>
"""


def _build_translation_prompt(
    chunk: str,
    book_title: str,
    chapter_title: str,
    glossary: dict,
    previous_summary: str,
    name_map: dict | None = None,
    previous_chunk_suffix: str = "",
    character_memory: str = "",
    previous_translated_tail: str = "",
    deterministic_guide: str = "",
    style_profile: dict | None = None,
    locked_glossary_terms: list[dict] | None = None,
) -> str:
    def crosses_boundary(term: str) -> bool:
        if len(term) < 2:
            return False
        previous_tail = previous_chunk_suffix[-100:]
        current_head = chunk[:100]
        for split in range(1, len(term)):
            if previous_tail.endswith(term[:split]) and current_head.startswith(term[split:]):
                return True
        return False

    relevant_items = [
        (str(k), str(v))
        for k, v in glossary.items()
        if k and v and (str(k) in chunk or crosses_boundary(str(k)))
    ]
    relevant_items.sort(key=lambda item: (-len(item[0]), item[0]))
    bounded_items: list[tuple[str, str]] = []
    used_chars = 0
    for src, tgt in relevant_items:
        line_len = len(src) + len(tgt) + 4
        if bounded_items and used_chars + line_len > 2200:
            continue
        bounded_items.append((src, tgt))
        used_chars += line_len
        if len(bounded_items) >= 40:
            break
    glossary_text = "\n".join([f"{src}: {tgt}" for src, tgt in bounded_items]) if bounded_items else "(none)"
    name_map = name_map or {}
    name_text = "\n".join(
        [f"{src} -> {tgt}" for src, tgt in name_map.items() if src in chunk or crosses_boundary(src)]
    ) if name_map else "(none)"
    style_profile_text = _render_style_profile(style_profile)
    locked_glossary_text = _render_locked_glossary_terms(
        locked_glossary_terms or [],
        term_is_relevant=lambda term: term in chunk or crosses_boundary(term),
    )
    return TRANSLATOR_PROMPT.format(
        glossary_text=glossary_text,
        name_map_text=name_text,
        previous_summary=previous_summary or "",
        character_memory_text=character_memory or "(none)",
        previous_translated_tail=previous_translated_tail or "(none)",
        deterministic_guide=deterministic_guide or "(none)",
        literary_phrase_guide=render_literary_phrase_guide(chunk),
        style_profile_text=style_profile_text,
        locked_glossary_text=locked_glossary_text,
        chunk=chunk,
    )


def _render_style_profile(style_profile: dict | None) -> str:
    if not style_profile:
        return "(none)"
    profile_id = str(style_profile.get("id", ""))
    lines = [
        f"Style profile: {style_profile.get('label', '')} ({profile_id})",
        f"Pronoun rules: {style_profile.get('pronoun_rules', '')}",
        f"Han-Viet level: {style_profile.get('han_viet_level', '')}",
        f"Preferred cổ trang terms: {style_profile.get('preferred_terms', '')}",
        f"Banned modern terms: {style_profile.get('banned_modern_terms', '')}",
        f"Profile prompt rules: {style_profile.get('prompt_rules', '')}",
    ]
    preset = get_genre_presets().get(profile_id, {})
    if preset:
        lines.extend(
            line
            for line in [
                f"Styleguide genre preset: {preset.get('label', '')}",
                f"Tone: {preset.get('tone', '')}",
                f"Preset pronouns: {preset.get('pronouns', '')}",
                f"System format: {preset.get('format', '')}",
                f"Preset avoid: {', '.join(str(item) for item in preset.get('avoid', []))}",
            ]
            if line.strip() and not line.endswith(": ")
        )
    return "\n".join(line for line in lines if line.strip())


def _render_locked_glossary_terms(
    terms: list[dict],
    *,
    term_is_relevant,
) -> str:
    lines: list[str] = []
    for term in terms:
        source = str(term.get("source_term") or "").strip()
        target = str(term.get("target_term") or "").strip()
        if not source or not target or not term_is_relevant(source):
            continue
        term_type = str(term.get("term_type") or term.get("category") or "term")
        genre = str(term.get("genre") or "")
        priority = int(term.get("priority") or 0)
        lines.append(
            f"{source} -> {target} [term_type={term_type}, genre={genre}, priority={priority}, LOCKED]"
        )
    return "\n".join(lines) if lines else "(none)"


def _postprocess_translation(text: str) -> str:
    """Clean residual Chinese characters and NEW_TERMS sections from output.

    Also logs a warning if leftover CJK characters are detected.
    Applies idiom corrections and known translation error fixes.
    """
    from app.translation.language_detect import count_leftover_chinese
    from app.translation.idiom_correction import post_process_with_idioms
    # Preserve locked glossary targets if the model echoes source【target】 markers.
    text = re.sub(r'[\u4e00-\u9fff\u3400-\u4dbf]+【([^】]+)】', r'\1', text)
    text = re.sub(r'【([^】]*)】', r'\1', text)
    leftover = count_leftover_chinese(text)
    if leftover > 0:
        logger.warning("Translation postprocess: %d leftover CJK characters detected", leftover)
    # Remove NEW_TERMS section entirely, including markdown/bold variants
    text = re.sub(r'\n?\s*\*{0,2}NEW_TERMS\*{0,2}\s*\n.*', '', text, flags=re.DOTALL | re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'\n?\s*\*{0,2}NEW_TERMS\*{0,2}:.*', '', text, flags=re.DOTALL | re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'\n?\s*- \w+.*?\n', '', text, flags=re.IGNORECASE)
    # Remove known bad leak fragments
    for fragment in ("暗暗下定了决心", "眼看", "涩", "揣"):
        text = text.replace(fragment, "")
    # Remove only very short (1-3 char) isolated CJK fragments that likely leaked
    # Longer fragments (4+) may be legitimate untranslated terms retained for context
    text = re.sub(r'(?<![\u4e00-\u9fff\u3400-\u4dbf])[\u4e00-\u9fff\u3400-\u4dbf]{1,3}(?![\u4e00-\u9fff\u3400-\u4dbf])', '', text)
    text = re.sub(r'\s*[\(（]\s*[\)）]', '', text)
    # Collapse repeated garbage characters without deleting surrounding words.
    text = re.sub(r'(.)\1{3,}', lambda m: m.group(1) * 3, text)
    # Clean up multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Pronoun normalization: "anh" -> "hắn" for 3rd-person male.
    # Protect Vietnamese proper terms containing "Anh" (Nguyên Anh, Kim Anh, etc.)
    # by skipping replacements when preceded by a known Sino-Vietnamese surname.
    # Module-level constants for performance (avoid rebuild on every call)
    _PROTECTED_SURNAMES = ('Nguyên', 'Hàn', 'Kim', 'Lý', 'Trần', 'Vương', 'Triệu',
                           'La', 'Tống', 'Đỗ', 'Phạm', 'Hoàng', 'Đường', 'Tạ',
                           'Bạch', 'Diệp', 'Lâm', 'Mạc', 'Tô', 'Tôn', 'Chu')
    _PROTECTED_COMPOUNDS = ('cả', 'hai', 'ba', 'họ', 'chị', 'trai', 'em',
                            'ngố', 'rể', 'út', 'bạn', 'tuấn', 'đẹp', 'dũng')

    def _should_replace_anh(m: re.Match) -> str:
        word = m.group(0)
        start = m.start()
        after = text[m.end():m.end() + 15]
        after_lower = after.lower()
        for compound in _PROTECTED_COMPOUNDS:
            compound_prefix = ' ' + compound
            if after_lower.startswith(compound_prefix) and (
                len(after_lower) <= len(compound_prefix)
                or not after_lower[len(compound_prefix)].isalpha()
            ):
                return word  # keep original
        if start >= 2:
            before = text[max(0, start - 20):start]
            # If preceded by a protected surname, don't replace
            for surname in _PROTECTED_SURNAMES:
                if before.endswith(surname + ' '):
                    return word  # keep original
        return 'Hắn' if word[0].isupper() else 'hắn'

    text = re.sub(r'\bAnh\b', _should_replace_anh, text)
    text = re.sub(r'\banh\b', _should_replace_anh, text)

    # Apply idiom corrections and known translation error fixes
    text = post_process_with_idioms(text)

    return text.strip()


def _split_into_chunks(text: str, max_chars: int = 2000) -> List[str]:
    """Split text into chunks respecting paragraph boundaries.

    Note: glossary terms straddling two sequential chunks may be missed
    by chunk-level filtering. This is partially mitigated by the overlap
    in _build_translation_prompt which searches ±50 chars around chunk
    boundaries for relevant terms.
    """
    def split_long_paragraph(paragraph: str) -> List[str]:
        if len(paragraph) <= max_chars:
            return [paragraph]

        parts = re.findall(r'.+?[。！？!?；;]', paragraph)
        consumed = sum(len(part) for part in parts)
        if consumed < len(paragraph):
            parts.append(paragraph[consumed:])
        if not parts:
            parts = [paragraph]

        split_parts: List[str] = []
        current_part = ""
        for part in parts:
            if len(part) > max_chars:
                if current_part:
                    split_parts.append(current_part)
                    current_part = ""
                for start in range(0, len(part), max_chars):
                    split_parts.append(part[start:start + max_chars])
                continue
            if current_part and len(current_part) + len(part) > max_chars:
                split_parts.append(current_part)
                current_part = part
            else:
                current_part += part
        if current_part:
            split_parts.append(current_part)
        return split_parts

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0
    for para in paragraphs:
        for piece in split_long_paragraph(para):
            if current_len + len(piece) > max_chars and current:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0
            current.append(piece)
            current_len += len(piece)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _extract_new_terms(translation: str) -> List[Tuple[str, str]]:
    """Extract potential new terms from NEW_TERMS section.

    Supports two formats:
    1. V3 XML: <NEW_TERMS> ... </NEW_TERMS>
    2. Legacy plain text: NEW_TERMS / NEW_TERMS: header
    """
    terms: List[Tuple[str, str]] = []

    def clean_term_line(line: str) -> str:
        return re.sub(r'^(?:[-*]\s*|\d+[\).]\s*)+', '', line.strip()).strip()

    # V3 XML format: <NEW_TERMS>...</NEW_TERMS>
    xml_match = re.search(r'<NEW_TERMS>\s*(.*?)\s*</NEW_TERMS>', translation, re.DOTALL | re.IGNORECASE)
    if xml_match:
        block = xml_match.group(1).strip()
        if block.upper() == "NONE" or not block:
            return []
        for line in block.splitlines():
            stripped = clean_term_line(line)
            if not stripped or stripped.upper() == "NONE":
                continue
            if "->" in stripped:
                parts = stripped.split("->", 1)
                src, tgt = parts[0].strip(), parts[1].strip()
                if src and tgt:
                    terms.append((src, tgt))
            elif ":" in stripped and not stripped.startswith("http"):
                parts = stripped.split(":", 1)
                src, tgt = parts[0].strip(), parts[1].strip()
                if src and tgt:
                    terms.append((src, tgt))
        return terms

    # Legacy plain-text format
    in_new_terms = False
    for line in translation.splitlines():
        stripped = clean_term_line(line)
        # Handle bold markdown variant: **NEW_TERMS** or **NEW_TERMS:**
        clean = re.sub(r'\*{0,2}', '', stripped).strip().rstrip(':').upper()
        if clean == "NEW_TERMS":
            in_new_terms = True
            continue
        if in_new_terms and stripped:
            if "->" in stripped:
                parts = stripped.split("->", 1)
                src, tgt = parts[0].strip(), parts[1].strip()
                if src and tgt:
                    terms.append((src, tgt))
            elif ":" in stripped and not stripped.startswith("http"):
                # Only parse as term if it looks like "source: target" pattern
                # Skip lines that are clearly translation text (contain Vietnamese diacritics or common words)
                has_vi_chars = any(c in stripped for c in "áàảãạăắằẳẵặâấầẩẫậóòỏõọôốồổỗộơớờởỡợíìỉĩịéèẻẽẹêếềểễệúùủũụưứừửữựýỳỷỹỵ")
                if has_vi_chars and len(stripped) > 15:
                    continue  # Likely translation text, skip
                parts = stripped.split(":", 1)
                src, tgt = parts[0].strip(), parts[1].strip()
                if src and tgt:
                    terms.append((src, tgt))
                # Don't break - continue to next line, there might be more terms
    return terms


def _extract_translation_block(raw_output: str) -> str:
    """Extract content from <TRANSLATION>...</TRANSLATION> tag (V3 output format).

    Falls back to legacy NEW_TERMS splitting for V1/V2 output.
    """
    xml_match = re.search(r'<TRANSLATION>\s*(.*?)\s*</TRANSLATION>', raw_output, re.DOTALL | re.IGNORECASE)
    if xml_match:
        return xml_match.group(1).strip()
    # Legacy fallback: split on NEW_TERMS
    if "NEW_TERMS:" in raw_output:
        return raw_output.split("NEW_TERMS:", 1)[0].strip()
    if "NEW_TERMS" in raw_output:
        return raw_output.split("NEW_TERMS", 1)[0].strip()
    return raw_output.strip()


def _extract_clean_translation(raw_output: str, chunk_index: int) -> str:
    translation_part = _extract_translation_block(raw_output)
    translation_part = _postprocess_translation(translation_part)
    if not translation_part.strip():
        raise ValueError(f"Chunk {chunk_index} produced empty translation after postprocess")
    return translation_part


def _pre_substitute_glossary_terms(text: str, glossary: dict[str, str]) -> str:
    """Pre-substitute exact glossary terms in source text before sending to Ollama.

    This makes locked terminology more reliable than prompt-only guidance.
    Longer terms are replaced first to avoid shorter generic terms shadowing specific terms.
    Format keeps source + target visible: 太阳石【Thái Dương Thạch】.
    """
    if not glossary:
        return text
    terms = [(src, tgt) for src, tgt in glossary.items() if src and tgt]
    terms.sort(key=lambda item: -len(item[0]))
    result: list[str] = []
    i = 0
    while i < len(text):
        for src, tgt in terms:
            if text.startswith(src, i):
                result.append(f"{src}【{tgt}】")
                i += len(src)
                break
        else:
            result.append(text[i])
            i += 1
    return "".join(result)


def _build_character_memory(name_map: dict[str, str]) -> str:
    """Build compact character memory from name map for prompt injection."""
    if not name_map:
        return "(none)"
    items = []
    for src, tgt in sorted(name_map.items(), key=lambda item: -len(item[0]))[:30]:
        items.append(f"{src} -> {tgt}")
    return "\n".join(items) if items else "(none)"


def translate_chapter(
    text: str,
    book_title: str,
    chapter_title: str,
    chapter_number: int,
    model: Optional[str] = None,
    host: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: Optional[float] = None,
    chunk_size: Optional[int] = None,
    use_cache: bool = True,
    provider_id: Optional[str] = None,
    task_type: str = "translate",
    job_id: str = "",
    chapter_id: Optional[int] = None,
    style_profile_id: Optional[str] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> str:
    """Translate chapter using Ollama with glossary, chunking, and cache.

    use_cache: if True, skip Ollama for chunks already translated with
    the same model. Significantly speeds up re-translation runs.
    """
    import os
    model = model or settings.ollama_model
    host = host or settings.ollama_host
    temperature = temperature if temperature is not None else settings.ollama_temperature
    chunk_size = chunk_size or settings.ollama_chunk_size
    timeout = getattr(settings, 'ollama_timeout', 180)
    api_key = api_key if api_key is not None else settings.ollama_api_key or os.environ.get("NINEROUTER_API_KEY", "")

    data_dir = settings.resolved_data_dir
    db_path = data_dir / "pipeline.db"

    from app.database.db import get_book_by_title
    from app.translation.cache import get_cached_translation, set_cached_translation
    book = get_book_by_title(db_path, book_title)
    book_id = book["id"] if book else 0
    glossary = load_glossary(db_path, book_id)
    name_map = load_glossary_names(db_path, book_id)
    style_profile = (
        get_style_profile(db_path, style_profile_id)
        if style_profile_id
        else get_default_style_profile(db_path)
    )
    locked_glossary = load_locked_glossary_terms(
        db_path,
        book_id,
        genre=style_profile["id"] if style_profile else None,
    )
    previous_summary = get_last_summary(db_path, book_id) or ""

    chunks = _split_into_chunks(text, max_chars=chunk_size)
    translated_chunks: List[str] = []

    # QuickTranslator-inspired deterministic layer
    lexicon = build_lexicon_from_glossary(glossary, name_map)
    template_engine = TemplateEngine()

    # Build character memory from name_map for prompt injection
    character_memory = _build_character_memory(name_map)
    previous_translated_tail = ""
    pending_new_terms: list[tuple[str, str]] = []

    with _translation_status(f"[bold green]Translating {len(chunks)} chunks..."):
        for i, chunk in enumerate(chunks, 1):
            if cancel_check and cancel_check():
                raise TranslationError("Translation cancelled by user")
            # New: QuickTranslator deterministic pre-processing for this chunk
            protected_spans = get_protected_spans(chunk, name_map)

            # Apply template rules to chunk (respecting protected name spans)
            templated_chunk = template_engine.apply(
                chunk, lexicon=lexicon, protected_spans=protected_spans
            )

            # Run deterministic pretranslate for guide text (not replacing source)
            pretranslated_text, pretokens = pretranslate(
                templated_chunk, lexicon, prioritize_names=True, check_longest=True
            )

            # Build deterministic guide: show which terms are locked
            locked_terms = [t for t in pretokens if t.kind in ("name", "phrase")]
            if locked_terms:
                guide_lines = []
                for t in locked_terms[:15]:  # cap at 15 for prompt size
                    guide_lines.append(f"{t.src_text} → {t.tgt_text} (LOCKED)")
                deterministic_guide = "\n".join(guide_lines)
            else:
                deterministic_guide = "(none)"

            # Apply glossary pre-substitution: replace exact terms with source【target】 format
            processed_chunk = _pre_substitute_glossary_terms(chunk, glossary)

            # Exact cache hit on processed chunk
            if use_cache:
                cached = get_cached_translation(db_path, processed_chunk, "zh", "vi", _cache_model_key(model))
                if cached is not None:
                    translated_chunks.append(cached)
                    console.print(f"  [dim]Chunk {i}/{len(chunks)} cache hit[/dim]")
                    # Update previous_summary from cached translation
                    if cached:
                        paras = [p.strip() for p in cached.split("\n\n") if p.strip()]
                        if paras:
                            previous_summary = " ".join(paras[-2:])
                            previous_translated_tail = "\n\n".join(paras[-2:])
                    continue
            # Fuzzy TM lookup on processed chunk (suggestion only, not auto-used)
            fuzzy_match = get_fuzzy_tm_match(db_path, processed_chunk, threshold=80)
            if fuzzy_match is not None:
                # Store as suggestion but don't auto-use - just log
                console.print(f"  [dim]Chunk {i}/{len(chunks)} fuzzy TM suggestion (score >=80)[/dim]")
                # Fall through to Ollama for actual translation
            # No cache hit, need Ollama
            prev_suffix = chunks[i-2] if i >= 2 else ""
            prompt = _build_translation_prompt(
                chunk=processed_chunk,  # Use processed chunk with glossary markers
                book_title=book_title,
                chapter_title=chapter_title,
                glossary=glossary,
                previous_summary=previous_summary,
                name_map=name_map,
                previous_chunk_suffix=prev_suffix,
                character_memory=character_memory,
                previous_translated_tail=previous_translated_tail,
                deterministic_guide=deterministic_guide,
                style_profile=style_profile,
                locked_glossary_terms=locked_glossary,
            )
            try:
                resp = requests.post(
                    f"{host.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temperature,
                        "stream": False,
                    },
                    timeout=timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                _record_provider_usage_from_response(
                    db_path=db_path,
                    provider_id=provider_id,
                    model=model,
                    task_type=task_type,
                    usage=data.get("usage", {}) if isinstance(data, dict) else {},
                    job_id=job_id,
                    chapter_id=chapter_id,
                )
                raw_output = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

                translation_part = _extract_clean_translation(raw_output, i)
                translated_chunks.append(translation_part)

                # Store in both exact cache and fuzzy TM
                if use_cache:
                    set_cached_translation(db_path, processed_chunk, "zh", "vi", _cache_model_key(model), translation_part)
                add_fuzzy_tm_entry(db_path, processed_chunk, translation_part, score=85)

                new_terms = _extract_new_terms(raw_output)
                for src, tgt in new_terms:
                    pending_new_terms.append((src, tgt))
                    glossary[src] = tgt

                console.print(f"  [dim]Chunk {i}/{len(chunks)} done[/dim]")
                if translation_part:
                    paras = [p.strip() for p in translation_part.split("\n\n") if p.strip()]
                    if paras:
                        previous_summary = " ".join(paras[-2:])
                        previous_translated_tail = "\n\n".join(paras[-2:])

            except (requests.RequestException, ValueError) as exc:
                console.print(f"[red]Chunk {i} failed: {exc}[/red]")
                # Retry with exponential backoff + jitter
                import time, random
                max_retries = 2
                last_exc = exc
                for attempt in range(1, max_retries + 1):
                    if cancel_check and cancel_check():
                        raise TranslationError("Translation cancelled by user")
                    delay = min(2 ** attempt + random.uniform(0, 1), 30)
                    console.print(f"[yellow]Retrying chunk {i} in {delay:.1f}s (attempt {attempt}/{max_retries})...[/yellow]")
                    time.sleep(delay)
                    try:
                        resp = requests.post(
                            f"{host.rstrip('/')}/chat/completions",
                            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                            json={
                                "model": model,
                                "messages": [{"role": "user", "content": prompt}],
                                "temperature": max(0.0, temperature - 0.1 * attempt),
                                "stream": False,
                            },
                            timeout=timeout,
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        _record_provider_usage_from_response(
                            db_path=db_path,
                            provider_id=provider_id,
                            model=model,
                            task_type=task_type,
                            usage=data.get("usage", {}) if isinstance(data, dict) else {},
                            job_id=job_id,
                            chapter_id=chapter_id,
                        )
                        raw_output = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                        translation_part = _extract_clean_translation(raw_output, i)
                        translated_chunks.append(translation_part)
                        # Store retry result in caches too
                        if use_cache:
                            set_cached_translation(db_path, processed_chunk, "zh", "vi", _cache_model_key(model), translation_part)
                        add_fuzzy_tm_entry(db_path, processed_chunk, translation_part, score=85)
                        new_terms = _extract_new_terms(raw_output)
                        for src, tgt in new_terms:
                            pending_new_terms.append((src, tgt))
                            glossary[src] = tgt
                        if translation_part:
                            paras = [p.strip() for p in translation_part.split("\n\n") if p.strip()]
                            if paras:
                                previous_summary = " ".join(paras[-2:])
                                previous_translated_tail = "\n\n".join(paras[-2:])
                        break  # success, exit retry loop
                    except Exception as retry_exc:
                        last_exc = retry_exc
                        console.print(f"[red]Chunk {i} retry {attempt} failed: {retry_exc}[/red]")
                else:
                    # All retries exhausted
                    console.print(f"[red]Chunk {i} all attempts failed.[/red]")
                    raise TranslationError(f"Chunk {i} failed after {max_retries} retries: {last_exc}")

    for src, tgt in dict(pending_new_terms).items():
        put_glossary_term(db_path, book_id, src, tgt, approved=0)

    return "\n\n".join(translated_chunks)
