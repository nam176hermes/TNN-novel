from __future__ import annotations

import re


DEFAULT_PRONOUN_MEMORY = [
    {
        "character": "Tần Minh",
        "rules": "khi tự xưng dùng ta; tránh tôi trong bối cảnh cổ trang.",
    },
    {
        "character": "Lục Trạch",
        "rules": "khi được gọi Lục ca thì người nói xưng ta, gọi huynh; không dùng anh/tôi.",
    },
    {
        "character": "Người lớn tuổi",
        "rules": "ưu tiên tiền bối, lão nhân, lão giả, lão phu tùy ngữ cảnh.",
    },
]

MODERN_PRONOUN_PATTERN = re.compile(r"\b(tôi|bạn|anh|em)\b", flags=re.IGNORECASE)
CLASSICAL_VOCATIVE_PATTERN = re.compile(
    r"\b("
    r"(?:[A-ZĐ][\wÀ-ỹ]+)\s+ca|"
    r"đại\s+ca|nhị\s+ca|tam\s+ca|"
    r"sư\s+huynh|sư\s+tỷ|sư\s+đệ|sư\s+muội|"
    r"tiền\s+bối|đạo\s+hữu|huynh|tỷ"
    r")\b\s*[,，]",
    flags=re.IGNORECASE,
)
THIRD_PERSON_AFTER_VOCATIVE_PATTERN = re.compile(r"\b(hắn|y|anh ấy|ông ấy|người ấy)\b", flags=re.IGNORECASE)


def render_pronoun_memory() -> str:
    lines = ["Pronoun memory:"]
    for item in DEFAULT_PRONOUN_MEMORY:
        lines.append(f"- {item['character']}: {item['rules']}")
    lines.extend(
        [
            "- Direct address matrix:",
            "  * Lục ca/đại ca/huynh/sư huynh -> gọi người nghe là huynh; người nói thường xưng ta/đệ/muội.",
            "  * Sư tỷ/tỷ -> gọi người nghe là tỷ; người nói thường xưng ta/đệ/muội.",
            "  * Tiền bối/đạo hữu -> gọi người nghe là tiền bối/đạo hữu; người nói xưng vãn bối/ta.",
            "  * Sau một vocative cổ trang, không dùng hắn/y/anh ấy để chỉ chính người đang được gọi.",
        ]
    )
    return "\n".join(lines)


def find_modern_pronoun_issues(text: str) -> list[dict]:
    seen: set[str] = set()
    issues: list[dict] = []
    for match in MODERN_PRONOUN_PATTERN.finditer(text):
        pronoun = match.group(1).lower()
        if pronoun in seen:
            continue
        seen.add(pronoun)
        issues.append(
            {
                "type": "pronoun_modern",
                "severity": "high",
                "message": f"Từ xưng hô hiện đại '{pronoun}' xuất hiện trong bối cảnh cổ trang.",
                "suggested_fix": "Ưu tiên ta/ngươi/huynh/tỷ/đệ/muội/tiền bối tùy quan hệ nhân vật.",
            }
        )
    return issues


def find_direct_address_issues(text: str) -> list[dict]:
    issues: list[dict] = []
    for sentence in re.split(r"(?<=[.!?。？！\n])", text):
        vocative_match = CLASSICAL_VOCATIVE_PATTERN.search(sentence)
        if not vocative_match:
            continue
        pronoun_match = THIRD_PERSON_AFTER_VOCATIVE_PATTERN.search(sentence[vocative_match.end():])
        if not pronoun_match:
            continue
        vocative = vocative_match.group(1).strip()
        pronoun = pronoun_match.group(1).lower()
        issues.append(
            {
                "type": "pronoun_direct_address",
                "severity": "high",
                "message": (
                    f"Sau lời gọi '{vocative}', bản dịch dùng '{pronoun}' cho người đang được đối thoại."
                ),
                "suggested_fix": (
                    "Nếu đang nói trực tiếp với người đó, dùng huynh/tỷ/tiền bối/đạo hữu/ngươi theo quan hệ; "
                    "không dùng hắn/y/anh ấy."
                ),
                "segment": sentence.strip()[:240],
            }
        )
    return issues


def find_pronoun_issues(text: str) -> list[dict]:
    return find_modern_pronoun_issues(text) + find_direct_address_issues(text)
