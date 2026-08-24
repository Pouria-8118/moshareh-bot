import os
import re
import sqlite3
import hashlib
import logging
import unicodedata
import html
from datetime import datetime, timezone
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

load_dotenv() 


try:
    from rapidfuzz import fuzz
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False

try:
    from hazm import Normalizer
    hazm_normalizer = Normalizer()
except Exception:
    hazm_normalizer = None


# -----------------------------
# Settings
# -----------------------------

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN environment variable not set.")
DB_PATH = "bot_couplets.s3db"

SOLO_TIMEOUT = 45
PVP_TIMEOUT = 45
DIFFICULTY_HARD_THRESHOLD = 10
FUZZY_THRESHOLD = 82

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# -----------------------------
# Database Connection
# -----------------------------

if not os.path.exists(DB_PATH):
    raise SystemExit(
        "Database file bot_couplets.s3db not found. Run build_couplets.py first."
    )

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row


# -----------------------------
# Text Normalization
# -----------------------------

ZWNJ = "\u200c"

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

CANONICAL_ALPHABET = set("ابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی")

CHAR_MAP = {
    "\u0622": "\u0627",
    "\u0623": "\u0627",
    "\u0625": "\u0627",
    "\u0671": "\u0627",
    "\u0672": "\u0627",
    "\u0673": "\u0627",
    "\u0675": "\u0627",
    "\u0621": "\u0627",
    "\u0649": "\u06CC",
    "\u064A": "\u06CC",
    "\u0626": "\u06CC",
    "\u06CD": "\u06CC",
    "\u06D2": "\u06CC",
    "\u06D0": "\u06CC",
    "\u0643": "\u06A9",
    "\u06AA": "\u06A9",
    "\u06AB": "\u06A9",
    "\u0624": "\u0648",
    "\u0629": "\u0647",
    "\u06C0": "\u0647",
    "\u06C1": "\u0647",
    "\u06BE": "\u0647",
    "\u0640": "",
    "\u200c": "",
}


def is_letter(ch: str) -> bool:
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


def clean_raw(text) -> str:
    if text is None:
        return ""
    s = str(text).replace("\r", " ").replace("\n", " ")
    return SPACE_RE.sub(" ", s).strip()


def normalize_text(text: str) -> str:
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


def hash_text(s: str):
    if not s:
        return None
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# -----------------------------
# Bot Tables Initialization
# -----------------------------

