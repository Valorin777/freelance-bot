"""Шаг 3 плана: прогон фильтра по заказам, уже сохранённым в raw_orders.

Ничего не записывает в базу — только печатает вердикты.

    .venv/bin/python scripts/test_filter.py [сколько заказов, по умолчанию 5]
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from anthropic import AsyncAnthropic  # noqa: E402

from config import load_config  # noqa: E402
from filter import OrderFilter  # noqa: E402
from storage import Storage  # noqa: E402

logging.basicConfig(level=logging.WARNING)


async def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5

    config = load_config()
    config.ensure_firebase()
    config.ensure_anthropic()

    storage = Storage(config.firebase_credentials)
    order_filter = OrderFilter(AsyncAnthropic(), config.filter_model)

    orders = await storage.get_unprocessed_raw_orders(limit=limit)
    if not orders:
        print("В raw_orders нет необработанных заказов. Сначала запустите scripts/test_parser.py")
        return

    for order in orders:
        verdict = await order_filter.evaluate(order.text)
        print("=" * 70)
        print(order.text[:300])
        print("-" * 70)
        if verdict is None:
            print("ОШИБКА API — вердикт не получен")
        else:
            mark = "✅ ПОДХОДИТ" if verdict.suitable else "⛔ ОТСЕЯН"
            print(f"{mark} · приоритет: {verdict.priority}")
            print(f"Причина: {verdict.reason}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
