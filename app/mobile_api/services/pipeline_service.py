from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
import re
import struct
import time
from dataclasses import replace
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from collections.abc import Callable

from app.database.db import (
    get_style_profile,
    get_default_style_profile,
    get_book_by_id,
    delete_chapter_translation_data,
    get_chapter_by_id,
    get_provider_defaults,
    get_reader_dictionary_cache,
    get_reader_ai_cache,
    load_glossary,
    load_glossary_names,
    list_glossary,
    list_chapters,
    list_model_providers,
    list_reader_annotations,
    list_reader_timeline_events,
    list_reader_xray_entities,
    record_job_attempt,
    add_reader_entity,
    add_reader_entity_mention,
    add_reader_timeline_event,
    soft_delete_chapter,
    update_chapter_paths,
    upsert_reader_ai_cache,
    upsert_reader_dictionary_cache,
)
from app.ingestion.source_adapters import SourceChapterContent, get_source_registry
from app.mobile_api.services.content_file_service import ContentFileService
from app.mobile_api.services import book_service as _book_service
from app.mobile_api.services.book_service import BookService
from app.mobile_api.services.import_commit_service import ImportCommitService
from app.ingestion.import_result import ChapterImportResult

from app.mobile_api.services.reader_dictionary_service import (
    MAX_READER_DICTIONARY_ARCHIVE_FILES as _MAX_READER_DICTIONARY_ARCHIVE_FILES,
    MAX_READER_DICTIONARY_BYTES as _MAX_READER_DICTIONARY_BYTES,
    READER_OFFLINE_DICTIONARY_ARCHIVE_SUFFIXES as _READER_OFFLINE_DICTIONARY_ARCHIVE_SUFFIXES,
    READER_OFFLINE_DICTIONARY_DIR,
    READER_OFFLINE_DICTIONARY_SUFFIXES,
    ReaderDictionaryService,
)
from app.mobile_api.services.reader_service import ReaderService
from app.translation.ollama_client import call_llm, is_retryable_provider_error, translate_chapter
from app.translation.idiom_correction import clean_translation_layout, post_process_with_idioms
from app.translation.literary_style import LITERARY_STYLE_GUIDE, render_literary_phrase_guide
from app.audio.edge_tts_engine import text_to_speech_file
from app.services.tts.tts_pipeline import TTSPipeline
from app.translation.qa_reviewer import run_qa_check
from app.translation.cache import get_cache_stats
from app.translation.presets import get_translation_preset
from app.translation.pronoun_memory import render_pronoun_memory
from app.scheduler.daily_queue import get_pending_chapters, get_failed_chapters
from app.mobile_api.dependencies import get_data_dir, get_db_path
from app.config import settings
from app.services.tts.availability import is_f5_provider, require_tts_runtime_available
from app.translation.qa_report import merge_qa_report
from app.mobile_api.services.qa_service import build_deterministic_chapter_qa_report
from app.storage.chapter_content import publish_translation, retire_artifact, write_versioned_text
from app.storage.artifact_paths import ArtifactClass


logger = logging.getLogger(__name__)

# Compatibility aliases retained at the original module import path.
MAX_READER_DICTIONARY_ARCHIVE_FILES = _MAX_READER_DICTIONARY_ARCHIVE_FILES
MAX_READER_DICTIONARY_BYTES = _MAX_READER_DICTIONARY_BYTES
READER_OFFLINE_DICTIONARY_ARCHIVE_SUFFIXES = _READER_OFFLINE_DICTIONARY_ARCHIVE_SUFFIXES




TRANSLATED_CHAPTER_STATUSES = {"translated", "qa_low", "audio_done"}
BOOK_COVER_CONTENT_TYPES = _book_service.BOOK_COVER_CONTENT_TYPES
BOOK_COVER_SUFFIXES = _book_service.BOOK_COVER_SUFFIXES
MAX_BOOK_COVER_BYTES = _book_service.MAX_BOOK_COVER_BYTES
MAX_READER_XRAY_AUTO_CHAPTERS = 50
MAX_READER_XRAY_AUTO_ENTITIES = 24
MAX_READER_XRAY_AUTO_MENTIONS_PER_ENTITY = 6
MAX_READER_XRAY_ENRICH_CONTEXT_CHAPTERS = 8
MAX_READER_XRAY_ENRICH_CONTEXT_CHARS = 12_000
MAX_READER_XRAY_ENRICH_CONTEXT_CHARS_PER_CHAPTER = 2_500
DICTIONARY_LOOKUP_LIMIT = 12
ONLINE_DICTIONARY_TIMEOUT_SECONDS = 2.0
DICTIONARY_SOURCE_PRIORITY = {
    "glossary": 0,
    "offline_dictionary": 1,
    "builtin": 2,
    "xray": 3,
    "online": 4,
}
CJK_TRADITIONAL_TO_SIMPLIFIED = str.maketrans({
    "萬": "万",
    "與": "与",
    "專": "专",
    "業": "业",
    "東": "东",
    "絲": "丝",
    "兩": "两",
    "嚴": "严",
    "喪": "丧",
    "個": "个",
    "豐": "丰",
    "臨": "临",
    "為": "为",
    "麗": "丽",
    "舉": "举",
    "義": "义",
    "烏": "乌",
    "樂": "乐",
    "喬": "乔",
    "習": "习",
    "鄉": "乡",
    "書": "书",
    "買": "买",
    "亂": "乱",
    "爭": "争",
    "於": "于",
    "雲": "云",
    "亞": "亚",
    "產": "产",
    "畝": "亩",
    "親": "亲",
    "褻": "亵",
    "億": "亿",
    "僕": "仆",
    "從": "从",
    "倉": "仓",
    "儀": "仪",
    "們": "们",
    "價": "价",
    "眾": "众",
    "優": "优",
    "會": "会",
    "傘": "伞",
    "偉": "伟",
    "傳": "传",
    "傷": "伤",
    "倫": "伦",
    "傾": "倾",
    "僅": "仅",
    "儲": "储",
    "兒": "儿",
    "兇": "凶",
    "兌": "兑",
    "黨": "党",
    "蘭": "兰",
    "關": "关",
    "興": "兴",
    "獸": "兽",
    "內": "内",
    "岡": "冈",
    "冊": "册",
    "寫": "写",
    "軍": "军",
    "農": "农",
    "決": "决",
    "況": "况",
    "凍": "冻",
    "淨": "净",
    "幾": "几",
    "劍": "剑",
    "劑": "剂",
    "勁": "劲",
    "動": "动",
    "務": "务",
    "勝": "胜",
    "勞": "劳",
    "勢": "势",
    "勸": "劝",
    "區": "区",
    "醫": "医",
    "華": "华",
    "協": "协",
    "單": "单",
    "賣": "卖",
    "衛": "卫",
    "卻": "却",
    "廠": "厂",
    "歷": "历",
    "厲": "厉",
    "壓": "压",
    "縣": "县",
    "參": "参",
    "雙": "双",
    "發": "发",
    "變": "变",
    "臺": "台",
    "葉": "叶",
    "號": "号",
    "歎": "叹",
    "嘆": "叹",
    "後": "后",
    "嚇": "吓",
    "聽": "听",
    "啟": "启",
    "吳": "吴",
    "員": "员",
    "週": "周",
    "命": "命",
    "響": "响",
    "問": "问",
    "啞": "哑",
    "喚": "唤",
    "喲": "哟",
    "嘗": "尝",
    "嘯": "啸",
    "噴": "喷",
    "嚮": "向",
    "圖": "图",
    "團": "团",
    "園": "园",
    "國": "国",
    "圍": "围",
    "聖": "圣",
    "場": "场",
    "壞": "坏",
    "塊": "块",
    "堅": "坚",
    "壇": "坛",
    "墳": "坟",
    "執": "执",
    "壽": "寿",
    "夢": "梦",
    "頭": "头",
    "奪": "夺",
    "奮": "奋",
    "奧": "奥",
    "婦": "妇",
    "姍": "姗",
    "嬰": "婴",
    "學": "学",
    "宮": "宫",
    "寢": "寝",
    "實": "实",
    "寧": "宁",
    "寶": "宝",
    "對": "对",
    "尋": "寻",
    "導": "导",
    "將": "将",
    "層": "层",
    "屬": "属",
    "歲": "岁",
    "峽": "峡",
    "島": "岛",
    "嶺": "岭",
    "嶽": "岳",
    "巔": "巅",
    "師": "师",
    "帳": "帐",
    "帶": "带",
    "幫": "帮",
    "幹": "干",
    "庫": "库",
    "廟": "庙",
    "廢": "废",
    "廣": "广",
    "廳": "厅",
    "開": "开",
    "異": "异",
    "弒": "弑",
    "張": "张",
    "強": "强",
    "彈": "弹",
    "歸": "归",
    "當": "当",
    "錄": "录",
    "徑": "径",
    "徹": "彻",
    "憶": "忆",
    "懷": "怀",
    "態": "态",
    "總": "总",
    "戀": "恋",
    "恆": "恒",
    "惡": "恶",
    "惱": "恼",
    "悅": "悦",
    "懸": "悬",
    "驚": "惊",
    "懼": "惧",
    "懲": "惩",
    "慘": "惨",
    "慚": "惭",
    "慶": "庆",
    "慮": "虑",
    "憑": "凭",
    "懶": "懒",
    "應": "应",
    "戲": "戏",
    "戰": "战",
    "戶": "户",
    "才": "才",
    "扎": "扎",
    "掃": "扫",
    "揚": "扬",
    "擾": "扰",
    "撫": "抚",
    "拋": "抛",
    "搶": "抢",
    "護": "护",
    "報": "报",
    "擔": "担",
    "擬": "拟",
    "擁": "拥",
    "攔": "拦",
    "撥": "拨",
    "擇": "择",
    "擊": "击",
    "擋": "挡",
    "據": "据",
    "擠": "挤",
    "揮": "挥",
    "挾": "挟",
    "損": "损",
    "換": "换",
    "搗": "捣",
    "捲": "卷",
    "掙": "挣",
    "掛": "挂",
    "採": "采",
    "探": "探",
    "接": "接",
    "控": "控",
    "推": "推",
    "掩": "掩",
    "措": "措",
    "揀": "拣",
    "煉": "炼",
    "練": "练",
    "築": "筑",
    "氣": "气",
    "靈": "灵",
    "陣": "阵",
    "門": "门",
    "長": "长",
    "風": "风",
    "飛": "飞",
    "龍": "龙",
    "鳳": "凤",
    "體": "体",
    "術": "术",
    "級": "级",
    "階": "阶",
    "訣": "诀",
    "藥": "药",
    "塵": "尘",
    "虛": "虚",
    "無": "无",
    "轉": "转",
    "結": "结",
    "黃": "黄",
})
READER_BUILTIN_DICTIONARY_PROVIDER = "cn-vi-webnovel-lexicon"
READER_BUILTIN_DICTIONARY: tuple[dict[str, object], ...] = (
    {
        "term": "灵石",
        "target": "linh thạch",
        "category": "item",
        "definition": "Đá chứa linh khí, thường dùng để tu luyện, luyện khí, mua bán trong giới tu tiên.",
        "variants": ["linh thạch", "linh thach", "spirit stone"],
    },
    {
        "term": "灵气",
        "target": "linh khí",
        "category": "concept",
        "definition": "Khí/nguồn năng lượng trời đất mà tu sĩ hấp thu để tu luyện.",
        "variants": ["linh khí", "linh khi", "spiritual qi"],
    },
    {
        "term": "练气",
        "target": "Luyện Khí",
        "category": "realm",
        "definition": "Cảnh giới tu luyện sơ kỳ, lấy việc dẫn khí nhập thể làm căn cơ.",
        "variants": ["luyện khí", "luyen khi", "luyện khí kỳ"],
    },
    {
        "term": "筑基",
        "target": "Trúc Cơ",
        "category": "realm",
        "definition": "Cảnh giới đặt nền móng tu luyện sau Luyện Khí, thường là bước vào đạo đồ vững chắc.",
        "variants": ["trúc cơ", "truc co", "trúc cơ kỳ"],
    },
    {
        "term": "金丹",
        "target": "Kim Đan",
        "category": "realm",
        "definition": "Cảnh giới ngưng tụ kim đan trong đan điền; mốc quan trọng của tu tiên.",
        "variants": ["kim đan", "kim dan", "kim đan kỳ"],
    },
    {
        "term": "元婴",
        "target": "Nguyên Anh",
        "category": "realm",
        "definition": "Cảnh giới kết thành nguyên anh, thường có thần thông và thọ nguyên vượt xa Kim Đan.",
        "variants": ["nguyên anh", "nguyen anh", "nguyên anh kỳ"],
    },
    {
        "term": "化神",
        "target": "Hóa Thần",
        "category": "realm",
        "definition": "Cảnh giới cao hơn Nguyên Anh, thần thức và pháp lực bước sang tầng sâu hơn.",
        "variants": ["hóa thần", "hoa than"],
    },
    {
        "term": "宗门",
        "target": "tông môn",
        "category": "faction",
        "definition": "Môn phái/đạo thống tu luyện có truyền thừa, đệ tử, trưởng lão và chưởng môn.",
        "variants": ["tông môn", "tong mon", "môn phái"],
    },
    {
        "term": "掌门",
        "target": "chưởng môn",
        "category": "title",
        "definition": "Người đứng đầu môn phái hoặc tông môn.",
        "variants": ["chưởng môn", "chuong mon", "掌教"],
    },
    {
        "term": "长老",
        "target": "trưởng lão",
        "category": "title",
        "definition": "Bậc cao tầng trong tông môn, thường quản sự vụ, truyền công hoặc chấp pháp.",
        "variants": ["trưởng lão", "truong lao"],
    },
    {
        "term": "师兄",
        "target": "sư huynh",
        "category": "address",
        "definition": "Cách gọi nam đồng môn nhập môn trước hoặc có vai vế cao hơn.",
        "variants": ["sư huynh", "su huynh"],
    },
    {
        "term": "师姐",
        "target": "sư tỷ",
        "category": "address",
        "definition": "Cách gọi nữ đồng môn nhập môn trước hoặc có vai vế cao hơn.",
        "variants": ["sư tỷ", "su ty"],
    },
    {
        "term": "师弟",
        "target": "sư đệ",
        "category": "address",
        "definition": "Cách gọi nam đồng môn nhập môn sau hoặc vai vế thấp hơn.",
        "variants": ["sư đệ", "su de"],
    },
    {
        "term": "师妹",
        "target": "sư muội",
        "category": "address",
        "definition": "Cách gọi nữ đồng môn nhập môn sau hoặc vai vế thấp hơn.",
        "variants": ["sư muội", "su muoi"],
    },
    {
        "term": "前辈",
        "target": "tiền bối",
        "category": "address",
        "definition": "Cách xưng hô kính trọng với người có bối phận, tu vi hoặc kinh nghiệm cao hơn.",
        "variants": ["tiền bối", "tien boi"],
    },
    {
        "term": "道友",
        "target": "đạo hữu",
        "category": "address",
        "definition": "Cách gọi lịch sự giữa người tu đạo, thường giữ sắc thái cổ phong.",
        "variants": ["đạo hữu", "dao huu"],
    },
    {
        "term": "功法",
        "target": "công pháp",
        "category": "skill",
        "definition": "Pháp môn tu luyện hoặc bộ pháp quyết để vận chuyển linh lực.",
        "variants": ["công pháp", "cong phap"],
    },
    {
        "term": "法宝",
        "target": "pháp bảo",
        "category": "item",
        "definition": "Bảo vật được luyện chế có uy năng pháp thuật, dùng trong chiến đấu hoặc hộ thân.",
        "variants": ["pháp bảo", "phap bao"],
    },
    {
        "term": "飞剑",
        "target": "phi kiếm",
        "category": "item",
        "definition": "Kiếm được tu sĩ tế luyện để ngự sử, phi hành hoặc đấu pháp từ xa.",
        "variants": ["phi kiếm", "phi kiem", "flying sword"],
    },
    {
        "term": "储物袋",
        "target": "túi trữ vật",
        "category": "item",
        "definition": "Pháp khí chứa đồ có không gian riêng, thường dùng để cất linh thạch, đan dược và pháp bảo.",
        "variants": ["túi trữ vật", "tui tru vat", "túi chứa đồ", "storage bag"],
    },
    {
        "term": "丹药",
        "target": "đan dược",
        "category": "item",
        "definition": "Thuốc luyện thành đan, thường dùng để chữa thương, tăng tu vi hoặc phá cảnh.",
        "variants": ["đan dược", "dan duoc"],
    },
    {
        "term": "洞府",
        "target": "động phủ",
        "category": "location",
        "definition": "Nơi tu luyện, ẩn cư hoặc cư trú của tu sĩ.",
        "variants": ["động phủ", "dong phu"],
    },
    {
        "term": "江湖",
        "target": "giang hồ",
        "category": "concept",
        "definition": "Thế giới võ lâm/nhân sĩ hành tẩu; không nên dịch thô là sông hồ.",
        "variants": ["giang hồ", "giang ho"],
    },
    {
        "term": "剑气",
        "target": "kiếm khí",
        "category": "skill",
        "definition": "Khí thế hoặc kình lực phát ra từ kiếm, thường sắc bén như lưỡi kiếm vô hình.",
        "variants": ["kiếm khí", "kiem khi"],
    },
    {
        "term": "阵法",
        "target": "trận pháp",
        "category": "formation",
        "definition": "Pháp trận bố trí bằng trận kỳ, trận bàn hoặc linh lực để phòng hộ, vây khốn, công kích hay tụ linh.",
        "variants": ["trận pháp", "tran phap", "pháp trận"],
    },
    {
        "term": "禁制",
        "target": "cấm chế",
        "category": "formation",
        "definition": "Lớp hạn chế/phong ấn pháp thuật dùng để che giấu, bảo vệ hoặc ngăn kẻ khác xâm nhập.",
        "variants": ["cấm chế", "cam che"],
    },
    {
        "term": "机缘",
        "target": "cơ duyên",
        "category": "concept",
        "definition": "Duyên may, cơ hội đặc biệt dẫn tới truyền thừa, bảo vật hoặc đột phá.",
        "variants": ["cơ duyên", "co duyen"],
    },
    {
        "term": "神识",
        "target": "thần thức",
        "category": "concept",
        "definition": "Năng lực cảm nhận/tinh thần của tu sĩ dùng để dò xét, khống chế pháp bảo hoặc quan sát.",
        "variants": ["thần thức", "than thuc"],
    },
    {
        "term": "心魔",
        "target": "tâm ma",
        "category": "concept",
        "definition": "Ma chướng trong tâm cảnh, thường xuất hiện khi tu luyện, phá cảnh hoặc bị chấp niệm quấy nhiễu.",
        "variants": ["tâm ma", "tam ma", "inner demon"],
    },
    {
        "term": "丹田",
        "target": "đan điền",
        "category": "body",
        "definition": "Nơi tích tụ và vận chuyển linh lực/pháp lực trong thân thể tu sĩ.",
        "variants": ["đan điền", "dan dien"],
    },
    {
        "term": "宿主",
        "target": "ký chủ",
        "category": "system",
        "definition": "Người được hệ thống ràng buộc; không dịch là chủ nhà trong truyện hệ thống.",
        "variants": ["ký chủ", "ky chu", "host"],
    },
    {
        "term": "积分",
        "target": "điểm tích lũy",
        "category": "system",
        "definition": "Điểm thưởng/đơn vị trao đổi trong hệ thống; không dịch là tích phân ở ngữ cảnh truyện hệ thống.",
        "variants": ["điểm tích lũy", "diem tich luy", "điểm hệ thống"],
    },
    {
        "term": "系统",
        "target": "hệ thống",
        "category": "system",
        "definition": "Cơ chế siêu nhiên/giao diện nhiệm vụ, phần thưởng, bảng thông tin trong truyện hệ thống.",
        "variants": ["hệ thống", "he thong"],
    },
    {
        "term": "叮",
        "target": "Đinh",
        "category": "system",
        "definition": "Âm báo hệ thống. Khi đứng trong thông báo nên giữ dạng [Đinh!] hoặc [Đinh--].",
        "variants": ["đinh", "ding", "[đinh!]"],
    },
    {
        "term": "任务",
        "target": "nhiệm vụ",
        "category": "system",
        "definition": "Nhiệm vụ do hệ thống, môn phái hoặc thế lực giao phó.",
        "variants": ["nhiệm vụ", "nhiem vu"],
    },
)

