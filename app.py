import os
import re
import asyncio
import logging
from datetime import datetime

import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

BOT_TOKEN = ""
YOUTUBE_API_KEY = ""

# Интервал проверки каналов (в минутах)
CHECK_INTERVAL_MINUTES = 15


MAX_CHANNELS_PER_USER = 20

# ═══════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ==================== БАЗА ДАННЫХ (aiosqlite) ====================

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "youtube_bot.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
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


# ==================== YOUTUBE API (через aiohttp) ====================

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


async def youtube_api_get(session: aiohttp.ClientSession, endpoint: str, params: dict):
    """Универсальный GET-запрос к YouTube API."""
    params['key'] = YOUTUBE_API_KEY
    url = f"{YOUTUBE_API_BASE}/{endpoint}"
    async with session.get(url, params=params) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise Exception(f"YouTube API ошибка {resp.status}: {text}")
        return await resp.json()


async def extract_channel_id(session: aiohttp.ClientSession, url: str) -> str | None:
    """Извлекает YouTube Channel ID из разных форматов ссылок."""
    url = url.strip()

    # Формат: youtube.com/channel/UCxxxx
    match = re.search(r'youtube\.com/channel/([a-zA-Z0-9_-]+)', url)
    if match:
        return match.group(1)

    # Формат: youtube.com/@username
    match = re.search(r'youtube\.com/@([a-zA-Z0-9_-]+)', url)
    if match:
        handle = match.group(1)
        data = await youtube_api_get(session, 'channels', {
            'part': 'id',
            'forHandle': handle
        })
        if data.get('items'):
            return data['items'][0]['id']
        data = await youtube_api_get(session, 'search', {
            'part': 'snippet',
            'q': f'@{handle}',
            'type': 'channel',
            'maxResults': 1
        })
        if data.get('items'):
            return data['items'][0]['snippet']['channelId']
        return None

    # Формат: youtube.com/c/CustomName или youtube.com/user/Username
    match = re.search(r'youtube\.com/(?:c|user)/([a-zA-Z0-9_-]+)', url)
    if match:
        name = match.group(1)
        data = await youtube_api_get(session, 'channels', {
            'part': 'id',
            'forUsername': name
        })
        if data.get('items'):
            return data['items'][0]['id']
        data = await youtube_api_get(session, 'search', {
            'part': 'snippet',
            'q': name,
            'type': 'channel',
            'maxResults': 1
        })
        if data.get('items'):
            return data['items'][0]['snippet']['channelId']
        return None

    # Если просто ввели @username без ссылки
    if url.startswith('@') and '/' not in url:
        handle = url[1:]
        data = await youtube_api_get(session, 'channels', {
            'part': 'id',
            'forHandle': handle
        })
        if data.get('items'):
            return data['items'][0]['id']
        return None

    return None


async def get_channel_info(session: aiohttp.ClientSession, channel_id: str) -> dict | None:
    try:
        data = await youtube_api_get(session, 'channels', {
            'part': 'snippet,contentDetails',
            'id': channel_id
        })
        if data.get('items'):
            return data['items'][0]
        return None
    except Exception as e:
        logging.error(f"Ошибка получения инфо о канале {channel_id}: {e}")
        return None


async def get_latest_video(session: aiohttp.ClientSession, channel_id: str) -> dict | None:
    channel_info = await get_channel_info(session, channel_id)
    if not channel_info:
        return None

    uploads_playlist_id = channel_info['contentDetails']['relatedPlaylists']['uploads']

    try:
        data = await youtube_api_get(session, 'playlistItems', {
            'part': 'snippet',
            'playlistId': uploads_playlist_id,
            'maxResults': 1
        })

        if not data.get('items'):
            return None

        video = data['items'][0]['snippet']
        thumbnails = video.get('thumbnails', {})
        thumbnail_url = (
            thumbnails.get('maxres', {}).get('url') or
            thumbnails.get('standard', {}).get('url') or
            thumbnails.get('high', {}).get('url') or
            thumbnails.get('medium', {}).get('url') or
            thumbnails.get('default', {}).get('url')
        )

        return {
            'video_id': video['resourceId']['videoId'],
            'title': video['title'],
            'published_at': video['publishedAt'],
            'channel_title': video['channelTitle'],
            'thumbnail': thumbnail_url,
            'description': video.get('description', '')[:200]
        }
    except Exception as e:
        logging.error(f"Ошибка получения видео для {channel_id}: {e}")
        return None


# ==================== AIORAM BOT ====================

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить канал", callback_data="add_channel")],
        [InlineKeyboardButton(text="📋 Мои каналы", callback_data="list_channels")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")]
    ])


