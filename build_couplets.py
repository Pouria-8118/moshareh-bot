#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_couplets.py

ساخت دیتابیس بیت‌ها برای ربات مشاعره از روی دیتابیس گنجور.

خروجی:
- bot_couplets.s3db
- جدول couplets
- ویوی ساده v_couplets_simple
- جداول آماری برای حروف اول/آخر
"""

import hashlib
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# -----------------------------
# تنظیمات اصلی
# -----------------------------

SOURCE_DB = "ganjoor.s3db"
TARGET_DB = "bot_couplets.s3db"

USE_HAZM_NORMALIZER = True
USE_HAZM_TOKENIZER = True

# اگر True باشد، مصرع‌های نثر با position=-1 بین دو مصرع، مانع جفت‌سازی می‌شوند.
# اگر می‌خواهی نثرها را کاملاً نادیده بگیری و فقط دنبال مصرع‌های بعدی بگردیم، این را False کن.
PROSE_IS_BARRIER = True

# اگر روی دیتابیس گنجور ایندکس نباشد، پیمایش ۱.۳ میلیون مصرع کند می‌شود.
# این گزینه یک ایندکس روی (poem_id, vorder) در دیتابیس مبدأ می‌سازد.
# اگر نمی‌خواهی دیتابیس مبدأ تغییر کند، این را False کن.
CREATE_SOURCE_INDEX_IF_NEEDED = True

BATCH_SIZE = 5000
NORMALIZATION_VERSION = "1.0-hazm-custom"

# حروف سخت طبق خواسته تو
HARD_LETTERS = set("ژصضطظعغفقلک")

# -----------------------------
# بارگذاری اختیاری hazm
# -----------------------------

hazm_normalizer = None
hazm_tokenizer = None

if USE_HAZM_NORMALIZER:
    try:
        from hazm import Normalizer
        hazm_normalizer = Normalizer()
    except Exception as e:
        print("WARNING: hazm Normalizer not available.")
        print(e)

if USE_HAZM_TOKENIZER:
    try:
        try:
            from hazm import WordTokenizer
            hazm_tokenizer = WordTokenizer()
        except Exception:
            from hazm import Tokenizer
            hazm_tokenizer = Tokenizer()
    except Exception as e:
        print("WARNING: hazm Tokenizer not available.")
        print(e)

# -----------------------------
# تنظیمات نرمال‌سازی
# -----------------------------

ZWNJ = "\u200c"

# اعراب عربی، علائم قرآنی و تتوییل
DIACRITICS_RE = re.compile(
    r"[\u0610-\u061A"
    r"\u064B-\u065F"
    r"\u0670"
    r"\u06D6-\u06DC"
    r"\u06DF-\u06E4"
    r"\u06E7"
    r"\u06E8"
    r"\u06EA-\u06ED"
    r"\u0640]"
)

SPACE_RE = re.compile(r"\s+")

# الفبای کانونیکال فارسی که برای بازی با آن کار می‌کنیم
CANONICAL_ALPHABET = set("ابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی")

# نگاشت حروف نزدیک به هم
# اگر خواستی سیاست حروف را عوض کنی، اینجا بهترین جا است.
CHAR_MAP = {
    # انواع الف
    "\u0622": "\u0627",  # آ
    "\u0623": "\u0627",  # أ
    "\u0625": "\u0627",  # إ
    "\u0671": "\u0627",  # ٱ
    "\u0672": "\u0627",  # ٲ
    "\u0673": "\u0627",  # ٳ
    "\u0675": "\u0627",  # ٵ
    "\u0621": "\u0627",  # ء

    # انواع ی
    "\u0649": "\u06CC",  # ى
    "\u064A": "\u06CC",  # ي
    "\u0626": "\u06CC",  # ئ
    "\u06CD": "\u06CC",  # ۍ
    "\u06D2": "\u06CC",  # ے
    "\u06D0": "\u06CC",  # ې

    # انواع ک
    "\u0643": "\u06A9",  # ك
    "\u06AA": "\u06A9",  # ڪ
    "\u06AB": "\u06A9",  # ګ

    # و
    "\u0624": "\u0648",  # ؤ

    # انواع ه
    "\u0629": "\u0647",  # ة
    "\u06C0": "\u0647",  # ۀ
    "\u06C1": "\u0647",  # ہ
    "\u06BE": "\u0647",  # ھ

    # کاراکترهای اضافی
    "\u0640": "",        # تتوییل
    "\u200c": "",        # نیم‌فاصله
}


# -----------------------------
# توابع کمکی متن
# -----------------------------

def is_letter(ch: str) -> bool:
    """
    تشخیص حرف.
    بعد از نگاشت، اگر در الفبای کانونیکال بود که قبول است.
    در غیر این صورت اگر در بازه‌های عربی/فارسی بود و دسته حرف داشت، قبول می‌کنیم.
    """
    if not ch:
        return False

    if ch in CANONICAL_ALPHABET:
        return True

    o = ord(ch)
    if (
        0x0621 <= o <= 0x06FF or
        0x0750 <= o <= 0x077F or
        0xFB50 <= o <= 0xFDFF or
        0xFE70 <= o <= 0xFEFF
    ):
        return unicodedata.category(ch).startswith("L")

    return False


def clean_raw(text: Optional[str]) -> str:
    """
    تمیز کردن متن خام برای ذخیره و نمایش.
    """
    if text is None:
        return ""

    s = str(text)
    s = s.replace("\r", " ").replace("\n", " ")
    s = SPACE_RE.sub(" ", s).strip()
    return s


def normalize_text(text: str) -> str:
    """
    نرمال‌سازی متن برای جستجو و مقایسه.

    خروجی:
    - فقط حروف
    - فاصله‌های استاندارد بین کلمات
    - بدون اعراب
    - بدون نیم‌فاصله
    - بدون علائم
    - حروف یکدست‌شده
    """
    if not text:
        return ""

    text = str(text)

    if hazm_normalizer is not None:
        try:
            normalized = hazm_normalizer.normalize(text)
            if normalized:
                text = normalized
        except Exception:
            pass

    text = DIACRITICS_RE.sub("", text)
    text = text.replace(ZWNJ, "")

    out = []
    for ch in text:
        if ch.isspace():
            out.append(" ")
            continue

        mapped = CHAR_MAP.get(ch, ch)
        if is_letter(mapped):
            out.append(mapped)

    s = "".join(out)
    s = SPACE_RE.sub(" ", s).strip()
    return s


def first_letter_from_normalized(text: str) -> str:
    """
    گرفتن اولین حرف از متن نرمال‌شده.
    """
    for ch in text:
        if ch != " " and is_letter(ch):
            return ch
    return ""


def last_letter_from_normalized(text: str) -> str:
    """
    گرفتن آخرین حرف از متن نرمال‌شده.
    """
    for ch in reversed(text):
        if ch != " " and is_letter(ch):
            return ch
    return ""


def first_letter_raw(text: str) -> str:
    """
    گرفتن اولین حرف از متن خام.
    این برای نگهداری شکل اصلی حرف مفید است.
    """
    if not text:
        return ""

    text = DIACRITICS_RE.sub("", text)

    for ch in text:
        if ch == ZWNJ or ch.isspace():
            continue

        if is_letter(CHAR_MAP.get(ch, ch)):
            return ch

    return ""


def last_letter_raw(text: str) -> str:
    """
    گرفتن آخرین حرف از متن خام.
    """
    if not text:
        return ""

    text = DIACRITICS_RE.sub("", text)

    for ch in reversed(text):
        if ch == ZWNJ or ch.isspace():
            continue

        if is_letter(CHAR_MAP.get(ch, ch)):
            return ch

    return ""


def tokenize_words(normalized_text: str) -> List[str]:
    """
    توکن‌سازی متن نرمال‌شده.
    اول سعی می‌کنیم از توکنایزر hazm استفاده کنیم.
    اگر نشد، به split ساده برمی‌گردیم.
    """
    if not normalized_text:
        return []

    if hazm_tokenizer is not None:
        try:
            raw_tokens = hazm_tokenizer.tokenize(normalized_text)

            if isinstance(raw_tokens, str):
                raw_tokens = [raw_tokens]

            flat = []
            for item in raw_tokens:
                if isinstance(item, str):
                    flat.append(item)
                elif isinstance(item, list):
                    flat.extend([str(x) for x in item])
                else:
                    flat.append(str(item))

            tokens = [
                t for t in flat
                if any(is_letter(c) for c in t)
            ]

            if tokens:
                return tokens
        except Exception:
            pass

    return normalized_text.split()


def hash_text(s: str) -> Optional[str]:
    """
    هش SHA-256 برای جستجوی سریع تطابق دقیق.
    """
    if not s:
        return None
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def is_pair(pos1: int, pos2: int) -> bool:
    """
    سیاست جفت‌سازی:
    - موضع اول باید زوج و غیرمنفی باشد.
    - موضع دوم باید دقیقاً یکی بعد از آن باشد.

    یعنی:
    0 و 1
    2 و 3
    4 و 5
    ...
    """
    return pos1 >= 0 and pos1 % 2 == 0 and pos2 == pos1 + 1


# -----------------------------
# بارگذاری جدول‌های کمکی
# -----------------------------

def load_poets(src: sqlite3.Connection) -> Tuple[Dict[int, str], Dict[int, Tuple[int, str]]]:
    poet_by_id: Dict[int, str] = {}
    poet_by_cat: Dict[int, Tuple[int, str]] = {}

    cur = src.execute("SELECT id, name, cat_id FROM poet")
    for pid, name, cat_id in cur:
        poet_by_id[pid] = name or ""
        if cat_id is not None:
            poet_by_cat[cat_id] = (pid, name or "")

    return poet_by_id, poet_by_cat


def load_cats(src: sqlite3.Connection) -> Dict[int, Dict]:
    cat_by_id: Dict[int, Dict] = {}

    cur = src.execute("SELECT id, poet_id, text, parent_id FROM cat")
    for cid, poet_id, text, parent_id in cur:
        cat_by_id[cid] = {
            "poet_id": poet_id,
            "text": text or "",
            "parent_id": parent_id,
        }

    return cat_by_id


def resolve_poet_for_cat(
    cat_id: Optional[int],
    cat_by_id: Dict[int, Dict],
    poet_by_id: Dict[int, str],
    poet_by_cat: Dict[int, Tuple[int, str]],
    cache: Dict[int, Tuple[Optional[int], str]]
) -> Tuple[Optional[int], str]:
    """
    پیدا کردن شاعر از روی cat_id.

    اول سعی می‌کنیم مستقیم از cat.poet_id به شاعر برسیم.
    اگر نشد، از روی درخت پدرها بالا می‌رویم.
    """
    if cat_id is None:
        return (None, "")

    if cat_id in cache:
        return cache[cat_id]

    original_cat_id = cat_id
    current = cat_id
    depth = 0

    while current is not None and depth < 100:
        cat = cat_by_id.get(current)
        if not cat:
            break

        pid = cat.get("poet_id")

        # حالت اول: cat.poet_id همان poet.id باشد
        if pid is not None:
            if pid in poet_by_id:
                res = (pid, poet_by_id[pid])
                cache[original_cat_id] = res
                return res

            # حالت دوم: cat.poet_id در واقع cat_id شاعر باشد
            if pid in poet_by_cat:
                res = poet_by_cat[pid]
                cache[original_cat_id] = res
                return res

        # اگر خود این دسته، دسته شاعر بود
        if current in poet_by_cat:
            res = poet_by_cat[current]
            cache[original_cat_id] = res
            return res

        parent = cat.get("parent_id")
        if parent in (0, None):
            # اگر به ریشه رسیدیم ولی شاعر پیدا نشد، متن خود دسته را به‌عنوان نام شاعر برمی‌گردانیم
            res = (None, cat.get("text") or "")
            cache[original_cat_id] = res
            return res

        current = parent
        depth += 1

    res = (None, "")
    cache[original_cat_id] = res
    return res


def load_poems(src: sqlite3.Connection) -> Dict[int, Tuple[Optional[int], str, str]]:
    poem_map: Dict[int, Tuple[Optional[int], str, str]] = {}

    cur = src.execute("SELECT id, cat_id, title, url FROM poem")
    for pid, cat_id, title, url in cur:
        poem_map[pid] = (cat_id, title or "", url or "")

    return poem_map


# -----------------------------
# ساخت ردیف بیت
# -----------------------------

def make_couplet_row(
    poem_id: int,
    couplet_no: int,
    pending: Dict,
    current: Dict,
    meta: Tuple[Optional[int], str, str, Optional[int], str]
) -> Optional[Tuple]:
    cat_id, poem_title, poem_url, poet_id, poet_name = meta

    raw1 = pending["text"]
    raw2 = current["text"]

    norm1 = normalize_text(raw1)
    norm2 = normalize_text(raw2)

    if not norm1 or not norm2:
        return None

    normalized_text = (norm1 + " " + norm2).strip()
    no_space_text = normalized_text.replace(" ", "")

    if not no_space_text:
        return None

    tokens = tokenize_words(normalized_text)

    first_word = tokens[0] if tokens else ""
    last_word = tokens[-1] if tokens else ""

    first_letter_canonical = first_letter_from_normalized(normalized_text)
    last_letter_canonical = last_letter_from_normalized(normalized_text)

    # اگر حرف اول یا آخر نداشته باشیم، برای مشاعره قابل استفاده نیست
    if not first_letter_canonical or not last_letter_canonical:
        return None

    first_raw = first_letter_raw(raw1)
    last_raw = last_letter_raw(raw2)

    difficulty = "hard" if last_letter_canonical in HARD_LETTERS else "normal"

    normalized_hash = hash_text(normalized_text)
    no_space_hash = hash_text(no_space_text)

    display_text = raw1 + "\n" + raw2
    tokenized_text = " ".join(tokens)

    return (
        poem_id,
        couplet_no,
        pending["vorder"],
        current["vorder"],
        pending["position"],
        current["position"],

        cat_id,
        poet_id,
        poet_name,
        poem_title,
        poem_url,

        raw1,
        raw2,
        display_text,

        normalized_text,
        tokenized_text,
        no_space_text,
        normalized_hash,
        no_space_hash,

        first_raw,
        last_raw,
        first_letter_canonical,
        last_letter_canonical,

        first_word,
        last_word,
        len(tokens),
        len(no_space_text),

        difficulty,
        f"{pending['position']}:{current['position']}",
        NORMALIZATION_VERSION,
    )


# -----------------------------
# ساخت اسکیما
# -----------------------------

def create_target_schema(tgt: sqlite3.Connection) -> None:
    tgt.execute("DROP VIEW IF EXISTS v_couplets_simple")
    tgt.execute("DROP TABLE IF EXISTS couplets")

    tgt.execute("""
        CREATE TABLE couplets (
            id INTEGER PRIMARY KEY,

            poem_id INTEGER NOT NULL,
            couplet_no INTEGER NOT NULL,

            verse1_vorder INTEGER,
            verse2_vorder INTEGER,
            verse1_position INTEGER,
            verse2_position INTEGER,

            poem_cat_id INTEGER,
            poet_id INTEGER,
            poet_name TEXT,
            poem_title TEXT,
            poem_url TEXT,

            hemistich1_raw TEXT NOT NULL,
            hemistich2_raw TEXT NOT NULL,
            display_text TEXT NOT NULL,

            normalized_text TEXT NOT NULL,
            tokenized_text TEXT,
            no_space_text TEXT NOT NULL,

            normalized_hash TEXT NOT NULL,
            no_space_hash TEXT NOT NULL,

            first_letter_raw TEXT,
            last_letter_raw TEXT,

            first_letter_canonical TEXT NOT NULL,
            last_letter_canonical TEXT NOT NULL,

            first_word_normalized TEXT,
            last_word_normalized TEXT,

            token_count INTEGER,
            char_count INTEGER,

            difficulty TEXT NOT NULL,
            position_pair TEXT,
            normalization_version TEXT
        )
    """)

    # ویوی ساده برای همان نیازی که اول گفتی:
    # بیت / حرف اول / حرف آخر / شاعر
    tgt.execute("""
        CREATE VIEW v_couplets_simple AS
        SELECT
            display_text AS bayt,
            first_letter_canonical AS first_letter,
            last_letter_canonical AS last_letter,
            poet_name AS poet,
            difficulty
        FROM couplets
    """)


def create_indexes(tgt: sqlite3.Connection) -> None:
    statements = [
        "CREATE INDEX IF NOT EXISTS idx_couplets_first_canonical ON couplets(first_letter_canonical)",
        "CREATE INDEX IF NOT EXISTS idx_couplets_last_canonical ON couplets(last_letter_canonical)",
        "CREATE INDEX IF NOT EXISTS idx_couplets_difficulty ON couplets(difficulty)",
        "CREATE INDEX IF NOT EXISTS idx_couplets_first_difficulty ON couplets(first_letter_canonical, difficulty)",
        "CREATE INDEX IF NOT EXISTS idx_couplets_last_first ON couplets(last_letter_canonical, first_letter_canonical)",
        "CREATE INDEX IF NOT EXISTS idx_couplets_poet_id ON couplets(poet_id)",
        "CREATE INDEX IF NOT EXISTS idx_couplets_poem_id ON couplets(poem_id)",
        "CREATE INDEX IF NOT EXISTS idx_couplets_normalized_hash ON couplets(normalized_hash)",
        "CREATE INDEX IF NOT EXISTS idx_couplets_no_space_hash ON couplets(no_space_hash)",
    ]

    for stmt in statements:
        tgt.execute(stmt)


def create_stats_tables(tgt: sqlite3.Connection) -> None:
    """
    این جدول‌ها بعداً برای انتخاب هوشمندانه بیت توسط ربات مفیدند.
    """
    tgt.execute("DROP TABLE IF EXISTS first_letter_stats")
    tgt.execute("""
        CREATE TABLE first_letter_stats AS
        SELECT
            first_letter_canonical AS letter,
            difficulty,
            COUNT(*) AS cnt
        FROM couplets
        GROUP BY first_letter_canonical, difficulty
    """)

    tgt.execute("DROP TABLE IF EXISTS last_first_transition")
    tgt.execute("""
        CREATE TABLE last_first_transition AS
        SELECT
            last_letter_canonical AS last_letter,
            first_letter_canonical AS first_letter,
            COUNT(*) AS cnt
        FROM couplets
        GROUP BY last_letter_canonical, first_letter_canonical
    """)

    tgt.execute("CREATE INDEX IF NOT EXISTS idx_first_letter_stats_letter ON first_letter_stats(letter)")
    tgt.execute("CREATE INDEX IF NOT EXISTS idx_last_first_transition_last ON last_first_transition(last_letter)")


# -----------------------------
# اجرای اصلی
# -----------------------------

INSERT_SQL = """
INSERT INTO couplets (
    poem_id,
    couplet_no,
    verse1_vorder,
    verse2_vorder,
    verse1_position,
    verse2_position,

    poem_cat_id,
    poet_id,
    poet_name,
    poem_title,
    poem_url,

    hemistich1_raw,
    hemistich2_raw,
    display_text,

    normalized_text,
    tokenized_text,
    no_space_text,

    normalized_hash,
    no_space_hash,

    first_letter_raw,
    last_letter_raw,

    first_letter_canonical,
    last_letter_canonical,

    first_word_normalized,
    last_word_normalized,

    token_count,
    char_count,

    difficulty,
    position_pair,
    normalization_version
) VALUES ({})
""".format(",".join(["?"] * 30))


def build() -> None:
    source_path = Path(SOURCE_DB)
    if not source_path.exists():
        raise SystemExit(f"Source database not found: {SOURCE_DB}")

    print("Connecting to databases...")

    src = sqlite3.connect(SOURCE_DB)
    tgt = sqlite3.connect(TARGET_DB)

    # سرعت بیشتر برای دیتابیس مقصد
    tgt.execute("PRAGMA journal_mode = WAL")
    tgt.execute("PRAGMA synchronous = OFF")
    tgt.execute("PRAGMA cache_size = -200000")
    tgt.execute("PRAGMA temp_store = MEMORY")

    if CREATE_SOURCE_INDEX_IF_NEEDED:
        try:
            print("Creating index on source verse table if missing...")
            src.execute("""
                CREATE INDEX IF NOT EXISTS idx_verse_poem_vorder
                ON verse(poem_id, vorder)
            """)
            src.commit()
        except Exception as e:
            print("Could not create source index:", e)

    print("Creating target schema...")
    create_target_schema(tgt)

    print("Loading poet, cat and poem maps...")
    poet_by_id, poet_by_cat = load_poets(src)
    cat_by_id = load_cats(src)
    poem_map = load_poems(src)

    cat_poet_cache: Dict[int, Tuple[Optional[int], str]] = {}
    poem_meta_cache: Dict[int, Tuple[Optional[int], str, str, Optional[int], str]] = {}

    def get_poem_meta(poem_id: int) -> Tuple[Optional[int], str, str, Optional[int], str]:
        if poem_id in poem_meta_cache:
            return poem_meta_cache[poem_id]

        info = poem_map.get(poem_id)
        if not info:
            res = (None, "", "", None, "")
        else:
            cat_id, title, url = info
            poet_id, poet_name = resolve_poet_for_cat(
                cat_id,
                cat_by_id,
                poet_by_id,
                poet_by_cat,
                cat_poet_cache
            )
            res = (cat_id, title, url, poet_id, poet_name)

        poem_meta_cache[poem_id] = res
        return res

    print("Reading verses...")
    cur = src.execute("""
        SELECT poem_id, vorder, position, text
        FROM verse
        ORDER BY poem_id, vorder
    """)

    batch: List[Tuple] = []

    pending: Optional[Dict] = None
    current_poem_id: Optional[int] = None
    couplet_no = 0

    seen = 0
    inserted = 0
    skipped = 0

    for poem_id, vorder, position, text in cur:
        seen += 1

        if seen % 100000 == 0:
            print(f"Seen verses: {seen}, inserted couplets: {inserted}")

        if poem_id is None:
            continue

        # اگر شعر عوض شد، جفت ناتمام قبلی را دور می‌ریزیم
        if poem_id != current_poem_id:
            current_poem_id = poem_id
            pending = None
            couplet_no = 0

        raw_text = clean_raw(text)

        # متن خالی را مانع در نظر می‌گیریم
        if not raw_text:
            pending = None
            continue

        try:
            pos = int(position)
        except Exception:
            pos = -999

        # نثر
        if pos == -1:
            if PROSE_IS_BARRIER:
                pending = None
            continue

        # positionهای نامعتبر دیگر
        if pos < 0:
            pending = None
            continue

        current_row = {
            "poem_id": poem_id,
            "vorder": vorder,
            "position": pos,
            "text": raw_text,
        }

        if pending is not None and is_pair(pending["position"], pos):
            next_couplet_no = couplet_no + 1
            meta = get_poem_meta(poem_id)

            row = make_couplet_row(
                poem_id,
                next_couplet_no,
                pending,
                current_row,
                meta
            )

            if row is not None:
                couplet_no = next_couplet_no
                batch.append(row)

                if len(batch) >= BATCH_SIZE:
                    tgt.executemany(INSERT_SQL, batch)
                    tgt.commit()
                    inserted += len(batch)
                    batch.clear()
            else:
                skipped += 1

            pending = None
        else:
            # اگر این مصرع می‌تواند شروع یک جفت جدید باشد
            if pos % 2 == 0:
                pending = current_row
            else:
                pending = None

    if batch:
        tgt.executemany(INSERT_SQL, batch)
        tgt.commit()
        inserted += len(batch)
        batch.clear()

    print("Creating indexes...")
    create_indexes(tgt)

    print("Creating stats tables...")
    create_stats_tables(tgt)

    tgt.execute("ANALYZE")
    tgt.commit()

    total = tgt.execute("SELECT COUNT(*) FROM couplets").fetchone()[0]
    hard_count = tgt.execute(
        "SELECT COUNT(*) FROM couplets WHERE difficulty = 'hard'"
    ).fetchone()[0]

    normal_count = tgt.execute(
        "SELECT COUNT(*) FROM couplets WHERE difficulty = 'normal'"
    ).fetchone()[0]

    print("=" * 40)
    print("Build finished.")
    print(f"Total couplets inserted: {total}")
    print(f"Hard couplets: {hard_count}")
    print(f"Normal couplets: {normal_count}")
    print(f"Skipped invalid/no-letter pairs: {skipped}")
    print(f"Target database: {TARGET_DB}")
    print("=" * 40)

    src.close()
    tgt.close()


if __name__ == "__main__":
    build()