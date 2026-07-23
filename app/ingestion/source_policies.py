from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlparse


@dataclass(frozen=True)
class SourcePolicy:
    source_id: str
    label: str
    domains: tuple[str, ...]
    delay_seconds: int = 10
    max_concurrency: int = 1
    retry_limit: int = 2
    cooldown_patterns: tuple[re.Pattern[str], ...] = ()

    def matches_hostname(self, hostname: str) -> bool:
        host = hostname.casefold().strip(".")
        return any(host == domain or host.endswith(f".{domain}") for domain in self.domains)

    def detects_cooldown(self, text: str) -> bool:
        return any(pattern.search(text) for pattern in self.cooldown_patterns)

    def to_public_dict(self) -> dict[str, int | str]:
        return {
            "source_id": self.source_id,
            "label": self.label,
            "delay_seconds": self.delay_seconds,
            "max_concurrency": self.max_concurrency,
            "retry_limit": self.retry_limit,
        }


COMMON_COOLDOWN_PATTERNS = (
    re.compile(r"(too many requests|rate limit|please wait|try again later)", re.I),
    re.compile(r"(访问过于频繁|请求过于频繁|请稍后|验证码|安全验证|人机验证)", re.I),
)

TURNSTILE_PATTERNS = (
    re.compile(r'data-sitekey\s*=\s*["\']([^"\']+)', re.I),
    re.compile(r'turnstile', re.I),
    re.compile(r'cf-turnstile', re.I),
    re.compile(r'challenge-platform', re.I),
)

RECAPTCHA_PATTERNS = (
    re.compile(r'g-recaptcha', re.I),
    re.compile(r'data-sitekey\s*=\s*["\']([^"\']+)', re.I),
    re.compile(r'recaptcha', re.I),
)


