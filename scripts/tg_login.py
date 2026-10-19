"""Двухшаговый вход в Telegram-сессию без интерактивного терминала.

Шаг 1 — отправить код на телефон:
    .venv/bin/python scripts/tg_login.py send +79991234567

Шаг 2 — ввести код из Telegram (и пароль 2FA, если включён):
    .venv/bin/python scripts/tg_login.py code 12345
    .venv/bin/python scripts/tg_login.py code 12345 мой_пароль_2fa
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon import TelegramClient  # noqa: E402
from telethon.errors import SessionPasswordNeededError  # noqa: E402

from config import load_config  # noqa: E402

STATE = Path(__file__).with_name(".login_state.json")


async def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        return

    config = load_config()
    config.ensure_telegram()

    session_dir = os.path.dirname(config.telethon_session)
    if session_dir:
        os.makedirs(session_dir, exist_ok=True)

    client = TelegramClient(
        config.telethon_session, config.telegram_api_id, config.telegram_api_hash
    )
    await client.connect()
    try:
        if await client.is_user_authorized():
            me = await client.get_me()
            print(f"Уже авторизованы как {me.first_name} (@{me.username})")
            return

        command = sys.argv[1]
        if command == "send":
            phone = sys.argv[2]
            sent = await client.send_code_request(phone)
            STATE.write_text(json.dumps({"phone": phone, "hash": sent.phone_code_hash}))
            print("Код отправлен — проверьте Telegram (сообщение от Telegram, не SMS)")
        elif command == "code":
            if not STATE.exists():
                print("Сначала выполните шаг send")
                return
            state = json.loads(STATE.read_text())
            code = sys.argv[2]
            try:
                await client.sign_in(state["phone"], code, phone_code_hash=state["hash"])
            except SessionPasswordNeededError:
                if len(sys.argv) > 3:
                    await client.sign_in(password=sys.argv[3])
                else:
                    print("Включён пароль 2FA. Повторите: tg_login.py code <код> <пароль>")
                    return
            me = await client.get_me()
            print(f"Успешный вход: {me.first_name} (@{me.username}). Сессия сохранена.")
            STATE.unlink(missing_ok=True)
        else:
            print(__doc__)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