def init_db():
    try:
        count = conn.execute("SELECT COUNT(*) FROM couplets").fetchone()[0]
        logger.info("Couplets table found. Count: %s", count)
    except sqlite3.OperationalError:
        raise SystemExit(
            "Table 'couplets' not found. Please run build_couplets.py first."
        )
    
    # Check if user_records needs migration
    cursor = conn.execute("PRAGMA table_info(user_records)")
    columns_info = cursor.fetchall()
    if columns_info:
        columns = {row[1] for row in columns_info}
        if "chat_id" not in columns:
            logger.info("Migrating user_records table to per-group structure...")
            conn.execute("ALTER TABLE user_records RENAME TO user_records_old")
            conn.execute("""
                CREATE TABLE user_records (
                    chat_id INTEGER,
                    user_id INTEGER,
                    username TEXT,
                    full_name TEXT,
                    best_score INTEGER DEFAULT 0,
                    updated_at TEXT,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO user_records (chat_id, user_id, username, full_name, best_score, updated_at)
                    SELECT user_id, user_id, username, full_name, best_score, updated_at FROM user_records_old
                """)
            except Exception as e:
                logger.warning(f"Migration error (non-critical): {e}")
            conn.execute("DROP TABLE IF EXISTS user_records_old")
            conn.commit()
            logger.info("Migration complete.")
    else:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_records (
                chat_id INTEGER,
                user_id INTEGER,
                username TEXT,
                full_name TEXT,
                best_score INTEGER DEFAULT 0,
                updated_at TEXT,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pvp_wins (
            chat_id INTEGER,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            wins INTEGER DEFAULT 0,
            updated_at TEXT,
            PRIMARY KEY (chat_id, user_id)
        )
    """)
    conn.commit()


# -----------------------------
# Couplet Queries
# -----------------------------

COUPLET_SELECT = """
SELECT
    id,
    poem_id,
    display_text,
    poet_name,
    poem_url,
    first_letter_canonical,
    last_letter_canonical,
    difficulty,
    normalized_text,
    no_space_text,
    normalized_hash,
    no_space_hash,
    char_count
FROM couplets
"""


def get_random_couplet(required_letter=None, hard=False, exclude_ids=None):
    def run_query(use_hard: bool):
        clauses = ["COALESCE(poet_name, '') != ''"]
        params = []
        if required_letter:
            clauses.append("first_letter_canonical = ?")
            params.append(required_letter)
        if use_hard:
            clauses.append("difficulty = 'hard'")
            
        if exclude_ids:
            placeholders = ",".join(["?"] * len(exclude_ids))
            clauses.append(f"id NOT IN ({placeholders})")
            params.extend(exclude_ids)
            
        where = " AND ".join(clauses)
        sql = f"{COUPLET_SELECT} WHERE {where} ORDER BY RANDOM() LIMIT 1"
        return conn.execute(sql, params).fetchone()

    row = run_query(hard)
    if row or not hard:
        return row
    return run_query(False)


def find_exact(normalized_hash, no_space_hash):
    sql = f"""
        {COUPLET_SELECT}
        WHERE normalized_hash = ? OR no_space_hash = ?
        LIMIT 1
    """
    return conn.execute(sql, (normalized_hash, no_space_hash)).fetchone()


def fuzzy_find(normalized: str, no_space: str, required_letter: str):
    if not RAPIDFUZZ_AVAILABLE:
        return None, 0
    if not required_letter:
        return None, 0
    input_len = len(no_space)
    lower = max(5, input_len - 10)
    upper = input_len + 10
    sql = f"""
        {COUPLET_SELECT}
        WHERE first_letter_canonical = ?
          AND char_count BETWEEN ? AND ?
          AND COALESCE(poet_name, '') != ''
    """
    rows = conn.execute(sql, (required_letter, lower, upper)).fetchall()
    if not rows:
        lower = max(5, input_len - 30)
        upper = input_len + 30
        sql = f"""
            {COUPLET_SELECT}
            WHERE first_letter_canonical = ?
              AND char_count BETWEEN ? AND ?
              AND COALESCE(poet_name, '') != ''
        """
        rows = conn.execute(sql, (required_letter, lower, upper)).fetchall()
    best_row = None
    best_score = 0
    for row in rows:
        try:
            db_no_space = row["no_space_text"] or ""
            if db_no_space == no_space:
                return row, 100
            s1 = fuzz.ratio(normalized, row["normalized_text"] or "")
            s2 = fuzz.ratio(no_space, db_no_space)
            s3 = fuzz.token_sort_ratio(normalized, row["normalized_text"] or "")
            score = max(s1, s2, s3)
        except Exception:
            continue
        if score > best_score:
            best_score = score
            best_row = row
            if score >= 98:
                break
    if best_score >= FUZZY_THRESHOLD:
        return best_row, best_score
    return None, best_score


def validate_user_couplet(text: str, required_letter=None):
    raw = clean_raw(text)
    normalized = normalize_text(raw)
    no_space = normalized.replace(" ", "")
    if len(no_space) < 6:
        return None, 0
    normalized_hash = hash_text(normalized)
    no_space_hash = hash_text(no_space)
    row = find_exact(normalized_hash, no_space_hash)
    if row:
        if not required_letter or row["first_letter_canonical"] == required_letter:
            return row, 100
    if required_letter:
        return fuzzy_find(normalized, no_space, required_letter)
    return None, 0


# -----------------------------
# Records (Per-Group)
# -----------------------------

def update_best(chat_id: int, user_id: int, username: str, full_name: str, score: int) -> int:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO user_records (chat_id, user_id, username, full_name, best_score, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET
            username = excluded.username,
            full_name = excluded.full_name,
            best_score = max(best_score, excluded.best_score),
            updated_at = excluded.updated_at
    """, (chat_id, user_id, username or "", full_name or "", score, now))
    conn.commit()
    row = conn.execute(
        "SELECT best_score FROM user_records WHERE chat_id = ? AND user_id = ?",
        (chat_id, user_id)
    ).fetchone()
    return row[0] if row else score


def get_best(chat_id: int, user_id: int) -> int:
    row = conn.execute(
        "SELECT best_score FROM user_records WHERE chat_id = ? AND user_id = ?",
        (chat_id, user_id)
    ).fetchone()
    return row[0] if row else 0


