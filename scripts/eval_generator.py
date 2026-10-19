"""Оффлайн-оценка генератора черновиков на 5 синтетических заказах.

Печатает черновики для ручной оценки + автоматически проверяет:
длину, запрещённые шаблонные фразы, отсутствие буллет-списков,
уместность упоминания портфолио.

    .venv/bin/python scripts/eval_generator.py
"""

import asyncio
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from anthropic import AsyncAnthropic  # noqa: E402

from config import load_config  # noqa: E402
from generator import DraftGenerator  # noqa: E402

logging.basicConfig(level=logging.WARNING)

FORBIDDEN_PHRASES = [
    "внимательно изучил",
    "буду рад сотрудничеству",
    "обладаю обширным опытом",
    "готов приступить немедленно",
    "качественно и в срок",
    "надеюсь на плодотворное",
    "имею большой опыт",
    "не просто",
    "отличная задача",
    "отличный проект",
]

# обращение на «ты» запрещено: только «Вы»
TY_FORMS = re.compile(r"\b(ты|тебе|тебя|тобой|твой|твоя|твоё|твои|сделаешь|хочешь)\b", re.IGNORECASE)

# (название, текст заказа, ожидаем упоминание prolatelier, ожидаем упоминание faithof)
CASES: list[tuple[str, str, bool, bool]] = [
    (
        "AI-ассистент для SaaS",
        "В наш SaaS нужно встроить AI-ассистента на базе Claude или GPT: чат с поддержкой "
        "контекста, суммаризация тикетов поддержки. Бэкенд на Python. Бюджет 150-200 тыс. руб.",
        True,
        False,
    ),
    (
        "интернет-магазин косметики",
        "Разработка интернет-магазина косметики: каталог, корзина, оплата, личный кабинет, "
        "админка. Брендбук готов. Бюджет 250 000 руб, срок 2 месяца. Важна мультивалютность — "
        "продаём в РФ и Казахстан.",
        False,
        True,
    ),
    (
        "корпоративный сайт клиники",
        "Нужен корпоративный сайт для стоматологической клиники. 6-8 страниц, онлайн-запись "
        "на приём, интеграция с CRM. Дизайн в Figma готов. Бюджет 120 000 руб.",
        False,
        False,
    ),
    (
        "Telegram-бот записи",
        "Нужен Telegram-бот для записи клиентов барбершопа: выбор мастера и времени, "
        "напоминания, оплата онлайн. ТЗ готово. Бюджет 35 000 руб.",
        False,
        False,
    ),
    (
        "портал пациентов без бюджета",
        "Медицинский центр ищет подрядчика на разработку портала для пациентов: онлайн-запись, "
        "личный кабинет с результатами анализов, интеграция с МИС. ТЗ на 30 страниц вышлем.",
        False,
        False,
    ),
]


def check_draft(draft: str, expect_prolatelier: bool, expect_faithof: bool) -> list[str]:
    problems: list[str] = []
    low = draft.lower()

    if not 200 <= len(draft) <= 1200:
        problems.append(f"длина {len(draft)} знаков (ожидалось 200-1200)")
    if "—" in draft or "–" in draft or "--" in draft:
        problems.append("длинное тире или двойной дефис (маркер ИИ-текста)")
    if TY_FORMS.search(draft):
        problems.append("обращение на «ты» вместо «Вы»")
    for phrase in FORBIDDEN_PHRASES:
        if phrase in low:
            problems.append(f"шаблонная фраза: «{phrase}»")
    for line in draft.splitlines():
        if line.strip().startswith(("-", "•", "*", "—")):
            problems.append("похоже на буллет-список")
            break
    if expect_prolatelier and "prolatelier" not in low:
        problems.append("не упомянут prolatelier.ru, хотя заказ про AI (мягкая проверка)")
    if expect_faithof and "faithof" not in low:
        problems.append("не упомянут faithof.ru, хотя заказ про e-commerce (мягкая проверка)")
    if not expect_prolatelier and "prolatelier" in low and not expect_faithof and "faithof" in low:
        problems.append("упомянуты оба проекта сразу — перебор")
    return problems


async def main() -> None:
    config = load_config()
    config.ensure_anthropic()
    generator = DraftGenerator(AsyncAnthropic(), config.generator_model)

    semaphore = asyncio.Semaphore(3)

    async def run_case(case):
        name, text, p, f = case
        async with semaphore:
            draft = await generator.generate(text)
        return name, text, p, f, draft

    results = await asyncio.gather(*(run_case(c) for c in CASES))

    total_problems = 0
    for name, text, expect_p, expect_f, draft in results:
        print("=" * 70)
        print(f"ЗАКАЗ: {name}")
        print("-" * 70)
        if draft is None:
            print("⚠️ ОШИБКА API — черновик не получен")
            total_problems += 1
            continue
        print(draft)
        print("-" * 70)
        problems = check_draft(draft, expect_p, expect_f)
        if problems:
            total_problems += len(problems)
            for p in problems:
                print(f"❌ {p}")
        else:
            print("✅ автоматические проверки пройдены")
        print()

    print("=" * 70)
    print(f"ИТОГ: {'все проверки пройдены' if total_problems == 0 else f'{total_problems} замечаний'}")
    if total_problems:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
