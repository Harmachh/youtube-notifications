import asyncio
import html
import logging
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

BOT_TOKEN =("BOT_TOKEN", "YOUR_BOT_TOKEN")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "900"))
MAX_CHANNELS = 20
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "youtube_bot.db")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
COOKIES = {"SOCS": "CAISHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVuIAEaBgiAo_CmBg"}
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}

TEXTS = {
    "ru": {
        "lang_pick": "🌐 <b>Выберите язык / Choose language:</b>",
        "lang_ok": "✅ Язык: <b>Русский</b>",
        "welcome": "👋 <b>Привет!</b>\nБот отслеживает новые видео на <b>YouTube</b> через RSS.\nПрисылай ссылку на канал, и я буду уведомлять о релизах.",
        "menu": "👋 <b>Главное меню:</b>",
        "btn_add": "➕ Добавить",
        "btn_list": "📋 Мои каналы",
        "btn_stats": "📊 Статистика",
        "btn_help": "❓ Помощь",
        "btn_lang": "🌐 Язык",
        "btn_back": "◀️ Назад",
        "btn_del": "❌ {title}",
        "help": "📖 Отправь ссылку на канал (<code>@handle</code>, <code>channel/UC...</code> или обычный URL).\nБот проверяет обновления каждые {intv} мин.",
        "limit": "⚠️ Лимит ({max_ch}) каналов исчерпан.",
        "prompt": "🔗 Отправь ссылку на YouTube-канал или <code>@handle</code>.",
        "empty": "📭 Список каналов пуст.",
        "channels": "📋 <b>Твои каналы:</b>\n\n",
        "stats": "📊 Пользователей: <b>{u}</b>\n📺 Подписок: <b>{c}</b>",
        "deleted": "✅ Удалено",
        "unknown": "❓ Неизвестная команда. Отправь ссылку на канал.",
        "checking": "🔍 Проверяю канал...",
        "not_found": "❌ Канал не найден.",
        "added": "✅ Добавлен: <b>{title}</b>\n🆔 <code>{cid}</code>",
        "last_vid": "\n\n🎬 <b>Последнее:</b> <a href='https://youtu.be/{vid}'>{vtitle}</a>",
        "exists": "⚠️ Этот канал уже добавлен.",
        "err": "❌ Ошибка обработки.",
        "notify": "🎬 <b>Новое видео!</b>\n\n📺 <b>{ch}</b>\n📝 {title}\n\n<a href='https://youtu.be/{vid}'>▶️ Смотреть</a>",
    },
    "en": {
        "lang_pick": "🌐 <b>Choose language / Выберите язык:</b>",
        "lang_ok": "✅ Language: <b>English</b>",
        "welcome": "👋 <b>Hello!</b>\nTrack new <b>YouTube</b> uploads via RSS.\nSend a channel link to get notified.",
        "menu": "👋 <b>Main Menu:</b>",
        "btn_add": "➕ Add",
        "btn_list": "📋 My channels",
        "btn_stats": "📊 Stats",
        "btn_help": "❓ Help",
        "btn_lang": "🌐 Language",
        "btn_back": "◀️ Back",
        "btn_del": "❌ {title}",
        "help": "📖 Send a YouTube channel link (<code>@handle</code>, <code>channel/UC...</code> or URL).\nChecks every {intv} min.",
        "limit": "⚠️ Limit ({max_ch}) channels reached.",
        "prompt": "🔗 Send a YouTube channel link or <code>@handle</code>.",
        "empty": "📭 Channel list is empty.",
        "channels": "📋 <b>Your channels:</b>\n\n",
        "stats": "📊 Users: <b>{u}</b>\n📺 Subscriptions: <b>{c}</b>",
        "deleted": "✅ Deleted",
        "unknown": "❓ Invalid command. Send a channel link.",
        "checking": "🔍 Checking channel...",
        "not_found": "❌ Channel not found.",
        "added": "✅ Added: <b>{title}</b>\n🆔 <code>{cid}</code>",
        "last_vid": "\n\n🎬 <b>Latest:</b> <a href='https://youtu.be/{vid}'>{vtitle}</a>",
        "exists": "⚠️ Already tracking this channel.",
        "err": "❌ Processing error.",
        "notify": "🎬 <b>New video!</b>\n\n📺 <b>{ch}</b>\n📝 {title}\n\n<a href='https://youtu.be/{vid}'>▶️ Watch</a>",
    },
}


