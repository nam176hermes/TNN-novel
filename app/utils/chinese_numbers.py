from __future__ import annotations


CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

CHINESE_UNITS = {
    "十": 10,
    "百": 100,
    "千": 1000,
    "万": 10000,
}


def parse_chinese_number(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text in CHINESE_DIGITS:
        return CHINESE_DIGITS[text]

    total = 0
    section = 0
    number = 0
    saw_numeric = False
    for char in text:
        if char in CHINESE_DIGITS:
            number = CHINESE_DIGITS[char]
            saw_numeric = True
            continue
        unit = CHINESE_UNITS.get(char)
        if unit is None:
            return None
        saw_numeric = True
        if unit == 10000:
            section = (section + number) or 1
            total += section * unit
            section = 0
        else:
            section += (number or 1) * unit
        number = 0

    parsed = total + section + number
    return parsed if saw_numeric and parsed > 0 else None