def increment_pvp_win(chat_id: int, user_id: int, username: str, full_name: str):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO pvp_wins (chat_id, user_id, username, full_name, wins, updated_at)
        VALUES (?, ?, ?, ?, 1, ?)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET
            username = excluded.username,
            full_name = excluded.full_name,
            wins = wins + 1,
            updated_at = excluded.updated_at
    """, (chat_id, user_id, username or "", full_name or "", now))
    conn.commit()


def get_top_records(chat_id: int, limit: int = 10):
    rows = conn.execute(
        "SELECT full_name, username, best_score FROM user_records WHERE chat_id = ? ORDER BY best_score DESC LIMIT ?",
        (chat_id, limit)
    ).fetchall()
    return rows


def get_top_wins(chat_id: int, limit: int = 10):
    rows = conn.execute(
        "SELECT full_name, username, wins FROM pvp_wins WHERE chat_id = ? ORDER BY wins DESC LIMIT ?",
        (chat_id, limit)
    ).fetchall()
    return rows


# -----------------------------
# Game States
# -----------------------------

solo_games = {}
pvp_games = {}


def solo_job_name(chat_id: int, user_id: int) -> str:
    return f"solo_{chat_id}_{user_id}"


def pvp_job_name(chat_id: int) -> str:
    return f"pvp_{chat_id}"


def cancel_jobs(context: ContextTypes.DEFAULT_TYPE, name: str):
    if not context.job_queue:
        return
    for job in context.job_queue.get_jobs_by_name(name):
        job.schedule_removal()


def get_remaining_time(context: ContextTypes.DEFAULT_TYPE, job_name: str) -> int:
    if not context.job_queue:
        return 0
    jobs = context.job_queue.get_jobs_by_name(job_name)
    if jobs:
        job = jobs[0]
        if job.next_t:
            delta = job.next_t - datetime.now(timezone.utc)
            return max(0, int(delta.total_seconds()))
    return 0


def schedule_solo_timer(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int):
    if not context.job_queue:
        return
    name = solo_job_name(chat_id, user_id)
    cancel_jobs(context, name)
    context.job_queue.run_once(
        solo_timeout,
        SOLO_TIMEOUT,
        name=name,
        chat_id=chat_id,
        data=(chat_id, user_id)
    )


def schedule_pvp_timer(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    if not context.job_queue:
        return
    name = pvp_job_name(chat_id)
    cancel_jobs(context, name)
    context.job_queue.run_once(
        pvp_timeout,
        PVP_TIMEOUT,
        name=name,
        chat_id=chat_id,
        data=chat_id
    )


# -----------------------------
# Message Formatting
# -----------------------------

def format_couplet_block(row) -> str:
    poet = row["poet_name"] or "ناشناس"
    display = html.escape(row['display_text'])
    poet_escaped = html.escape(poet)
    return f"<b>{display}</b>\n\n🖋 <i>{poet_escaped}</i>"


def couplet_keyboard(row, chat_id=None, user_id=None, is_pvp=False):
    url = row["poem_url"]
    buttons = []
    if url:
        buttons.append([InlineKeyboardButton("📚 شعر کامل در گنجور", url=url)])
    if is_pvp:
        buttons.append([InlineKeyboardButton("🛑 پایان مشاعره", callback_data="end_pvp_game")])
    else:
        buttons.append([InlineKeyboardButton("🛑 پایان مشاعره", callback_data=f"end_solo_game_{user_id}")])
    return InlineKeyboardMarkup(buttons)


def get_restart_keyboard(game_type: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("بازی مجدد 🔄", callback_data=f"restart_{game_type}_game")]
    ])


def safe_name(user) -> str:
    if not user:
        return "کاربر"
    return user.full_name or user.username or str(user.id)


# -----------------------------
# Commands Setup
# -----------------------------

async def setup_commands(application: Application):
    commands = [
        ("solo", "شروع مشاعره با ربات (رکوردی)"),
        ("pvp", "شروع مشاعره دو نفره در گروه"),
        ("stop", "توقف بازی فعال"),
        ("record", "نمایش رکورد شخصی"),
        ("top", "نمایش برترین‌های گروه"),
        ("help", "راهنمای ربات"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands menu updated.")


# -----------------------------
# Commands
# -----------------------------

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 شروع مشاعره با ربات", callback_data="start_solo_game")]
    ])
    text = (
        "<b>«از صدای سخن عشق ندیدم خوش‌تر</b>\n"
        "<b>یادگاری که در این گنبد دوار بماند»</b>\n\n"
        "سلام دوست عزیز! 🌸 به ربات مشاعره خوش اومدی.\n\n"
        "🎯 <b>هدف بازی:</b>\n"
        "در این بازی، ربات یا حریف شما یک بیت شعر می‌فرسته و شما باید با حرف آخر اون بیت، یک بیت جدید بفرستید.\n\n"
        "🎮 <b>حالت‌های بازی:</b>\n"
        "🔹 <b>مشاعره با ربات (رکوردی):</b> توانایی خودت رو محک بزن و رکوردت رو ثبت کن!\n"
        "🔹 <b>مشاعره دو نفره:</b> توی گروه‌ها با دوستات رقابت کن (دستور /pvp).\n\n"
        "⏱ <b>زمان:</b> برای هر پاسخ ۴۵ ثانیه وقت داری.\n"
        "🔥 <b>سختی:</b> هرچی بیشتر پیش بری، بیت‌های سخت‌تری ازت پرسیده میشه!\n\n"
        "آماده‌ای؟ روی دکمه زیر بزن تا شروع کنیم! 👇"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_cmd(update, context)


async def record_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    best = get_best(chat.id, user.id)
    await update.message.reply_text(
        f"🥇 بیشترین رکورد ثبت‌شده برای {html.escape(safe_name(user))}: <b>{best}</b>",
        parse_mode="HTML"
    )


async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text(
            "⚠️ این دستور فقط در گروه‌ها قابل استفاده است.",
            parse_mode="HTML"
        )
        return

    title = html.escape(chat.title or "گروه")
    rows = get_top_records(chat.id, 10)

    lines = [f"🏆 <b>بیشترین امتیازات گروه «{title}»</b>\n"]
    medals = ["🥇", "🥈", "🥉"]

    if not rows:
        lines.append("هنوز رکوردی ثبت نشده است.")
    else:
        for i, row in enumerate(rows):
            name = html.escape(row["full_name"] or row["username"] or "کاربر")
            score = row["best_score"]
            prefix = medals[i] if i < 3 else f"{i + 1}-"
            lines.append(f"{prefix} {name} با امتیاز <b>{score}</b>")

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("بیشترین بردها 🏅", callback_data="top_wins")]
    ])

    await update.message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)


async def start_solo_logic(update_or_query, context, is_callback=False):
    if is_callback:
        chat_id = update_or_query.message.chat_id
        user = update_or_query.from_user
        msg = update_or_query.message
    else:
        chat_id = update_or_query.effective_chat.id
        user = update_or_query.effective_user
        msg = update_or_query.message

    if not context.job_queue:
        await msg.reply_text("⚠️ تایمر فعال نیست.", parse_mode="HTML")
        return

    pvp = pvp_games.get(chat_id)
    if pvp and pvp.get("active"):
        await msg.reply_text("⚠️ لطفاً ابتدا بازی دو نفره فعال را با /stop متوقف کنید.", parse_mode="HTML")
        return

    key = (chat_id, user.id)
    if key in solo_games:
        await msg.reply_text("⚠️ شما در حال حاضر یک بازی فعال دارید.", parse_mode="HTML")
        return

    row = get_random_couplet(required_letter=None, hard=False)
    if not row:
        await msg.reply_text("⚠️ بیتی برای شروع پیدا نکردم.", parse_mode="HTML")
        return

    state = {
        "score": 0,
        "turn_count": 0,
        "required": row["last_letter_canonical"],
        "active": True,
        "username": user.username or "",
        "full_name": safe_name(user),
        "used_ids": {row["id"]},
    }

    solo_games[key] = state
    schedule_solo_timer(context, chat_id, user.id)

    text = (
        f"🎮 <b>مشاعره با ربات شروع شد.</b>\n"
        f"👤 {html.escape(safe_name(user))}\n"
        f"🏆 امتیاز: 0\n\n"
        f"{format_couplet_block(row)}\n\n"
        f"شما باید بیتی با «<b>{html.escape(row['last_letter_canonical'])}</b>» بفرمایید.\n\n"
        f"⏱ زمان: {SOLO_TIMEOUT} ثانیه"
    )

    keyboard = couplet_keyboard(row, chat_id, user.id, is_pvp=False)

    if is_callback:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=keyboard)
        try:
            await update_or_query.message.delete()
        except Exception:
            pass
    else:
        await msg.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def solo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_solo_logic(update, context, is_callback=False)


async def pvp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("⚠️ بازی دو نفره فقط در گروه‌ها قابل انجام است.", parse_mode="HTML")
        return

    existing = pvp_games.get(chat.id)

    if existing and existing.get("active"):
        await update.message.reply_text("⚠️ یک بازی دو نفره در این گروه در حال انجام است.", parse_mode="HTML")
        return

    if existing:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("پیوستن به بازی 🎮", callback_data="pvp_join")]
        ])
        await update.message.reply_text(
            "⏳ یک بازی در حالت انتظار است.\n"
            "نفر دوم می‌تواند با دکمه زیر به بازی ملحق شود.",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return

    pvp_games[chat.id] = {
        "active": False,
        "players": [],
        "names": {},
        "usernames": {},
        "scores": [0, 0],
        "turn": 0,
        "required": None,
        "used_ids": set(),
    }

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("پیوستن به بازی 🎮", callback_data="pvp_join")]
    ])

    await update.message.reply_text(
        "⚔️ برای آغاز بازی مشاعره دو نفره، باید دو نفر به بازی ملحق شوند.\n"
        "لطفاً روی دکمه زیر کلیک کنید.",
        parse_mode="HTML",
        reply_markup=keyboard
    )


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    stopped = False

    key = (chat_id, user.id)
    solo = solo_games.get(key)

    if solo:
        solo_games.pop(key, None)
        cancel_jobs(context, solo_job_name(chat_id, user.id))

        best = update_best(
            chat_id,
            user.id,
            user.username or "",
            safe_name(user),
            solo["score"]
        )

        await update.message.reply_text(
            f"🛑 <b>مشاعره به پایان رسید</b>\n\n"
            f"🏆 امتیاز این دست: {solo['score']}\n"
            f"🥇 بیشترین رکورد: {best}",
            parse_mode="HTML",
            reply_markup=get_restart_keyboard("solo")
        )
        stopped = True

    pvp = pvp_games.get(chat_id)

    if pvp:
        if pvp.get("active"):
            if pvp["scores"][0] > pvp["scores"][1]:
                winner_index = 0
            elif pvp["scores"][1] > pvp["scores"][0]:
                winner_index = 1
            else:
                winner_index = -1
            
            if winner_index != -1:
                winner_id = pvp["players"][winner_index]
                winner_name = pvp["names"][winner_id]
                winner_username = pvp.get("usernames", {}).get(winner_id, "")
                increment_pvp_win(chat_id, winner_id, winner_username, winner_name)
                
            await update.message.reply_text("🛑 <b>بازی دو نفره متوقف شد.</b>", parse_mode="HTML", reply_markup=get_restart_keyboard("pvp"))
        else:
            await update.message.reply_text("🛑 <b>بازی دو نفره در حالت انتظار لغو شد.</b>", parse_mode="HTML")
            
        pvp_games.pop(chat_id, None)
        cancel_jobs(context, pvp_job_name(chat_id))
        stopped = True

    if not stopped:
        await update.message.reply_text("⚠️ بازی فعالی برای توقف پیدا نکردم.", parse_mode="HTML")


# -----------------------------
# Callback Handlers
# -----------------------------

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not query.message:
        return

    chat_id = query.message.chat_id
    user = query.from_user

    if query.data == "start_solo_game":
        await start_solo_logic(query, context, is_callback=True)
        return

    if query.data == "restart_solo_game":
        await start_solo_logic(query, context, is_callback=True)
        return

    if query.data == "restart_pvp_game":
        pvp_games.pop(chat_id, None)
        pvp_games[chat_id] = {
            "active": False,
            "players": [],
            "names": {},
            "usernames": {},
            "scores": [0, 0],
            "turn": 0,
            "required": None,
            "used_ids": set(),
        }
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("پیوستن به بازی 🎮", callback_data="pvp_join")]
        ])
        await query.edit_message_text(
            "⚔️ برای آغاز بازی مشاعره دو نفره، باید دو نفر به بازی ملحق شوند.\n"
            "لطفاً روی دکمه زیر کلیک کنید.",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return

    if query.data.startswith("end_solo_game_"):
        target_user_id = int(query.data.split("_")[-1])
        if user.id != target_user_id:
            await query.answer("⚠️ فقط بازیکن می‌تواند بازی را متوقف کند.", show_alert=True)
            return

        key = (chat_id, user.id)
        solo = solo_games.pop(key, None)
        if solo:
            cancel_jobs(context, solo_job_name(chat_id, user.id))
            best = update_best(chat_id, user.id, user.username or "", safe_name(user), solo["score"])
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🛑 <b>مشاعره به پایان رسید.</b>\n\n"
                    f"🏆 امتیاز این دست: {solo['score']}\n"
                    f"🥇 بیشترین رکورد: {best}"
                ),
                parse_mode="HTML",
                reply_markup=get_restart_keyboard("solo")
            )
            try:
                await query.message.delete()
            except Exception:
                pass
        else:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ بازی قبلاً به پایان رسیده است.", parse_mode="HTML")
        return

    if query.data == "end_pvp_game":
        pvp = pvp_games.get(chat_id)
        if pvp:
            if pvp.get("active"):
                if pvp["scores"][0] > pvp["scores"][1]:
                    winner_index = 0
                elif pvp["scores"][1] > pvp["scores"][0]:
                    winner_index = 1
                else:
                    winner_index = -1
                
                if winner_index != -1:
                    winner_id = pvp["players"][winner_index]
                    winner_name = pvp["names"][winner_id]
                    winner_username = pvp.get("usernames", {}).get(winner_id, "")
                    increment_pvp_win(chat_id, winner_id, winner_username, winner_name)

            pvp_games.pop(chat_id, None)
            cancel_jobs(context, pvp_job_name(chat_id))
            await context.bot.send_message(
                chat_id=chat_id,
                text="🛑 <b>بازی دو نفره متوقف شد.</b>",
                parse_mode="HTML",
                reply_markup=get_restart_keyboard("pvp")
            )
            try:
                await query.message.delete()
            except Exception:
                pass
        else:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ بازی قبلاً به پایان رسیده است.", parse_mode="HTML")
        return

    if query.data == "top_wins":
        chat = query.message.chat
        title = html.escape(chat.title or "گروه")
        rows = get_top_wins(chat.id, 10)

        lines = [f"🏅 <b>بیشترین بردهای گروه «{title}»</b>\n"]
        medals = ["🥇", "🥈", "🥉"]

        if not rows:
            lines.append("هنوز بردی ثبت نشده است.")
        else:
            for i, row in enumerate(rows):
                name = html.escape(row["full_name"] or row["username"] or "کاربر")
                wins = row["wins"]
                prefix = medals[i] if i < 3 else f"{i + 1}-"
                lines.append(f"{prefix} {name} با <b>{wins}</b> برد")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("بیشترین رکوردها 🏆", callback_data="top_records")]
        ])

        await query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)
        return

    if query.data == "top_records":
        chat = query.message.chat
        title = html.escape(chat.title or "گروه")
        rows = get_top_records(chat.id, 10)

        lines = [f"🏆 <b>بیشترین امتیازات گروه «{title}»</b>\n"]
        medals = ["🥇", "🥈", "🥉"]

        if not rows:
            lines.append("هنوز رکوردی ثبت نشده است.")
        else:
            for i, row in enumerate(rows):
                name = html.escape(row["full_name"] or row["username"] or "کاربر")
                score = row["best_score"]
                prefix = medals[i] if i < 3 else f"{i + 1}-"
                lines.append(f"{prefix} {name} با امتیاز <b>{score}</b>")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("بیشترین بردها 🏅", callback_data="top_wins")]
        ])

        await query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)
        return

    if query.data == "pvp_join":
        pvp = pvp_games.get(chat_id)

        if not pvp:
            await query.edit_message_text("⚠️ این بازی دیگر فعال نیست. از /pvp استفاده کنید.", parse_mode="HTML")
            return

        if pvp.get("active"):
            await query.edit_message_text("⚠️ بازی در حال انجام است.", parse_mode="HTML")
            return

        if user.id not in pvp["players"]:
            pvp["players"].append(user.id)
            pvp["names"][user.id] = safe_name(user)
            pvp["usernames"][user.id] = user.username or ""

        if len(pvp["players"]) == 1:
            name = pvp["names"][pvp["players"][0]]
            text = (
                "⚔️ <b>مشاعره دو نفره</b>\n\n"
                f"۱. {html.escape(name)}\n\n"
                "منتظر نفر دوم..."
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("پیوستن به بازی 🎮", callback_data="pvp_join")]
            ])
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

        elif len(pvp["players"]) >= 2:
            pvp["players"] = pvp["players"][:2]
            await query.edit_message_text("🎮 هر دو بازیکن آماده شدند. در حال شروع بازی...", parse_mode="HTML")
            await start_pvp_game(context, chat_id)


async def start_pvp_game(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    pvp = pvp_games.get(chat_id)

    if not pvp:
        return

    row = get_random_couplet(required_letter=None, hard=False)

    if not row:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ بیتی برای شروع پیدا نکردم.",
            parse_mode="HTML"
        )
        pvp_games.pop(chat_id, None)
        return

    pvp["active"] = True
    pvp["turn"] = 0
    pvp["scores"] = [0, 0]
    pvp["required"] = row["last_letter_canonical"]
    pvp["used_ids"] = {row["id"]}

    schedule_pvp_timer(context, chat_id)

    p1 = pvp["names"][pvp["players"][0]]
    p2 = pvp["names"][pvp["players"][1]]

    text = (
        f"⚔️ <b>بازی مشاعره شروع شد!</b>\n"
        f"👥 {html.escape(p1)} در مقابل {html.escape(p2)}\n\n"
        f"{format_couplet_block(row)}\n\n"
        f"🎯 {html.escape(p1)} باید بیتی با «<b>{html.escape(row['last_letter_canonical'])}</b>» بفرستد.\n\n"
        f"⏱ زمان: {PVP_TIMEOUT} ثانیه"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=couplet_keyboard(row, chat_id, is_pvp=True)
    )


# -----------------------------
# Timers
# -----------------------------

async def solo_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job

    if not job:
        return

    key = job.data
    chat_id = job.chat_id or key[0]
    user_id = key[1]

    state = solo_games.pop(key, None)

    if not state:
        return

    best = update_best(
        chat_id,
        user_id,
        state.get("username", ""),
        state.get("full_name", ""),
        state["score"]
    )

    text = (
        f"⏰ <b>مهلت شما به پایان رسید.</b>\n"
        f"🏆 امتیاز این دست: {state['score']}\n"
        f"🥇 بیشترین رکورد شما: {best}"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=get_restart_keyboard("solo")
    )


async def pvp_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job

    if not job:
        return

    chat_id = job.chat_id or job.data
    pvp = pvp_games.get(chat_id)

    if not pvp or not pvp.get("active"):
        return

    loser_index = pvp["turn"]
    winner_index = 1 - loser_index

    loser_id = pvp["players"][loser_index]
    winner_id = pvp["players"][winner_index]

    loser_name = pvp["names"][loser_id]
    winner_name = pvp["names"][winner_id]
    winner_username = pvp.get("usernames", {}).get(winner_id, "")
    
    increment_pvp_win(chat_id, winner_id, winner_username, winner_name)

    scores_text = (
        f"{html.escape(pvp['names'][pvp['players'][0]])}: {pvp['scores'][0]} | "
        f"{html.escape(pvp['names'][pvp['players'][1]])}: {pvp['scores'][1]}"
    )

    pvp_games.pop(chat_id, None)

    text = (
        f"⏰ زمان <b>{html.escape(loser_name)}</b> تمام شد.\n"
        f"🏆 برنده: <b>{html.escape(winner_name)}</b>\n"
        f"📊 امتیازها: {scores_text}"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=get_restart_keyboard("pvp")
    )


# -----------------------------
# User Message Processing
# -----------------------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return

    if not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    text = update.effective_message.text or update.effective_message.caption

    if not text:
        return

    pvp = pvp_games.get(chat_id)
    if pvp and pvp.get("active"):
        current_player_id = pvp["players"][pvp["turn"]]
        if user.id == current_player_id:
            await process_pvp_move(update, context, pvp, user, text)
        return

    key = (chat_id, user.id)
    solo = solo_games.get(key)

    if solo and solo.get("active"):
        await process_solo_move(update, context, key, solo, user, text)


async def process_solo_move(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    key,
    solo,
    user,
    text: str
):
    required = solo["required"]
    used_ids = solo.get("used_ids", set())

    row, score = validate_user_couplet(text, required)

    if not row:
        chat_id = key[0]
        user_id = key[1]
        remaining = get_remaining_time(context, solo_job_name(chat_id, user_id))

        await update.effective_message.reply_text(
            f"❌ {html.escape(safe_name(user))}، این بیت قبول نشد.\n"
            f"باید بیتی با حرف «<b>{html.escape(required)}</b>» بفرستی.\n"
            f"⏳ هنوز <b>{remaining}</b> ثانیه وقت داری!",
            parse_mode="HTML"
        )
        return

    if row["id"] in used_ids:
        chat_id = key[0]
        user_id = key[1]
        remaining = get_remaining_time(context, solo_job_name(chat_id, user_id))

        await update.effective_message.reply_text(
            f"⚠️ <b>بیت تکراری مجاز نیست!</b>\n"
            f"❌ {html.escape(safe_name(user))}، این بیت قبول نشد.\n"
            f"باید بیتی با حرف «<b>{html.escape(required)}</b>» بفرستی.\n"
            f"⏳ هنوز <b>{remaining}</b> ثانیه وقت داری!",
            parse_mode="HTML"
        )
        return

    chat_id = key[0]
    user_id = key[1]
    
    used_ids.add(row["id"])
    solo["used_ids"] = used_ids

    cancel_jobs(context, solo_job_name(chat_id, user_id))

    solo["score"] += 1
    solo["turn_count"] += 1

    score = solo["score"]
    if score < 10:
        hard_mode = False
    elif 10 <= score < 20:
        hard_mode = (score % 2 == 0) 
    elif 20 <= score < 30:
        hard_mode = (score % 4 != 0)  
    else:
        hard_mode = True  

    bot_row = get_random_couplet(
        required_letter=row["last_letter_canonical"],
        hard=hard_mode,
        exclude_ids=list(used_ids)
    )

    if not bot_row:
        solo_games.pop(key, None)

        best = update_best(
            chat_id,
            user.id,
            solo.get("username", ""),
            solo.get("full_name", ""),
            solo["score"]
        )

        await update.effective_message.reply_text(
            f"🎉 <b>عالی بود!</b> ربات برای حرف آخر تو پاسخی نداشت.\n"
            f"🏆 امتیاز این دست: {solo['score']}\n"
            f"🥇 بیشترین رکورد: {best}",
            parse_mode="HTML",
            reply_markup=get_restart_keyboard("solo")
        )
        return

    solo["required"] = bot_row["last_letter_canonical"]
    solo["used_ids"].add(bot_row["id"])
    schedule_solo_timer(context, chat_id, user_id)

    text = (
        f"✅ <b>احسنت!</b>\n"
        f"🏆 امتیاز: {solo['score']}\n\n"
        f"{format_couplet_block(bot_row)}\n\n"
        f"شما باید بیتی با «<b>{html.escape(bot_row['last_letter_canonical'])}</b>» بفرمایید.\n\n"
        f"⏱ زمان: {SOLO_TIMEOUT} ثانیه"
    )

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=couplet_keyboard(bot_row, chat_id, user_id, is_pvp=False)
    )


async def process_pvp_move(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    pvp,
    user,
    text: str
):
    chat_id = update.effective_chat.id
    required = pvp["required"]
    used_ids = pvp.get("used_ids", set())

    row, score = validate_user_couplet(text, required)

    if not row:
        remaining = get_remaining_time(context, pvp_job_name(chat_id))
        await update.effective_message.reply_text(
            f"❌ {html.escape(safe_name(user))}، این بیت قبول نشد.\n"
            f"باید با حرف «<b>{html.escape(required)}</b>» شروع شود.\n"
            f"⏳ هنوز <b>{remaining}</b> ثانیه وقت داری!",
            parse_mode="HTML"
        )
        return

    if row["id"] in used_ids:
        remaining = get_remaining_time(context, pvp_job_name(chat_id))
        await update.effective_message.reply_text(
            f"⚠️ <b>بیت تکراری مجاز نیست!</b>\n"
            f"❌ {html.escape(safe_name(user))}، این بیت قبول نشد.\n"
            f"باید با حرف «<b>{html.escape(required)}</b>» شروع شود.\n"
            f"⏳ هنوز <b>{remaining}</b> ثانیه وقت داری!",
            parse_mode="HTML"
        )
        return

    used_ids.add(row["id"])
    pvp["used_ids"] = used_ids

    cancel_jobs(context, pvp_job_name(chat_id))

    current_index = pvp["turn"]
    next_index = 1 - current_index

    pvp["scores"][current_index] += 1
    pvp["turn"] = next_index
    pvp["required"] = row["last_letter_canonical"]

    schedule_pvp_timer(context, chat_id)

    next_name = pvp["names"][pvp["players"][next_index]]

    scores_text = (
        f"{html.escape(pvp['names'][pvp['players'][0]])}: {pvp['scores'][0]} | "
        f"{html.escape(pvp['names'][pvp['players'][1]])}: {pvp['scores'][1]}"
    )

    text = (
        f"✅ <b>احسنت!</b>\n"
        f"🎯 نوبت: {html.escape(next_name)}\n"
        f"🔤 حرف شروع: «<b>{html.escape(row['last_letter_canonical'])}</b>»\n\n"
        f"⏱ زمان: {PVP_TIMEOUT} ثانیه\n"
        f"📊 امتیازها: {scores_text}"
    )

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML"
    )


# -----------------------------
# Bot Execution
# -----------------------------

def main():
    token = BOT_TOKEN.strip()

    if not token:
        raise SystemExit(
            "Bot token is not set.\n"
            "Set the BOT_TOKEN environment variable"
        )

    init_db()

    app = Application.builder().token(token).post_init(setup_commands).build()

    if not app.job_queue:
        logger.warning("JobQueue is not active. Timers will not work.")

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("solo", solo_cmd))
    app.add_handler(CommandHandler("pvp", pvp_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("record", record_cmd))
    app.add_handler(CommandHandler("top", top_cmd))

    app.add_handler(CallbackQueryHandler(callback_handler))

    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
            handle_text
        )
    )

    logger.info("Bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()