def tr(lang: str, key: str, **kw) -> str:
    res = TEXTS.get(lang, TEXTS["ru"]).get(key, TEXTS["ru"].get(key, key))
    return res.format(**kw) if kw else res


@dataclass(slots=True)
class Video:
    vid: str
    title: str
    thumb: str | None


class Database:
    def __init__(self, path: str):
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self):
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript("""
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                lang TEXT DEFAULT 'ru'
            );
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                channel_id TEXT NOT NULL,
                channel_title TEXT,
                last_video_id TEXT,
                UNIQUE(chat_id, channel_id)
            );
            CREATE INDEX IF NOT EXISTS idx_channel_id ON channels(channel_id);
        """)
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()

    async def get_lang(self, chat_id: int) -> str:
        async with self._db.execute("SELECT lang FROM users WHERE chat_id = ?", (chat_id,)) as cur:
            row = await cur.fetchone()
            return row["lang"] if row and row["lang"] in ("ru", "en") else "ru"

    async def set_lang(self, chat_id: int, lang: str):
        await self._db.execute(
            "INSERT INTO users (chat_id, lang) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET lang = excluded.lang",
            (chat_id, lang),
        )
        await self._db.commit()

    async def add_channel(self, chat_id: int, cid: str, title: str, last_vid: str | None) -> bool:
        try:
            await self._db.execute(
                "INSERT INTO channels (chat_id, channel_id, channel_title, last_video_id) VALUES (?, ?, ?, ?)",
                (chat_id, cid, title, last_vid),
            )
            await self._db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def get_user_channels(self, chat_id: int):
        async with self._db.execute("SELECT * FROM channels WHERE chat_id = ?", (chat_id,)) as cur:
            return await cur.fetchall()

    async def count_user_channels(self, chat_id: int) -> int:
        async with self._db.execute("SELECT COUNT(*) FROM channels WHERE chat_id = ?", (chat_id,)) as cur:
            return (await cur.fetchone())[0]

    async def remove_channel(self, chat_id: int, cid: str) -> bool:
        await self._db.execute("DELETE FROM channels WHERE chat_id = ? AND channel_id = ?", (chat_id, cid))
        await self._db.commit()
        return self._db.total_changes > 0

    async def delete_user(self, chat_id: int):
        await self._db.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
        await self._db.execute("DELETE FROM channels WHERE chat_id = ?", (chat_id,))
        await self._db.commit()

    async def get_distinct_channels(self):
        async with self._db.execute("SELECT DISTINCT channel_id FROM channels") as cur:
            return [r[0] for r in await cur.fetchall()]

    async def get_subscribers(self, cid: str):
        async with self._db.execute(
            """
            SELECT c.id, c.chat_id, c.last_video_id, u.lang 
            FROM channels c 
            LEFT JOIN users u ON c.chat_id = u.chat_id 
            WHERE c.channel_id = ?
            """,
            (cid,),
        ) as cur:
            return await cur.fetchall()

    async def update_last_video(self, record_id: int, vid: str):
        await self._db.execute("UPDATE channels SET last_video_id = ? WHERE id = ?", (vid, record_id))
        await self._db.commit()

    async def get_stats(self):
        async with self._db.execute("SELECT COUNT(DISTINCT chat_id), COUNT(*) FROM channels") as cur:
            return await cur.fetchone()


