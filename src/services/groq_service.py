import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
import httpx
from src.config import settings

logger = logging.getLogger(__name__)


class GroqService:
    GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

    SYSTEM_PROMPT = """Ты — персональный AI-рекрутер для начинающего разработчика (Junior / Стажер).
Твоя задача — объективно оценить вакансию с HeadHunter и определить, подходит ли она данному кандидату.

ПРОФИЛЬ КАНДИДАТА:
- Уровень: Junior / Стажер (начинающий специалист).
- Основной стек кандидата: Python, Django, FastAPI, SQLAlchemy, Pydantic, Docker, Git, CI/CD, Pytest/Unittest, REST API.
- Желаемая занятость: готов работать 25-30 часов в неделю (если график гибкий — идеально, но обычный full-time тоже допустим, если вакансия подходит).
- Зарплатные ожидания: за 25-30 часов нужно получать от 50 000 руб/мес (эквивалент от 80 000 руб/мес на полный день).

ПРАВИЛА ОЦЕНКИ:
1. ЗАРПЛАТА:
   - Если зарплата ЯВНО указана и она МЕНЬШЕ 60 000 руб/мес (на руки/до вычета) -> СТРОГО ОТКЛОНЯТЬ (is_suitable = false).
   - Если зарплата >= 60 000 руб/мес или НЕ УКАЗАНА ("по договорённости") -> ДОПУСКАТЬ к оценке.

2. СТЕК И ТРЕБОВАНИЯ:
   - ПРИОРИТЕТ 1: Вакансии на Python (Backend, Web, API, стажировки), где требуется или приветствуется стек кандидата -> ПОДХОДИТ (is_suitable = true, высокий match_score).
   - ПРИОРИТЕТ 2: Стажировки или вакансии с низким порогом входа ("без опыта", "всему научим", базовые знания алгоритмов и программирования) -> ПОДХОДИТ (is_suitable = true).
   - СТРОГО ОТКЛОНЯТЬ (is_suitable = false):
     * Неподходящие специализации: 1С, PHP, веб-дизайн, верстка без бэкенда, проджект-менеджмент, продажи, техподдержка.
     * Информационная безопасность, кибербезопасность, пентест (тестирование на проникновение), Bug Bounty, поиск уязвимостей.
     * Глубокий Data Science / ML / LLM / Computer Vision / высшая математика.
     * Системное администрирование низкого уровня, глубокие сети (OSI, BGP, NAT, Cisco, Mikrotik), железо, монтаж.
     * Вакансии уровня Senior / Lead / Middle с жестким требованием от 3-5 лет коммерческого опыта.

ОТВЕТ ДОЛЖЕН БЫТЬ СТРОГО В ФОРМАТЕ JSON:
{
  "is_suitable": true/false,
  "match_score": число от 0 до 100,
  "matched_skills": ["найденные", "технологии", "кандидата"],
  "summary_requirements": ["краткий", "пункт", "реальных", "требований", "к", "кандидату"],
  "reason": "краткое обоснование решения (1-2 предложения)"
}"""

    def __init__(self):
        self.api_key = settings.GROQ_API_KEY
        self.primary_model = settings.GROQ_PRIMARY_MODEL
        self.fallback_model = settings.GROQ_FALLBACK_MODEL

    def compress_vacancy_text(self, item: Dict[str, Any]) -> str:
        """
        Cleans and compacts vacancy HTML into a token-efficient plain text representation.
        Caps content to ~2500 characters so each request consumes only ~700-900 tokens.
        """
        title = item.get("title", "")
        company = item.get("company", "")
        salary = item.get("salary_raw") or "Не указана (по договорённости)"
        address = item.get("address", "")
        emp_text = item.get("employment_text", "")
        key_skills = item.get("key_skills", [])

        desc_html = item.get("description_html", "")
        soup = BeautifulSoup(desc_html, "html.parser")

        # Remove irrelevant tags
        for tag in soup(["script", "style", "header", "footer"]):
            tag.decompose()

        desc_text = soup.get_text(" ", strip=True)
        # Collapse multiple spaces
        desc_text = re.sub(r"\s+", " ", desc_text)

        # Cap description to 2500 characters
        if len(desc_text) > 2500:
            desc_text = desc_text[:2500] + "... [сокращено]"

        skills_str = ", ".join(key_skills) if key_skills else "Не указаны"
        loc_str = f"{address} ({emp_text})" if emp_text else address

        compact_prompt = (
            f"Название: {title}\n"
            f"Компания: {company}\n"
            f"Зарплата: {salary}\n"
            f"Локация и формат: {loc_str}\n"
            f"Ключевые навыки: {skills_str}\n"
            f"Описание и требования:\n{desc_text}"
        )
        return compact_prompt

    async def _call_groq_model(
        self,
        client: httpx.AsyncClient,
        model: str,
        user_prompt: str
    ) -> Tuple[int, Optional[Dict[str, Any]], Optional[int]]:
        """
        Calls Groq API with given model and JSON output mode.
        Returns (status_code, parsed_json_or_none, retry_after_seconds_or_none).
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }

        try:
            resp = await client.post(
                self.GROQ_API_URL,
                headers=headers,
                json=payload,
                timeout=18.0
            )

            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                return 200, parsed, None

            retry_after = None
            if resp.status_code == 429:
                ra_header = resp.headers.get("retry-after")
                if ra_header:
                    try:
                        retry_after = int(float(ra_header))
                    except Exception:
                        retry_after = 5

            logger.warning(
                f"Groq API model '{model}' returned status {resp.status_code}: {resp.text[:150]}"
            )
            return resp.status_code, None, retry_after

        except Exception as e:
            logger.error(f"Groq API call exception for model '{model}': {e}")
            return 500, None, None

    async def evaluate_vacancy(self, item: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Evaluates a single vacancy via Groq AI.
        Uses primary model, handles 429 with backoff and automatic failover to fallback model.
        Returns:
            (passed, enriched_item)
        """
        if not self.api_key:
            logger.error("GROQ_API_KEY is not set! Skipping AI evaluation.")
            return False, {}

        user_prompt = self.compress_vacancy_text(item)

        async with httpx.AsyncClient() as client:
            # 1. Try primary model
            status, result, retry_after = await self._call_groq_model(
                client, self.primary_model, user_prompt
            )

            # 2. If 429 on primary model, check retry_after or failover
            if status == 429:
                if retry_after and retry_after <= 5:
                    logger.info(f"Groq 429 hit. Waiting {retry_after}s according to Retry-After header...")
                    await asyncio.sleep(retry_after)
                    status, result, _ = await self._call_groq_model(
                        client, self.primary_model, user_prompt
                    )

                # If still failing, failover to fallback model
                if status != 200:
                    logger.warning(
                        f"Failing over to Groq fallback model '{self.fallback_model}'..."
                    )
                    status, result, _ = await self._call_groq_model(
                        client, self.fallback_model, user_prompt
                    )

            if status != 200 or not result:
                logger.error(f"Failed to evaluate vacancy ID {item.get('id')} via Groq AI.")
                return False, {}

            is_suitable = bool(result.get("is_suitable", False))
            match_score = int(result.get("match_score", 0))
            matched_skills = result.get("matched_skills", [])
            summary_reqs = result.get("summary_requirements", [])
            reason = result.get("reason", "")

            # Format requirements as clean bullet points
            req_snippet = ""
            if summary_reqs and isinstance(summary_reqs, list):
                req_snippet = "\n".join(f"• {r.lstrip('•-*— ')}" for r in summary_reqs[:5])

            enriched = {
                "id": str(item.get("id")),
                "title": item.get("title", ""),
                "company": item.get("company", "Не указана"),
                "salary_formatted": item.get("salary_raw") or "Не указана (по договорённости)",
                "salary_from": None,
                "salary_to": None,
                "currency": "RUB",
                "url": item.get("url", f"https://hh.ru/vacancy/{item.get('id')}"),
                "area_name": item.get("address", ""),
                "schedule_name": item.get("employment_text", ""),
                "format_info": f"📍 {item.get('address', '')}" if "санкт-петербург" in str(item.get("address", "")).lower() else f"🌐 Удалённая работа ({item.get('address', '')})",
                "match_score": match_score,
                "matched_skills": matched_skills,
                "requirements_snippet": req_snippet,
                "ai_reason": reason,
                "published_at": item.get("published_at")
            }

            logger.info(
                f"Groq оценка [{item.get('id')} - {item.get('title')}]: "
                f"suitable={is_suitable}, score={match_score}%, reason='{reason[:80]}...'"
            )
            return is_suitable, enriched
