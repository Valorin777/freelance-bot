"""Запуск только бота-уведомителя (без парсера и Claude).

Нужен для первичной настройки: отправьте боту /start, он покажет ваш chat id.
Также работают /history и /stats.

    .venv/bin/python scripts/run_bot_only.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import NotifierBot  # noqa: E402
from config import load_config  # noqa: E402
from storage import Storage  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")
logger = logging.getLogger("run_bot_only")


async def main() -> None:
    config = load_config()
    config.ensure_bot()
    config.ensure_firebase()

    storage = Storage(config.firebase_credentials)
    notifier = NotifierBot(config.bot_token, config.chat_id, storage)
    logger.info("Бот запущен. Откройте его в Telegram и отправьте /start")
    await notifier.start_polling()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