class YouTubeParser:
    PATTERNS = (
        r"/feeds/videos\.xml\?channel_id=(UC[a-zA-Z0-9_-]{22})",
        r'itemprop="channelId"\s+content="(UC[a-zA-Z0-9_-]{22})"',
        r'itemprop="identifier"\s+content="(UC[a-zA-Z0-9_-]{22})"',
        r'"externalId":"(UC[a-zA-Z0-9_-]{22})"',
    )

    def __init__(self, session: aiohttp.ClientSession, limit: int = 5):
        self.session = session
        self.sem = asyncio.Semaphore(limit)

    async def resolve_id(self, raw: str) -> str | None:
        raw = raw.strip()
        if m := re.search(r"youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})", raw):
            return m.group(1)

        url = f"https://www.youtube.com/{raw}" if raw.startswith("@") else raw
        if not url.startswith("http"):
            url = f"https://{url}"

        try:
            async with self.sem, self.session.get(url, headers=HEADERS, cookies=COOKIES, timeout=10) as r:
                if r.status != 200:
                    return None
                body = await r.text()
                for pat in self.PATTERNS:
                    if hit := re.search(pat, body):
                        return hit.group(1)
        except Exception:
            return None
        return None

    async def fetch_feed(self, cid: str) -> tuple[str, Video | None] | None:
        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
        try:
            async with self.sem, self.session.get(feed_url, headers=HEADERS, timeout=10) as r:
                if r.status != 200:
                    return None
                root = ET.fromstring(await r.text())
        except Exception:
            return None

        title = root.findtext("atom:title", default=cid, namespaces=NS)
        entry = root.find("atom:entry", NS)
        if entry is None:
            return title, None

        vid = entry.findtext("yt:videoId", namespaces=NS)
        if not vid:
            return title, None

        vtitle = entry.findtext("atom:title", default="", namespaces=NS)
        thumb = None
        if (group := entry.find("media:group", NS)) is not None:
            if (t_node := group.find("media:thumbnail", NS)) is not None:
                thumb = t_node.attrib.get("url")
        thumb = thumb or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

        return title, Video(vid=vid, title=vtitle, thumb=thumb)


db = Database(DB_PATH)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


def kb_lang() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
        InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
    ]])


def kb_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(lang, "btn_add"), callback_data="nav:add")],
        [InlineKeyboardButton(text=tr(lang, "btn_list"), callback_data="nav:list")],
        [
            InlineKeyboardButton(text=tr(lang, "btn_stats"), callback_data="nav:stats"),
            InlineKeyboardButton(text=tr(lang, "btn_help"), callback_data="nav:help"),
        ],
        [InlineKeyboardButton(text=tr(lang, "btn_lang"), callback_data="nav:lang")],
    ])


def kb_back(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=tr(lang, "btn_back"), callback_data="nav:menu")
    ]])


@dp.message(Command("start"))
async def handle_start(m: types.Message):
    lang = await db.get_lang(m.chat.id)
    await m.answer(tr(lang, "welcome"), reply_markup=kb_menu(lang))


