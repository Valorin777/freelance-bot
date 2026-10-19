# Freelance Bot

Бот, который читает Telegram-каналы с фриланс-заказами и присылает мне
только подходящие. Каждый пост проходит через LLM: подходит ли под мой стек,
нормальный ли бюджет, не демпинг ли. Для подходящих сразу пишется черновик
отклика, и в личку приходит карточка «заказ + черновик + кнопки».
Отправляю отклик заказчику я сам, бот этого не делает.

```
каналы ──Telethon──▶ raw_orders (Firestore)
                         │
                  фильтр (LLM): подходит? приоритет? почему?
                         │
                  filtered_orders
                         │ если подходит
                  черновик отклика (LLM)
                         │
          бот (aiogram) ──▶ карточка в личку  [📋 Скопировать] [✅ Отправлено]
```

Если бот лежал, при старте он догоняет пропущенные посты (до 1000 на канал),
повторяет заказы, на которых упал API, и досылает недоставленные карточки.

## Стек

Python 3.12, Telethon (user-сессия, чтобы читать чужие каналы), aiogram 3,
Anthropic API, Firestore.

## Запуск

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env    # заполнить
.venv/bin/python main.py
```

При первом запуске Telethon спросит номер телефона и код из Telegram,
дальше сессия хранится в `data/`.

## Переменные окружения

- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` — с my.telegram.org, для чтения каналов
- `TELETHON_SESSION` — путь к файлу сессии
- `TELEGRAM_CHANNELS` — каналы через запятую
- `BOT_TOKEN` — бот для уведомлений от @BotFather
- `TELEGRAM_CHAT_ID` — куда слать карточки (бот подскажет id по `/start`)
- `ANTHROPIC_API_KEY`, `FILTER_MODEL`, `GENERATOR_MODEL` — модели для фильтра и черновиков
- `FIREBASE_CREDENTIALS` — путь к JSON сервисного аккаунта Firebase

## Команды бота

- `/start` — показать chat id
- `/history` — последние 10 заказов и что с ними
- `/stats` — сколько за неделю найдено, прошло фильтр и отправлено

## Проверка по частям

| Скрипт | Что проверяет |
| --- | --- |
| `scripts/test_parser.py` | посты из каналов доходят до базы |
| `scripts/eval_filter.py` | фильтр на 20 синтетических заказах |
| `scripts/test_filter.py [N]` | фильтр на реальных заказах из базы |
| `scripts/eval_generator.py` | черновики на 5 заказах |
| `scripts/test_generator.py "текст"` | черновик для любого текста |

Критерии отбора лежат в промпте `FILTER_SYSTEM` (`filter/order_filter.py`),
тон откликов в `GENERATOR_SYSTEM` (`generator/draft_generator.py`).
