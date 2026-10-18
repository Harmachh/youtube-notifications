import os
import re
import html
import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import datetime

import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

BOT_TOKEN = "YOUR_BOT_TOKEN"

# Интервал проверки каналов (в минутах)
CHECK_INTERVAL_MINUTES = 15

MAX_CHANNELS_PER_USER = 20

# ═══════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ==================== ЛОКАЛИЗАЦИЯ (RU / EN) ====================

TEXTS = {
    "ru": {
        "choose_lang": "🌐 <b>Выберите язык / Choose your language:</b>",
        "lang_set": "✅ Язык установлен: <b>Русский</b>",
        "welcome": (
            "👋 <b>Привет!</b>\n\n"
            "Я бот для отслеживания новых видео на <b>YouTube</b> (через RSS без лимитов API).\n"
            "Добавь каналы по ссылке, и я буду присылать уведомления о новых роликах!"
        ),
        "main_menu_title": "👋 <b>Главное меню</b>\n\nВыбери действие:",
        "btn_add": "➕ Добавить канал",
        "btn_list": "📋 Мои каналы",
        "btn_stats": "📊 Статистика",
        "btn_help": "❓ Помощь",
        "btn_lang": "🌐 Язык / Language",
        "btn_back": "◀️ В главное меню",
        "btn_back_short": "◀️ Назад",
        "btn_delete": "❌ Удалить {title}",
        "help": (
            "📖 <b>Как пользоваться ботом:</b>\n\n"
            "1️⃣ Нажми <b>«Добавить канал»</b>\n"
            "2️⃣ Отправь ссылку на YouTube-канал\n"
            "3️⃣ Бот проверяет каналы каждые <b>{interval} минут</b>\n"
            "4️⃣ При выходе нового видео пришлёт уведомление\n\n"
            "<b>Поддерживаемые ссылки:</b>\n"
            "• <code>youtube.com/channel/UC...</code>\n"
            "• <code>youtube.com/@username</code>\n"
            "• <code>youtube.com/c/Name</code>\n"
            "• <code>youtube.com/user/Name</code>\n\n"
            "Можно просто отправить <code>@username</code>"
        ),
        "limit_alert": "⚠️ Лимит каналов ({max_channels}) достигнут! Удали лишние в «Мои каналы».",
        "limit_msg": (
            "⚠️ <b>Лимит каналов достигнут!</b>\n\n"
            "Максимум <b>{max_channels}</b> каналов на пользователя.\n"
            "Удали лишние в разделе «Мои каналы»."
        ),
        "send_link_prompt": (
            "🔗 <b>Отправь ссылку на YouTube-канал</b>\n\n"
            "Примеры:\n"
            "• <code>https://youtube.com/@MrBeast</code>\n"
            "• <code>https://youtube.com/channel/UC...</code>\n"
            "• <code>https://youtube.com/c/ChannelName</code>\n"
            "• Или просто <code>@username</code>"
        ),
        "no_channels": (
            "📭 <b>У тебя пока нет отслеживаемых каналов.</b>\n\n"
            "Нажми «Добавить канал», чтобы начать!"
        ),
        "your_channels": "📋 <b>Твои каналы:</b>\n\n",
        "last_check": "   └ Последняя проверка: {time}\n\n",
        "stats": (
            "📊 <b>Статистика бота:</b>\n\n"
            "👤 Пользователей: <b>{users}</b>\n"
            "📺 Всего подписок: <b>{channels}</b>"
        ),
        "channel_deleted": "✅ Канал удалён!",
        "channel_not_found_alert": "⚠️ Канал не найден",
        "unknown_text": "❓ Я не понял. Отправь ссылку на YouTube-канал или выбери действие в меню.",
        "checking_channel": "🔍 <b>Проверяю канал...</b>",
        "err_extract_id": "❌ <b>Не удалось определить канал.</b>\n\nПроверь ссылку и попробуй снова.",
        "err_channel_not_found": "❌ <b>Канал не найден или его RSS-фид недоступен.</b>\nПроверь ссылку и попробуй снова.",
        "channel_added": (
            "✅ <b>Канал добавлен!</b>\n\n"
            "📺 <b>{title}</b>\n"
            "🆔 <code>{channel_id}</code>"
        ),
        "latest_video_part": (
            "\n\n🎬 <b>Последнее видео:</b>\n"
            "<a href='https://youtube.com/watch?v={video_id}'>{video_title}</a>"
        ),
        "already_tracked": "⚠️ <b>Этот канал уже отслеживается!</b>",
        "err_generic": "❌ <b>Произошла ошибка.</b>\nПопробуй позже или проверь ссылку.",
        "new_video_notification": (
            "🎬 <b>Новое видео!</b>\n\n"
            "📺 Канал: <b>{channel_title}</b>\n"
            "📝 {video_title}\n\n"
            "<a href='{video_url}'>▶️ Смотреть на YouTube</a>"
        ),
    },
    "en": {
        "choose_lang": "🌐 <b>Choose your language / Выберите язык:</b>",
        "lang_set": "✅ Language set to: <b>English</b>",
        "welcome": (
            "👋 <b>Hello!</b>\n\n"
            "I am a bot for tracking new <b>YouTube</b> videos (via RSS with no API limits).\n"
            "Send me a channel link, and I will notify you whenever a new video comes out!"
        ),
        "main_menu_title": "👋 <b>Main Menu</b>\n\nChoose an action:",
        "btn_add": "➕ Add Channel",
        "btn_list": "📋 My Channels",
        "btn_stats": "📊 Statistics",
        "btn_help": "❓ Help",
        "btn_lang": "🌐 Language / Язык",
        "btn_back": "◀️ Back to Main Menu",
        "btn_back_short": "◀️ Back",
        "btn_delete": "❌ Delete {title}",
        "help": (
            "📖 <b>How to use the bot:</b>\n\n"
            "1️⃣ Click <b>«Add Channel»</b>\n"
            "2️⃣ Send a link to a YouTube channel\n"
            "3️⃣ The bot checks channels every <b>{interval} minutes</b>\n"
            "4️⃣ When a new video is uploaded, you'll get a notification\n\n"
            "<b>Supported links:</b>\n"
            "• <code>youtube.com/channel/UC...</code>\n"
            "• <code>youtube.com/@username</code>\n"
            "• <code>youtube.com/c/Name</code>\n"
            "• <code>youtube.com/user/Name</code>\n\n"
            "You can also just send <code>@username</code>"
        ),
        "limit_alert": "⚠️ Channel limit ({max_channels}) reached! Remove some in «My Channels».",
        "limit_msg": (
            "⚠️ <b>Channel limit reached!</b>\n\n"
            "Maximum <b>{max_channels}</b> channels per user.\n"
            "Remove unused channels in «My Channels»."
        ),
        "send_link_prompt": (
            "🔗 <b>Send a link to a YouTube channel</b>\n\n"
            "Examples:\n"
            "• <code>https://youtube.com/@MrBeast</code>\n"
            "• <code>https://youtube.com/channel/UC...</code>\n"
            "• <code>https://youtube.com/c/ChannelName</code>\n"
            "• Or simply <code>@username</code>"
        ),
        "no_channels": (
            "📭 <b>You have no tracked channels yet.</b>\n\n"
            "Click «Add Channel» to get started!"
        ),
        "your_channels": "📋 <b>Your channels:</b>\n\n",
        "last_check": "   └ Last check: {time}\n\n",
        "stats": (
            "📊 <b>Bot Statistics:</b>\n\n"
            "👤 Users: <b>{users}</b>\n"
            "📺 Total subscriptions: <b>{channels}</b>"
        ),
        "channel_deleted": "✅ Channel deleted!",
        "channel_not_found_alert": "⚠️ Channel not found",
        "unknown_text": "❓ I didn't understand that. Send a YouTube channel link or use the menu below.",
        "checking_channel": "🔍 <b>Checking channel...</b>",
        "err_extract_id": "❌ <b>Could not resolve channel ID.</b>\n\nCheck the link and try again.",
        "err_channel_not_found": "❌ <b>Channel not found or its RSS feed is unavailable.</b>\nCheck the link and try again.",
        "channel_added": (
            "✅ <b>Channel added!</b>\n\n"
            "📺 <b>{title}</b>\n"
            "🆔 <code>{channel_id}</code>"
        ),
        "latest_video_part": (
            "\n\n🎬 <b>Latest video:</b>\n"
            "<a href='https://youtube.com/watch?v={video_id}'>{video_title}</a>"
        ),
        "already_tracked": "⚠️ <b>You are already tracking this channel!</b>",
        "err_generic": "❌ <b>An error occurred.</b>\nPlease try again later or check the link.",
        "new_video_notification": (
            "🎬 <b>New video!</b>\n\n"
            "📺 Channel: <b>{channel_title}</b>\n"
            "📝 {video_title}\n\n"
            "<a href='{video_url}'>▶️ Watch on YouTube</a>"
        ),
    }
}


