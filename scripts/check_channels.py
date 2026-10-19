"""Проверка каналов-кандидатов через Telethon: существует, активен, есть ли заказы.

    .venv/bin/python scripts/check_channels.py user1 user2 user3 ...

Печатает JSON-строку на канал: подписчики, постов/день, доля постов похожих на заказы.
Требует остановленного парсера (session-файл занят одним процессом).
"""

import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon import TelegramClient  # noqa: E402
from telethon.tl.functions.channels import GetFullChannelRequest  # noqa: E402

from config import load_config  # noqa: E402

ORDER_WORDS = re.compile(
    r"нужен|нужно|нужна|ищу |ищем |требуется|бюджет|оплата|сделать|разработать|"
    r"доработ|создать|написать бота|парсер|интеграц|лендинг|сайт|веб-приложение|тз |№|"
    r"задача|заказ",
    re.IGNORECASE,
)


async def check(client: TelegramClient, username: str) -> dict:
    info: dict = {"username": username}
    try:
        entity = await client.get_entity(username)
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
        return info

    info["title"] = getattr(entity, "title", "")
    info["is_group"] = bool(getattr(entity, "megagroup", False))
    try:
        full = await client(GetFullChannelRequest(entity))
        info["subscribers"] = full.full_chat.participants_count
    except Exception:
        info["subscribers"] = None

    messages = []
    try:
        async for m in client.iter_messages(entity, limit=30):
            if m.raw_text:
                messages.append(m)
    except Exception as e:
        info["error"] = f"messages: {type(e).__name__}"
        return info

    if not messages:
        info["posts_per_day"] = 0.0
        info["order_share"] = 0.0
        return info

    now = datetime.now(timezone.utc)
    span_days = max((now - messages[-1].date).total_seconds() / 86400, 0.25)
    info["posts_per_day"] = round(len(messages) / span_days, 1)
    info["days_since_last_post"] = round((now - messages[0].date).total_seconds() / 86400, 1)
    order_like = sum(1 for m in messages if ORDER_WORDS.search(m.raw_text))
    info["order_share"] = round(order_like / len(messages), 2)
    info["sample"] = messages[0].raw_text[:150].replace("\n", " ")
    return info


async def main() -> None:
    usernames = [u.strip().lstrip("@") for u in sys.argv[1:] if u.strip()]
    if not usernames:
        print(__doc__)
        return

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
        for username in usernames:
            result = await check(client, username)
            print(json.dumps(result, ensure_ascii=False))
            await asyncio.sleep(1.5)  # бережём лимиты Telegram
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
