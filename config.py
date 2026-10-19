"""Загрузка конфигурации из .env."""

import logging
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _normalize_channel(raw: str) -> str:
    """Приводит @username / https://t.me/s/username / t.me/username к username."""
    ch = raw.strip()
    for prefix in ("https://t.me/s/", "https://t.me/", "http://t.me/", "t.me/s/", "t.me/", "@"):
        if ch.startswith(prefix):
            ch = ch[len(prefix):]
    return ch.strip("/")


@dataclass
class Config:
    telegram_api_id: int
    telegram_api_hash: str
    telethon_session: str
    channels: list[str]
    filter_model: str
    generator_model: str
    firebase_credentials: str
    bot_token: str
    chat_id: int
    anthropic_key_set: bool = field(default=False)

    def ensure_telegram(self) -> None:
        if not self.telegram_api_id or not self.telegram_api_hash:
            raise SystemExit(
                "Не заданы TELEGRAM_API_ID / TELEGRAM_API_HASH. "
                "Получите их на https://my.telegram.org и заполните .env"
            )
        if not self.channels:
            raise SystemExit("Не задан TELEGRAM_CHANNELS в .env")

    def ensure_firebase(self) -> None:
        if not self.firebase_credentials:
            raise SystemExit("Не задан FIREBASE_CREDENTIALS в .env")
        if not os.path.exists(self.firebase_credentials):
            raise SystemExit(
                f"Файл сервисного аккаунта Firebase не найден: {self.firebase_credentials}"
            )

    def ensure_anthropic(self) -> None:
        if not self.anthropic_key_set:
            raise SystemExit("Не задан ANTHROPIC_API_KEY в .env")

    def ensure_bot(self) -> None:
        if not self.bot_token:
            raise SystemExit("Не задан BOT_TOKEN в .env (создайте бота через @BotFather)")
        if not self.chat_id:
            logger.warning(
                "TELEGRAM_CHAT_ID не задан (или 0): уведомления отправляться не будут. "
                "Отправьте боту /start, чтобы узнать свой chat id, впишите его в .env "
                "и перезапустите."
            )


def load_config() -> Config:
    load_dotenv()

    channels_raw = os.getenv("TELEGRAM_CHANNELS", "")
    channels = [_normalize_channel(c) for c in channels_raw.split(",") if c.strip()]

    return Config(
        telegram_api_id=int(os.getenv("TELEGRAM_API_ID", "0") or "0"),
        telegram_api_hash=os.getenv("TELEGRAM_API_HASH", ""),
        telethon_session=os.getenv("TELETHON_SESSION", "data/telethon_session"),
        channels=channels,
        filter_model=os.getenv("FILTER_MODEL", "claude-sonnet-4-6"),
        generator_model=os.getenv("GENERATOR_MODEL", "claude-sonnet-4-6"),
        firebase_credentials=os.getenv("FIREBASE_CREDENTIALS", ""),
        bot_token=os.getenv("BOT_TOKEN", ""),
        chat_id=int(os.getenv("TELEGRAM_CHAT_ID", "0") or "0"),
        anthropic_key_set=bool(os.getenv("ANTHROPIC_API_KEY")),
    )
