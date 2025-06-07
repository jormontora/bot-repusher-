import os
import re
import logging
import hashlib
import asyncio
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import FSInputFile
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
import yt_dlp

API_TOKEN = '7654313992:AAF-IlnkA50SEBC_ajaicQu-Id8_WbYZMqM'  # <-- Replace with your bot token

# Кастомний фільтр для логів (ігнорувати "Update id=... is not handled...")
class UsefulLogFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return not (
            "Update id=" in msg and "is not handled" in msg
        )

# Налаштування логування
file_handler = logging.FileHandler("bot.log", encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
file_handler.addFilter(UsefulLogFilter())
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
console_handler.addFilter(UsefulLogFilter())
logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, console_handler]
)
logger = logging.getLogger(__name__)

# Ініціалізація бота та диспетчера (aiogram v3)
bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# Директорія для кешу відео
CACHE_DIR = "video_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# Файли для збереження даних
USERS_FILE = "users.json"
GROUPS_FILE = "groups.json"
BANNED_FILE = "banned.json"
STATS_FILE = "stats.json"

# Регулярні вирази для TikTok (включаючи vt.tiktok.com), Instagram Reels, YouTube Shorts, Facebook Reels
TIKTOK_PATTERN = r'(https?://(?:www\.)?(?:tiktok\.com/[^\s]+|vm\.tiktok\.com/\S+|vt\.tiktok\.com/\S+))'
INSTA_REELS_PATTERN = r'(https?://(?:www\.)?instagram\.com/(?:reel|reels|p)/[^\s]+)'
YTSHORTS_PATTERN = r'(https?://(?:www\.)?(?:youtube\.com/shorts/[^\s]+|youtu\.be/[^\s]+))'
FB_REELS_PATTERN = (
    r'(https?://(?:www\.)?(?:facebook\.com/(?:reel|reels|share/v|share/r)/[^\s]+|fb\.watch/[^\s]+))'
)

# --- Адмінські змінні та структури ---
ADMIN_IDS = {752113604}  # Заміни на свій Telegram user_id
OWNER_ID = 752113604     # Власник бота

max_cache_size = 2 * 1024 * 1024 * 1024  # 2 ГБ за замовчуванням
max_video_size = 50 * 1024 * 1024        # 50 МБ за замовчуванням

# --- JSON persistence helpers ---
def load_json(filename, default):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_stats():
    stats = load_json(STATS_FILE, {"processed_videos": 0, "max_cache_size": max_cache_size, "max_video_size": max_video_size})
    return stats

def set_stats(stats):
    save_json(STATS_FILE, stats)

def get_users():
    return set(load_json(USERS_FILE, []))

def add_user(user_id):
    users = get_users()
    users.add(user_id)
    save_json(USERS_FILE, list(users))

def get_groups():
    return set(load_json(GROUPS_FILE, []))

def add_group(group_id):
    groups = get_groups()
    groups.add(group_id)
    save_json(GROUPS_FILE, list(groups))

def get_banned():
    return set(load_json(BANNED_FILE, []))

def ban_user(user_id):
    banned = get_banned()
    banned.add(user_id)
    save_json(BANNED_FILE, list(banned))

def unban_user(user_id):
    banned = get_banned()
    banned.discard(user_id)
    save_json(BANNED_FILE, list(banned))

