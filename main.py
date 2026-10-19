"""Точка входа: запускает парсер каналов, пайплайн обработки и бота-уведомителя."""

import asyncio
import logging

from anthropic import AsyncAnthropic

from bot import NotifierBot
from config import load_config
from filter import OrderFilter
from generator import DraftGenerator
from models import RawOrder
from parser import ChannelParser
from pipeline import Pipeline
from storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("main")


async def main() -> None:
    config = load_config()
    config.ensure_telegram()
    config.ensure_firebase()
    config.ensure_anthropic()
    config.ensure_bot()

    storage = Storage(config.firebase_credentials)
    anthropic_client = AsyncAnthropic()  # ключ берётся из ANTHROPIC_API_KEY
    order_filter = OrderFilter(anthropic_client, config.filter_model)
    generator = DraftGenerator(anthropic_client, config.generator_model)
    notifier = NotifierBot(config.bot_token, config.chat_id, storage)
    pipeline = Pipeline(storage, order_filter, generator, notifier)

    queue: "asyncio.Queue[RawOrder]" = asyncio.Queue()
    channel_parser = ChannelParser(
        api_id=config.telegram_api_id,
        api_hash=config.telegram_api_hash,
        session_path=config.telethon_session,
        channels=config.channels,
        storage=storage,
        on_new_order=queue.put,
    )

    # При первом запуске Telethon интерактивно спросит телефон и код подтверждения
    await channel_parser.start()
    logger.info("Все компоненты запущены. Ожидаю новые заказы…")

    await asyncio.gather(
        channel_parser.run(),
        notifier.start_polling(),
        pipeline.run(queue),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановлено")
    # SystemExit (ошибки конфигурации) не перехватываем: его сообщение должно
    # попасть в stderr, а процесс — завершиться с ненулевым кодом
