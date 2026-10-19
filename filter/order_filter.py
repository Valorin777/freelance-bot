"""Модуль 2: фильтрация заказов через Claude API (structured outputs)."""

import logging
from typing import Literal

import anthropic
from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

FILTER_SYSTEM = """\
Ты — строгий фильтр вакансий и заказов для фулстек-разработчика с опытом.

Профиль разработчика:
- Стек: Next.js, TypeScript, FastAPI, Firebase, Anthropic API (AI-интеграции), Telegram-боты
- Уровень: уверенный разработчик с живыми продакшн-проектами, НЕ джуниор
- Интересуют: сайты, веб-приложения, лендинги, интернет-магазины, интеграции, AI-фичи, боты
- Формат работы: разовые заказы И проектная/частичная занятость, подработка, контракт,
  part-time удалёнка — то, что можно совмещать. НЕ ищет работу в штат на полный день.

Тебе дают текст поста из Telegram-канала. Пропускай ДВА типа постов:
  (A) разовый заказ/проект от клиента («нужно сделать сайт/бота/интеграцию»);
  (B) вакансию с проектной/частичной занятостью или подработкой по стеку
      (part-time, проектно, на несколько часов в день, контракт, разовый проект,
      «нужен разработчик на проект», удалёнка с гибкой загрузкой).

Оцени пост:

1. Что это? Реклама курсов/сервисов, резюме исполнителей («ищу заказы», «возьму проект»),
   дайджесты, посты-анонсы каналов, сбор в «команду» без конкретики, сетевой маркетинг —
   suitable=false.

2. Формат занятости (ВАЖНО):
   - разовый заказ или проектная/частичная занятость / подработка / контракт / part-time →
     это подходит (см. дальше по бюджету и стеку);
   - вакансия В ШТАТ НА ПОЛНЫЙ ДЕНЬ (full-time, полная занятость, 5/2, оформление в штат,
     офис/гибрид с обязательным присутствием, релокация) → suitable=false, даже если стек подходит.
   - если занятость не указана явно, но это разовый заказ/проект — считать подходящим.

3. Бюджет / оплата:
   - разовый заказ ниже ~15–20 тыс. руб. за сайт/лендинг или ниже ~8–10 тыс. за фичу/интеграцию
     → suitable=false;
   - для part-time/проектной вакансии смотри на адекватность ставки/вилки: явно джуниорская
     оплата или «оплата символическая» → suitable=false; вилка не указана, но работодатель и
     задача серьёзные → это НЕ повод отсекать;
   - демпинг (задача «на пять минут», «кто дешевле всех») → suitable=false.

4. Маркеры демпинга — при любом suitable=false: «недорого», «за отзыв», «срочно и дёшево»,
   «студент подойдёт», «бюджет минимальный», «оплата символическая» и близкие.

5. Соответствие стеку: задача явно вне веб-стека (нативная мобильная разработка, 1С, десктоп,
   чистый дизайн без кода, ручное тестирование, копирайтинг, вёрстка писем) → suitable=false.

6. Конкретность: подходит по формату/стеку/оплате, но расплывчато — priority="medium".
   Чёткая задача + адекватная оплата → priority="high".

kind — тип поста: "order" (разовый заказ/проект от клиента) или "parttime"
       (проектная/частичная занятость, подработка, контракт). Для отсеянных ставь наиболее близкое.
reason — 1–2 предложения по-русски: почему прошло или не прошло фильтр.
"""


class FilterVerdict(BaseModel):
    """Результат фильтрации одного заказа."""

    suitable: bool = Field(description="Подходит ли пост разработчику")
    kind: Literal["order", "parttime"] = Field(
        description="Тип: order — разовый заказ/проект от клиента; "
        "parttime — проектная/частичная занятость, подработка, контракт"
    )
    priority: Literal["high", "medium"] = Field(
        description="Приоритет: high — чёткая задача и адекватная оплата, "
        "medium — проходит, но есть вопросы (расплывчато и т.п.)"
    )
    reason: str = Field(description="Краткое обоснование решения, 1-2 предложения по-русски")


class OrderFilter:
    def __init__(self, client: AsyncAnthropic, model: str):
        self._client = client
        self._model = model

    async def evaluate(self, order_text: str) -> FilterVerdict | None:
        """Оценивает текст заказа. Возвращает None при ошибке API (заказ можно повторить позже)."""
        try:
            response = await self._client.messages.parse(
                model=self._model,
                max_tokens=1024,
                system=FILTER_SYSTEM,
                messages=[
                    {
                        "role": "user",
                        "content": f"Пост из Telegram-канала:\n\n{order_text}",
                    }
                ],
                output_format=FilterVerdict,
            )
        except anthropic.RateLimitError:
            logger.warning("Claude API: превышен лимит запросов (фильтр), заказ будет повторён")
            return None
        except anthropic.APIStatusError as e:
            logger.error("Claude API: ошибка %s при фильтрации: %s", e.status_code, e.message)
            return None
        except anthropic.APIConnectionError:
            logger.error("Claude API: сетевая ошибка при фильтрации")
            return None
        except ValidationError:
            # ответ не прошёл валидацию схемы (например, JSON обрезан по max_tokens)
            logger.exception("Фильтр вернул невалидный структурированный ответ, заказ будет повторён")
            return None

        if response.parsed_output is None:
            logger.error("Фильтр не вернул структурированный ответ (stop_reason=%s)", response.stop_reason)
            return None
        return response.parsed_output