_VIET_CAPITAL_WORD = (
    r"[A-ZÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝĂĐĨŨƠƯẠẢẤẦẨẪẬẮẰẲẴẶẸẺẼẾỀỂỄỆ"
    r"ỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰỲỴỶỸ]"
    r"[a-zàáâãèéêìíòóôõùúýăđĩũơưạảấầẩẫậắằẳẵặẹẻẽếềểễệ"
    r"ỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]*"
)
_VIET_PROPER_NAME_RE = re.compile(rf"\b{_VIET_CAPITAL_WORD}(?:\s+{_VIET_CAPITAL_WORD}){{1,3}}\b")
_XRAY_NAME_STOPWORDS = {
    "Ai",
    "Bởi",
    "Các",
    "Còn",
    "Cuối",
    "Dù",
    "Đến",
    "Đó",
    "Đột",
    "Hắn",
    "Khi",
    "Lúc",
    "Một",
    "Nàng",
    "Nếu",
    "Nhưng",
    "Rồi",
    "Sau",
    "Tại",
    "Theo",
    "Trong",
    "Trước",
    "Từ",
    "Vì",
}
_XRAY_NON_NAME_PHRASES = {
    "Chương",
    "Hồi",
}
_XRAY_REALM_KEYWORDS = (
    "Luyện Khí",
    "Trúc Cơ",
    "Kim Đan",
    "Nguyên Anh",
    "Hóa Thần",
    "Luyện Hư",
    "Hợp Thể",
    "Đại Thừa",
    "Độ Kiếp",
)
_XRAY_ORG_SUFFIXES = ("Tông", "Môn", "Phái", "Các", "Điện", "Cung", "Viện", "Bang", "Hội")
_XRAY_PLACE_SUFFIXES = ("Thôn", "Trấn", "Thành", "Sơn", "Cốc", "Đảo", "Quốc", "Vực", "Châu")


def _chapter_has_translation(chapter: dict) -> bool:
    status = str(chapter.get("status") or "")
    return bool(chapter.get("translated_text_path") or chapter.get("content_html_path")) or status in TRANSLATED_CHAPTER_STATUSES


def _build_retranslate_prompt(paragraph: str, style_profile: dict | None = None) -> str:
    return (
        "Translate this Chinese paragraph to Vietnamese.\n\n"
        f"Selected style: {json.dumps(style_profile or {}, ensure_ascii=False)}\n"
        f"{render_pronoun_memory()}\n"
        f"{render_literary_phrase_guide(paragraph)}\n\n"
        "Return only the Vietnamese translation.\n\n"
        f"Chinese paragraph:\n{paragraph}"
    )


def _build_polish_prompt(paragraph: str, instructions: str = "", style_profile: dict | None = None) -> str:
    extra_instructions = instructions.strip() or "Improve flow, fix awkward phrasing, keep meaning."
    return (
        "Polish this Vietnamese translation for a Chinese web novel.\n\n"
        f"Selected style: {json.dumps(style_profile or {}, ensure_ascii=False)}\n"
        f"{render_pronoun_memory()}\n"
        "Literary phrase guide:\n"
        f"{LITERARY_STYLE_GUIDE}\n\n"
        f"Additional instructions: {extra_instructions}\n"
        "Return only the polished Vietnamese paragraph.\n\n"
        f"Vietnamese paragraph:\n{paragraph}"
    )


def _build_chapter_polish_prompt(
    source_text: str,
    rough_translation: str,
    *,
    book_title: str,
    chapter_title: str,
    chapter_number: int,
    style_profile: dict | None = None,
) -> str:
    return (
        "Polish this chapter into fluent Vietnamese according to the selected style.\n\n"
        f"Selected style: {json.dumps(style_profile or {}, ensure_ascii=False)}\n"
        f"{render_pronoun_memory()}\n\n"
        f"{render_literary_phrase_guide(source_text)}\n\n"
        "Rules:\n"
        "- Keep every source paragraph represented; do not summarize.\n"
        "- Preserve pronoun referents and relationships; follow the selected style.\n"
        "- Keep names, kinship titles, cultivation terms, sects, places, and chapter meaning stable.\n"
        "- Return only the polished Vietnamese chapter.\n\n"
        f"Book: {book_title}\n"
        f"Chapter: {chapter_number} - {chapter_title}\n\n"
        f"Chinese source:\n{source_text}\n\n"
        f"Rough Vietnamese translation:\n{rough_translation}"
    )


def _build_qa_rewrite_prompt(
    source_text: str,
    polished_translation: str,
    qa_report: dict,
    *,
    book_title: str,
    chapter_title: str,
    chapter_number: int,
    style_profile: dict | None = None,
) -> str:
    return (
        "Rewrite only the flawed Vietnamese passages identified by QA, while preserving the full chapter.\n\n"
        f"Selected style: {json.dumps(style_profile or {}, ensure_ascii=False)}\n"
        f"{render_pronoun_memory()}\n\n"
        f"{render_literary_phrase_guide(source_text)}\n\n"
        "Return the complete corrected Vietnamese chapter only.\n\n"
        f"Book: {book_title}\n"
        f"Chapter: {chapter_number} - {chapter_title}\n\n"
        f"Chinese source:\n{source_text}\n\n"
        f"Current Vietnamese translation:\n{polished_translation}\n\n"
        f"QA issues:\n{json.dumps(qa_report.get('issues', []), ensure_ascii=False)}"
    )


def _split_reader_paragraphs(text: str) -> list[str]:
    return [paragraph.strip() for paragraph in re.split(r"\n{2,}", text) if paragraph.strip()]


def _reader_search_pattern(
    query: str,
    *,
    case_sensitive: bool = False,
    regex: bool = False,
    whole_word: bool = False,
) -> re.Pattern[str]:
    pattern = query.strip() if regex else re.escape(query.strip())
    if whole_word:
        pattern = rf"(?<![\w]){pattern}(?![\w])"
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(pattern, flags)


def _reader_search_snippet(text: str, start: int, match_length: int) -> str:
    left = max(0, start - 42)
    right = min(len(text), start + max(match_length, 1) + 42)
    return f"{'...' if left > 0 else ''}{text[left:right]}{'...' if right < len(text) else ''}"


def _reader_search_result(
    *,
    chapter: dict,
    char_end: int | None = None,
    char_start: int | None = None,
    source: str,
    paragraph_index: int,
    text: str,
    match: re.Match[str],
) -> dict:
    source_score = 100 if source == "translation" else 90 if source == "highlight" else 85
    safe_char_start = match.start() if char_start is None else max(0, int(char_start))
    safe_char_end = match.end() if char_end is None else max(safe_char_start, int(char_end))
    return {
        "chapter_id": chapter["id"],
        "chapter_number": chapter["chapter_number"],
        "chapter_title": chapter["title"],
        "char_start": safe_char_start,
        "char_end": safe_char_end,
        "snippet": _reader_search_snippet(text, match.start(), len(match.group(0))),
        "paragraph_index": paragraph_index,
        "score": max(1, source_score - paragraph_index),
        "source": source,
    }


def _normalize_reader_ai_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _reader_ai_text_hash(text: str) -> str:
    return hashlib.sha256(_normalize_reader_ai_text(text).encode("utf-8")).hexdigest()


def _matching_reader_terms(glossary: dict[str, str], text: str) -> list[dict]:
    normalized_text = _normalize_reader_ai_text(text)
    terms: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for source, target in glossary.items():
        if not source or not target:
            continue
        if source not in normalized_text and target not in normalized_text:
            continue
        key = (source, target)
        if key in seen:
            continue
        seen.add(key)
        terms.append({
            "source": source,
            "target": target,
            "note": "thuật ngữ trong glossary",
        })
        if len(terms) >= 8:
            break
    return terms


def _build_reader_explain_prompt(
    *,
    book_title: str,
    chapter_title: str,
    chapter_number: int,
    selected_text: str,
    context_before: str,
    context_after: str,
    spoiler_mode: str,
    glossary_terms: list[dict],
) -> str:
    spoiler_rule = (
        "Không tiết lộ nội dung sau đoạn được chọn. Chỉ giải thích dựa trên đoạn chọn và ngữ cảnh đã cung cấp."
        if spoiler_mode == "no_spoiler"
        else "Có thể dùng ngữ cảnh rộng hơn nếu cần, nhưng không bịa tình tiết."
    )
    glossary_text = "\n".join(
        f"- {term['source']} => {term['target']}: {term.get('note') or ''}".strip()
        for term in glossary_terms
    ) or "(không có term khớp sẵn)"
    return (
        "Bạn là trợ lý đọc tiểu thuyết Trung-Việt cho truyện tiên hiệp, kiếm hiệp, huyền huyễn.\n"
        "Giải thích ngắn gọn bằng tiếng Việt, văn phong tự nhiên, không sửa bản dịch gốc.\n"
        f"{spoiler_rule}\n\n"
        "Trả về JSON hợp lệ theo schema:\n"
        '{"explanation":"giải thích ngắn",'
        '"terms":[{"source":"筑基","target":"Trúc Cơ","note":"cảnh giới tu luyện"}]}\n\n'
        f"Truyện: {book_title}\n"
        f"Chương: {chapter_number} - {chapter_title}\n"
        f"Glossary khớp sẵn:\n{glossary_text}\n\n"
        f"Ngữ cảnh trước:\n{context_before or '(trống)'}\n\n"
        f"Đoạn được chọn:\n{selected_text}\n\n"
        f"Ngữ cảnh sau:\n{context_after or '(trống)'}"
    )


