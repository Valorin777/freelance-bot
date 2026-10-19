"""Подписывает аккаунт на все каналы из TELEGRAM_CHANNELS (.env).

Подписка нужна, чтобы Telegram присылал апдейты о новых постах в реальном времени.
Идёт с паузами и уважает FloodWait. Запускать при остановленном парсере.

    .venv/bin/python scripts/join_channels.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon import TelegramClient  # noqa: E402
from telethon.errors import (  # noqa: E402
    FloodWaitError,
    UserAlreadyParticipantError,
)
from telethon.tl.functions.channels import JoinChannelRequest  # noqa: E402

from config import load_config  # noqa: E402

JOIN_DELAY = 15  # секунд между подписками — бережём лимиты Telegram


async def main() -> None:
    config = load_config()
    config.ensure_telegram()
    client = TelegramClient(
        config.telethon_session, config.telegram_api_id, config.telegram_api_hash
    )
    await client.connect()
    try:
        if not await client.is_user_authorized():
            print("Сессия не авторизована — сначала scripts/tg_login.py")
            return
        for i, channel in enumerate(config.channels):
            try:
                entity = await client.get_entity(channel)
                await client(JoinChannelRequest(entity))
                print(f"✅ подписан: {channel}")
            except UserAlreadyParticipantError:
                print(f"✅ уже подписан: {channel}")
            except FloodWaitError as e:
                wait = min(e.seconds, 600)
                print(f"⏳ FloodWait {e.seconds}s на {channel}, жду {wait}s…")
                await asyncio.sleep(wait)
                try:
                    await client(JoinChannelRequest(await client.get_entity(channel)))
                    print(f"✅ подписан со второй попытки: {channel}")
                except Exception as e2:
                    print(f"❌ {channel}: {type(e2).__name__}: {e2}")
            except Exception as e:
                print(f"❌ {channel}: {type(e).__name__}: {e}")
            if i < len(config.channels) - 1:
                await asyncio.sleep(JOIN_DELAY)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
