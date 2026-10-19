"""Шаг 4 плана: генерация черновика отклика для проверки качества вручную.

Либо по id заказа из raw_orders, либо по тексту:

    .venv/bin/python scripts/test_generator.py "текст заказа..."
    .venv/bin/python scripts/test_generator.py --id frilanc_12345
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from anthropic import AsyncAnthropic  # noqa: E402

from config import load_config  # noqa: E402
from generator import DraftGenerator  # noqa: E402

logging.basicConfig(level=logging.WARNING)


async def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return

    config = load_config()
    config.ensure_anthropic()

    if sys.argv[1] == "--id":
        if len(sys.argv) < 3:
            print(__doc__)
            return
        config.ensure_firebase()
        from storage import Storage

        storage = Storage(config.firebase_credentials)
        order = await storage.get_raw_order(sys.argv[2])
        if order is None:
            print(f"Заказ {sys.argv[2]} не найден в raw_orders")
            return
        text = order.text
    else:
        text = sys.argv[1]

    generator = DraftGenerator(AsyncAnthropic(), config.generator_model)
    draft = await generator.generate(text)

    print("=" * 70)
    print("ЗАКАЗ:")
    print(text[:500])
    print("=" * 70)
    print("ЧЕРНОВИК:")
    print(draft or "ОШИБКА — черновик не получен")


if __name__ == "__main__":
    asyncio.run(main())