@dp.message(Command("help"))
async def handle_help(m: types.Message):
    lang = await db.get_lang(m.chat.id)
    await m.answer(tr(lang, "help", intv=CHECK_INTERVAL // 60), reply_markup=kb_back(lang))


@dp.message(Command("lang"))
async def handle_lang_cmd(m: types.Message):
    lang = await db.get_lang(m.chat.id)
    await m.answer(tr(lang, "lang_pick"), reply_markup=kb_lang())


@dp.callback_query(F.data.startswith("lang:"))
async def cb_lang(c: types.CallbackQuery):
    lang = c.data.split(":")[1]
    await db.set_lang(c.message.chat.id, lang)
    await c.answer()
    await c.message.edit_text(f"{tr(lang, 'lang_ok')}\n\n{tr(lang, 'welcome')}", reply_markup=kb_menu(lang))


@dp.callback_query(F.data.startswith("nav:"))
async def cb_nav(c: types.CallbackQuery):
    action = c.data.split(":")[1]
    chat_id = c.message.chat.id
    lang = await db.get_lang(chat_id)
    await c.answer()

    match action:
        case "menu":
            await c.message.edit_text(tr(lang, "menu"), reply_markup=kb_menu(lang))
        case "lang":
            await c.message.edit_text(tr(lang, "lang_pick"), reply_markup=kb_lang())
        case "help":
            await c.message.edit_text(tr(lang, "help", intv=CHECK_INTERVAL // 60), reply_markup=kb_back(lang))
        case "stats":
            u, ch = await db.get_stats()
            await c.message.edit_text(tr(lang, "stats", u=u, c=ch), reply_markup=kb_back(lang))
        case "add":
            if await db.count_user_channels(chat_id) >= MAX_CHANNELS:
                await c.answer(tr(lang, "limit", max_ch=MAX_CHANNELS), show_alert=True)
                return
            await c.message.edit_text(tr(lang, "prompt"), reply_markup=kb_back(lang))
        case "list":
            rows = await db.get_user_channels(chat_id)
            if not rows:
                await c.message.edit_text(tr(lang, "empty"), reply_markup=kb_menu(lang))
                return
            buttons = [
                [InlineKeyboardButton(text=tr(lang, "btn_del", title=r["channel_title"][:25]), callback_data=f"del:{r['channel_id']}")]
                for r in rows
            ]
            buttons.append([InlineKeyboardButton(text=tr(lang, "btn_back"), callback_data="nav:menu")])
            await c.message.edit_text(tr(lang, "channels"), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.callback_query(F.data.startswith("del:"))
async def cb_delete(c: types.CallbackQuery):
    cid = c.data.split(":")[1]
    chat_id = c.message.chat.id
    lang = await db.get_lang(chat_id)
    await db.remove_channel(chat_id, cid)
    await c.answer(tr(lang, "deleted"))

    rows = await db.get_user_channels(chat_id)
    if not rows:
        await c.message.edit_text(tr(lang, "empty"), reply_markup=kb_menu(lang))
        return
    buttons = [
        [InlineKeyboardButton(text=tr(lang, "btn_del", title=r["channel_title"][:25]), callback_data=f"del:{r['channel_id']}")]
        for r in rows
    ]
    buttons.append([InlineKeyboardButton(text=tr(lang, "btn_back"), callback_data="nav:menu")])
    await c.message.edit_text(tr(lang, "channels"), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.message(F.text)
async def handle_input(m: types.Message, parser: YouTubeParser):
    chat_id = m.chat.id
    lang = await db.get_lang(chat_id)
    text = m.text.strip()

    if not (text.startswith(("@", "http://", "https://", "www.")) or "youtube.com" in text or "youtu.be" in text):
        await m.answer(tr(lang, "unknown"), reply_markup=kb_menu(lang))
        return

    if await db.count_user_channels(chat_id) >= MAX_CHANNELS:
        await m.answer(tr(lang, "limit", max_ch=MAX_CHANNELS), reply_markup=kb_menu(lang))
        return

    status = await m.answer(tr(lang, "checking"))
    cid = await parser.resolve_id(text)
    if not cid:
        await status.edit_text(tr(lang, "not_found"), reply_markup=kb_back(lang))
        return

    feed = await parser.fetch_feed(cid)
    if not feed:
        await status.edit_text(tr(lang, "not_found"), reply_markup=kb_back(lang))
        return

    title, video = feed
    ok = await db.add_channel(chat_id, cid, title, video.vid if video else None)
    if not ok:
        await status.edit_text(tr(lang, "exists"), reply_markup=kb_menu(lang))
        return

    out = tr(lang, "added", title=html.escape(title), cid=cid)
    if video:
        out += tr(lang, "last_vid", vid=video.vid, vtitle=html.escape(video.title))
    await status.edit_text(out, reply_markup=kb_menu(lang), disable_web_page_preview=False)


async def send_notify(chat_id: int, text: str, thumb: str | None):
    try:
        if thumb:
            await bot.send_photo(chat_id=chat_id, photo=thumb, caption=text)
        else:
            await bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=False)
    except TelegramForbiddenError:
        await db.delete_user(chat_id)
    except Exception as e:
        logging.warning("Send error %s: %s", chat_id, e)


async def monitor(parser: YouTubeParser):
    while True:
        try:
            channels = await db.get_distinct_channels()
            for cid in channels:
                feed = await parser.fetch_feed(cid)
                if not feed or not feed[1]:
                    continue

                title, video = feed
                subs = await db.get_subscribers(cid)

                for row in subs:
                    rec_id, chat_id, last_vid, lang = row["id"], row["chat_id"], row["last_video_id"], row["lang"] or "ru"
                    if last_vid is None:
                        await db.update_last_video(rec_id, video.vid)
                        continue

                    if video.vid != last_vid:
                        await db.update_last_video(rec_id, video.vid)
                        msg = tr(lang, "notify", ch=html.escape(title), title=html.escape(video.title), vid=video.vid)
                        asyncio.create_task(send_notify(chat_id, msg, video.thumb))
        except Exception as e:
            logging.error("Monitor loop error: %s", e)

        await asyncio.sleep(CHECK_INTERVAL)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    await db.connect()

    async with aiohttp.ClientSession() as session:
        parser = YouTubeParser(session)
        dp["parser"] = parser

        asyncio.create_task(monitor(parser))
        try:
            await dp.start_polling(bot)
        finally:
            await db.close()


if __name__ == "__main__":
    asyncio.run(main())