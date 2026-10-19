"""Модуль 1: сбор заказов из Telegram-каналов через Telethon (user-сессия)."""

import asyncio
import logging
import os
import re
from typing import Awaitable, Callable

from telethon import TelegramClient, events
from telethon import utils as tl_utils

from models import RawOrder
from storage import Storage

logger = logging.getLogger(__name__)

# Посты короче этого порога почти наверняка не являются заказами —
# не тратим на них вызовы Claude API.
MIN_TEXT_LENGTH = 60
BACKFILL_HARD_CAP = 1000  # предохранитель бэкфилла на канал за один запуск
SAVE_RETRIES = 3

# Служебные сообщения ботов-модераторов в чатах: отбрасываем до сохранения,
# чтобы не тратить на них вызовы Claude API
NOISE_PATTERNS = re.compile(
    r"необходимо пройти верификацию|запрещено отправлять ссылки|"
    r"ограничен доступ к сообщениям|нарушение правил чата|"
    r"чтоб писать в чат подпишись",
    re.IGNORECASE,
)


class ChannelParser:
    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_path: str,
        channels: list[str],
        storage: Storage,
        on_new_order: Callable[[RawOrder], Awaitable[None]],
    ):
        session_dir = os.path.dirname(session_path)
        if session_dir:
            os.makedirs(session_dir, exist_ok=True)
        # catch_up=True: после разрыва соединения Telethon сам запрашивает
        # пропущенные апдейты каналов (pts хранится в session-файле)
        self._client = TelegramClient(session_path, api_id, api_hash, catch_up=True)
        self._channels = channels
        self._storage = storage
        self._on_new_order = on_new_order
        # последний записанный в parser_state id (монотонный, на этот запуск)
        self._last_state: dict[str, int] = {}
        # если сохранение поста окончательно провалилось, state не должен уйти
        # дальше него — иначе бэкфилл после рестарта пост не доберёт
        self._state_cap: dict[str, int] = {}

    async def start(self) -> None:
        """Логинится (при первом запуске интерактивно), подписывается на каналы
        и добирает посты, вышедшие пока бот не работал."""
        await self._client.start()
        me = await self._client.get_me()
        logger.info("Telethon: вошли как %s", getattr(me, "username", None) or me.id)

        entities = []
        for channel in self._channels:
            try:
                entity = await self._client.get_entity(channel)
                entities.append(entity)
                logger.info("Слушаю канал: %s", channel)
            except Exception:
                logger.exception("Не удалось подключиться к каналу %s", channel)

        if not entities:
            raise SystemExit("Ни один канал из TELEGRAM_CHANNELS не доступен — проверьте .env")

        # Обработчик регистрируем ДО бэкфилла: пост, пришедший во время бэкфилла,
        # не потеряется, а возможный дубль отсечётся по id документа в Firestore.
        self._client.add_event_handler(self._handle_new_message, events.NewMessage(chats=entities))
        await self._backfill(entities)

    async def run(self) -> None:
        await self._client.run_until_disconnected()
        # Нормальный выход отсюда означает, что соединение потеряно и апдейты
        # больше не приходят — процессу нет смысла жить дальше.
        raise RuntimeError("Соединение Telethon разорвано — перезапустите процесс")

    # ---------- внутреннее ----------

    @staticmethod
    def _channel_key(entity) -> str:
        return getattr(entity, "username", None) or str(entity.id)

    async def _backfill(self, entities: list) -> None:
        """Добирает посты, вышедшие за время простоя (по last_message_id из Firestore)."""
        try:
            state = await self._storage.get_parser_state()
        except Exception:
            logger.exception("Не удалось прочитать parser_state — бэкфилл пропущен")
            return

        for entity in entities:
            channel = self._channel_key(entity)
            last_id = state.get(channel, 0)
            if not last_id:
                continue  # первый запуск: историю не тянем, начинаем с новых постов
            try:
                count = 0
                # без limit: iter_messages с reverse=True отдаёт СТАРЕЙШИЕ первыми,
                # и жёсткий limit молча потерял бы хвост длинного простоя
                async for message in self._client.iter_messages(
                    entity, min_id=last_id, reverse=True
                ):
                    count += 1
                    if count > BACKFILL_HARD_CAP:
                        logger.warning(
                            "Канал %s: бэкфилл остановлен предохранителем на %d сообщениях",
                            channel,
                            BACKFILL_HARD_CAP,
                        )
                        break
                    await self._save_message(message, channel)
                if count:
                    logger.info("Канал %s: просмотрено %d постов за время простоя", channel, count)
            except Exception:
                logger.exception("Ошибка бэкфилла канала %s", channel)

    async def _handle_new_message(self, event: events.NewMessage.Event) -> None:
        try:
            chat = await event.get_chat()
            username = getattr(chat, "username", None)
            # resolve_id корректно снимает префикс -100 (в отличие от строковой
            # замены, которая ломается на id с ведущим нулём)
            channel = username or str(tl_utils.resolve_id(event.chat_id)[0])
            await self._save_message(event.message, channel)
        except Exception:
            logger.exception("Ошибка при обработке поста из канала")

    async def _save_message(self, message, channel: str) -> None:
        text = (message.raw_text or "").strip()
        if len(text) < MIN_TEXT_LENGTH:
            return
        if NOISE_PATTERNS.search(text):
            return

        if channel.isdigit():  # приватный канал без username
            link = f"https://t.me/c/{channel}/{message.id}"
        else:
            link = f"https://t.me/{channel}/{message.id}"

        order = RawOrder(
            id=f"{channel}_{message.id}",
            channel=channel,
            message_id=message.id,
            text=text,
            link=link,
            posted_at=message.date,
        )

        created = False
        for attempt in range(1, SAVE_RETRIES + 1):
            try:
                created = await self._storage.save_raw_order(order)
                break
            except Exception:
                if attempt == SAVE_RETRIES:
                    logger.exception(
                        "Заказ %s не сохранён после %d попыток — "
                        "будет добран бэкфиллом после рестарта",
                        order.id,
                        SAVE_RETRIES,
                    )
                    # не пускаем parser_state дальше провалившегося поста
                    cap = message.id - 1
                    self._state_cap[channel] = min(self._state_cap.get(channel, cap), cap)
                    return
                logger.warning(
                    "Ошибка Firestore при сохранении %s (попытка %d), повторяю…",
                    order.id,
                    attempt,
                )
                await asyncio.sleep(2 * attempt)

        if not created:
            return  # дубль — уже обрабатывали

        await self._advance_state(channel, message.id)
        logger.info("Новый заказ из %s: %s…", channel, text[:60].replace("\n", " "))
        await self._on_new_order(order)

    async def _advance_state(self, channel: str, message_id: int) -> None:
        """Продвигает last_message_id канала: только вперёд и не дальше cap."""
        cap = self._state_cap.get(channel)
        if cap is not None and message_id > cap:
            return
        if message_id <= self._last_state.get(channel, 0):
            return
        self._last_state[channel] = message_id
        try:
            await self._storage.update_last_message_id(channel, message_id)
        except Exception:
            logger.warning("Не удалось обновить parser_state для %s", channel)