def t(lang: str, key: str, **kwargs) -> str:
    """Возвращает локализованную строку по языку и ключу."""
    lang_dict = TEXTS.get(lang, TEXTS["ru"])
    text = lang_dict.get(key, TEXTS["ru"].get(key, key))
    return text.format(**kwargs) if kwargs else text


# ==================== БАЗА ДАННЫХ (aiosqlite) ====================

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "youtube_bot.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                lang TEXT DEFAULT 'ru'
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                youtube_channel_id TEXT NOT NULL,
                youtube_channel_title TEXT,
                last_video_id TEXT,
                last_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, youtube_channel_id)
            )
        ''')
        await db.commit()


async def get_user_lang(chat_id: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT lang FROM users WHERE chat_id = ?', (chat_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def get_lang_or_default(chat_id: int) -> str:
    lang = await get_user_lang(chat_id)
    return lang if lang in ("ru", "en") else "ru"


async def set_user_lang(chat_id: int, lang: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO users (chat_id, lang) VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET lang = excluded.lang
        ''', (chat_id, lang))
        await db.commit()


async def add_channel(chat_id, channel_id, channel_title=None, last_video_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute('''
                INSERT INTO channels (chat_id, youtube_channel_id, youtube_channel_title, last_video_id)
                VALUES (?, ?, ?, ?)
            ''', (chat_id, channel_id, channel_title, last_video_id))
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def get_channels(chat_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if chat_id:
            async with db.execute('SELECT * FROM channels WHERE chat_id = ?', (chat_id,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        else:
            async with db.execute('SELECT * FROM channels') as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]


async def count_user_channels(chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT COUNT(*) FROM channels WHERE chat_id = ?', (chat_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0]


async def update_last_video(db_id, video_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            UPDATE channels SET last_video_id = ?, last_check = CURRENT_TIMESTAMP WHERE id = ?
        ''', (video_id, db_id))
        await db.commit()


async def remove_channel(chat_id, youtube_channel_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'DELETE FROM channels WHERE chat_id = ? AND youtube_channel_id = ?',
            (chat_id, youtube_channel_id)
        )
        await db.commit()
        return db.total_changes > 0


async def get_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT COUNT(DISTINCT chat_id), COUNT(*) FROM channels') as cursor:
            return await cursor.fetchone()


# ==================== ПАРСИНГ YOUTUBE И RSS (без API-ключей) ====================

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_COOKIES = {
    "CONSENT": "YES+1",
    "SOCS": "CAISHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVuIAEaBgiAo_CmBg",
}

ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


async def extract_channel_id(session: aiohttp.ClientSession, url_or_handle: str) -> str | None:
    """Извлекает YouTube Channel ID (UC...) из ссылки или @handle без использования YouTube API."""
    text = url_or_handle.strip()

    # 1. Прямая ссылка: youtube.com/channel/UCxxxx
    match = re.search(r"youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})", text)
    if match:
        return match.group(1)

    # 2. Формируем полный URL для запроса страницы
    if text.startswith("@") and "/" not in text:
        page_url = f"https://www.youtube.com/{text}"
    elif text.startswith(("http://", "https://")):
        page_url = text
    elif text.startswith(("www.youtube.com", "youtube.com", "m.youtube.com")):
        page_url = f"https://{text}"
    else:
        return None

    try:
        async with session.get(
            page_url,
            headers=DEFAULT_HEADERS,
            cookies=DEFAULT_COOKIES,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status != 200:
                return None
            page_html = await resp.text()

        # Ищем channel_id по нескольким надежным паттернам в коде страницы
        patterns = [
            r'/feeds/videos\.xml\?channel_id=(UC[a-zA-Z0-9_-]{22})',
            r'itemprop="identifier"\s+content="(UC[a-zA-Z0-9_-]{22})"',
            r'itemprop="channelId"\s+content="(UC[a-zA-Z0-9_-]{22})"',
            r'"externalId":"(UC[a-zA-Z0-9_-]{22})"',
            r'"browseId":"(UC[a-zA-Z0-9_-]{22})"',
        ]
        for pattern in patterns:
            found = re.search(pattern, page_html)
            if found:
                return found.group(1)
    except Exception as e:
        logging.error(f"Ошибка извлечения ID канала из {text}: {e}")

    return None


async def fetch_channel_rss(session: aiohttp.ClientSession, channel_id: str) -> dict | None:
    """
    Запрашивает RSS-фид канала YouTube и возвращает название канала и данные о последнем видео.
    Полностью бесплатно и без квот API.
    """
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        async with session.get(
            feed_url,
            headers=DEFAULT_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status != 200:
                return None
            xml_text = await resp.text()

        root = ET.fromstring(xml_text)
        title_el = root.find("atom:title", ATOM_NS)
        channel_title = title_el.text if title_el is not None else channel_id

        entry = root.find("atom:entry", ATOM_NS)
        latest_video = None

        if entry is not None:
            vid_el = entry.find("yt:videoId", ATOM_NS)
            vtitle_el = entry.find("atom:title", ATOM_NS)
            pub_el = entry.find("atom:published", ATOM_NS)

            video_id = vid_el.text if vid_el is not None else None
            video_title = vtitle_el.text if vtitle_el is not None else "Untitled"
            published_at = pub_el.text if pub_el is not None else ""

            thumb_url = None
            desc_text = ""
            media_group = entry.find("media:group", ATOM_NS)
            if media_group is not None:
                thumb_el = media_group.find("media:thumbnail", ATOM_NS)
                if thumb_el is not None:
                    thumb_url = thumb_el.attrib.get("url")
                desc_el = media_group.find("media:description", ATOM_NS)
                if desc_el is not None and desc_el.text:
                    desc_text = desc_el.text[:200]

            if not thumb_url and video_id:
                thumb_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

            if video_id:
                latest_video = {
                    "video_id": video_id,
                    "title": video_title,
                    "published_at": published_at,
                    "channel_title": channel_title,
                    "thumbnail": thumb_url,
                    "description": desc_text,
                }

        return {
            "channel_id": channel_id,
            "channel_title": channel_title,
            "latest_video": latest_video,
        }
    except Exception as e:
        logging.error(f"Ошибка чтения RSS для {channel_id}: {e}")
        return None


# ==================== AIOGRAM BOT ====================

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru"),
            InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en"),
        ]
    ])


def main_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "btn_add"), callback_data="add_channel")],
        [InlineKeyboardButton(text=t(lang, "btn_list"), callback_data="list_channels")],
        [InlineKeyboardButton(text=t(lang, "btn_stats"), callback_data="stats")],
        [InlineKeyboardButton(text=t(lang, "btn_help"), callback_data="help")],
        [InlineKeyboardButton(text=t(lang, "btn_lang"), callback_data="change_lang")],
    ])


def back_menu_button(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="back_menu")]
    ])


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    lang = await get_user_lang(message.chat.id)
    if not lang:
        await message.answer(
            TEXTS["ru"]["choose_lang"],
            reply_markup=language_keyboard()
        )
        return

    await message.answer(
        t(lang, "welcome"),
        reply_markup=main_menu(lang)
    )


@dp.message(Command("lang", "language"))
async def cmd_lang(message: types.Message):
    lang = await get_lang_or_default(message.chat.id)
    await message.answer(
        t(lang, "choose_lang"),
        reply_markup=language_keyboard()
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    lang = await get_lang_or_default(message.chat.id)
    await message.answer(
        t(lang, "help", interval=CHECK_INTERVAL_MINUTES),
        reply_markup=back_menu_button(lang)
    )


@dp.callback_query(F.data == "change_lang")
async def callback_change_lang(callback: types.CallbackQuery):
    lang = await get_lang_or_default(callback.message.chat.id)
    await callback.message.edit_text(
        t(lang, "choose_lang"),
        reply_markup=language_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("set_lang_"))
async def callback_set_lang(callback: types.CallbackQuery):
    lang = callback.data.replace("set_lang_", "")
    if lang not in ("ru", "en"):
        lang = "ru"

    await set_user_lang(callback.message.chat.id, lang)
    await callback.answer(t(lang, "lang_set").replace("<b>", "").replace("</b>", ""))
    await callback.message.edit_text(
        f"{t(lang, 'lang_set')}\n\n{t(lang, 'welcome')}",
        reply_markup=main_menu(lang)
    )


@dp.callback_query(F.data == "add_channel")
async def callback_add_channel(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    lang = await get_lang_or_default(chat_id)

    user_count = await count_user_channels(chat_id)
    if user_count >= MAX_CHANNELS_PER_USER:
        await callback.answer(
            t(lang, "limit_alert", max_channels=MAX_CHANNELS_PER_USER),
            show_alert=True
        )
        return

    await callback.message.edit_text(
        t(lang, "send_link_prompt"),
        reply_markup=back_menu_button(lang)
    )
    await callback.answer()


@dp.callback_query(F.data == "list_channels")
async def callback_list_channels(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    lang = await get_lang_or_default(chat_id)
    channels = await get_channels(chat_id)

    if not channels:
        await callback.message.edit_text(
            t(lang, "no_channels"),
            reply_markup=main_menu(lang)
        )
        await callback.answer()
        return

    text = t(lang, "your_channels")
    keyboard = []

    for ch in channels:
        safe_title = html.escape(ch["youtube_channel_title"] or ch["youtube_channel_id"])
        text += f"📺 <b>{safe_title}</b>\n"
        text += t(lang, "last_check", time=ch["last_check"])
        keyboard.append([
            InlineKeyboardButton(
                text=t(lang, "btn_delete", title=(ch["youtube_channel_title"] or "")[:25]),
                callback_data=f"del_{ch['youtube_channel_id']}"
            )
        ])

    keyboard.append([InlineKeyboardButton(text=t(lang, "btn_back_short"), callback_data="back_menu")])

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@dp.callback_query(F.data == "stats")
async def callback_stats(callback: types.CallbackQuery):
    lang = await get_lang_or_default(callback.message.chat.id)
    users_count, channels_count = await get_stats()
    await callback.message.edit_text(
        t(lang, "stats", users=users_count, channels=channels_count),
        reply_markup=back_menu_button(lang)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("del_"))
async def callback_delete_channel(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    lang = await get_lang_or_default(chat_id)
    channel_id = callback.data.replace("del_", "")
    success = await remove_channel(chat_id, channel_id)
    if success:
        await callback.answer(t(lang, "channel_deleted"))
    else:
        await callback.answer(t(lang, "channel_not_found_alert"))
    await callback_list_channels(callback)


@dp.callback_query(F.data == "back_menu")
async def callback_back_menu(callback: types.CallbackQuery):
    lang = await get_lang_or_default(callback.message.chat.id)
    await callback.message.edit_text(
        t(lang, "main_menu_title"),
        reply_markup=main_menu(lang)
    )
    await callback.answer()


@dp.callback_query(F.data == "help")
async def callback_help_callback(callback: types.CallbackQuery):
    lang = await get_lang_or_default(callback.message.chat.id)
    await callback.message.edit_text(
        t(lang, "help", interval=CHECK_INTERVAL_MINUTES),
        reply_markup=back_menu_button(lang)
    )
    await callback.answer()


@dp.message(F.text)
async def process_text(message: types.Message):
    chat_id = message.chat.id
    lang = await get_lang_or_default(chat_id)
    text = message.text.strip()

    is_link = text.startswith(("http://", "https://", "www.", "youtube.com", "m.youtube.com", "youtu.be"))
    is_handle = text.startswith("@") and "/" not in text

    if not is_link and not is_handle:
        await message.answer(
            t(lang, "unknown_text"),
            reply_markup=main_menu(lang)
        )
        return

    user_count = await count_user_channels(chat_id)
    if user_count >= MAX_CHANNELS_PER_USER:
        await message.answer(
            t(lang, "limit_msg", max_channels=MAX_CHANNELS_PER_USER),
            reply_markup=main_menu(lang)
        )
        return

    processing_msg = await message.answer(t(lang, "checking_channel"))

    async with aiohttp.ClientSession() as session:
        try:
            channel_id = await extract_channel_id(session, text)
            if not channel_id:
                await processing_msg.edit_text(
                    t(lang, "err_extract_id"),
                    reply_markup=back_menu_button(lang)
                )
                return

            rss_data = await fetch_channel_rss(session, channel_id)
            if not rss_data:
                await processing_msg.edit_text(
                    t(lang, "err_channel_not_found"),
                    reply_markup=back_menu_button(lang)
                )
                return

            channel_title = rss_data["channel_title"]
            latest = rss_data["latest_video"]
            last_video_id = latest["video_id"] if latest else None

            success = await add_channel(chat_id, channel_id, channel_title, last_video_id)

            if success:
                result_text = t(
                    lang,
                    "channel_added",
                    title=html.escape(channel_title),
                    channel_id=channel_id
                )
                if latest:
                    result_text += t(
                        lang,
                        "latest_video_part",
                        video_id=latest["video_id"],
                        video_title=html.escape(latest["title"])
                    )
                await processing_msg.edit_text(
                    result_text,
                    reply_markup=main_menu(lang),
                    disable_web_page_preview=False
                )
            else:
                await processing_msg.edit_text(
                    t(lang, "already_tracked"),
                    reply_markup=main_menu(lang)
                )

        except Exception as e:
            logging.error(f"Ошибка добавления канала: {e}")
            await processing_msg.edit_text(
                t(lang, "err_generic"),
                reply_markup=back_menu_button(lang)
            )


# ==================== ПРОВЕРКА НОВЫХ ВИДЕО (фоновая задача) ====================

async def check_new_videos():
    """Бесконечный цикл проверки каналов через RSS с кэшированием одинаковых каналов за проход."""
    while True:
        all_channels = await get_channels()

        if all_channels:
            logging.info(f"Проверка {len(all_channels)} подписок через RSS...")
            new_videos_count = 0
            rss_cache: dict[str, dict | None] = {}

            async with aiohttp.ClientSession() as session:
                for channel in all_channels:
                    db_id = channel["id"]
                    chat_id = channel["chat_id"]
                    yt_channel_id = channel["youtube_channel_id"]
                    last_video_id = channel["last_video_id"]

                    try:
                        # Если канал уже запрашивали в этом цикле — берем из кэша
                        if yt_channel_id not in rss_cache:
                            rss_cache[yt_channel_id] = await fetch_channel_rss(session, yt_channel_id)

                        rss_data = rss_cache[yt_channel_id]
                        if not rss_data or not rss_data["latest_video"]:
                            continue

                        latest = rss_data["latest_video"]
                        current_video_id = latest["video_id"]

                        if last_video_id is None:
                            await update_last_video(db_id, current_video_id)
                            continue

                        if current_video_id != last_video_id:
                            await update_last_video(db_id, current_video_id)
                            new_videos_count += 1

                            lang = await get_lang_or_default(chat_id)
                            video_url = f"https://youtube.com/watch?v={current_video_id}"
                            message_text = t(
                                lang,
                                "new_video_notification",
                                channel_title=html.escape(latest["channel_title"]),
                                video_title=html.escape(latest["title"]),
                                video_url=video_url
                            )

                            try:
                                if latest["thumbnail"]:
                                    await bot.send_photo(
                                        chat_id=chat_id,
                                        photo=latest["thumbnail"],
                                        caption=message_text
                                    )
                                else:
                                    await bot.send_message(
                                        chat_id=chat_id,
                                        text=message_text,
                                        disable_web_page_preview=False
                                    )
                            except Exception as e:
                                logging.error(f"Ошибка отправки фото в {chat_id}: {e}")
                                try:
                                    await bot.send_message(
                                        chat_id=chat_id,
                                        text=message_text,
                                        disable_web_page_preview=False
                                    )
                                except Exception as e2:
                                    logging.error(f"Не удалось отправить сообщение: {e2}")

                    except Exception as e:
                        logging.error(f"Ошибка проверки канала {yt_channel_id}: {e}")

            if new_videos_count > 0:
                logging.info(f"Найдено и отправлено {new_videos_count} уведомлений о новых видео!")

        await asyncio.sleep(CHECK_INTERVAL_MINUTES * 60)


# ==================== ЗАПУСК ====================

async def main():
    await init_db()
    asyncio.create_task(check_new_videos())
    logging.info("Бот запущен! Проверка каналов каждые %s минут.", CHECK_INTERVAL_MINUTES)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())