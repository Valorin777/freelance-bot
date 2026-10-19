"""Общие модели данных."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class RawOrder:
    """Сырой заказ, извлечённый из поста в Telegram-канале."""

    id: str  # "{channel}_{message_id}" — используется как id документа в Firestore
    channel: str  # username канала без @ (или числовой id, если username нет)
    message_id: int
    text: str
    link: str  # ссылка на пост
    posted_at: datetime
