"""Модуль 4: Telegram-бот для уведомлений (aiogram 3)."""

import html
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from filter import FilterVerdict
from models import RawOrder
from storage import Storage

logger = logging.getLogger(__name__)

ORDER_TEXT_PREVIEW = 600  # сколько символов заказа показывать в карточке
DRAFT_PREVIEW = 1500  # лимит черновика в карточке (полный текст — по кнопке «Скопировать»)


class NotifierBot:
    def __init__(self, token: str, chat_id: int, storage: Storage):
        self._bot = Bot(
            token=token,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML,
                link_preview_is_disabled=True,
            ),
        )
        self._chat_id = chat_id
        self._storage = storage
        self._dp = Dispatcher()
        self._dp.include_router(self._build_router())

    # ---------- отправка карточки заказа ----------

    async def notify(self, order: RawOrder, verdict: FilterVerdict, draft: str) -> bool:
        """Шлёт карточку «заказ + черновик + кнопки» в личку. True, если отправилось."""
        if not self._chat_id:
            logger.warning(
                "TELEGRAM_CHAT_ID не задан — карточка заказа %s не отправлена", order.id
            )
            return False

        preview = order.text[:ORDER_TEXT_PREVIEW]
        if len(order.text) > ORDER_TEXT_PREVIEW:
            preview += "…"

        draft_preview = draft[:DRAFT_PREVIEW]
        if len(draft) > DRAFT_PREVIEW:
            draft_preview += "…\n(полный текст — по кнопке «Скопировать»)"

        prio_emoji = "🔥" if verdict.priority == "high" else "📋"
        prio_label = "высокий" if verdict.priority == "high" else "средний"
        kind = getattr(verdict, "kind", "order")
        if kind == "parttime":
            head_emoji, head_label = "🧩", "Подработка / проект"
        else:
            head_emoji, head_label = "🆕", "Новый заказ"

        message = (
            f"{prio_emoji} <b>{head_label}</b> · приоритет: {prio_label}\n"
            f"{head_emoji} Канал: {html.escape(order.channel)}\n\n"
            f"{html.escape(preview)}\n\n"
            f'🔗 <a href="{html.escape(order.link, quote=True)}">Открыть пост</a>\n'
            f"<i>{html.escape(verdict.reason)}</i>\n\n"
            f"💬 <b>Черновик отклика:</b>\n{html.escape(draft_preview)}"
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="📋 Скопировать", callback_data=f"copy:{order.id}"),
                    InlineKeyboardButton(text="✅ Отправлено", callback_data=f"sent:{order.id}"),
                ]
            ]
        )

        try:
            await self._bot.send_message(self._chat_id, message, reply_markup=keyboard)
            return True
        except Exception:
            logger.exception("Не удалось отправить карточку заказа %s", order.id)
            return False

    # ---------- команды и кнопки ----------

    def _build_router(self) -> Router:
        router = Router()
        storage = self._storage

        def _is_owner(chat_id: int) -> bool:
            return bool(self._chat_id) and chat_id == self._chat_id

        @router.message(Command("start"))
        async def cmd_start(message: Message) -> None:
            # /start отвечает всем: так пользователь узнаёт свой chat id для .env
            await message.answer(
                "Бот мониторинга фриланс-заказов.\n"
                f"Ваш chat id: <code>{message.chat.id}</code>\n\n"
                "Если уведомления не приходят — впишите этот id в TELEGRAM_CHAT_ID "
                "в .env и перезапустите бота.\n\n"
                "Команды: /history — последние заказы, /stats — статистика за неделю."
            )

        @router.message(Command("history"))
        async def cmd_history(message: Message) -> None:
            if not _is_owner(message.chat.id):
                return
            try:
                items = await storage.get_recent_filtered(limit=10)
            except Exception:
                logger.exception("Ошибка Firestore в /history")
                await message.answer("Не удалось получить историю — ошибка базы данных.")
                return

            if not items:
                await message.answer("История пуста — заказов пока не было.")
                return

            lines = ["<b>Последние 10 заказов:</b>\n"]
            for item in items:
                if item.get("sent"):
                    status = "✅ отправлен"
                elif item.get("suitable"):
                    status = "📨 ждёт отправки"
                else:
                    status = "⛔ отсеян"
                snippet = html.escape((item.get("text") or "").replace("\n", " ")[:70])
                link = html.escape(item.get("link") or "", quote=True)
                lines.append(f'• {status} — <a href="{link}">{snippet}…</a>')
            await message.answer("\n".join(lines))

        @router.message(Command("stats"))
        async def cmd_stats(message: Message) -> None:
            if not _is_owner(message.chat.id):
                return
            try:
                stats = await storage.get_week_stats()
            except Exception:
                logger.exception("Ошибка Firestore в /stats")
                await message.answer("Не удалось получить статистику — ошибка базы данных.")
                return
            await message.answer(
                "<b>Статистика за 7 дней:</b>\n"
                f"Найдено заказов: {stats['found']}\n"
                f"Прошло фильтр: {stats['passed']}\n"
                f"Отправлено откликов: {stats['sent']}"
            )

        @router.callback_query(F.data.startswith("copy:"))
        async def on_copy(callback: CallbackQuery) -> None:
            order_id = callback.data.split(":", 1)[1]
            try:
                draft = await storage.get_draft(order_id)
            except Exception:
                logger.exception("Ошибка Firestore при получении черновика %s", order_id)
                draft = None
            if draft and callback.message:
                # <pre> — в Telegram текст копируется по одному тапу;
                # режем на части с запасом до лимита в 4096 символов
                for i in range(0, len(draft), 3500):
                    await callback.message.answer(f"<pre>{html.escape(draft[i:i + 3500])}</pre>")
                await callback.answer()
            else:
                await callback.answer("Черновик не найден", show_alert=True)

        @router.callback_query(F.data.startswith("sent:"))
        async def on_sent(callback: CallbackQuery) -> None:
            order_id = callback.data.split(":", 1)[1]
            try:
                await storage.mark_sent(order_id)
            except Exception:
                logger.exception("Ошибка Firestore при отметке %s отправленным", order_id)
                await callback.answer("Ошибка базы данных", show_alert=True)
                return
            await callback.answer("Отмечено как отправленное ✅")

        return router

    async def start_polling(self) -> None:
        # handle_signals=False — сигналы обрабатывает main, не aiogram
        await self._dp.start_polling(self._bot, handle_signals=False)