def get_cache_path(url):
    url_hash = hashlib.md5(url.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{url_hash}.mp4")

# --- Адмінські декоратори ---
def admin_only(func):
    async def wrapper(message: types.Message, *args, **kwargs):
        # Видаляємо всі зайві ключі з kwargs (aiogram v3 може передавати dispatcher, bots, event_from_user тощо)
        for k in list(kwargs.keys()):
            if k not in ("self",):
                kwargs.pop(k)
        if message.from_user.id not in ADMIN_IDS:
            await message.reply("Нет прав.")
            return
        return await func(message, *args, **kwargs)
    return wrapper

def owner_only(func):
    async def wrapper(message: types.Message, *args, **kwargs):
        for k in list(kwargs.keys()):
            if k not in ("self",):
                kwargs.pop(k)
        if message.from_user.id != OWNER_ID:
            await message.reply("Нет прав.")
            return
        return await func(message, *args, **kwargs)
    return wrapper

# --- Команди для користувачів ---
async def send_welcome(message: types.Message):
    await message.reply("Привет! Пришли мне ссылку на TikTok, Instagram Reels, YouTube Shorts или Facebook Reels, и я пришлю тебе видео.")

async def send_help(message: types.Message):
    await message.reply(
        "Этот бот скачивает видео из TikTok, Instagram Reels, YouTube Shorts и Facebook Reels.\n"
        "Просто отправь ссылку на видео.\n"
        "Максимальный размер файла — 50 МБ."
    )

@admin_only
async def admin_stats(message: types.Message):
    cache_size = get_cache_size()
    stats = get_stats()
    await message.reply(
        f"Статистика:\n"
        f"Обработано видео: {stats.get('processed_videos', 0)}\n"
        f"Размер кеша: {cache_size // (1024*1024)} МБ\n"
        f"Унікальних користувачів: {len(get_users())}\n"
        f"Групп: {len(get_groups())}"
    )

@admin_only
async def admin_clear_cache(message: types.Message):
    clear_cache_on_start()
    await message.reply("Кеш очищен.")

@admin_only
async def admin_users(message: types.Message):
    users = get_users()
    if users:
        user_lines = []
        for uid in users:
            try:
                user = await bot.get_chat(uid)
                name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
                username = f"@{user.username}" if user.username else ""
                user_lines.append(f"{uid} - {name} {username}".strip())
            except Exception:
                user_lines.append(f"{uid} - Пользователь")
        await message.reply("Уникальні користувачі:\n" + "\n".join(user_lines))
    else:
        await message.reply("Пользователей пока нет.")

@admin_only
async def admin_groups(message: types.Message):
    groups = get_groups()
    if groups:
        group_lines = []
        for gid in groups:
            try:
                chat = await bot.get_chat(gid)
                title = chat.title or ""
                group_lines.append(f"{gid} - {title}")
            except Exception:
                group_lines.append(f"{gid} - Група")
        await message.reply("Групи:\n" + "\n".join(group_lines))
    else:
        await message.reply("Груп поки немає.")

@admin_only
async def admin_set_max_cache(message: types.Message):
    try:
        size_mb = int(message.text.split()[1])
        stats = get_stats()
        stats["max_cache_size"] = size_mb * 1024 * 1024
        set_stats(stats)
        await message.reply(f"Новий ліміт кешу: {size_mb} МБ")
    except Exception:
        await message.reply("Використання: /set_max_cache SIZE_MB")

@admin_only
async def admin_set_max_video(message: types.Message):
    try:
        size_mb = int(message.text.split()[1])
        stats = get_stats()
        stats["max_video_size"] = size_mb * 1024 * 1024
        set_stats(stats)
        await message.reply(f"Новий ліміт розміру відео: {size_mb} МБ")
    except Exception:
        await message.reply("Використання: /set_max_video SIZE_MB")

@admin_only
async def admin_ban_user(message: types.Message):
    try:
        user_id = int(message.text.split()[1])
        ban_user(user_id)
        await message.reply(f"Користувач {user_id} заблокований.")
    except Exception:
        await message.reply("Використання: /ban_user USER_ID")

@admin_only
async def admin_unban_user(message: types.Message):
    try:
        user_id = int(message.text.split()[1])
        unban_user(user_id)
        await message.reply(f"Користувач {user_id} розблокований.")
    except Exception:
        await message.reply("Використання: /unban_user USER_ID")

@admin_only
async def admin_help(message: types.Message):
    await message.reply(
        "/stats — статистика\n"
        "/clear_cache — очистити кеш\n"
        "/users — користувачі\n"
        "/groups — групи\n"
        "/set_max_cache SIZE_MB — ліміт кешу\n"
        "/set_max_video SIZE_MB — Ліміт відео\n"
        "/ban_user USER_ID — БАН\n"
        "/unban_user USER_ID — розбан\n"
        "/logs N — N рядків логів\n"
        "/shutdown — вимкнути бота\n"
        "/broadcast TEXT — розсилка"
    )

@admin_only
async def admin_logs(message: types.Message):
    try:
        n = int(message.text.split()[1])
        with open("bot.log", encoding="utf-8") as f:
            lines = f.readlines()[-n:]
        await message.reply("".join(lines[-20:])[-4000:] or "Логів немає.")
    except Exception:
        await message.reply("Використання: /logs N")

@owner_only
async def admin_shutdown(message: types.Message):
    await message.reply("Бот вимикається...")
    await bot.session.close()
    exit(0)

@admin_only
async def admin_broadcast(message: types.Message):
    text = message.text.partition(' ')[2].strip()
    if not text:
        await message.reply("Використання: /broadcast TEXT")
        return
    count = 0
    for uid in get_users():
        try:
            await bot.send_message(uid, text)
            count += 1
        except Exception:
            pass
    for gid in get_groups():
        try:
            await bot.send_message(gid, text)
            count += 1
        except Exception:
            pass
    await message.reply(f"Розіслано {count} користувачам/групам.")

# --- Модифікації для збору статистики та бану ---
def link_filter(message: types.Message):
    # Перевіряємо наявність будь-якої з посилань у тексті повідомлення
    text = message.text or ""
    return (
        re.search(TIKTOK_PATTERN, text)
        or re.search(INSTA_REELS_PATTERN, text)
        or re.search(YTSHORTS_PATTERN, text)
        or re.search(FB_REELS_PATTERN, text)
    )

def clear_cache_on_start():
    for filename in os.listdir(CACHE_DIR):
        file_path = os.path.join(CACHE_DIR, filename)
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
                logger.info(f"Кеш-файл {file_path} видалено при старті бота.")
        except Exception as e:
            logger.warning(f"Не вдалося видалити кеш-файл {file_path}: {e}")

def get_cache_size():
    total = 0
    for dirpath, dirnames, filenames in os.walk(CACHE_DIR):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
    return total

# Додаємо функцію для оновлення прогресу завантаження (має бути до handle_video_link)
async def update_progress_message(bot, chat_id, message_id, percent):
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=f"Скачивание: {percent:.1f}%"
        )
    except Exception:
        pass

