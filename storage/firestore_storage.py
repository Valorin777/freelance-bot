"""Работа с Firebase Firestore: raw_orders и filtered_orders."""

import logging
from datetime import datetime, timedelta, timezone

import firebase_admin
from firebase_admin import credentials, firestore_async
from google.api_core import exceptions as gexc
from google.cloud import firestore as gcf
from google.cloud.firestore_v1.base_query import FieldFilter

from models import RawOrder

logger = logging.getLogger(__name__)

RAW_COLLECTION = "raw_orders"
FILTERED_COLLECTION = "filtered_orders"
PARSER_STATE_COLLECTION = "parser_state"  # last_message_id по каждому каналу (для бэкфилла)


class Storage:
    def __init__(self, credentials_path: str):
        cred = credentials.Certificate(credentials_path)
        self._app = firebase_admin.initialize_app(cred)
        self._db = firestore_async.client(self._app)
        self._raw = self._db.collection(RAW_COLLECTION)
        self._filtered = self._db.collection(FILTERED_COLLECTION)
        self._parser_state = self._db.collection(PARSER_STATE_COLLECTION)

    @staticmethod
    def _raw_order_from_doc(doc) -> RawOrder:
        data = doc.to_dict() or {}
        return RawOrder(
            id=doc.id,
            channel=data.get("channel", ""),
            message_id=data.get("message_id", 0),
            text=data.get("text", ""),
            link=data.get("link", ""),
            posted_at=data.get("posted_at") or datetime.now(timezone.utc),
        )

    # ---------- raw_orders ----------

    async def save_raw_order(self, order: RawOrder) -> bool:
        """Сохраняет сырой заказ. Возвращает False, если такой пост уже есть."""
        try:
            await self._raw.document(order.id).create(
                {
                    "channel": order.channel,
                    "message_id": order.message_id,
                    "text": order.text,
                    "link": order.link,
                    "posted_at": order.posted_at,
                    "created_at": datetime.now(timezone.utc),
                    "processed": False,
                }
            )
            return True
        except gexc.AlreadyExists:
            logger.debug("Заказ %s уже сохранён, пропускаю", order.id)
            return False

    async def get_unprocessed_raw_orders(self, limit: int = 50) -> list[RawOrder]:
        """Заказы, ещё не прошедшие через фильтр (для догона после рестарта)."""
        query = self._raw.where(filter=FieldFilter("processed", "==", False)).limit(limit)
        return [self._raw_order_from_doc(doc) async for doc in query.stream()]

    async def get_raw_order(self, order_id: str) -> RawOrder | None:
        doc = await self._raw.document(order_id).get()
        if not doc.exists:
            return None
        return self._raw_order_from_doc(doc)

    async def mark_raw_processed(self, order_id: str) -> None:
        await self._raw.document(order_id).update({"processed": True})

    # ---------- parser_state (бэкфилл после простоя) ----------

    async def get_parser_state(self) -> dict[str, int]:
        """last_message_id по каждому каналу."""
        state: dict[str, int] = {}
        async for doc in self._parser_state.stream():
            state[doc.id] = (doc.to_dict() or {}).get("last_message_id", 0)
        return state

    async def update_last_message_id(self, channel: str, message_id: int) -> None:
        await self._parser_state.document(channel).set(
            {"last_message_id": message_id}, merge=True
        )

    # ---------- filtered_orders ----------

    async def save_filtered_order(
        self,
        order: RawOrder,
        suitable: bool,
        priority: str,
        reason: str,
        draft: str | None,
        kind: str = "order",
    ) -> None:
        await self._filtered.document(order.id).set(
            {
                "channel": order.channel,
                "message_id": order.message_id,
                "text": order.text,
                "link": order.link,
                "posted_at": order.posted_at,
                "suitable": suitable,
                "kind": kind,
                "priority": priority,
                "reason": reason,
                "draft": draft,
                "notified": False,
                "sent": False,
                "created_at": datetime.now(timezone.utc),
            }
        )

    async def mark_notified(self, order_id: str) -> None:
        await self._filtered.document(order_id).update({"notified": True})

    async def mark_sent(self, order_id: str) -> None:
        await self._filtered.document(order_id).update(
            {"sent": True, "sent_at": datetime.now(timezone.utc)}
        )

    async def get_draft(self, order_id: str) -> str | None:
        doc = await self._filtered.document(order_id).get()
        if not doc.exists:
            return None
        return (doc.to_dict() or {}).get("draft")

    async def get_unnotified_orders(self, limit: int = 20) -> list[dict]:
        """Подходящие заказы, карточка по которым так и не была доставлена.

        Только equality-фильтры — композитный индекс Firestore не требуется."""
        query = (
            self._filtered.where(filter=FieldFilter("suitable", "==", True))
            .where(filter=FieldFilter("notified", "==", False))
            .limit(limit)
        )
        items: list[dict] = []
        async for doc in query.stream():
            data = doc.to_dict() or {}
            data["id"] = doc.id
            items.append(data)
        return items

    async def get_recent_filtered(self, limit: int = 10) -> list[dict]:
        """Последние отфильтрованные заказы (для /history)."""
        query = (
            self._filtered.order_by("created_at", direction=gcf.Query.DESCENDING)
            .limit(limit)
        )
        items: list[dict] = []
        async for doc in query.stream():
            data = doc.to_dict() or {}
            data["id"] = doc.id
            items.append(data)
        return items

    async def get_week_stats(self) -> dict:
        """Статистика за 7 дней: найдено / прошло фильтр / отправлено."""
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)

        found = 0
        raw_query = self._raw.where(filter=FieldFilter("created_at", ">=", week_ago))
        async for _ in raw_query.stream():
            found += 1

        passed = 0
        sent = 0
        filtered_query = self._filtered.where(filter=FieldFilter("created_at", ">=", week_ago))
        async for doc in filtered_query.stream():
            data = doc.to_dict() or {}
            if data.get("suitable"):
                passed += 1
            if data.get("sent"):
                sent += 1

        return {"found": found, "passed": passed, "sent": sent}
