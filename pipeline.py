"""Оркестрация: сырой заказ -> фильтр -> генератор -> уведомление."""

import asyncio
import logging
from datetime import datetime, timezone

from bot import NotifierBot
from filter import FilterVerdict, OrderFilter
from generator import DraftGenerator
from models import RawOrder
from storage import Storage

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        storage: Storage,
        order_filter: OrderFilter,
        generator: DraftGenerator,
        notifier: NotifierBot,
    ):
        self._storage = storage
        self._filter = order_filter
        self._generator = generator
        self._notifier = notifier
        # id заказов, полностью обработанных в этом запуске: защита от двойной
        # обработки, когда заказ попал и в catch-up-выборку, и в живую очередь
        self._done: set[str] = set()
        # id заказов, карточка по которым уже доставлена в этом запуске:
        # защита от дубля, если mark_notified упал после успешной отправки
        self._delivered: set[str] = set()

    async def run(self, queue: "asyncio.Queue[RawOrder]") -> None:
        """Догоняет необработанное, дошлёт недоставленные карточки, затем — очередь."""
        await self._catch_up()
        await self._renotify()
        while True:
            order = await queue.get()
            try:
                if order.id not in self._done:
                    await self.process(order)
            except Exception:
                logger.exception("Ошибка обработки заказа %s", order.id)
            finally:
                queue.task_done()

    async def _catch_up(self) -> None:
        """Обрабатывает заказы, накопившиеся пока бот не работал (или упавшие ранее).

        Выбирает пачками, пока необработанные не закончатся; заказы, обработать
        которые не удалось (ошибка API), не повторяет в этом же запуске.
        """
        attempted: set[str] = set()
        limit = 50
        while True:
            try:
                orders = await self._storage.get_unprocessed_raw_orders(limit=limit)
            except Exception:
                logger.exception("Не удалось получить необработанные заказы из Firestore")
                return
            pending = [o for o in orders if o.id not in attempted]
            if not pending:
                # всё из выборки уже пробовали: либо бэклог кончился, либо первые
                # limit заказов упали с ошибкой API — расширяем выборку и смотрим глубже
                if len(orders) < limit or limit >= 500:
                    return
                limit = min(limit * 2, 500)
                continue
            logger.info("Догоняю %d необработанных заказов", len(pending))
            for order in pending:
                attempted.add(order.id)
                try:
                    await self.process(order)
                except Exception:
                    logger.exception("Ошибка обработки заказа %s при догоне", order.id)

    async def _renotify(self) -> None:
        """Дошлёт карточки, которые не удалось доставить ранее (notified=False).

        Покрывает и сценарий первого запуска с TELEGRAM_CHAT_ID=0: после того как
        пользователь впишет свой chat id и перезапустит бота, накопившиеся
        подходящие заказы придут в личку."""
        attempted: set[str] = set()
        while True:
            try:
                items = await self._storage.get_unnotified_orders()
            except Exception:
                logger.exception("Не удалось получить недоставленные уведомления")
                return
            pending = [
                d for d in items
                if d["id"] not in attempted and d["id"] not in self._delivered
            ]
            if not pending:
                return
            delivered_any = False
            for data in pending:
                attempted.add(data["id"])
                try:
                    draft = data.get("draft")
                    if not draft:
                        continue
                    # данные из базы могут быть битыми — не даём одному документу
                    # уронить процесс в crash-loop
                    priority = data.get("priority")
                    if priority not in ("high", "medium"):
                        priority = "medium"
                    order = RawOrder(
                        id=data["id"],
                        channel=data.get("channel", ""),
                        message_id=data.get("message_id", 0),
                        text=data.get("text", ""),
                        link=data.get("link", ""),
                        posted_at=data.get("posted_at") or datetime.now(timezone.utc),
                    )
                    kind = data.get("kind")
                    if kind not in ("order", "parttime"):
                        kind = "order"
                    verdict = FilterVerdict(
                        suitable=True, kind=kind, priority=priority, reason=data.get("reason") or ""
                    )
                    if await self._notifier.notify(order, verdict, draft):
                        self._delivered.add(order.id)
                        delivered_any = True
                        try:
                            await self._storage.mark_notified(order.id)
                        except Exception:
                            logger.exception("Не удалось отметить %s как доставленный", order.id)
                except Exception:
                    logger.exception("Не удалось дослать карточку %s", data.get("id"))
            if not delivered_any:
                return  # доставка не работает (нет chat id / сети) — не крутимся впустую

    async def process(self, order: RawOrder) -> None:
        """Полная цепочка для одного заказа.

        Если фильтр или генератор вернули None (ошибка API), заказ остаётся
        с processed=False и будет повторён при следующем запуске.
        """
        verdict = await self._filter.evaluate(order.text)
        if verdict is None:
            return

        draft: str | None = None
        if verdict.suitable:
            draft = await self._generator.generate(order.text, kind=verdict.kind)
            if draft is None:
                return  # повторим весь заказ позже

        try:
            await self._storage.save_filtered_order(
                order,
                suitable=verdict.suitable,
                priority=verdict.priority,
                reason=verdict.reason,
                draft=draft,
                kind=verdict.kind,
            )
            await self._storage.mark_raw_processed(order.id)
        except Exception:
            logger.exception("Ошибка Firestore при сохранении результата %s", order.id)
            return
        self._done.add(order.id)

        if verdict.suitable:
            logger.info(
                "Заказ %s прошёл фильтр (%s): %s", order.id, verdict.priority, verdict.reason
            )
        else:
            logger.info("Заказ %s отсеян: %s", order.id, verdict.reason)

        if verdict.suitable and draft:
            delivered = await self._notifier.notify(order, verdict, draft)
            if delivered:
                self._delivered.add(order.id)
                try:
                    await self._storage.mark_notified(order.id)
                except Exception:
                    logger.exception("Не удалось отметить %s как доставленный", order.id)