def _build_reader_xray_enrich_prompt(
    *,
    book_title: str,
    chapter_number: int | None,
    spoiler_mode: str,
    chapter_text: str,
    entities: list[dict],
    timeline: list[dict],
) -> str:
    spoiler_rule = (
        "No-spoiler: chỉ dùng thông tin tới chương hiện tại, không suy đoán sự kiện sau chương này."
        if spoiler_mode == "no_spoiler"
        else "Có thể dùng toàn bộ dữ liệu đã cung cấp, nhưng không bịa tình tiết."
    )
    def compact_relationships(metadata: dict) -> list[dict]:
        raw_relationships = metadata.get("relationships")
        if not isinstance(raw_relationships, list):
            return []
        relationships: list[dict] = []
        for relationship in raw_relationships[:8]:
            if not isinstance(relationship, dict):
                continue
            compact_relationship = {}
            for key in ("target", "relation", "evidence", "chapter_number", "strength", "source_type"):
                value = relationship.get(key)
                if value not in (None, "", []):
                    compact_relationship[key] = value
            if compact_relationship:
                relationships.append(compact_relationship)
        return relationships

    compact_entities = []
    for entity in entities[:40]:
        metadata = entity.get("metadata") if isinstance(entity.get("metadata"), dict) else {}
        compact_entities.append(
            {
                "name": entity.get("name"),
                "type": entity.get("type"),
                "aliases": entity.get("aliases", []),
                "description": entity.get("description"),
                "first_chapter_number": entity.get("first_chapter_number"),
                "faction": metadata.get("faction"),
                "factions": metadata.get("factions"),
                "parent": metadata.get("parent") or metadata.get("parent_faction"),
                "owner": metadata.get("owner"),
                "user": metadata.get("user"),
                "category": metadata.get("category"),
                "order": metadata.get("order"),
                "previous": metadata.get("previous"),
                "next": metadata.get("next"),
                "power_rank": metadata.get("power_rank"),
                "power_label": metadata.get("power_label"),
                "power_basis": metadata.get("power_basis"),
                "relationships": compact_relationships(metadata),
                "mentions": [
                    {
                        "chapter_number": mention.get("chapter_number"),
                        "context": mention.get("context"),
                    }
                    for mention in entity.get("mentions", [])[:3]
                ],
            }
        )
    compact_timeline = [
        {
            "chapter_number": event.get("chapter_number"),
            "event_order": event.get("event_order"),
            "title": event.get("title"),
            "summary": event.get("summary"),
            "entities": event.get("entities", []),
        }
        for event in timeline[:80]
    ]
    return (
        "Bạn là hệ thống X-Ray AI cho app đọc truyện tiên hiệp/kiếm hiệp/huyền huyễn.\n"
        "Nhiệm vụ: dựng relationship graph, faction tree, power ranking, cảnh giới, kỹ năng, vật phẩm và timeline sâu hơn từ dữ liệu hiện có.\n"
        f"{spoiler_rule}\n"
        "Trả về JSON hợp lệ, không markdown, đúng schema:\n"
        '{"entities":[{"name":"Hàn Lập","type":"character","aliases":["Hàn tiểu tử"],'
        '"description":"hồ sơ ngắn","faction":"Thất Huyền Môn","power_rank":12,'
        '"power_label":"Luyện Khí sơ kỳ","power_basis":"bằng chứng",'
        '"relationships":[{"target":"Mặc Cư Nhân","relation":"bị quan sát căn cốt",'
        '"evidence":"bằng chứng ngắn","chapter_number":2,"strength":0.8}]}],'
        '"relationships":[{"source":"Hàn Lập","target":"Trúc Cơ","relation":"đang hướng tới cảnh giới",'
        '"evidence":"bằng chứng ngắn","chapter_number":2,"strength":0.8}],'
        '"factions":[{"name":"Thất Huyền Môn","description":"mô tả","parent":"",'
        '"members":["Hàn Lập"],"chapter_number":2}],'
        '"power_rankings":[{"name":"Hàn Lập","rank":12,"label":"Luyện Khí hậu kỳ",'
        '"basis":"bằng chứng","faction":"Thất Huyền Môn"}],'
        '"items":[{"name":"Thanh Trúc Phong Vân Kiếm","description":"pháp khí",'
        '"owner":"Hàn Lập","category":"pháp khí","chapter_number":2}],'
        '"skills":[{"name":"Ngự Kiếm Thuật","description":"kiếm quyết",'
        '"user":"Hàn Lập","category":"kiếm quyết","chapter_number":2}],'
        '"realms":[{"name":"Luyện Khí","description":"cảnh giới nhập môn","order":1,'
        '"chapter_number":2}],'
        '"timeline":[{"chapter_number":2,"event_order":2,"title":"sự kiện","summary":"tóm tắt",'
        '"entities":["Hàn Lập"]}]}\n\n'
        f"Truyện: {book_title}\n"
        f"Chương hiện tại: {chapter_number or '(không rõ)'}\n"
        f"Entities hiện có:\n{json.dumps(compact_entities, ensure_ascii=False)}\n\n"
        f"Timeline hiện có:\n{json.dumps(compact_timeline, ensure_ascii=False)}\n\n"
        f"Nội dung chương tham chiếu:\n{chapter_text[:12000] or '(trống)'}"
    )


def _json_object_from_llm_text(text: str) -> dict:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    if not value.startswith("{"):
        start = value.find("{")
        end = value.rfind("}")
        if start >= 0 and end > start:
            value = value[start:end + 1]
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_reader_explain_response(
    raw: dict,
    *,
    selected_text: str,
    fallback_terms: list[dict],
) -> dict:
    explanation = str(raw.get("explanation") or "").strip()
    if not explanation:
        explanation = (
            f"Đoạn được chọn: “{selected_text}”. "
            "Chưa có phản hồi AI chi tiết; hãy dùng glossary bên dưới nếu có thuật ngữ khớp."
        )

    raw_terms = raw.get("terms", [])
    if not isinstance(raw_terms, list):
        raw_terms = []
    terms: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in [*fallback_terms, *raw_terms]:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        note = str(item.get("note") or "").strip()
        if not source and not target:
            continue
        key = (source, target)
        if key in seen:
            continue
        seen.add(key)
        terms.append({"source": source, "target": target, "note": note})
    return {
        "explanation": explanation,
        "terms": terms[:10],
    }


def _reader_xray_plain_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\r\n?", "\n", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _reader_xray_context(text: str, start: int, match_length: int) -> str:
    left = max(0, start - 48)
    right = min(len(text), start + max(match_length, 1) + 72)
    return text[left:right].strip()


def _reader_xray_entity_type(name: str) -> str:
    if any(keyword in name for keyword in _XRAY_REALM_KEYWORDS):
        return "realm"
    if name.endswith(_XRAY_ORG_SUFFIXES):
        return "faction"
    if name.endswith(_XRAY_PLACE_SUFFIXES):
        return "location"
    return "character"


def _reader_xray_is_plausible_name(name: str) -> bool:
    words = name.split()
    if len(words) < 2 or len(words) > 4:
        return False
    if words[0] in _XRAY_NAME_STOPWORDS:
        return False
    if any(word in _XRAY_NON_NAME_PHRASES for word in words):
        return False
    return len(name) <= 40


def _reader_xray_add_candidate(
    candidates: dict[str, dict],
    *,
    name: str,
    entity_type: str,
    chapter: dict,
    paragraph_index: int,
    mention_text: str,
    context: str,
    aliases: list[str] | None = None,
    source: str,
) -> None:
    name = re.sub(r"\s+", " ", name).strip(" ,.;:!?“”\"'")
    mention_text = mention_text.strip()
    if not name or not mention_text:
        return
    item = candidates.setdefault(
        name,
        {
            "name": name,
            "entity_type": entity_type,
            "aliases": [],
            "first_chapter_number": int(chapter.get("chapter_number") or 0),
            "mentions": [],
            "source": source,
        },
    )
    item["first_chapter_number"] = min(
        int(item["first_chapter_number"] or 0),
        int(chapter.get("chapter_number") or 0),
    )
    for alias in aliases or []:
        alias = alias.strip()
        if alias and alias != name and alias not in item["aliases"]:
            item["aliases"].append(alias)
    mentions = item["mentions"]
    if len(mentions) >= MAX_READER_XRAY_AUTO_MENTIONS_PER_ENTITY:
        return
    mention_key = (chapter["id"], paragraph_index, mention_text)
    if any(existing["key"] == mention_key for existing in mentions):
        return
    mentions.append(
        {
            "key": mention_key,
            "chapter_id": chapter["id"],
            "chapter_number": int(chapter.get("chapter_number") or 0),
            "paragraph_index": paragraph_index,
            "mention_text": mention_text,
            "context": context,
        }
    )


def _reader_xray_match_glossary_terms(
    *,
    candidates: dict[str, dict],
    chapter: dict,
    paragraph_index: int,
    paragraph: str,
    glossary: dict[str, str],
) -> None:
    for source, target in glossary.items():
        source = str(source or "").strip()
        target = str(target or "").strip()
        if not source or not target:
            continue
        matched_text = ""
        start = -1
        for term in (target, source):
            if not term:
                continue
            start = paragraph.find(term)
            if start >= 0:
                matched_text = term
                break
        if start < 0:
            continue
        _reader_xray_add_candidate(
            candidates,
            name=target,
            entity_type=_reader_xray_entity_type(target),
            chapter=chapter,
            paragraph_index=paragraph_index,
            mention_text=matched_text,
            context=_reader_xray_context(paragraph, start, len(matched_text)),
            aliases=[source],
            source="glossary",
        )


def _reader_xray_match_proper_names(
    *,
    candidates: dict[str, dict],
    chapter: dict,
    paragraph_index: int,
    paragraph: str,
) -> None:
    for match in _VIET_PROPER_NAME_RE.finditer(paragraph):
        name = match.group(0).strip()
        words = name.split()
        if words and words[0] in _XRAY_NAME_STOPWORDS:
            name = " ".join(words[1:])
        if not _reader_xray_is_plausible_name(name):
            continue
        _reader_xray_add_candidate(
            candidates,
            name=name,
            entity_type=_reader_xray_entity_type(name),
            chapter=chapter,
            paragraph_index=paragraph_index,
            mention_text=name,
            context=_reader_xray_context(paragraph, match.start(), len(name)),
            source="heuristic",
        )


def _reader_xray_timeline_summary(paragraphs: list[str], entity_names: list[str]) -> str:
    lead = _normalize_reader_ai_text(paragraphs[0]) if paragraphs else ""
    if len(lead) > 180:
        lead = f"{lead[:177].rstrip()}..."
    if entity_names:
        names = ", ".join(entity_names[:4])
        return f"Chương có diễn biến liên quan đến {names}. {lead}".strip()
    return lead or "Chương đã được đưa vào tuyến sự kiện đọc."


def _dictionary_match_forms(value: str) -> set[str]:
    normalized = re.sub(r"\s+", " ", str(value or "").casefold()).strip()
    if not normalized:
        return set()
    folded = normalized.translate(CJK_TRADITIONAL_TO_SIMPLIFIED)
    no_accents = normalized.replace("đ", "d")
    no_accents = "".join(
        char
        for char in unicodedata.normalize("NFD", no_accents)
        if unicodedata.category(char) != "Mn"
    )
    folded_no_accents = folded.replace("đ", "d")
    folded_no_accents = "".join(
        char
        for char in unicodedata.normalize("NFD", folded_no_accents)
        if unicodedata.category(char) != "Mn"
    )
    return {normalized, folded, no_accents, folded_no_accents}


def _dictionary_match_score(query: str, *values: str) -> tuple[int, int, int] | None:
    query_forms = _dictionary_match_forms(query)
    if not query_forms:
        return None
    best_score: tuple[int, int, int] | None = None
    for value in values:
        value_forms = _dictionary_match_forms(value)
        if not value_forms:
            continue
        for normalized_query in query_forms:
            for normalized_value in value_forms:
                if normalized_query == normalized_value:
                    score = (0, 0, -len(normalized_value))
                elif normalized_value in normalized_query:
                    score = (1, normalized_query.find(normalized_value), -len(normalized_value))
                elif normalized_query in normalized_value:
                    score = (2, normalized_value.find(normalized_query), -len(normalized_query))
                else:
                    continue
                if best_score is None or score < best_score:
                    best_score = score
    return best_score


def _dictionary_query_matches(query: str, *values: str) -> bool:
    return _dictionary_match_score(query, *values) is not None


def _dictionary_source_values(source: dict) -> list[str]:
    values = [
        str(source.get("term") or ""),
        str(source.get("target") or ""),
        str(source.get("definition") or ""),
        str(source.get("category") or ""),
        str(source.get("provider") or ""),
        str(source.get("part_of_speech") or ""),
    ]
    for key in ("aliases", "variants"):
        items = source.get(key) or []
        if isinstance(items, str):
            values.extend(_dictionary_split_variants(items))
        elif isinstance(items, list):
            values.extend(str(item) for item in items)
    return [value for value in values if value.strip()]


def _rank_dictionary_sources(query: str, sources: list[dict]) -> list[dict]:
    ranked: list[tuple[tuple[int, int, int], int, int, dict]] = []
    for index, source in enumerate(sources):
        score = _dictionary_match_score(query, *_dictionary_source_values(source))
        if score is None:
            score = (9, 1_000_000, 0)
        source_priority = DICTIONARY_SOURCE_PRIORITY.get(str(source.get("source") or ""), 99)
        ranked.append((score, source_priority, index, source))
    return [item[3] for item in sorted(ranked, key=lambda item: item[:3])]


def _dictionary_split_variants(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,;\n|]+", value) if item.strip()]


def _dictionary_contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value))