# Основний хендлер для обробки посилань на відео
async def handle_video_link(message: types.Message):
    logger.info(f"Тип чату: {message.chat.type}, id чату: {message.chat.id}")
    logger.info(f"User: id={message.from_user.id}, username={message.from_user.username}, "
                f"first_name={message.from_user.first_name}, last_name={message.from_user.last_name}, "
                f"language={message.from_user.language_code}")
    if message.chat.type in ("group", "supergroup"):
        logger.info(f"Group title: {message.chat.title}, group username: {message.chat.username}")

    if message.from_user.id in get_banned():
        await message.reply("Ви заблоковані для використання бота.")
        return

    add_user(message.from_user.id)
    if message.chat.type in ("group", "supergroup"):
        add_group(message.chat.id)
    stats = get_stats()

    cache_size = get_cache_size()
    if cache_size > stats.get("max_cache_size", max_cache_size):
        logger.info("Кеш перевищує ліміт, очищаю...")
        clear_cache_on_start()

    text = message.text or ""
    url = (
        re.search(TIKTOK_PATTERN, text)
        or re.search(INSTA_REELS_PATTERN, text)
        or re.search(YTSHORTS_PATTERN, text)
        or re.search(FB_REELS_PATTERN, text)
    )
    if not url:
        await message.reply("Не вдалося знайти посилання.")
        return
    video_url = url.group(0)
    cache_path = get_cache_path(video_url)
    video_sent = False

    async def schedule_file_removal(path):
        await asyncio.sleep(600)  # 10 хвилин
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Файл {path} видалено автоматично через 10 хвилин.")
        except Exception as e:
            logger.warning(f"Помилка при атвоудаленні файлу: {e}")

    if os.path.exists(cache_path):
        logger.info(f"Відео знайдено в кеші: {cache_path}")
        progress_msg = await message.reply("Відео знайдено в кеші. Відправляю...")
        await asyncio.sleep(1)
        video_file = FSInputFile(cache_path)
        await message.reply_video(video_file)
        video_sent = True
        await bot.delete_message(message.chat.id, progress_msg.message_id)
        logger.info(f"Відео з кешу відправлено користувачу: {message.from_user.id}")
        asyncio.create_task(schedule_file_removal(cache_path))
        if video_sent:
            try:
                await bot.delete_message(message.chat.id, message.message_id)
            except Exception as e:
                logger.warning(f"Не вдалося видалити повідомлення: {e}")
        return

    progress = {'percent': 0}
    progress_msg = await message.reply("Скачую відео, почекайте...")

    def progress_hook(d):
        if d['status'] == 'finished':
            progress['finished'] = True

        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded = d.get('downloaded_bytes', 0)
            if total:
                percent = downloaded / total * 100
                if abs(percent - progress.get('percent', 0)) >= 1:
                    progress['percent'] = percent
                    asyncio.get_running_loop().create_task(
                        update_progress_message(bot, message.chat.id, progress_msg.message_id, percent)
                    )

    stats = get_stats()
    ydl_opts = {
        'outtmpl': cache_path,
        'format': 'mp4',
        'quiet': True,
        'max_filesize': stats.get("max_video_size", max_video_size),
        'progress_hooks': [progress_hook],
        'noplaylist': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            video_path = cache_path
        if os.path.getsize(video_path) > stats.get("max_video_size", max_video_size):
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=progress_msg.message_id,
                text="Відео занадто велике для відправки."
            )
            os.remove(video_path)
            return
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=progress_msg.message_id,
            text="Відправляю.."
        )
        video_file = FSInputFile(video_path)
        await message.reply_video(video_file)
        video_sent = True
        stats["processed_videos"] = stats.get("processed_videos", 0) + 1
        set_stats(stats)
        await bot.delete_message(message.chat.id, progress_msg.message_id)
        logger.info(f"Відео відправлено користувачу {message.from_user.id}")
        asyncio.create_task(schedule_file_removal(video_path))
        if video_sent:
            try:
                await bot.delete_message(message.chat.id, message.message_id)
            except Exception as e:
                logger.warning(f"Не вдалося видалити повідомлення: {e}")
    except Exception as e:
        logger.error(f"Помилка при скачуванні: {e}")
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=progress_msg.message_id,
            text=f"Помилка при скачуванні: {e}"
        )
        # Не видаляємо повідомлення користувача, якщо не вдалося скачати відео