SOURCE_POLICIES: tuple[SourcePolicy, ...] = (
    SourcePolicy(
        "69shuba",
        "69shuba",
        ("69shuba.com", "69shuba.cx", "69shux.com"),
        delay_seconds=8,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "69shumi",
        "69shumi",
        ("69shumi.net", "69shumi.com"),
        delay_seconds=8,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "biquge",
        "Biquge",
        ("biquge.tw",),
        delay_seconds=10,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "22biqu",
        "22biqu",
        ("22biqu.com",),
        delay_seconds=10,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "uukanshu",
        "Uukanshu",
        ("uukanshu.cc",),
        delay_seconds=12,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "17k",
        "17K",
        ("17k.com",),
        delay_seconds=15,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "52shuku",
        "52shuku",
        ("52shuku.net",),
        delay_seconds=10,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "fanqienovel",
        "Fanqie Novel",
        ("fanqienovel.com",),
        delay_seconds=15,
        max_concurrency=1,
        retry_limit=1,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "jjwxc",
        "JJWXC",
        ("jjwxc.net",),
        delay_seconds=15,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "qidian",
        "Qidian",
        ("qidian.com",),
        delay_seconds=15,
        max_concurrency=1,
        retry_limit=1,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "novel543",
        "Novel543",
        ("novel543.com",),
        delay_seconds=10,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "bookqq",
        "Book QQ",
        ("book.qq.com",),
        delay_seconds=12,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "hetushu",
        "Hetushu",
        ("hetushu.com",),
        delay_seconds=12,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "ixdzs8",
        "Ixdzs8",
        ("ixdzs8.com", "ixdzs.com"),
        delay_seconds=10,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "xbanxia",
        "Xbanxia",
        ("xbanxia.cc", "xbanxia.com"),
        delay_seconds=10,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "kakuyomu",
        "Kakuyomu",
        ("kakuyomu.jp",),
        delay_seconds=5,
        max_concurrency=1,
        retry_limit=1,
    ),
    SourcePolicy(
        "syosetu",
        "Syosetu",
        ("syosetu.com",),
        delay_seconds=5,
        max_concurrency=1,
        retry_limit=1,
    ),
    SourcePolicy(
        "pixiv",
        "Pixiv",
        ("pixiv.net",),
        delay_seconds=5,
        max_concurrency=1,
        retry_limit=1,
    ),
    # ── P14: New source policies ported from Excerpo ─────────────────────────
    SourcePolicy(
        "royalroad",
        "Royal Road",
        ("royalroad.com",),
        delay_seconds=3,
        max_concurrency=2,
        retry_limit=3,
    ),
    SourcePolicy(
        "scribblehub",
        "Scribble Hub",
        ("scribblehub.com",),
        delay_seconds=3,
        max_concurrency=2,
        retry_limit=3,
    ),
    SourcePolicy(
        "ao3",
        "Archive of Our Own",
        ("archiveofourown.org",),
        delay_seconds=3,
        max_concurrency=2,
        retry_limit=3,
    ),
    SourcePolicy(
        "lnmtl",
        "LNMTL",
        ("lnmtl.com",),
        delay_seconds=5,
        max_concurrency=1,
        retry_limit=2,
    ),
    SourcePolicy(
        "foxaholic",
        "Foxaholic",
        ("foxaholic.com",),
        delay_seconds=5,
        max_concurrency=1,
        retry_limit=2,
    ),
    SourcePolicy(
        "shubaow",
        "Shubaow",
        ("shubaow.org",),
        delay_seconds=8,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "wbnovel",
        "WBNovel",
        ("wbnovel.com",),
        delay_seconds=5,
        max_concurrency=1,
        retry_limit=2,
    ),
    SourcePolicy(
        "meionovel",
        "Meionovel",
        ("meionovel.id", "meionovels.com"),
        delay_seconds=5,
        max_concurrency=1,
        retry_limit=2,
    ),
    SourcePolicy(
        "centralnovel",
        "Central Novel",
        ("centralnovel.com",),
        delay_seconds=5,
        max_concurrency=1,
        retry_limit=2,
    ),
    SourcePolicy(
        "ranobelib",
        "RanobeLib",
        ("ranobelib.me",),
        delay_seconds=5,
        max_concurrency=1,
        retry_limit=2,
    ),
    SourcePolicy(
        "syosetu_org",
        "Syosetu.org",
        ("syosetu.org",),
        delay_seconds=5,
        max_concurrency=1,
        retry_limit=1,
    ),
    SourcePolicy(
        "novelgo",
        "NovelGo",
        ("novelgo.id",),
        delay_seconds=5,
        max_concurrency=1,
        retry_limit=2,
    ),
    SourcePolicy(
        "novellunar",
        "NovelLunar",
        ("novellunar.com",),
        delay_seconds=5,
        max_concurrency=1,
        retry_limit=2,
    ),
    SourcePolicy(
        "phoenixnovels",
        "Phoenix Novels",
        ("phoenixnovels.com.br",),
        delay_seconds=5,
        max_concurrency=1,
        retry_limit=2,
    ),
    SourcePolicy(
        "chireads",
        "Chireads",
        ("chireads.com",),
        delay_seconds=5,
        max_concurrency=1,
        retry_limit=2,
    ),
    SourcePolicy(
        "fenrirscans",
        "Fenrir Scans",
        ("fenrirscans.com",),
        delay_seconds=5,
        max_concurrency=1,
        retry_limit=2,
    ),
    SourcePolicy(
        "23qb",
        "23qb",
        ("23qb.net",),
        delay_seconds=8,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "ihuaben",
        "ihuaben",
        ("ihuaben.com",),
        delay_seconds=8,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "shuhaige",
        "shuhaige",
        ("shuhaige.net",),
        delay_seconds=8,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "sto55",
        "sto55",
        ("sto55.com",),
        delay_seconds=8,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "sto9",
        "sto9",
        ("sto9.com",),
        delay_seconds=8,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "ttkan",
        "ttkan",
        ("ttkan.co",),
        delay_seconds=8,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "twkan",
        "twkan",
        ("twkan.com",),
        delay_seconds=8,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "xbiquge",
        "xbiquge",
        ("xbiquge.bz", "xbiquge.co", "xbiquge.info", "xbiquge.so", "xbiquge.la", "xbiquge.me"),
        delay_seconds=8,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "powanjuan",
        "powanjuan",
        ("powanjuan.cc",),
        delay_seconds=8,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
    SourcePolicy(
        "po18",
        "PO18",
        ("po18.tw",),
        delay_seconds=8,
        max_concurrency=1,
        retry_limit=1,
        cooldown_patterns=COMMON_COOLDOWN_PATTERNS,
    ),
)


def get_source_policy(url: str) -> SourcePolicy | None:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    for policy in SOURCE_POLICIES:
        if policy.matches_hostname(hostname):
            return policy
    return None


def source_policy_public_dict(url: str) -> dict[str, int | str] | None:
    policy = get_source_policy(url)
    return policy.to_public_dict() if policy else None


def is_allowed_source_url(url: str) -> bool:
    return get_source_policy(url) is not None


def _has_specific_source_path(path: str) -> bool:
    segments = [segment for segment in path.strip("/").split("/") if segment]
    if not segments:
        return False
    generic_roots = {"book", "read", "dir", "novel", "works", "chapter"}
    return not (len(segments) == 1 and segments[0].casefold() in generic_roots)


def chapter_url_matches_source_book(source_url: str, chapter_url: str) -> bool:
    source = urlparse(source_url)
    chapter = urlparse(chapter_url)
    if source.netloc.casefold() != chapter.netloc.casefold():
        return False

    source_path = source.path.rstrip("/")
    chapter_path = chapter.path.rstrip("/")
    if _has_specific_source_path(source_path) and (
        chapter_path == source_path or chapter_path.startswith(f"{source_path}/")
    ):
        return True

    source_book_match = re.search(r"/(?:book|read|dir|novel|works)/(\d+)(?:[/.]|$)", source.path, re.IGNORECASE)
    if source_book_match:
        book_id = re.escape(source_book_match.group(1))
        source_policy = get_source_policy(source_url)
        if source_policy and source_policy.source_id == "17k":
            return bool(re.search(rf"^/chapter/{book_id}(?:[/.]|$)", chapter.path, re.IGNORECASE))
        return bool(
            re.search(
                rf"/(?:book|read|dir|novel|works)/{book_id}(?:[/.]|$)",
                chapter.path,
                re.IGNORECASE,
            )
        )

    return False
