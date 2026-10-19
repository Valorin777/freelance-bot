"""Оффлайн-оценка фильтра на 20 синтетических заказах разного качества.

Не требует Firebase и Telegram — только ANTHROPIC_API_KEY в .env.

    .venv/bin/python scripts/eval_filter.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from anthropic import AsyncAnthropic  # noqa: E402

from config import load_config  # noqa: E402
from filter import OrderFilter  # noqa: E402

logging.basicConfig(level=logging.WARNING)

# (название, текст заказа, ожидаемый suitable, ожидаемый priority или None)
CASES: list[tuple[str, str, bool, str | None]] = [
    (
        "сайт с чётким ТЗ и бюджетом 120к",
        "Нужен корпоративный сайт для стоматологической клиники. 6-8 страниц, онлайн-запись "
        "на приём, интеграция с CRM. Дизайн в Figma готов. Бюджет 120 000 руб. Срок — месяц. "
        "Пишите в ЛС с примерами работ.",
        True,
        "high",
    ),
    (
        "серьёзно, но расплывчато, без бюджета",
        "Ищем разработчика для создания веб-платформы для нашей логистической компании. "
        "Детали обсудим с кандидатом. Оплата достойная, работаем по договору.",
        True,
        "medium",
    ),
    (
        "лендинг за 10к — ниже порога",
        "Нужен лендинг для инфопродукта. Бюджет 10 000 рублей. Срок — 2 дня.",
        False,
        None,
    ),
    (
        "фича за 3к — ниже порога",
        "Надо добавить кнопку оплаты на существующий сайт. Бюджет 3000 руб.",
        False,
        None,
    ),
    (
        "маркер «недорого»",
        "Сделать сайт-визитку недорого. Кто возьмётся? Пишите в личку.",
        False,
        None,
    ),
    (
        "оплата отзывом",
        "Нужен телеграм-бот для салона. Плачу отзывом и рекомендацией, отличный кейс "
        "для портфолио начинающему разработчику.",
        False,
        None,
    ),
    (
        "«студент подойдёт»",
        "Ищу студента для простого сайта на Тильде. Задача несложная, оплата небольшая, "
        "студент подойдёт.",
        False,
        None,
    ),
    (
        "резюме исполнителя, не заказ",
        "Разработчик Python/Django, 5 лет опыта. Ищу заказы и проекты, рассмотрю любые "
        "предложения. Портфолио в профиле, отвечаю быстро.",
        False,
        None,
    ),
    (
        "реклама курса",
        "🔥 Курс «Веб-разработчик с нуля до PRO» — скидка 50% только сегодня! Трудоустройство "
        "гарантируем. Записывайся по ссылке в описании.",
        False,
        None,
    ),
    (
        "мобильная разработка Kotlin — вне стека",
        "Требуется разработчик мобильного приложения на Kotlin для Android. Приложение "
        "доставки еды. Бюджет 300 000 руб.",
        False,
        None,
    ),
    (
        "1С — вне стека",
        "Нужен программист 1С для доработки конфигурации УТ 11. Оплата почасовая, 2500 руб/час.",
        False,
        None,
    ),
    (
        "AI-интеграция 150-200к",
        "В наш SaaS нужно встроить AI-ассистента на базе Claude или GPT: чат с поддержкой "
        "контекста, суммаризация тикетов поддержки. Бэкенд на Python. Бюджет 150-200 тыс. руб, "
        "готовы обсуждать.",
        True,
        "high",
    ),
    (
        "Telegram-бот 35к с ТЗ",
        "Нужен Telegram-бот для записи клиентов барбершопа: выбор мастера и времени, "
        "напоминания, оплата онлайн. ТЗ готово. Бюджет 35 000 руб.",
        True,
        "high",
    ),
    (
        "интеграция за 15к — выше порога фичи",
        "Подключить оплату ЮKassa к сайту на Next.js. Бюджет 15 000 руб. Доступы дадим, "
        "нужно в течение недели.",
        True,
        None,
    ),
    (
        "интернет-магазин 250к",
        "Разработка интернет-магазина косметики: каталог, корзина, оплата, личный кабинет, "
        "админка. Брендбук и структура готовы. Бюджет 250 000 руб, срок 2 месяца.",
        True,
        "high",
    ),
    (
        "серьёзный портал без озвученного бюджета",
        "Медицинский центр ищет подрядчика на разработку портала для пациентов: онлайн-запись, "
        "личный кабинет с результатами анализов, интеграция с МИС. Подробное ТЗ на 30 страниц "
        "вышлем. Бюджет обсуждается по итогам вашей оценки.",
        True,
        None,
    ),
    (
        "«срочно и дёшево»",
        "Срочно и дёшево нужен сайт до завтра, бюджет минимальный, кто свободен прямо сейчас?",
        False,
        None,
    ),
    (
        "дайджест канала, не заказ",
        "📊 Дайджест за неделю: 12 новых проектов в нашем канале! Подписывайтесь, чтобы не "
        "пропускать свежие заказы.",
        False,
        None,
    ),
    (
        "чистый дизайн — вне стека",
        "Ищу дизайнера для отрисовки макетов лендинга в Figma, 5 экранов. Бюджет 20 000 руб.",
        False,
        None,
    ),
    (
        "сайт-визитка 25к — выше порога",
        "Нужен простой сайт для фотографа: портфолио, обо мне, контакты. 3-4 страницы. "
        "Бюджет 25 000 руб.",
        True,
        None,
    ),
]


async def main() -> None:
    config = load_config()
    config.ensure_anthropic()
    order_filter = OrderFilter(AsyncAnthropic(), config.filter_model)

    semaphore = asyncio.Semaphore(4)

    async def run_case(case):
        name, text, expected_suitable, expected_priority = case
        async with semaphore:
            verdict = await order_filter.evaluate(text)
        return name, expected_suitable, expected_priority, verdict

    results = await asyncio.gather(*(run_case(c) for c in CASES))

    passed = 0
    failed_names = []
    for name, expected_suitable, expected_priority, verdict in results:
        if verdict is None:
            print(f"⚠️  API ERROR  {name}")
            failed_names.append(name)
            continue
        ok = verdict.suitable == expected_suitable
        prio_ok = expected_priority is None or verdict.priority == expected_priority
        mark = "✅" if (ok and prio_ok) else ("🟡" if ok else "❌")
        if ok and prio_ok:
            passed += 1
        else:
            failed_names.append(name)
        print(
            f"{mark} {name}\n"
            f"   ожидалось: suitable={expected_suitable}"
            + (f", priority={expected_priority}" if expected_priority else "")
            + f" | получено: suitable={verdict.suitable}, priority={verdict.priority}\n"
            f"   причина: {verdict.reason}"
        )

    total = len(CASES)
    print("\n" + "=" * 70)
    print(f"ИТОГ: {passed}/{total} совпали полностью")
    if failed_names:
        print("Расхождения:", "; ".join(failed_names))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
