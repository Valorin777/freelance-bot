"""Шаг 2 плана: тест парсера без ключей Claude.

Запускает только Telethon-парсер + Firebase: слушает каналы и складывает
заказы в raw_orders. Убедитесь, что документы появляются в Firestore.

    .venv/bin/python scripts/test_parser.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config  # noqa: E402
from models import RawOrder  # noqa: E402
from parser import ChannelParser  # noqa: E402
from storage import Storage  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")
logger = logging.getLogger("test_parser")


async def main() -> None:
    config = load_config()
    config.ensure_telegram()
    config.ensure_firebase()

    storage = Storage(config.firebase_credentials)

    async def on_new_order(order: RawOrder) -> None:
        logger.info("✅ Сохранён в raw_orders: %s\n%s\n", order.id, order.text[:200])

    channel_parser = ChannelParser(
        api_id=config.telegram_api_id,
        api_hash=config.telegram_api_hash,
        session_path=config.telethon_session,
        channels=config.channels,
        storage=storage,
        on_new_order=on_new_order,
    )
    await channel_parser.start()
    logger.info("Парсер запущен. Жду новые посты (Ctrl+C для выхода)…")
    await channel_parser.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