def back_menu_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="back_menu")]
    ])


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 <b>Привет!</b>\n\n"
        "Я бот для отслеживания новых видео на <b>YouTube</b>.\n"
        "Добавь каналы по ссылке, и я буду присылать уведомления о новых роликах!",
        reply_markup=main_menu()
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "📖 <b>Как пользоваться ботом:</b>\n\n"
        "1️⃣ Нажми <b>«Добавить канал»</b>\n"
        "2️⃣ Отправь ссылку на YouTube-канал\n"
        "3️⃣ Бот проверяет каналы каждые <b>30 минут</b>\n"
        "4️⃣ При выходе нового видео пришлёт уведомление\n\n"
        "<b>Поддерживаемые ссылки:</b>\n"
        "• <code>youtube.com/channel/UC...</code>\n"
        "• <code>youtube.com/@username</code>\n"
        "• <code>youtube.com/c/Name</code>\n"
        "• <code>youtube.com/user/Name</code>\n\n"
        "Можно просто отправить <code>@username</code>",
        reply_markup=back_menu_button()
    )


@dp.callback_query(F.data == "add_channel")
async def callback_add_channel(callback: types.CallbackQuery):
    # Проверяем лимит
    user_count = await count_user_channels(callback.message.chat.id)
    if user_count >= MAX_CHANNELS_PER_USER:
        await callback.answer(
            f"⚠️ Лимит каналов ({MAX_CHANNELS_PER_USER}) достигнут! Удали лишние в «Мои каналы».",
            show_alert=True
        )
        return

    await callback.message.edit_text(
        "🔗 <b>Отправь ссылку на YouTube-канал</b>\n\n"
        "Примеры:\n"
        "• <code>https://youtube.com/@MrBeast</code>\n"
        "• <code>https://youtube.com/channel/UC...</code>\n"
        "• <code>https://youtube.com/c/ChannelName</code>\n"
        "• Или просто <code>@username</code>",
        reply_markup=back_menu_button()
    )
    await callback.answer()


@dp.callback_query(F.data == "list_channels")
async def callback_list_channels(callback: types.CallbackQuery):
    channels = await get_channels(callback.message.chat.id)

    if not channels:
        await callback.message.edit_text(
            "📭 <b>У тебя пока нет отслеживаемых каналов.</b>\n\n"
            "Нажми «Добавить канал», чтобы начать!",
            reply_markup=main_menu()
        )
        await callback.answer()
        return

    text = "📋 <b>Твои каналы:</b>\n\n"
    keyboard = []

    for ch in channels:
        text += f"📺 <b>{ch['youtube_channel_title']}</b>\n"
        text += f"   └ Последняя проверка: {ch['last_check']}\n\n"
        keyboard.append([
            InlineKeyboardButton(
                text=f"❌ Удалить {ch['youtube_channel_title'][:25]}",
                callback_data=f"del_{ch['youtube_channel_id']}"
            )
        ])

    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_menu")])

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@dp.callback_query(F.data == "stats")
async def callback_stats(callback: types.CallbackQuery):
    users_count, channels_count = await get_stats()
    await callback.message.edit_text(
        f"📊 <b>Статистика бота:</b>\n\n"
        f"👤 Пользователей: <b>{users_count}</b>\n"
        f"📺 Всего каналов: <b>{channels_count}</b>",
        reply_markup=back_menu_button()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("del_"))
async def callback_delete_channel(callback: types.CallbackQuery):
    channel_id = callback.data.replace("del_", "")
    success = await remove_channel(callback.message.chat.id, channel_id)
    if success:
        await callback.answer("✅ Канал удалён!")
    else:
        await callback.answer("⚠️ Канал не найден")
    await callback_list_channels(callback)


@dp.callback_query(F.data == "back_menu")
async def callback_back_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "👋 <b>Главное меню</b>\n\nВыбери действие:",
        reply_markup=main_menu()
    )
    await callback.answer()


@dp.callback_query(F.data == "help")
async def callback_help_callback(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📖 <b>Как пользоваться ботом:</b>\n\n"
        "1️⃣ Нажми <b>«Добавить канал»</b>\n"
        "2️⃣ Отправь ссылку на YouTube-канал\n"
        "3️⃣ Бот проверяет каналы каждые <b>30 минут</b>\n"
        "4️⃣ При выходе нового видео пришлёт уведомление\n\n"
        "<b>Поддерживаемые ссылки:</b>\n"
        "• <code>youtube.com/channel/UC...</code>\n"
        "• <code>youtube.com/@username</code>\n"
        "• <code>youtube.com/c/Name</code>\n"
        "• <code>youtube.com/user/Name</code>\n\n"
        "Можно просто отправить <code>@username</code>",
        reply_markup=back_menu_button()
    )
    await callback.answer()


