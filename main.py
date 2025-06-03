import os
import re
import logging
import hashlib
import asyncio
from aiogram import Bot, Dispatcher, types
import yt_dlp

API_TOKEN = '7654313992:AAF-IlnkA50SEBC_ajaicQu-Id8_WbYZMqM'  # <-- Replace with your bot token

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

CACHE_DIR = "video_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# Оновлені патерни для TikTok, Instagram Reels та YouTube Shorts (включаючи короткі посилання)
TIKTOK_PATTERN = r'(https?://(?:www\.)?(?:tiktok\.com/[^\s]+|vm\.tiktok\.com/[^\s/]+))'
INSTA_REELS_PATTERN = r'(https?://(?:www\.)?instagram\.com/(?:reel|p)/[^\s/?&#]+)'
YTSHORTS_PATTERN = r'(https?://(?:www\.)?(?:youtube\.com/shorts/[^\s/?&#]+|youtu\.be/[^\s/?&#]+))'

async def send_welcome(message: types.Message):
    await message.reply("Привет! Пришли мне ссылку на TikTok или Instagram Reels, и я отправлю тебе видео.")

async def send_help(message: types.Message):
    await message.reply(
        "Этот бот скачивает видео из TikTok и Instagram Reels.\n"
        "Просто отправьте ссылку на видео.\n"
        "Максимальный размер файла — 50 МБ."
    )

def get_cache_path(url):
    url_hash = hashlib.md5(url.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{url_hash}.mp4")

async def update_progress_message(bot, chat_id, message_id, percent):
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=f"Скачивание: {percent:.1f}%"
        )
    except Exception:
        pass

async def handle_video_link(message: types.Message):
    url = (
        re.search(TIKTOK_PATTERN, message.text or "")
        or re.search(INSTA_REELS_PATTERN, message.text or "")
        or re.search(YTSHORTS_PATTERN, message.text or "")
    )
    if not url:
        await message.reply("Не удалось найти ссылку.")
        return
    video_url = url.group(0)
    logger.info(f"Получена ссылка: {video_url} от пользователя {message.from_user.id}")

    cache_path = get_cache_path(video_url)
    video_sent = False  # Флаг, отправлено ли видео

    async def schedule_file_removal(path):
        await asyncio.sleep(600)  # 10 минут
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Файл {path} удалён автоматически через 10 минут.")
        except Exception as e:
            logger.warning(f"Ошибка при автоудалении файла: {e}")

    if os.path.exists(cache_path):
        logger.info(f"Видео найдено в кэше: {cache_path}")
        progress_msg = await message.reply("Видео найдено в кэше. Отправляю...")
        await asyncio.sleep(1)
        with open(cache_path, 'rb') as video:
            await message.reply_video(video)
            video_sent = True
        await bot.delete_message(message.chat.id, progress_msg.message_id)
        logger.info(f"Видео из кэша отправлено пользователю {message.from_user.id}")
        # Планируем автоудаление файла через 10 минут
        asyncio.create_task(schedule_file_removal(cache_path))
        # Удаляем сообщение пользователя только после отправки видео
        if video_sent:
            try:
                await bot.delete_message(message.chat.id, message.message_id)
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение: {e}")
        return

    progress = {'percent': 0}
    progress_msg = await message.reply("Скачиваю видео, подождите...")

    def progress_hook(d):
        # Не удаляем сообщение пользователя в этом хуке!
        if d['status'] == 'finished':
            progress['finished'] = True

        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded = d.get('downloaded_bytes', 0)
            if total:
                percent = downloaded / total * 100
                if abs(percent - progress.get('percent', 0)) >= 1:
                    progress['percent'] = percent
                    asyncio.run_coroutine_threadsafe(
                        update_progress_message(bot, message.chat.id, progress_msg.message_id, percent),
                        asyncio.get_event_loop()
                    )

    ydl_opts = {
        'outtmpl': cache_path,
        'format': 'mp4',
        'quiet': True,
        'max_filesize': 50 * 1024 * 1024,  # 50 MB
        'progress_hooks': [progress_hook],
        'noplaylist': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            video_path = cache_path
        # Проверяем размер файла
        if os.path.getsize(video_path) > 50 * 1024 * 1024:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=progress_msg.message_id,
                text="Видео слишком большое для отправки (более 50 МБ)."
            )
            os.remove(video_path)
            # Удаляем сообщение пользователя только после ответа
            try:
                await bot.delete_message(message.chat.id, message.message_id)
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение: {e}")
            return
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=progress_msg.message_id,
            text="Видео скачано, отправляю..."
        )
        with open(video_path, 'rb') as video:
            await message.reply_video(video)
            video_sent = True
        await bot.delete_message(message.chat.id, progress_msg.message_id)
        logger.info(f"Видео отправлено пользователю {message.from_user.id}")
        # Планируем автоудаление файла через 10 минут
        asyncio.create_task(schedule_file_removal(video_path))
        # Удаляем сообщение пользователя только после отправки видео
        if video_sent:
            try:
                await bot.delete_message(message.chat.id, message.message_id)
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение: {e}")
    except Exception as e:
        logger.error(f"Ошибка при скачивании: {e}")
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=progress_msg.message_id,
            text=f"Ошибка при скачивании: {e}"
        )
        # Удаляем сообщение пользователя только после ответа об ошибке
        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except Exception as ex:
            logger.warning(f"Не удалось удалить сообщение: {ex}")

def link_filter(message: types.Message):
    return (
        (message.text and re.search(TIKTOK_PATTERN, message.text))
        or (message.text and re.search(INSTA_REELS_PATTERN, message.text))
        or (message.text and re.search(YTSHORTS_PATTERN, message.text))
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

async def main():
    clear_cache_on_start()
    dp.message(lambda m: m.text and m.text.startswith('/start'))(send_welcome)
    dp.message(lambda m: m.text and m.text.startswith('/help'))(send_help)
    dp.message(link_filter)(handle_video_link)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