def _fetch_mymemory_cjk_translation(normalized: str, *, timeout: float) -> list[dict]:
    url = "https://api.mymemory.translated.net/get?" + urlencode({
        "q": normalized,
        "langpair": "zh-CN|vi",
    })
    request = Request(url, headers={"User-Agent": "novel-pipeline-reader/1.0"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed public dictionary host
        payload = json.loads(response.read().decode("utf-8"))

    candidates: list[str] = []
    if isinstance(payload, dict):
        response_data = payload.get("responseData")
        if isinstance(response_data, dict):
            candidates.append(str(response_data.get("translatedText") or ""))
        for match in payload.get("matches") or []:
            if isinstance(match, dict):
                candidates.append(str(match.get("translation") or ""))

    for candidate in candidates:
        target = _normalize_reader_ai_text(candidate)
        if target and target.casefold() != normalized.casefold():
            return [
                {
                    "source": "online",
                    "provider": "mymemory.translated.net",
                    "term": normalized,
                    "target": target,
                    "definition": "Bản dịch nhanh Trung-Việt từ MyMemory.",
                    "part_of_speech": "translation",
                }
            ]
    return []


def _fetch_wiktionary_cjk_lookup(normalized: str, *, timeout: float) -> list[dict]:
    url = (
        "https://zh.wiktionary.org/w/api.php"
        f"?action=query&format=json&prop=extracts&exintro=1&explaintext=1&redirects=1&titles={quote(normalized)}"
    )
    request = Request(url, headers={"User-Agent": "novel-pipeline-reader/1.0"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed public dictionary host
        payload = json.loads(response.read().decode("utf-8"))

    pages = ((payload.get("query") or {}).get("pages") or {}) if isinstance(payload, dict) else {}
    if not isinstance(pages, dict):
        return []

    results: list[dict] = []
    for page in pages.values():
        if not isinstance(page, dict) or page.get("missing") is not None:
            continue
        extract = str(page.get("extract") or "").strip()
        if not extract:
            continue
        if len(extract) > 420:
            extract = f"{extract[:417].rstrip()}..."
        results.append(
            {
                "source": "online",
                "provider": "zh.wiktionary.org",
                "term": str(page.get("title") or normalized).strip(),
                "definition": extract,
                "part_of_speech": "",
            }
        )
        if len(results) >= 2:
            break
    return results


def fetch_online_dictionary_lookup(query: str, *, timeout: float = ONLINE_DICTIONARY_TIMEOUT_SECONDS) -> list[dict]:
    """Best-effort public dictionary lookup.

    The reader dictionary is offline-first. This helper is intentionally small
    and monkeypatchable so network failures never break the reader endpoint.
    """
    normalized = query.strip()
    if _dictionary_contains_cjk(normalized):
        try:
            translated = _fetch_mymemory_cjk_translation(normalized, timeout=timeout)
        except Exception:
            translated = []
        if translated:
            return translated
        return _fetch_wiktionary_cjk_lookup(normalized, timeout=timeout)

    if not re.fullmatch(r"[A-Za-z][A-Za-z '-]{0,63}", normalized):
        return []

    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{quote(normalized)}"
    request = Request(url, headers={"User-Agent": "novel-pipeline-reader/1.0"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed public dictionary host
        payload = json.loads(response.read().decode("utf-8"))

    results: list[dict] = []
    for entry in payload if isinstance(payload, list) else []:
        word = str(entry.get("word") or normalized).strip()
        for meaning in entry.get("meanings") or []:
            part_of_speech = str(meaning.get("partOfSpeech") or "").strip()
            for definition in meaning.get("definitions") or []:
                text = str(definition.get("definition") or "").strip()
                if not text:
                    continue
                results.append(
                    {
                        "source": "online",
                        "provider": "dictionaryapi.dev",
                        "term": word,
                        "definition": text,
                        "part_of_speech": part_of_speech,
                    }
                )
                if len(results) >= 3:
                    return results
    return results


def _reader_dictionary_builtin_results(query: str) -> list[dict]:
    results: list[dict] = []
    for entry in READER_BUILTIN_DICTIONARY:
        variants = [str(item) for item in entry.get("variants", []) if str(item).strip()]
        if not _dictionary_query_matches(
            query,
            str(entry.get("term") or ""),
            str(entry.get("target") or ""),
            str(entry.get("definition") or ""),
            *variants,
        ):
            continue
        results.append(_reader_dictionary_builtin_entry(entry))
    return results


def _reader_dictionary_builtin_entry(entry: dict[str, object]) -> dict:
    variants = [str(item) for item in entry.get("variants", []) if str(item).strip()]
    return {
        "source": "builtin",
        "provider": READER_BUILTIN_DICTIONARY_PROVIDER,
        "term": str(entry.get("term") or ""),
        "target": str(entry.get("target") or ""),
        "definition": str(entry.get("definition") or ""),
        "category": str(entry.get("category") or "term"),
        "variants": variants,
    }


def _reader_dictionary_builtin_pack_results() -> list[dict]:
    return [_reader_dictionary_builtin_entry(entry) for entry in READER_BUILTIN_DICTIONARY]


def _reader_dictionary_file_entry(row: dict, provider: str) -> dict | None:
    normalized_row = {str(key or "").strip().casefold(): value for key, value in row.items()}
    term = str(
        normalized_row.get("term")
        or normalized_row.get("source_term")
        or normalized_row.get("source")
        or "",
    ).strip()
    target = str(
        normalized_row.get("target")
        or normalized_row.get("target_term")
        or normalized_row.get("translation")
        or "",
    ).strip()
    definition = str(
        normalized_row.get("definition")
        or normalized_row.get("note")
        or normalized_row.get("notes")
        or normalized_row.get("notes_vi")
        or "",
    ).strip()
    category = str(normalized_row.get("category") or normalized_row.get("term_type") or "term").strip() or "term"
    variants = _dictionary_split_variants(str(normalized_row.get("variants") or normalized_row.get("aliases") or ""))

    if not term and not target:
        return None

    return {
        "source": "offline_dictionary",
        "provider": provider,
        "term": term,
        "target": target,
        "definition": definition or target or term,
        "category": category,
        "variants": variants,
    }


def _reader_dictionary_rows_from_json_file(path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        terms = payload.get("terms") or payload.get("entries") or payload.get("dictionary")
        if isinstance(terms, list):
            return [item for item in terms if isinstance(item, dict)]
        return [payload]
    return []


def _reader_dictionary_rows_from_jsonl_file(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
    except (OSError, UnicodeDecodeError):
        return []
    return rows


def _reader_dictionary_rows_from_delimited_file(path: Path, *, delimiter: str) -> list[dict]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = [
                [column.strip() for column in row]
                for row in csv.reader(handle, delimiter=delimiter)
                if any(column.strip() for column in row)
            ]
    except (OSError, UnicodeDecodeError, csv.Error):
        return []

    rows = [row for row in rows if not (row[0] if row else "").startswith("#")]
    if not rows:
        return []

    header_aliases = {
        "aliases",
        "category",
        "definition",
        "note",
        "notes",
        "notes_vi",
        "source",
        "source_term",
        "target",
        "target_term",
        "term",
        "term_type",
        "translation",
        "variants",
    }
    first_row_keys = {column.casefold() for column in rows[0]}
    if first_row_keys & header_aliases:
        header = rows[0]
        return [
            {header[index]: value for index, value in enumerate(row) if index < len(header)}
            for row in rows[1:]
        ]

    field_names = ["term", "target", "definition", "variants", "category"]
    return [
        {field_names[index]: value for index, value in enumerate(row) if index < len(field_names)}
        for row in rows
    ]


def _reader_dictionary_rows_from_tsv_file(path: Path) -> list[dict]:
    return _reader_dictionary_rows_from_delimited_file(path, delimiter="\t")


def _reader_dictionary_rows_from_csv_file(path: Path) -> list[dict]:
    return _reader_dictionary_rows_from_delimited_file(path, delimiter=",")


def _reader_dictionary_rows_from_cedict_file(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        return []

    pattern = re.compile(r"^(\S+)\s+(\S+)\s+\[([^\]]+)\]\s+/(.*)/\s*$")
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        match = pattern.match(text)
        if not match:
            continue
        traditional, simplified, pinyin, definition_blob = match.groups()
        definitions = [item.strip() for item in definition_blob.split("/") if item.strip()]
        variants = [traditional, pinyin, *definitions]
        rows.append(
            {
                "term": simplified,
                "target": pinyin,
                "definition": "; ".join(definitions),
                "category": "cc-cedict",
                "variants": "|".join(dict.fromkeys(item for item in variants if item and item != simplified)),
            }
        )
    return rows


def _reader_dictionary_rows_from_dsl_file(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        return []

    current_term = ""
    current_definition_lines: list[str] = []

    def clean_dsl_text(value: str) -> str:
        text = value.strip()
        text = re.sub(r"\[/?[a-z][^\]]*\]", "", text, flags=re.IGNORECASE)
        text = text.replace("\\[", "[").replace("\\]", "]")
        return re.sub(r"\s+", " ", text).strip()

    def flush_current_entry() -> None:
        nonlocal current_term, current_definition_lines
        term = clean_dsl_text(current_term)
        cleaned_lines = [clean_dsl_text(line) for line in current_definition_lines]
        cleaned_lines = [line for line in cleaned_lines if line]
        if term and cleaned_lines:
            variants = ""
            body_lines: list[str] = []
            for line in cleaned_lines:
                if line.casefold().startswith("variants:"):
                    variants = line.split(":", 1)[1].strip()
                elif line.casefold().startswith("aliases:") and not variants:
                    variants = line.split(":", 1)[1].strip()
                else:
                    body_lines.append(line)
            target = body_lines[0] if body_lines else term
            definition_lines = body_lines[1:] if len(body_lines) > 1 else body_lines
            rows.append(
                {
                    "term": term,
                    "target": target,
                    "definition": " ".join(definition_lines).strip() or target,
                    "category": "term",
                    "variants": variants,
                }
            )
        current_term = ""
        current_definition_lines = []

    for raw_line in lines:
        if not raw_line.strip():
            flush_current_entry()
            continue
        if raw_line.lstrip().startswith("#"):
            continue
        if raw_line[:1].isspace():
            if current_term:
                current_definition_lines.append(raw_line)
            continue
        flush_current_entry()
        current_term = raw_line.strip()

    flush_current_entry()
    return rows


def _reader_dictionary_stardict_options(ifo_content: bytes) -> dict[str, str]:
    try:
        lines = ifo_content.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError:
        lines = ifo_content.decode("utf-8", errors="ignore").splitlines()
    options: dict[str, str] = {}
    for line in lines:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        options[key.strip().casefold()] = value.strip()
    return options


def _clean_stardict_definition_line(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = re.sub(r"\[/?[a-z][^\]]*\]", "", text, flags=re.IGNORECASE)
    text = text.replace("\\n", "\n")
    return re.sub(r"\s+", " ", text).strip()


def _reader_dictionary_row_from_stardict_definition(term: str, definition: str) -> dict | None:
    lines = [_clean_stardict_definition_line(line) for line in definition.replace("\r\n", "\n").splitlines()]
    lines = [line for line in lines if line]
    if not term.strip() or not lines:
        return None

    variants = ""
    category = "stardict"
    body_lines: list[str] = []
    for line in lines:
        lowered = line.casefold()
        if lowered.startswith("variants:") or lowered.startswith("aliases:"):
            variants = line.split(":", 1)[1].strip()
        elif lowered.startswith("category:"):
            category = line.split(":", 1)[1].strip() or category
        else:
            body_lines.append(line)

    target = body_lines[0] if body_lines else term
    definition_lines = body_lines[1:] if len(body_lines) > 1 else body_lines
    return {
        "term": term.strip(),
        "target": target,
        "definition": " ".join(definition_lines).strip() or target,
        "category": category,
        "variants": variants,
    }


def _reader_dictionary_rows_from_stardict_bytes(
    *,
    ifo_content: bytes,
    idx_content: bytes,
    dict_content: bytes,
) -> list[dict]:
    options = _reader_dictionary_stardict_options(ifo_content)
    offset_size = 8 if options.get("idxoffsetbits") == "64" else 4
    offset_format = ">Q" if offset_size == 8 else ">I"
    rows: list[dict] = []
    cursor = 0
    while cursor < len(idx_content):
        separator = idx_content.find(b"\0", cursor)
        if separator < 0:
            break
        try:
            term = idx_content[cursor:separator].decode("utf-8").strip()
        except UnicodeDecodeError:
            term = idx_content[cursor:separator].decode("utf-8", errors="ignore").strip()
        cursor = separator + 1
        if not term:
            break
        if cursor + offset_size + 4 > len(idx_content):
            break

        offset = struct.unpack(offset_format, idx_content[cursor:cursor + offset_size])[0]
        cursor += offset_size
        size = struct.unpack(">I", idx_content[cursor:cursor + 4])[0]
        cursor += 4
        if offset < 0 or size <= 0 or offset + size > len(dict_content):
            continue
        definition_bytes = dict_content[offset:offset + size]
        try:
            definition = definition_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            definition = definition_bytes.decode("utf-8", errors="ignore")
        row = _reader_dictionary_row_from_stardict_definition(term, definition)
        if row is not None:
            rows.append(row)
    return rows


def _reader_dictionary_jsonl_bytes(rows: list[dict]) -> bytes:
    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _reader_dictionary_file_rows(path: Path) -> list[dict]:
    suffix = path.suffix.casefold()
    if suffix == ".json":
        return _reader_dictionary_rows_from_json_file(path)
    if suffix == ".jsonl":
        return _reader_dictionary_rows_from_jsonl_file(path)
    if suffix == ".tsv":
        return _reader_dictionary_rows_from_tsv_file(path)
    if suffix == ".csv":
        return _reader_dictionary_rows_from_csv_file(path)
    if suffix == ".dsl":
        return _reader_dictionary_rows_from_dsl_file(path)
    if suffix in {".u8", ".txt"}:
        return _reader_dictionary_rows_from_cedict_file(path)
    return []


def _reader_dictionary_file_results(data_dir: Path, query: str) -> list[dict]:
    dictionaries_dir = data_dir / READER_OFFLINE_DICTIONARY_DIR
    if not dictionaries_dir.exists() or not dictionaries_dir.is_dir():
        return []

    results: list[dict] = []
    for path in sorted(dictionaries_dir.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.suffix.casefold() not in READER_OFFLINE_DICTIONARY_SUFFIXES:
            continue
        for row in _reader_dictionary_file_rows(path):
            entry = _reader_dictionary_file_entry(row, path.name)
            if entry is None:
                continue
            if not _dictionary_query_matches(
                query,
                entry.get("term") or "",
                entry.get("target") or "",
                entry.get("definition") or "",
                *[str(item) for item in entry.get("variants") or []],
            ):
                continue
            results.append(entry)
            if len(results) >= DICTIONARY_LOOKUP_LIMIT:
                return results
    return results


def _reader_dictionary_file_pack_results(data_dir: Path) -> list[dict]:
    dictionaries_dir = data_dir / READER_OFFLINE_DICTIONARY_DIR
    if not dictionaries_dir.exists() or not dictionaries_dir.is_dir():
        return []

    results: list[dict] = []
    for path in sorted(dictionaries_dir.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.suffix.casefold() not in READER_OFFLINE_DICTIONARY_SUFFIXES:
            continue
        for row in _reader_dictionary_file_rows(path):
            entry = _reader_dictionary_file_entry(row, path.name)
            if entry is not None:
                results.append(entry)
    return results


def _reader_dictionary_glossary_result(term: dict) -> dict:
    variants = _dictionary_split_variants(term.get("variants"))
    return {
        "source": "glossary",
        "term": term.get("source_term") or "",
        "target": term.get("target_term") or "",
        "definition": term.get("notes_vi") or term.get("target_term") or "",
        "category": term.get("category") or term.get("term_type") or "term",
        "book_id": int(term.get("book_id") or 0),
        "mode": term.get("mode") or "",
        "variants": variants,
    }


def _reader_dictionary_xray_result(entity: dict) -> dict:
    mentions = entity.get("mentions") or []
    first_mention = mentions[0] if mentions else {}
    return {
        "source": "xray",
        "term": entity.get("name") or "",
        "target": entity.get("name") or "",
        "definition": entity.get("description") or first_mention.get("context") or "",
        "category": entity.get("entity_type") or "entity",
        "aliases": entity.get("aliases") or [],
        "first_chapter_number": int(entity.get("first_chapter_number") or 0),
        "mention_count": int(entity.get("mention_count") or len(mentions)),
        "mentions": mentions[:3],
    }


def _dedupe_dictionary_sources(sources: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for source in sources:
        key = (
            str(source.get("source") or ""),
            str(source.get("term") or "").casefold(),
            str(source.get("target") or "").casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
        if len(deduped) >= DICTIONARY_LOOKUP_LIMIT:
            break
    return deduped


def _dedupe_dictionary_pack_sources(sources: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for source in sources:
        key = (
            str(source.get("source") or ""),
            str(source.get("term") or "").casefold(),
            str(source.get("target") or "").casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


def _reader_dictionary_pack_counts(sources: list[dict]) -> dict:
    counts = {
        "glossary": 0,
        "builtin": 0,
        "offline_dictionary": 0,
        "xray": 0,
    }
    for source in sources:
        source_name = str(source.get("source") or "")
        if source_name in counts:
            counts[source_name] += 1
    return counts


def _metadata_string(metadata: dict, *keys: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _metadata_number(metadata: dict, *keys: str) -> float | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str) and value.strip():
            try:
                return float(value)
            except ValueError:
                continue
    return None


def _metadata_string_list(metadata: dict, key: str) -> list[str]:
    value = metadata.get(key)
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _reader_xray_graph_entities(entities: list[dict], full_entities: list[dict]) -> list[dict]:
    full_by_id = {entity["id"]: entity for entity in full_entities}
    graph_entities: list[dict] = []
    for entity in entities:
        full = full_by_id.get(entity["id"], {})
        graph_entities.append(
            {
                **entity,
                "aliases": full.get("aliases", entity.get("aliases", [])),
                "description": full.get("description", entity.get("description", "")),
                "metadata": full.get("metadata", entity.get("metadata", {})),
            }
        )
    return graph_entities


def _relationship_payload(
    *,
    source: str,
    target: str,
    relation: str,
    evidence: str,
    chapter_number: int,
    strength: float,
    source_type: str,
) -> dict:
    return {
        "source": source,
        "target": target,
        "relation": relation,
        "evidence": evidence,
        "chapter_number": max(0, int(chapter_number or 0)),
        "strength": round(max(0.0, min(1.0, float(strength))), 3),
        "source_type": source_type,
    }


def _reader_xray_relationships(
    entities: list[dict],
    timeline: list[dict],
    *,
    max_chapter_number: int | None,
) -> list[dict]:
    visible_names = {str(entity.get("name") or "") for entity in entities}
    relationships: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    def add_relationship(payload: dict) -> None:
        if not payload["source"] or not payload["target"]:
            return
        if payload["source"] not in visible_names or payload["target"] not in visible_names:
            return
        if max_chapter_number is not None and payload["chapter_number"] > max_chapter_number:
            return
        key = (payload["source"], payload["target"], payload["relation"])
        if key in seen:
            return
        seen.add(key)
        relationships.append(payload)

    for entity in entities:
        metadata = entity.get("metadata") if isinstance(entity.get("metadata"), dict) else {}
        raw_relationships = metadata.get("relationships")
        if not isinstance(raw_relationships, list):
            continue
        for raw in raw_relationships:
            if not isinstance(raw, dict):
                continue
            target = str(raw.get("target") or "").strip()
            relation = str(raw.get("relation") or raw.get("type") or "liên hệ").strip()
            evidence = str(raw.get("evidence") or raw.get("summary") or "").strip()
            chapter_number = int(raw.get("chapter_number") or entity.get("first_chapter_number") or 0)
            strength = raw.get("strength")
            add_relationship(
                _relationship_payload(
                    source=str(entity.get("name") or ""),
                    target=target,
                    relation=relation,
                    evidence=evidence,
                    chapter_number=chapter_number,
                    strength=float(strength) if isinstance(strength, int | float) else 0.75,
                    source_type=str(raw.get("source_type") or "metadata"),
                )
            )

    for event in timeline:
        names = [name for name in event.get("entities", []) if name in visible_names]
        if len(names) < 2:
            continue
        source = names[0]
        for target in names[1:]:
            add_relationship(
                _relationship_payload(
                    source=source,
                    target=target,
                    relation="cùng sự kiện",
                    evidence=str(event.get("summary") or event.get("title") or ""),
                    chapter_number=int(event.get("chapter_number") or 0),
                    strength=0.5,
                    source_type="timeline",
                )
            )

    return relationships


def _entity_factions(entity: dict) -> list[str]:
    metadata = entity.get("metadata") if isinstance(entity.get("metadata"), dict) else {}
    factions = _metadata_string_list(metadata, "factions")
    faction = _metadata_string(metadata, "faction", "sect", "organization")
    if faction:
        factions.append(faction)
    return list(dict.fromkeys(factions))


def _reader_xray_faction_tree(entities: list[dict]) -> list[dict]:
    faction_entities = [entity for entity in entities if entity.get("type") == "faction"]
    faction_names = {str(entity.get("name") or "") for entity in faction_entities}
    members_by_faction: dict[str, list[str]] = {name: [] for name in faction_names}
    children_by_parent: dict[str, list[str]] = {name: [] for name in faction_names}

    for entity in entities:
        if entity.get("type") == "faction":
            continue
        for faction in _entity_factions(entity):
            if faction in members_by_faction:
                members_by_faction[faction].append(str(entity.get("name") or ""))

    for faction in faction_entities:
        metadata = faction.get("metadata") if isinstance(faction.get("metadata"), dict) else {}
        parent = _metadata_string(metadata, "parent", "parent_faction")
        name = str(faction.get("name") or "")
        if parent in children_by_parent and name:
            children_by_parent[parent].append(name)

    tree: list[dict] = []
    for faction in faction_entities:
        metadata = faction.get("metadata") if isinstance(faction.get("metadata"), dict) else {}
        name = str(faction.get("name") or "")
        tree.append(
            {
                "name": name,
                "description": str(faction.get("description") or ""),
                "parent": _metadata_string(metadata, "parent", "parent_faction"),
                "first_chapter_number": int(faction.get("first_chapter_number") or 0),
                "members": sorted(dict.fromkeys(members_by_faction.get(name, []))),
                "children": sorted(dict.fromkeys(children_by_parent.get(name, []))),
            }
        )
    return tree


def _reader_xray_power_rankings(entities: list[dict]) -> list[dict]:
    rankings: list[dict] = []
    for entity in entities:
        metadata = entity.get("metadata") if isinstance(entity.get("metadata"), dict) else {}
        rank = _metadata_number(metadata, "power_rank", "power_level", "rank")
        label = _metadata_string(metadata, "power_label", "realm", "rank_label")
        if rank is None and not label:
            continue
        rankings.append(
            {
                "name": str(entity.get("name") or ""),
                "type": str(entity.get("type") or ""),
                "rank": int(rank or 0),
                "label": label,
                "basis": _metadata_string(metadata, "power_basis", "basis", "evidence"),
                "chapter_number": int(entity.get("first_chapter_number") or 0),
                "faction": (_entity_factions(entity) or [""])[0],
            }
        )
    return sorted(
        rankings,
        key=lambda item: (item["rank"], -item["chapter_number"], item["name"]),
        reverse=True,
    )



class PipelineService:
    def __init__(self):
        self.data_dir = get_data_dir()
        self.db_path = get_db_path()
        self.legacy_artifact_root = settings.artifact_legacy_root
        self.content_file_service = ContentFileService(
            data_dir=self.data_dir,
            db_path=self.db_path,
            legacy_artifact_root=self.legacy_artifact_root,
        )
        self.reader_service = ReaderService(
            db_path=self.db_path,
            content_file_service=self.content_file_service,
        )
        self.reader_dictionary_service = ReaderDictionaryService(
            data_dir=self.data_dir,
            file_rows=_reader_dictionary_file_rows,
            stardict_rows=_reader_dictionary_rows_from_stardict_bytes,
            jsonl_bytes=_reader_dictionary_jsonl_bytes,
        )

    def _content_files(self) -> ContentFileService:
        service = getattr(self, "content_file_service", None)
        data_root = getattr(self, "data_dir", None)
        database_path = getattr(self, "db_path", None)
        if data_root is None:
            data_root = Path(database_path).resolve().parent if database_path is not None else settings.resolved_data_dir
        if database_path is None:
            database_path = Path(data_root) / "pipeline.db"
        configured_legacy_root = getattr(self, "legacy_artifact_root", settings.artifact_legacy_root)
        legacy_root = Path(configured_legacy_root) if configured_legacy_root is not None else None
        if (
            service is None
            or service.data_dir != Path(data_root)
            or service.db_path != Path(database_path)
            or service.legacy_artifact_root != legacy_root
        ):
            service = ContentFileService(
                data_dir=data_root,
                db_path=database_path,
                legacy_artifact_root=legacy_root,
            )
            self.content_file_service = service
        return service

    def _books(self) -> BookService:
        return BookService(data_dir=self.data_dir, db_path=self.db_path, content_files=self._content_files())

    def _imports(self) -> ImportCommitService:
        return ImportCommitService(data_dir=self.data_dir, db_path=self.db_path,
            books=self._books(), content_files=self._content_files())

    def _reader(self) -> ReaderService:
        service = getattr(self, "reader_service", None)
        content_files = self._content_files()
        if (
            service is None
            or service.db_path != Path(self.db_path)
            or service.content_file_service is not content_files
        ):
            service = ReaderService(
                db_path=self.db_path,
                content_file_service=content_files,
            )
            self.reader_service = service
        return service

    def _reader_dictionaries(self) -> ReaderDictionaryService:
        service = getattr(self, "reader_dictionary_service", None)
        data_dir = Path(self.data_dir)
        if service is None or service.data_dir != data_dir:
            service = ReaderDictionaryService(
                data_dir=data_dir,
                file_rows=_reader_dictionary_file_rows,
                stardict_rows=_reader_dictionary_rows_from_stardict_bytes,
                jsonl_bytes=_reader_dictionary_jsonl_bytes,
            )
            self.reader_dictionary_service = service
        return service

    _safe_filename_part = staticmethod(ImportCommitService._safe_filename_part)

    _unlink_path = staticmethod(BookService._unlink_path)

    def _cover_url(self, cover_path: str | None) -> str:
        return self._books()._cover_url(cover_path)

    def resolve_artifact_file(self, value: str | Path | None, artifact_class: ArtifactClass) -> Path:
        return self._content_files().resolve_artifact_file(value, artifact_class)

    def _book_cover_extension(self, filename: str, content_type: str) -> str:
        return self._books()._book_cover_extension(filename, content_type)

    def _safe_book_cover_stem(self, title: str, book_id: int) -> str:
        return self._books()._safe_book_cover_stem(title, book_id)

    def list_reader_dictionaries(self) -> list[dict]:
        return self._reader_dictionaries().list_reader_dictionaries()

    def save_reader_dictionary(self, *, filename: str, content: bytes) -> dict:
        return self._reader_dictionaries().save_reader_dictionary(filename=filename, content=content)

    def delete_reader_dictionary(self, filename: str) -> bool:
        return self._reader_dictionaries().delete_reader_dictionary(filename)

    def get_reader_dictionary_path(self, filename: str) -> Path | None:
        return self._reader_dictionaries().get_reader_dictionary_path(filename)

    def _book_payload(self, book: dict | None) -> dict | None:
        return self._books()._book_payload(book)

    def _book_id_for_title(self, title: str) -> int:
        return self._books()._book_id_for_title(title)

    def _book_id_for_import(
        self,
        title: str,
        *,
        author: str = "",
        source: str = "manual",
        source_url: str = "",
    ) -> int:
        return self._books()._book_id_for_import(title, author=author, source=source, source_url=source_url)

    # Books
    def list_books(self) -> list[dict]:
        return self._books().list_books()

    def list_translated_book_summaries(self) -> list[dict]:
        return self._books().list_translated_book_summaries()

    def get_book(self, book_id: int) -> dict | None:
        return self._books().get_book(book_id)

    def create_book(
        self,
        title: str,
        author: str = "",
        source: str = "manual",
        source_url: str = "",
        cover_path: str = "",
    ) -> int:
        return self._books().create_book(title, author, source, source_url, cover_path)

    def update_book(self, book_id: int, **kwargs) -> dict | None:
        return self._books().update_book(book_id, **kwargs)

    def update_book_cover(
        self,
        book_id: int,
        *,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> dict | None:
        return self._books().update_book_cover(book_id, filename=filename, content_type=content_type, content=content)

    def delete_book(self, book_id: int) -> bool:
        return self._books().delete_book(book_id)

    # Chapters
    def get_chapter(self, chapter_id: int) -> dict | None:
        return get_chapter_by_id(self.db_path, chapter_id)

    def get_chapter_for_book(self, book_id: int, chapter_id: int) -> dict | None:
        chapter = get_chapter_by_id(self.db_path, chapter_id)
        if not chapter or chapter.get("book_id") != book_id:
            return None
        return chapter

    def list_chapters(self, book_id: int | None = None) -> list[dict]:
        return list_chapters(self.db_path, book_id)

    def get_chapter_source(self, chapter_id: int, *, chapter=None) -> str | None:
        return self._content_files().get_chapter_source(chapter_id, chapter=chapter)

    def get_chapter_translation(self, chapter_id: int, *, chapter=None) -> str | None:
        return self._content_files().get_chapter_translation(chapter_id, chapter=chapter)

    def get_chapter_content(self, chapter_id: int, *, chapter=None) -> dict | None:
        return self._content_files().get_chapter_content(chapter_id, chapter=chapter)

    # Reader state compatibility facade
    def get_reader_state(self, book_id: int) -> dict | None:
        return self._reader().get_reader_state(book_id)

    def save_reader_progress(
        self,
        book_id: int,
        *,
        chapter_id: int,
        mode: str = "scroll",
        percent: int = 0,
        paragraph_index: int = 0,
        char_offset: int = 0,
        absolute_char_offset: int = 0,
        page_index: int = 0,
        anchor: dict | None = None,
        updated_at: str | None = None,
    ) -> dict | None:
        return self._reader().save_reader_progress(
            book_id,
            chapter_id=chapter_id,
            mode=mode,
            percent=percent,
            paragraph_index=paragraph_index,
            char_offset=char_offset,
            absolute_char_offset=absolute_char_offset,
            page_index=page_index,
            anchor=anchor,
            updated_at=updated_at,
        )

    def list_reader_annotations(self, book_id: int) -> list[dict] | None:
        return self._reader().list_reader_annotations(book_id)

    def create_reader_annotation(
        self,
        book_id: int,
        chapter_id: int,
        *,
        kind: str,
        paragraph_index: int = 0,
        char_start: int = 0,
        char_end: int = 0,
        selected_text: str = "",
        note: str = "",
        color: str = "yellow",
        client_id: str = "",
    ) -> dict | None:
        return self._reader().create_reader_annotation(
            book_id,
            chapter_id,
            kind=kind,
            paragraph_index=paragraph_index,
            char_start=char_start,
            char_end=char_end,
            selected_text=selected_text,
            note=note,
            color=color,
            client_id=client_id,
        )

    def import_reader_annotations(self, book_id: int, *, annotations: list[dict]) -> dict | None:
        return self._reader().import_reader_annotations(book_id, annotations=annotations)

    def update_reader_annotation(
        self,
        book_id: int,
        annotation_id: int,
        **updates,
    ) -> dict | None:
        return self._reader().update_reader_annotation(book_id, annotation_id, **updates)

    def delete_reader_annotation(self, book_id: int, annotation_id: int) -> bool:
        return self._reader().delete_reader_annotation(book_id, annotation_id)

    def sync_reader_state(
        self,
        book_id: int,
        *,
        device_id: str = "",
        last_sync_at: str | None = None,
        progress: dict | None = None,
        annotations: list[dict] | None = None,
    ) -> dict | None:
        return self._reader().sync_reader_state(
            book_id,
            device_id=device_id,
            last_sync_at=last_sync_at,
            progress=progress,
            annotations=annotations,
        )

    def search_reader_book(
        self,
        book_id: int,
        *,
        query: str,
        scopes: set[str],
        case_sensitive: bool = False,
        regex: bool = False,
        whole_word: bool = False,
    ) -> list[dict] | None:
        if not get_book_by_id(self.db_path, book_id):
            return None
        query = query.strip()
        if not query:
            return []

        try:
            matcher = _reader_search_pattern(
                query,
                case_sensitive=case_sensitive,
                regex=regex,
                whole_word=whole_word,
            )
        except re.error as exc:
            raise ValueError(f"Invalid search regex: {exc}") from exc

        results: list[dict] = []
        chapters_by_id = {chapter["id"]: chapter for chapter in self.list_chapters(book_id)}

        if "translation" in scopes:
            for chapter in sorted(chapters_by_id.values(), key=lambda item: (item["chapter_number"], item["id"])):
                text = self.get_chapter_translation(chapter["id"], chapter=chapter)
                if not text:
                    continue
                for paragraph_index, paragraph in enumerate(_split_reader_paragraphs(text)):
                    match = matcher.search(paragraph)
                    if match:
                        results.append(
                            _reader_search_result(
                                chapter=chapter,
                                char_start=match.start(),
                                char_end=match.end(),
                                source="translation",
                                paragraph_index=paragraph_index,
                                text=paragraph,
                                match=match,
                            )
                        )

        if "notes" in scopes or "highlights" in scopes:
            for annotation in list_reader_annotations(self.db_path, book_id):
                source = "note" if annotation["kind"] == "note" else "highlight" if annotation["kind"] == "highlight" else ""
                source_scope = "notes" if source == "note" else "highlights" if source == "highlight" else ""
                if source_scope not in scopes:
                    continue
                chapter = chapters_by_id.get(annotation["chapter_id"])
                if not chapter:
                    continue
                text = annotation["note"] if source == "note" else annotation["selected_text"]
                if source == "note":
                    text = "\n".join(item for item in [annotation["note"], annotation["selected_text"]] if item)
                match = matcher.search(text or "")
                if match:
                    annotation_char_start = max(0, int(annotation.get("char_start") or 0))
                    annotation_char_end = max(annotation_char_start, int(annotation.get("char_end") or annotation_char_start))
                    if source == "note" and annotation["note"] and match.start() < len(annotation["note"]):
                        char_start = annotation_char_start
                        char_end = annotation_char_end
                    else:
                        selected_text_offset = 0
                        if source == "note" and annotation["note"] and annotation["selected_text"]:
                            selected_text_offset = len(annotation["note"]) + 1
                        selected_offset = max(0, match.start() - selected_text_offset)
                        char_start = annotation_char_start + selected_offset
                        char_end = char_start + len(match.group(0))
                    results.append(
                        _reader_search_result(
                            chapter=chapter,
                            char_start=char_start,
                            char_end=char_end,
                            source=source,
                            paragraph_index=annotation["paragraph_index"],
                            text=text or "",
                            match=match,
                        )
                    )

        return sorted(
            results,
            key=lambda result: (
                result["chapter_number"],
                result["paragraph_index"],
                -result["score"],
                result["source"],
            ),
        )

    def _reader_ai_provider_options(self) -> dict | None:
        defaults = get_provider_defaults(self.db_path)
        providers = {
            str(provider.get("id")): provider
            for provider in list_model_providers(self.db_path)
            if int(provider.get("enabled") or 0) == 1
        }
        candidate_ids = [
            defaults.get("reader_explain"),
            defaults.get("polish"),
            defaults.get("translate"),
            defaults.get("qa"),
            "ollama",
        ]

        seen: set[str] = set()
        for provider_id in candidate_ids:
            if not provider_id or provider_id in seen:
                continue
            seen.add(provider_id)
            provider = providers.get(provider_id)
            if not provider:
                continue
            api_key_env = str(provider.get("api_key_env") or "").strip()
            api_key = os.environ.get(api_key_env, "").strip() if api_key_env else ""
            if api_key_env and not api_key:
                continue
            return {
                "provider_id": provider["id"],
                "model": provider["model"],
                "host": provider["base_url"],
                "api_key": api_key,
            }
        return None

    def explain_reader_selection(
        self,
        book_id: int,
        chapter_id: int,
        *,
        text: str,
        context_before: str = "",
        context_after: str = "",
        spoiler_mode: str = "no_spoiler",
    ) -> dict | None:
        book = get_book_by_id(self.db_path, book_id)
        chapter = self.get_chapter_for_book(book_id, chapter_id)
        if not book or not chapter:
            return None

        selected_text = _normalize_reader_ai_text(text)
        if not selected_text:
            raise ValueError("Selected text is required")

        text_hash = _reader_ai_text_hash(selected_text)
        cached = get_reader_ai_cache(
            self.db_path,
            book_id=book_id,
            chapter_id=chapter_id,
            text_hash=text_hash,
            spoiler_mode=spoiler_mode,
        )
        if cached:
            return cached

        fallback_terms = _matching_reader_terms(load_glossary(self.db_path, book_id), selected_text)
        provider_options = self._reader_ai_provider_options()
        raw_payload: dict = {}
        if provider_options:
            prompt = _build_reader_explain_prompt(
                book_title=book["title"],
                chapter_title=chapter["title"],
                chapter_number=int(chapter["chapter_number"]),
                selected_text=selected_text,
                context_before=context_before.strip(),
                context_after=context_after.strip(),
                spoiler_mode=spoiler_mode,
                glossary_terms=fallback_terms,
            )
            try:
                llm_text = call_llm(
                    prompt=prompt,
                    model=provider_options["model"],
                    host=provider_options["host"],
                    api_key=provider_options["api_key"],
                    db_path=self.db_path,
                    provider_id=provider_options["provider_id"],
                    task_type="reader_explain",
                    chapter_id=chapter_id,
                )
                raw_payload = _json_object_from_llm_text(llm_text)
                if not raw_payload and llm_text.strip():
                    raw_payload = {"explanation": llm_text.strip(), "terms": []}
            except Exception as exc:  # pragma: no cover - provider failures should not break reading
                raw_payload = {
                    "explanation": f"Chưa gọi được AI explain: {exc}",
                    "terms": [],
                }

        response = _normalize_reader_explain_response(
            raw_payload,
            selected_text=selected_text,
            fallback_terms=fallback_terms,
        )
        return upsert_reader_ai_cache(
            self.db_path,
            book_id=book_id,
            chapter_id=chapter_id,
            text_hash=text_hash,
            spoiler_mode=spoiler_mode,
            selected_text=selected_text,
            response=response,
        )

    def _ensure_reader_xray_auto_extracted(self, book_id: int) -> None:
        existing_entities = list_reader_xray_entities(self.db_path, book_id)
        existing_timeline = list_reader_timeline_events(self.db_path, book_id)
        if existing_entities and existing_timeline:
            return

        chapters = sorted(
            list_chapters(self.db_path, book_id),
            key=lambda item: int(item.get("chapter_number") or 0),
        )
        glossary = {
            **load_glossary(self.db_path, book_id),
            **load_glossary_names(self.db_path, book_id),
        }
        candidates: dict[str, dict] = {}
        chapter_payloads: list[tuple[dict, list[str]]] = []

        for chapter in chapters[:MAX_READER_XRAY_AUTO_CHAPTERS]:
            text = self.get_chapter_translation(chapter["id"]) or self.get_chapter_source(chapter["id"]) or ""
            text = _reader_xray_plain_text(text)
            if not text:
                continue
            paragraphs = _split_reader_paragraphs(text)
            if not paragraphs:
                paragraphs = [text]
            chapter_payloads.append((chapter, paragraphs))
            for paragraph_index, paragraph in enumerate(paragraphs):
                _reader_xray_match_glossary_terms(
                    candidates=candidates,
                    chapter=chapter,
                    paragraph_index=paragraph_index,
                    paragraph=paragraph,
                    glossary=glossary,
                )
                _reader_xray_match_proper_names(
                    candidates=candidates,
                    chapter=chapter,
                    paragraph_index=paragraph_index,
                    paragraph=paragraph,
                )

        ranked_candidates = sorted(
            candidates.values(),
            key=lambda item: (
                len(item["mentions"]),
                1 if item.get("source") == "glossary" else 0,
                -int(item["first_chapter_number"] or 0),
                item["name"],
            ),
            reverse=True,
        )[:MAX_READER_XRAY_AUTO_ENTITIES]
        entity_names_by_chapter: dict[int, list[str]] = {}

        if existing_entities:
            for entity in existing_entities:
                for mention in entity.get("mentions", []):
                    entity_names_by_chapter.setdefault(mention["chapter_id"], [])
                    if entity["name"] not in entity_names_by_chapter[mention["chapter_id"]]:
                        entity_names_by_chapter[mention["chapter_id"]].append(entity["name"])
        else:
            for index, candidate in enumerate(ranked_candidates):
                mentions = candidate["mentions"]
                if not mentions:
                    continue
                entity = add_reader_entity(
                    self.db_path,
                    book_id=book_id,
                    entity_type=candidate["entity_type"],
                    name=candidate["name"],
                    aliases=candidate["aliases"],
                    description="Tự nhận diện từ nội dung chương đã có.",
                    first_chapter_number=int(candidate["first_chapter_number"] or 0),
                    importance=max(1, 100 - index * 3 + len(mentions)),
                    metadata={"source": "auto_xray_extractor"},
                )
                for mention in mentions:
                    add_reader_entity_mention(
                        self.db_path,
                        book_id=book_id,
                        entity_id=entity["id"],
                        chapter_id=mention["chapter_id"],
                        chapter_number=mention["chapter_number"],
                        paragraph_index=mention["paragraph_index"],
                        mention_text=mention["mention_text"],
                        context=mention["context"],
                    )
                    entity_names_by_chapter.setdefault(mention["chapter_id"], [])
                    if candidate["name"] not in entity_names_by_chapter[mention["chapter_id"]]:
                        entity_names_by_chapter[mention["chapter_id"]].append(candidate["name"])

        if not existing_timeline:
            for chapter, paragraphs in chapter_payloads:
                chapter_number = int(chapter.get("chapter_number") or 0)
                title = str(chapter.get("title") or "").strip() or f"Chương {chapter_number}"
                entity_names = entity_names_by_chapter.get(chapter["id"], [])
                add_reader_timeline_event(
                    self.db_path,
                    book_id=book_id,
                    chapter_id=chapter["id"],
                    chapter_number=chapter_number,
                    event_order=1,
                    title=title,
                    summary=_reader_xray_timeline_summary(paragraphs, entity_names),
                    entities=entity_names,
                )

    def _reader_xray_has_ai_enrichment(self, book_id: int, chapter_number: int | None = None) -> bool:
        entities = list_reader_xray_entities(self.db_path, book_id)
        for entity in entities:
            metadata = entity.get("metadata") or {}
            relationships = metadata.get("relationships") if isinstance(metadata, dict) else None
            if chapter_number is not None:
                if isinstance(relationships, list) and any(
                    isinstance(relationship, dict)
                    and str(relationship.get("source_type") or "") == "ai"
                    and int(relationship.get("chapter_number") or 0) == chapter_number
                    for relationship in relationships
                ):
                    return True
                if (
                    isinstance(metadata, dict)
                    and str(metadata.get("source") or "").startswith("ai_xray")
                    and int(entity.get("first_chapter_number") or 0) == chapter_number
                    and any(int(mention.get("chapter_number") or 0) == chapter_number for mention in entity.get("mentions") or [])
                ):
                    return True
                continue

            if isinstance(metadata, dict) and str(metadata.get("source") or "").startswith("ai_xray"):
                return True
            if isinstance(relationships, list) and relationships:
                return True
        return any(
            str(event.get("title") or "").startswith("[AI]")
            and (chapter_number is None or int(event.get("chapter_number") or 0) == chapter_number)
            for event in list_reader_timeline_events(self.db_path, book_id)
        )

    def _maybe_auto_enrich_reader_xray(self, book_id: int, chapter_id: int | None, spoiler_mode: str) -> None:
        if os.getenv("READER_XRAY_AUTO_AI", "").strip().lower() not in {"1", "true", "yes", "on"}:
            return
        if chapter_id is None:
            return

        book = get_book_by_id(self.db_path, book_id)
        chapter = self.get_chapter_for_book(book_id, chapter_id)
        if not book or not chapter:
            return

        current_chapter_number = int(chapter.get("chapter_number") or 0)
        if self._reader_xray_has_ai_enrichment(book_id, current_chapter_number):
            return

        provider_options = self._reader_ai_provider_options()
        if not provider_options:
            return

        max_chapter_number = None if spoiler_mode == "allow_spoiler" else current_chapter_number
        entities = list_reader_xray_entities(
            self.db_path,
            book_id,
            max_chapter_number=max_chapter_number,
        )
        timeline = list_reader_timeline_events(
            self.db_path,
            book_id,
            max_chapter_number=max_chapter_number,
        )
        chapter_text = self.get_chapter_translation(chapter_id) or self.get_chapter_source(chapter_id) or ""

        prompt = _build_reader_xray_enrich_prompt(
            book_title=book["title"],
            chapter_number=current_chapter_number,
            spoiler_mode=spoiler_mode,
            chapter_text=chapter_text,
            entities=entities,
            timeline=timeline,
        )
        try:
            llm_text = call_llm(
                prompt=prompt,
                model=provider_options["model"],
                host=provider_options["host"],
                api_key=provider_options["api_key"],
                db_path=self.db_path,
                provider_id=provider_options["provider_id"],
                task_type="reader_xray_auto_enrich",
                chapter_id=chapter_id,
            )
            payload = _json_object_from_llm_text(llm_text)
            if payload:
                self._apply_reader_xray_ai_payload(
                    book_id,
                    payload,
                    default_chapter_id=chapter_id,
                    default_chapter_number=current_chapter_number,
                )
        except Exception:
            return

    def get_reader_xray(
        self,
        book_id: int,
        *,
        chapter_id: int | None = None,
        spoiler_mode: str = "no_spoiler",
        auto_ai: bool = True,
    ) -> dict | None:
        if not get_book_by_id(self.db_path, book_id):
            return None

        current_chapter_number: int | None = None
        if chapter_id is not None:
            chapter = self.get_chapter_for_book(book_id, chapter_id)
            if not chapter:
                return None
            current_chapter_number = int(chapter.get("chapter_number") or 0)

        self._ensure_reader_xray_auto_extracted(book_id)
        if auto_ai:
            self._maybe_auto_enrich_reader_xray(book_id, chapter_id, spoiler_mode)

        max_chapter_number = None if spoiler_mode == "allow_spoiler" else current_chapter_number or 0
        entities = list_reader_xray_entities(
            self.db_path,
            book_id,
            max_chapter_number=max_chapter_number,
        )
        timeline = list_reader_timeline_events(
            self.db_path,
            book_id,
            max_chapter_number=max_chapter_number,
        )
        full_entities = entities if max_chapter_number is None else list_reader_xray_entities(self.db_path, book_id)
        graph_entities = _reader_xray_graph_entities(entities, full_entities)
        return {
            "book_id": book_id,
            "current_chapter_number": current_chapter_number,
            "spoiler_mode": spoiler_mode,
            "entities": entities,
            "relationships": _reader_xray_relationships(
                graph_entities,
                timeline,
                max_chapter_number=max_chapter_number,
            ),
            "faction_tree": _reader_xray_faction_tree(graph_entities),
            "power_rankings": _reader_xray_power_rankings(graph_entities),
            "timeline": timeline,
        }

    def _apply_reader_xray_ai_payload(self, book_id: int, payload: dict, *,
                                      default_chapter_id: int | None, default_chapter_number: int) -> None:
        from app.mobile_api.services.reader_xray_payload import apply_reader_xray_payload
        apply_reader_xray_payload(self.db_path, book_id, payload,
            default_chapter_id=default_chapter_id, default_chapter_number=default_chapter_number,
            entity_type_for_name=_reader_xray_entity_type)

    def _reader_xray_enrich_book_context_text(self, book_id: int) -> str:
        chapters = sorted(
            self.list_chapters(book_id),
            key=lambda item: (
                int(item.get("chapter_number") or 0),
                int(item.get("id") or 0),
            ),
        )
        parts: list[str] = []
        remaining = MAX_READER_XRAY_ENRICH_CONTEXT_CHARS

        for chapter in chapters[:MAX_READER_XRAY_ENRICH_CONTEXT_CHAPTERS]:
            chapter_id = int(chapter.get("id") or 0)
            if chapter_id <= 0:
                continue
            text = self.get_chapter_translation(chapter_id) or self.get_chapter_source(chapter_id) or ""
            text = _reader_xray_plain_text(text).strip()
            if not text:
                continue
            chapter_number = int(chapter.get("chapter_number") or 0)
            chapter_title = str(chapter.get("title") or "").strip()
            header = f"Chương {chapter_number}" if chapter_number > 0 else "Chương"
            if chapter_title:
                header = f"{header}: {chapter_title}"
            chunk = f"{header}\n{text[:MAX_READER_XRAY_ENRICH_CONTEXT_CHARS_PER_CHAPTER].strip()}"
            if len(chunk) > remaining:
                chunk = chunk[:remaining].rstrip()
            if not chunk:
                break
            parts.append(chunk)
            remaining -= len(chunk) + 2
            if remaining <= 0:
                break

        return "\n\n".join(parts)

    def enrich_reader_xray(
        self,
        book_id: int,
        *,
        chapter_id: int | None = None,
        spoiler_mode: str = "no_spoiler",
    ) -> dict | None:
        book = get_book_by_id(self.db_path, book_id)
        if not book:
            return None

        current_chapter_number = 0
        chapter_text = ""
        if chapter_id is not None:
            chapter = self.get_chapter_for_book(book_id, chapter_id)
            if not chapter:
                return None
            current_chapter_number = int(chapter.get("chapter_number") or 0)
            chapter_text = self.get_chapter_translation(chapter_id) or self.get_chapter_source(chapter_id) or ""
        else:
            chapter_text = self._reader_xray_enrich_book_context_text(book_id)

        current_xray = self.get_reader_xray(
            book_id,
            chapter_id=chapter_id,
            spoiler_mode=spoiler_mode,
            auto_ai=False,
        )
        if current_xray is None:
            return None

        provider_options = self._reader_ai_provider_options()
        if not provider_options:
            raise ValueError("Reader X-Ray AI provider is not configured")

        prompt = _build_reader_xray_enrich_prompt(
            book_title=book["title"],
            chapter_number=current_chapter_number or None,
            spoiler_mode=spoiler_mode,
            chapter_text=chapter_text,
            entities=current_xray.get("entities", []),
            timeline=current_xray.get("timeline", []),
        )
        llm_text = call_llm(
            prompt=prompt,
            model=provider_options["model"],
            host=provider_options["host"],
            api_key=provider_options["api_key"],
            db_path=self.db_path,
            provider_id=provider_options["provider_id"],
            task_type="reader_xray_enrich",
            chapter_id=chapter_id,
        )
        payload = _json_object_from_llm_text(llm_text)
        if not payload:
            raise ValueError("Reader X-Ray AI returned malformed JSON")

        self._apply_reader_xray_ai_payload(
            book_id,
            payload,
            default_chapter_id=chapter_id,
            default_chapter_number=current_chapter_number,
        )
        return self.get_reader_xray(book_id, chapter_id=chapter_id, spoiler_mode=spoiler_mode, auto_ai=False)

    def get_reader_dictionary_pack(
        self,
        book_id: int,
        *,
        chapter_id: int | None = None,
    ) -> dict | None:
        if not get_book_by_id(self.db_path, book_id):
            return None

        current_chapter_number: int | None = None
        if chapter_id is not None:
            chapter = self.get_chapter_for_book(book_id, chapter_id)
            if not chapter:
                return None
            current_chapter_number = int(chapter.get("chapter_number") or 0)

        glossary_sources = [
            _reader_dictionary_glossary_result(term)
            for term in list_glossary(self.db_path, book_id)
        ]
        builtin_sources = _reader_dictionary_builtin_pack_results()
        file_sources = _reader_dictionary_file_pack_results(self.data_dir)

        self._ensure_reader_xray_auto_extracted(book_id)
        xray_sources = [
            _reader_dictionary_xray_result(entity)
            for entity in list_reader_xray_entities(
                self.db_path,
                book_id,
                max_chapter_number=current_chapter_number,
            )
        ]

        sources = _dedupe_dictionary_pack_sources(
            [*glossary_sources, *builtin_sources, *file_sources, *xray_sources]
        )
        return {
            "book_id": book_id,
            "chapter_id": chapter_id,
            "sources": sources,
            "source_count": len(sources),
            "counts": _reader_dictionary_pack_counts(sources),
            "online": {
                "status": "skipped",
                "error": "",
                "count": 0,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def lookup_reader_dictionary(
        self,
        book_id: int,
        *,
        query: str,
        chapter_id: int | None = None,
        include_online: bool = True,
    ) -> dict | None:
        if not get_book_by_id(self.db_path, book_id):
            return None

        normalized_query = _normalize_reader_ai_text(query)
        if not normalized_query:
            raise ValueError("Query is required")

        current_chapter_number: int | None = None
        if chapter_id is not None:
            chapter = self.get_chapter_for_book(book_id, chapter_id)
            if not chapter:
                return None
            current_chapter_number = int(chapter.get("chapter_number") or 0)

        offline_sources: list[dict] = []
        glossary_terms = list_glossary(self.db_path, book_id)
        for term in glossary_terms:
            variants = _dictionary_split_variants(term.get("variants"))
            if _dictionary_query_matches(
                normalized_query,
                term.get("source_term") or "",
                term.get("target_term") or "",
                term.get("notes_vi") or "",
                *variants,
            ):
                offline_sources.append(_reader_dictionary_glossary_result(term))

        offline_sources.extend(_reader_dictionary_builtin_results(normalized_query))
        offline_sources.extend(_reader_dictionary_file_results(self.data_dir, normalized_query))

        self._ensure_reader_xray_auto_extracted(book_id)
        entities = list_reader_xray_entities(
            self.db_path,
            book_id,
            max_chapter_number=current_chapter_number,
        )
        for entity in entities:
            aliases = [str(item) for item in entity.get("aliases") or []]
            mentions = entity.get("mentions") or []
            mention_text = " ".join(
                str(mention.get("mention_text") or "") + " " + str(mention.get("context") or "")
                for mention in mentions[:5]
            )
            if _dictionary_query_matches(
                normalized_query,
                entity.get("name") or "",
                entity.get("description") or "",
                mention_text,
                *aliases,
            ):
                offline_sources.append(_reader_dictionary_xray_result(entity))

        online_status = "skipped"
        online_sources: list[dict] = []
        online_error = ""
        online_cache = {
            "hit": False,
            "stored": False,
            "scope": "online",
            "updated_at": "",
        }
        if include_online:
            query_norm = normalized_query.casefold()
            cached = get_reader_dictionary_cache(
                self.db_path,
                book_id=book_id,
                query_norm=query_norm,
            )
            if cached is not None:
                online_sources = cached["sources"]
                online_status = cached["online"]["status"] or "empty"
                online_error = cached["online"]["error"]
                online_cache["hit"] = True
                online_cache["updated_at"] = cached.get("updated_at", "")
            else:
                try:
                    online_sources = fetch_online_dictionary_lookup(normalized_query)
                    online_status = "ok" if online_sources else "empty"
                    upsert_reader_dictionary_cache(
                        self.db_path,
                        book_id=book_id,
                        query=normalized_query,
                        query_norm=query_norm,
                        response={
                            "sources": online_sources,
                            "online": {
                                "status": online_status,
                                "error": "",
                                "count": len(online_sources),
                            },
                        },
                    )
                    online_cache["stored"] = True
                except Exception as exc:  # pragma: no cover - exact network failures are environment-specific
                    online_status = "error"
                    online_error = str(exc)

        ranked_offline_sources = _rank_dictionary_sources(normalized_query, offline_sources)
        ranked_sources = _rank_dictionary_sources(normalized_query, [*offline_sources, *online_sources])
        sources = _dedupe_dictionary_sources(ranked_sources)
        return {
            "book_id": book_id,
            "chapter_id": chapter_id,
            "query": normalized_query,
            "sources": sources,
            "offline_count": len(_dedupe_dictionary_sources(ranked_offline_sources)),
            "online": {
                "status": online_status,
                "error": online_error,
                "count": len(online_sources),
            },
            "cache": online_cache,
        }

    def update_chapter_translation(self, chapter_id: int, text: str, **options) -> bool:
        return publish_translation(
            self.db_path, self.data_dir, chapter_id, clean_translation_layout(text), **options,
        ) is not None

    def delete_chapter_translation(self, book_id: int, chapter_id: int) -> bool:
        chapter = self.get_chapter_for_book(book_id, chapter_id)
        if not chapter or not delete_chapter_translation_data(self.db_path, chapter_id):
            return False
        for key in ("translated_text_path", "content_html_path", "audio_path"):
            retire_artifact(chapter.get(key), self.data_dir, self.db_path)
        return True

    def delete_chapter(self, book_id: int, chapter_id: int) -> bool:
        chapter = self.get_chapter_for_book(book_id, chapter_id)
        if not chapter or not soft_delete_chapter(self.db_path, chapter_id):
            return False
        for key in ("raw_text_path", "cleaned_text_path", "translated_text_path", "content_html_path", "audio_path"):
            retire_artifact(chapter.get(key), self.data_dir, self.db_path)
        return True

    def _provider_call_options(
        self,
        task_type: str,
        model: str | None = None,
        host: str | None = None,
    ) -> dict:
        provider_id = get_provider_defaults(self.db_path).get(task_type)
        provider = next((item for item in list_model_providers(self.db_path) if item["id"] == provider_id), None)
        api_key = None

        if provider:
            model = model or provider["model"]
            host = host or provider["base_url"]
            api_key_env = str(provider.get("api_key_env") or "").strip()
            api_key = os.environ.get(api_key_env, "").strip() if api_key_env else ""
            if api_key_env and not api_key:
                raise ValueError(f"Provider {provider['id']} requires {api_key_env}")

        return {
            "model": model,
            "host": host,
            "api_key": api_key,
            "provider_id": provider_id if provider else None,
        }

    def _provider_options_for_preset_task(self, preset_id: str, task_type: str) -> dict:
        preset = get_translation_preset(preset_id)
        provider_id = preset.providers.get(task_type) or get_provider_defaults(self.db_path).get(task_type)
        provider = next((item for item in list_model_providers(self.db_path) if item["id"] == provider_id), None)
        if not provider:
            raise ValueError(f"Provider {provider_id} not found for preset {preset.id}/{task_type}")

        api_key_env = str(provider.get("api_key_env") or "").strip()
        api_key = os.environ.get(api_key_env, "").strip() if api_key_env else ""
        if api_key_env and not api_key:
            raise ValueError(f"Provider {provider['id']} requires {api_key_env}")

        return {
            "provider_id": provider["id"],
            "model": provider["model"],
            "host": provider["base_url"],
            "api_key": api_key,
        }

    def _record_pipeline_stage_attempt(
        self,
        *,
        job_id: str,
        chapter_id: int,
        stage: str,
        provider_options: dict,
        status: str,
        started_at: float,
        error: str = "",
    ) -> None:
        if not job_id:
            return

        record_job_attempt(
            self.db_path,
            job_id=job_id,
            chapter_id=chapter_id,
            stage=stage,
            provider_id=str(provider_options.get("provider_id") or ""),
            model=str(provider_options.get("model") or ""),
            status=status,
            error=error,
            elapsed_ms=int((time.monotonic() - started_at) * 1000),
        )

    # Translation
    def translate_chapter(
        self,
        book_id: int,
        chapter_id: int,
        model: str | None = None,
        host: str | None = None,
        api_key: str | None = None,
        provider_id: str | None = None,
        job_id: str = "",
        style_profile_id: str | None = None,
        chunk_size: int | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> str:
        book = get_book_by_id(self.db_path, book_id)
        if not book:
            raise ValueError(f"Book {book_id} not found")
        chapter = self.get_chapter_for_book(book_id, chapter_id)
        if not chapter:
            raise ValueError(f"Chapter {chapter_id} not found")
        source_text = self.get_chapter_source(chapter_id)
        if not source_text:
            raise ValueError(f"No source text for chapter {chapter_id}")
        translated = translate_chapter(
            text=source_text,
            book_title=book["title"],
            chapter_title=chapter["title"],
            chapter_number=chapter["chapter_number"],
            model=model,
            host=host,
            api_key=api_key,
            provider_id=provider_id,
            job_id=job_id,
            chapter_id=chapter_id,
            style_profile_id=style_profile_id,
            chunk_size=chunk_size,
            cancel_check=cancel_check,
        )
        self.update_chapter_translation(chapter_id, translated, expected_content_revision=chapter["content_revision"])
        return translated

    def translate_chapter_with_pipeline(
        self,
        book_id: int,
        chapter_id: int,
        *,
        preset_id: str = "balanced",
        style_profile_id: str | None = None,
        job_id: str = "",
        chunk_size: int | None = None,
        stage_callback: Callable[[dict], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        provider_snapshot: dict | None = None,
    ) -> dict:
        preset = get_translation_preset(preset_id)
        effective_chunk_size = chunk_size if chunk_size is not None else preset.chunk_size

        def notify_stage(
            stage: str,
            status: str,
            provider_options: dict,
            started_at: float | None = None,
            error: str = "",
        ) -> None:
            if stage_callback is None:
                return
            elapsed_ms = int((time.monotonic() - started_at) * 1000) if started_at is not None else 0
            stage_callback(
                {
                    "stage": stage,
                    "status": status,
                    "provider_id": provider_options.get("provider_id") or "",
                    "model": provider_options.get("model") or "",
                    "elapsed_ms": max(0, elapsed_ms),
                    "error": error,
                }
            )

        book = get_book_by_id(self.db_path, book_id)
        if not book:
            raise ValueError(f"Book {book_id} not found")
        chapter = self.get_chapter_for_book(book_id, chapter_id)
        if not chapter:
            raise ValueError(f"Chapter {chapter_id} not found")
        source_text = self.get_chapter_source(chapter_id)
        if not source_text:
            raise ValueError(f"No source text for chapter {chapter_id}")

        # Resolve effective options once; all stages in this job use this snapshot.
        tasks = ["translate"] + (["polish"] if preset.polish_enabled else []) + (["qa"] if preset.qa_enabled else []) + (["rewrite"] if preset.rewrite_failed else [])
        snapshot = provider_snapshot if provider_snapshot is not None else {}
        if "providers" not in snapshot:
            snapshot["providers"] = {task: self._provider_options_for_preset_task(preset.id, task) for task in tasks}
            snapshot["style"] = get_style_profile(self.db_path, style_profile_id) if style_profile_id else get_default_style_profile(self.db_path)
        options = snapshot["providers"]
        effective_style = snapshot["style"]
        def check_cancel():
            if cancel_check and cancel_check():
                raise RuntimeError("Translation cancelled by user")
        def stage(task, operation):
            check_cancel()
            started = time.monotonic()
            notify_stage(task, "running", options[task])
            try:
                value = operation()
                if task != "qa" and (not isinstance(value, str) or not value.strip()):
                    raise ValueError(f"{task} output is empty")
            except Exception:
                notify_stage(task, "failed", options[task], started, "Stage failed")
                self._record_pipeline_stage_attempt(job_id=job_id, chapter_id=chapter_id, stage=task,
                    provider_options=options[task], status="failed", started_at=started, error="Stage failed")
                raise
            notify_stage(task, "success", options[task], started)
            self._record_pipeline_stage_attempt(job_id=job_id, chapter_id=chapter_id, stage=task,
                provider_options=options[task], status="success", started_at=started)
            return value
        mapped_chunks = []
        translate_options = options["translate"]
        rough_translation = stage("translate", lambda: translate_chapter(
            text=source_text, book_title=book["title"], chapter_title=chapter["title"],
            chapter_number=chapter["chapter_number"], model=translate_options["model"],
            host=translate_options["host"], api_key=translate_options["api_key"],
            provider_id=translate_options["provider_id"], task_type="translate", job_id=job_id,
            chapter_id=chapter_id, style_profile_id=style_profile_id, chunk_size=effective_chunk_size,
            cancel_check=cancel_check, db_path=self.db_path, book_id=book_id,
            chunk_callback=lambda source, target: mapped_chunks.append((source, target)),
            style_profile_snapshot=effective_style,
        ))
        if not mapped_chunks:
            mapped_chunks = [(source_text, rough_translation)]
        final_chunks, reviewed, polish_fallback = [], [], False
        def inspect(source, target):
            cfg = options["qa"]
            return stage("qa", lambda: run_qa_check(
                source_text=source, translated_text=target, model=cfg["model"], host=cfg["host"],
                api_key=cfg["api_key"], db_path=self.db_path, provider_id=cfg["provider_id"],
                task_type="qa", job_id=job_id, chapter_id=chapter_id,
                style_profile_id=effective_style.get("id") if effective_style else style_profile_id,
            ))
        for index, (source, target) in enumerate(mapped_chunks):
            check_cancel()
            if preset.polish_enabled:
                cfg = options["polish"]
                try:
                    target = stage("polish", lambda: call_llm(
                        prompt=_build_chapter_polish_prompt(source, target, book_title=book["title"],
                            chapter_title=chapter["title"], chapter_number=chapter["chapter_number"], style_profile=effective_style),
                        model=cfg["model"], host=cfg["host"], api_key=cfg["api_key"], db_path=self.db_path,
                        provider_id=cfg["provider_id"], task_type="polish", job_id=job_id, chapter_id=chapter_id,
                    ))
                except Exception as exc:
                    if not is_retryable_provider_error(exc):
                        raise
                    polish_fallback = True
                    notify_stage("polish", "fallback", cfg, error="Polish unavailable; retained translation")
                    self._record_pipeline_stage_attempt(job_id=job_id, chapter_id=chapter_id, stage="polish",
                        provider_options=cfg, status="fallback", started_at=time.monotonic(), error="Polish unavailable")
            target = post_process_with_idioms(target)
            if not target.strip():
                raise ValueError("Final translation is empty")
            if preset.qa_enabled:
                qa = inspect(source, target)
                if preset.rewrite_failed and qa.get("verdict") == "FAIL" and qa.get("qa_complete", True):
                    cfg = options["rewrite"]
                    target = stage("rewrite", lambda: call_llm(
                        prompt=_build_qa_rewrite_prompt(source, target, qa, book_title=book["title"],
                            chapter_title=chapter["title"], chapter_number=chapter["chapter_number"], style_profile=effective_style),
                        model=cfg["model"], host=cfg["host"], api_key=cfg["api_key"], db_path=self.db_path,
                        provider_id=cfg["provider_id"], task_type="rewrite", job_id=job_id, chapter_id=chapter_id,
                    ))
                    target = post_process_with_idioms(target)
                    if not target.strip():
                        raise ValueError("Rewrite output is empty")
                    qa = inspect(source, target)
                reviewed.append({**qa, "chunk_index": index})
            final_chunks.append(target)
        final_translation = "\n\n".join(final_chunks)
        rules = build_deterministic_chapter_qa_report(
            book_id=book_id, chapter_id=chapter_id, source_text=source_text, translated_text=final_translation,
            glossary_terms=list_glossary(self.db_path, book_id), job_id=job_id,
        )
        completed = [item for item in reviewed if item.get("qa_complete", True)]
        semantic = None
        if reviewed:
            semantic = {"chunks": reviewed, "qa_complete": len(completed) == len(mapped_chunks),
                "verdict": "FAIL" if any(item.get("verdict") == "FAIL" for item in reviewed) else
                           "WARNING" if any(item.get("verdict") in {"WARN", "WARNING"} for item in reviewed) else "PASS",
                "issues": [issue for item in reviewed for issue in item.get("issues", [])]}
            for key in ("quality_score", "fidelity_score", "style_score", "glossary_score", "audiobook_score"):
                semantic[key] = round(sum(float(item.get(key, 0)) for item in completed) / len(completed), 2) if completed else 0
        coverage = {"total_chunks": len(mapped_chunks), "evaluated_chunks": len(completed),
            "source_chars": len(source_text),
            "reviewed_source_chars": sum(len(mapped_chunks[item["chunk_index"]][0]) for item in completed),
            "complete": bool(reviewed) and len(completed) == len(mapped_chunks),
            "required": preset.qa_enabled, "pipeline_complete": not polish_fallback}
        report = merge_qa_report(rules, semantic, coverage,
            {"preset_id": preset.id, "style_profile_id": effective_style.get("id") if effective_style else style_profile_id})
        check_cancel()
        self.update_chapter_translation(chapter_id, final_translation,
            expected_content_revision=chapter["content_revision"], qa_report=report)
        return {"text": final_translation, "qa_report": report if preset.qa_enabled else None, "preset_id": preset.id}

    def retranslate_paragraph(
        self,
        book_id: int,
        chapter_id: int,
        paragraph_index: int,
        model: str | None = None,
        host: str | None = None,
    ) -> str:
        """Retranslate a single paragraph from source text."""
        source_text = self.get_chapter_source(chapter_id)
        if not source_text:
            raise ValueError(f"No source text for chapter {chapter_id}")

        paragraphs = [p.strip() for p in source_text.split("\n\n") if p.strip()]
        if paragraph_index < 0 or paragraph_index >= len(paragraphs):
            raise ValueError(f"Paragraph index {paragraph_index} out of range (0-{len(paragraphs)-1})")

        paragraph = paragraphs[paragraph_index]
        provider_options = self._provider_call_options("retranslate", model=model, host=host)

        # Translate just this paragraph
        translated = call_llm(
            prompt=_build_retranslate_prompt(paragraph, get_default_style_profile(self.db_path)),
            model=provider_options["model"],
            host=provider_options["host"],
            api_key=provider_options["api_key"],
            db_path=self.db_path,
            provider_id=provider_options["provider_id"],
            task_type="retranslate",
            chapter_id=chapter_id,
        )
        return post_process_with_idioms(translated)

    def polish_paragraph(
        self,
        book_id: int,
        chapter_id: int,
        paragraph_index: int,
        instructions: str = "",
        model: str | None = None,
        host: str | None = None,
    ) -> str:
        """Polish a translated paragraph."""
        translated_text = self.get_chapter_translation(chapter_id)
        if not translated_text:
            raise ValueError(f"No translation for chapter {chapter_id}")

        paragraphs = [p.strip() for p in translated_text.split("\n\n") if p.strip()]
        if paragraph_index < 0 or paragraph_index >= len(paragraphs):
            raise ValueError(f"Paragraph index {paragraph_index} out of range (0-{len(paragraphs)-1})")

        paragraph = paragraphs[paragraph_index]
        prompt = _build_polish_prompt(paragraph, instructions, get_default_style_profile(self.db_path))
        provider_options = self._provider_call_options("polish", model=model, host=host)
        polished = call_llm(
            prompt=prompt,
            model=provider_options["model"],
            host=provider_options["host"],
            api_key=provider_options["api_key"],
            db_path=self.db_path,
            provider_id=provider_options["provider_id"],
            task_type="polish",
            chapter_id=chapter_id,
        )
        return post_process_with_idioms(polished)

    def update_paragraph(
        self,
        chapter_id: int,
        paragraph_index: int,
        new_text: str,
        source: bool = False,
    ) -> bool:
        """Update a single paragraph in source or translated text."""
        chapter = get_chapter_by_id(self.db_path, chapter_id)
        if not chapter:
            return False

        if source:
            text = self.get_chapter_source(chapter_id)
            if not text:
                return False
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            if paragraph_index < 0 or paragraph_index >= len(paragraphs):
                return False
            paragraphs[paragraph_index] = new_text
            updated_text = "\n\n".join(paragraphs)
            raw_path = write_versioned_text(self.data_dir / "raw", f"chapter_{chapter_id}", updated_text)
            try:
                update_chapter_paths(self.db_path, chapter_id, raw_text_path=raw_path,
                                     expected_content_revision=chapter["content_revision"])
            except Exception:
                raw_path.unlink(missing_ok=True)
                raise
            retire_artifact(chapter["raw_text_path"], self.data_dir, self.db_path)
        else:
            text = self.get_chapter_translation(chapter_id)
            if not text:
                return False
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            if paragraph_index < 0 or paragraph_index >= len(paragraphs):
                return False
            paragraphs[paragraph_index] = new_text
            updated_text = "\n\n".join(paragraphs)
            self.update_chapter_translation(chapter_id, updated_text, expected_content_revision=chapter["content_revision"])

        return True

    # TTS
    def generate_audio(
        self,
        book_id: int,
        chapter_id: int,
        voice: str | None = None,
        rate: str = "-5%",
        volume: str = "+0%",
        job_id: str = "",
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, str], None] | None = None,
        parent_job_id: str = "",
    ) -> Path | None:
        chapter = get_chapter_by_id(self.db_path, chapter_id)
        if not chapter:
            return None
        book = get_book_by_id(self.db_path, book_id)
        if not book:
            return None
        if chapter.get("book_id") != book_id:
            return None
        text = self.get_chapter_translation(chapter_id)
        if not text:
            return None
        provider = settings.tts_provider
        legacy_fallback = text_to_speech_file
        if is_f5_provider(provider):
            require_tts_runtime_available(provider=provider)
            legacy_fallback = None
        if not hasattr(self, "_tts_batches"):
            self._tts_batches = {}
        pipeline = self._tts_batches.get(parent_job_id) if parent_job_id else None
        if pipeline is None:
            pipeline = TTSPipeline(self.db_path, self.data_dir, legacy_fallback=legacy_fallback)
            if parent_job_id:
                self._tts_batches[parent_job_id] = pipeline
        generate_kwargs: dict[str, object] = {
            "book_id": book_id,
            "chapter_id": chapter_id,
            "job_id": job_id,
            "voice_config": {"voice": voice or "", "rate": rate, "volume": volume},
            "parent_job_id": parent_job_id,
        }
        if cancel_check is not None:
            generate_kwargs["cancel_check"] = cancel_check
        if progress_callback is not None:
            generate_kwargs["progress_callback"] = progress_callback
        try:
            report = pipeline.generate_chapter(**generate_kwargs)
        finally:
            if not parent_job_id:
                pipeline.close()
        if report.status != "completed" or not report.output_mp3_path:
            raise RuntimeError(report.error_message or "TTS failed. Check TTS settings and server logs.")
        return Path(report.output_mp3_path)

    def close_audio_batch(self, job_id: str) -> None:
        pipeline = getattr(self, "_tts_batches", {}).pop(job_id, None)
        if pipeline is not None:
            pipeline.close()

    # QA
    def run_qa_check(
        self,
        book_id: int,
        chapter_id: int,
        model: str | None = None,
        host: str | None = None,
        api_key: str | None = None,
        provider_id: str | None = None,
        job_id: str = "",
    ) -> dict:
        book = get_book_by_id(self.db_path, book_id)
        if not book:
            raise ValueError(f"Book {book_id} not found")
        chapter = self.get_chapter_for_book(book_id, chapter_id)
        if not chapter:
            raise ValueError(f"Chapter {chapter_id} not found")
        source_text = self.get_chapter_source(chapter_id)
        if not source_text:
            raise ValueError(f"No source text for chapter {chapter_id}")
        translated_text = self.get_chapter_translation(chapter_id)
        if not translated_text:
            raise ValueError(f"No translation for chapter {chapter_id}")
        report = run_qa_check(
            source_text=source_text,
            translated_text=translated_text,
            model=model,
            host=host,
            api_key=api_key,
            db_path=self.db_path,
            provider_id=provider_id,
            job_id=job_id,
            chapter_id=chapter_id,
        )
        return report

    # Cache
    def get_cache_stats(self) -> dict:
        return get_cache_stats(self.db_path)

    def clear_cache(self) -> int:
        from app.translation.cache import clear_translation_cache
        return clear_translation_cache(self.db_path)

    # Daily queue
    def get_pending_chapters(self, book_id: int | None = None, limit: int = 15) -> list[dict]:
        return get_pending_chapters(self.db_path, book_id, limit)

    def get_failed_chapters(self, limit: int = 15) -> list[dict]:
        return get_failed_chapters(self.db_path, limit)

    # Import
    def import_from_text(
        self,
        title: str,
        chapter_number: int,
        chapter_title: str,
        text: str,
        source_type: str = "paste",
        source_url: str = "",
        author: str = "",
        book_source: str = "manual",
        book_source_url: str = "",
        adapter_id: str = "",
    ) -> ChapterImportResult:
        return self._imports().import_from_text(
            title, chapter_number, chapter_title, text, source_type, source_url,
            author, book_source, book_source_url, adapter_id,
        )

    _write_import_text_file = ImportCommitService._write_import_text_file

    _prepare_reviewed_import_items = ImportCommitService._prepare_reviewed_import_items

    _import_chapter_fingerprint = staticmethod(ImportCommitService._import_chapter_fingerprint)

    _classify_reviewed_import_items = ImportCommitService._classify_reviewed_import_items

    _stage_reviewed_import_files = ImportCommitService._stage_reviewed_import_files

    _finalize_reviewed_import_files = staticmethod(ImportCommitService._finalize_reviewed_import_files)

    def import_reviewed_text_plan(
        self,
        *,
        title: str,
        chapters: list[dict],
        content_kind: str,
        duplicate_strategy: str = "skip",
        target_book_id: int | None = None,
        author: str = "",
        source_type: str = "wizard",
    ) -> dict:
        return self._imports().import_reviewed_text_plan(
            title=title,
            chapters=chapters,
            content_kind=content_kind,
            duplicate_strategy=duplicate_strategy,
            target_book_id=target_book_id,
            author=author,
            source_type=source_type,
            stage_files=self._stage_reviewed_import_files,
        )

    def preview_source_url(self, url: str) -> dict:
        return get_source_registry().preview(url).to_dict()

    def fetch_source_chapter(self, url: str) -> SourceChapterContent:
        return get_source_registry().fetch_chapter(url)

    def import_from_source_url(
        self,
        *,
        book_title: str,
        author: str = "",
        source: str = "",
        source_url: str,
        chapter_url: str,
        chapter_number: int = 1,
        chapter_title: str = "",
    ) -> ChapterImportResult:
        chapter = self.fetch_source_chapter(chapter_url)
        imported = self.import_from_text(
            title=book_title,
            chapter_number=chapter_number or chapter.chapter_number,
            chapter_title=chapter_title or chapter.title,
            text=chapter.text,
            source_type="url",
            source_url=chapter.source_url,
            author=author,
            book_source=source or chapter.source,
            book_source_url=source_url,
            adapter_id=chapter.adapter_id,
        )
        return replace(
            imported,
            fetch_method=chapter.fetch_method,
            fetch_attempts=chapter.fetch_attempts,
            fetch_elapsed_ms=chapter.fetch_elapsed_ms,
        )

    def import_from_file(
        self,
        title: str,
        chapter_number: int,
        chapter_title: str,
        file_path: Path,
        filename: str = "",
    ) -> dict:
        return self._imports().import_from_file(title, chapter_number, chapter_title, file_path, filename)

    def add_url_note(
        self,
        title: str,
        url: str,
        notes: str = "",
        chapter_number: int = 1,
        chapter_title: str = "",
    ) -> int:
        # Save URL note as a text file in raw directory
        return self._imports().add_url_note(title, url, notes, chapter_number, chapter_title)