@dp.message(F.text)
async def process_text(message: types.Message):
    text = message.text.strip()
    is_link = text.startswith(("http", "www", "youtube.com", "youtu.be"))
    is_handle = text.startswith("@") and "/" not in text

    if not is_link and not is_handle:
        await message.answer(
            "❓ Я не понял. Отправь ссылку на YouTube-канал или выбери действие в меню.",
            reply_markup=main_menu()
        )
        return

    # Проверяем лимит каналов
    user_count = await count_user_channels(message.chat.id)
    if user_count >= MAX_CHANNELS_PER_USER:
        await message.answer(
            f"⚠️ <b>Лимит каналов достигнут!</b>\n\n"
            f"Максимум <b>{MAX_CHANNELS_PER_USER}</b> каналов на пользователя.\n"
            f"Удали лишние в разделе «Мои каналы».",
            reply_markup=main_menu()
        )
        return

    processing_msg = await message.answer("🔍 <b>Проверяю канал...</b>")

    async with aiohttp.ClientSession() as session:
        try:
            channel_id = await extract_channel_id(session, text)
            if not channel_id:
                await processing_msg.edit_text(
                    "❌ <b>Не удалось определить канал.</b>\n\nПроверь ссылку и попробуй снова.",
                    reply_markup=back_menu_button()
                )
                return

            channel_info = await get_channel_info(session, channel_id)
            if not channel_info:
                await processing_msg.edit_text(
                    "❌ <b>Канал не найден.</b>\nВозможно, ссылка неверная или канал удалён.",
                    reply_markup=back_menu_button()
                )
                return

            channel_title = channel_info['snippet']['title']
            latest = await get_latest_video(session, channel_id)
            last_video_id = latest['video_id'] if latest else None

            success = await add_channel(message.chat.id, channel_id, channel_title, last_video_id)

            if success:
                result_text = (
                    f"✅ <b>Канал добавлен!</b>\n\n"
                    f"📺 <b>{channel_title}</b>\n"
                    f"🆔 <code>{channel_id}</code>"
                )
                if latest:
                    result_text += (
                        f"\n\n🎬 <b>Последнее видео:</b>\n"
                        f"<a href=\'https://youtube.com/watch?v={latest['video_id']}\'>{latest['title']}</a>"
                    )
                await processing_msg.edit_text(
                    result_text,
                    reply_markup=main_menu(),
                    disable_web_page_preview=False
                )
            else:
                await processing_msg.edit_text(
                    "⚠️ <b>Этот канал уже отслеживается!</b>",
                    reply_markup=main_menu()
                )

        except Exception as e:
            logging.error(f"Ошибка добавления канала: {e}")
            await processing_msg.edit_text(
                "❌ <b>Произошла ошибка.</b>\nПопробуй позже или проверь ссылку.",
                reply_markup=back_menu_button()
            )


# ==================== ПРОВЕРКА НОВЫХ ВИДЕО (фоновая задача) ====================

async def check_new_videos():
    """Бесконечный цикл проверки каналов."""
    while True:
        all_channels = await get_channels()

        if all_channels:
            logging.info(f"Проверка {len(all_channels)} каналов...")
            new_videos_count = 0

            async with aiohttp.ClientSession() as session:
                for channel in all_channels:
                    db_id = channel['id']
                    chat_id = channel['chat_id']
                    yt_channel_id = channel['youtube_channel_id']
                    last_video_id = channel['last_video_id']

                    try:
                        latest = await get_latest_video(session, yt_channel_id)
                        if not latest:
                            continue

                        current_video_id = latest['video_id']

                        if last_video_id is None:
                            await update_last_video(db_id, current_video_id)
                            continue

                        if current_video_id != last_video_id:
                            await update_last_video(db_id, current_video_id)
                            new_videos_count += 1

                            video_url = f"https://youtube.com/watch?v={current_video_id}"
                            message_text = (
                                f"🎬 <b>Новое видео!</b>\n\n"
                                f"📺 Канал: <b>{latest['channel_title']}</b>\n"
                                f"📝 {latest['title']}\n\n"
                                f"<a href=\'{video_url}\'>▶️ Смотреть на YouTube</a>"
                            )

                            try:
                                if latest['thumbnail']:
                                    await bot.send_photo(
                                        chat_id=chat_id,
                                        photo=latest['thumbnail'],
                                        caption=message_text
                                    )
                                else:
                                    await bot.send_message(
                                        chat_id=chat_id,
                                        text=message_text,
                                        disable_web_page_preview=False
                                    )
                            except Exception as e:
                                logging.error(f"Ошибка отправки в {chat_id}: {e}")
                                try:
                                    await bot.send_message(
                                        chat_id=chat_id,
                                        text=message_text,
                                        disable_web_page_preview=False
                                    )
                                except Exception as e2:
                                    logging.error(f"Не удалось отправить: {e2}")

                    except Exception as e:
                        logging.error(f"Ошибка проверки канала {yt_channel_id}: {e}")

            if new_videos_count > 0:
                logging.info(f"Найдено {new_videos_count} новых видео!")

        await asyncio.sleep(CHECK_INTERVAL_MINUTES * 60)


# ==================== ЗАПУСК ====================

async def main():
    await init_db()
    asyncio.create_task(check_new_videos())
    logging.info("Бот запущен! Проверка каналов каждые %s минут.", CHECK_INTERVAL_MINUTES)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