# --- Головна асинхронна функція запуску бота ---
async def main():
    clear_cache_on_start()
    dp.message.register(send_welcome, F.text.func(lambda t: t and t.startswith('/start')))
    dp.message.register(send_help, F.text.func(lambda t: t and t.startswith('/help')))
    dp.message.register(admin_stats, F.text.func(lambda t: t and t.startswith('/stats')))
    dp.message.register(admin_clear_cache, F.text.func(lambda t: t and t.startswith('/clear_cache')))
    dp.message.register(admin_users, F.text.func(lambda t: t and t.startswith('/users')))
    dp.message.register(admin_groups, F.text.func(lambda t: t and t.startswith('/groups')))
    dp.message.register(admin_set_max_cache, F.text.func(lambda t: t and t.startswith('/set_max_cache')))
    dp.message.register(admin_set_max_video, F.text.func(lambda t: t and t.startswith('/set_max_video')))
    dp.message.register(admin_ban_user, F.text.func(lambda t: t and t.startswith('/ban_user')))
    dp.message.register(admin_unban_user, F.text.func(lambda t: t and t.startswith('/unban_user')))
    dp.message.register(admin_help, F.text.func(lambda t: t and t.startswith('/admin_help')))
    dp.message.register(admin_logs, F.text.func(lambda t: t and t.startswith('/logs')))
    dp.message.register(admin_shutdown, F.text.func(lambda t: t and t.startswith('/shutdown')))
    dp.message.register(admin_broadcast, F.text.func(lambda t: t and t.startswith('/broadcast')))
    dp.message.register(handle_video_link, link_filter)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
