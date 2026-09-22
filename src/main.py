import asyncio
from datetime import datetime
import logging
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from typing import Dict, Any, List
from telebot.async_telebot import AsyncTeleBot
from sqlalchemy import select, func

from src.config import settings
from src.database.session import init_db, async_session_factory
from src.database.models import Vacancy
from src.services.hh_client import HHClient
from src.services.filter_service import FilterService
from src.services.notification_service import NotificationService
from src.bot.handlers import register_handlers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("hhparser")


class JobMonitor:
    def __init__(self):
        self.bot = AsyncTeleBot(settings.BOT_TOKEN)
        self.hh_client = HHClient()
        self.filter_service = FilterService()
        self.notification_service = NotificationService(self.bot, settings.CHAT_ID)
        self.lock = asyncio.Lock()

    async def get_existing_ids(self) -> set[str]:
        async with async_session_factory() as session:
            result = await session.execute(select(Vacancy.id))
            return set(result.scalars().all())

    async def is_first_run(self) -> bool:
        async with async_session_factory() as session:
            result = await session.execute(select(func.count(Vacancy.id)))
            count = result.scalar() or 0
            return count == 0

    async def save_vacancy(self, session, vac: Dict[str, Any]):
        pub_at = vac.get("published_at")
        if isinstance(pub_at, str):
            try:
                pub_datetime = datetime.fromisoformat(pub_at).replace(tzinfo=None)
            except Exception:
                pub_datetime = datetime.utcnow()
        elif isinstance(pub_at, datetime):
            pub_datetime = pub_at.replace(tzinfo=None)
        else:
            pub_datetime = datetime.utcnow()

        skills_str = ", ".join(vac.get("matched_skills", []))

        vacancy_record = Vacancy(
            id=str(vac["id"]),
            title=vac["title"],
            company=vac["company"],
            salary_from=vac.get("salary_from"),
            salary_to=vac.get("salary_to"),
            currency=vac.get("currency"),
            url=vac["url"],
            area_name=vac.get("area_name", ""),
            schedule_name=vac.get("schedule_name", ""),
            match_score=vac.get("match_score", 0),
            matched_skills=skills_str,
            published_at=pub_datetime,
            created_at=datetime.utcnow()
        )
        session.add(vacancy_record)

    async def run_check(self) -> int:
        async with self.lock:
            logger.info("Запуск поиска вакансий на HeadHunter...")
            first_run = await self.is_first_run()
            existing_ids = await self.get_existing_ids()

            raw_items = await self.hh_client.get_all_target_vacancies(existing_ids=existing_ids)
            logger.info(f"Получено {len(raw_items)} новых вакансий для детального анализа.")

            passed_vacancies: List[Dict[str, Any]] = []
            for item in raw_items:
                vac_id = str(item.get("id"))
                if vac_id in existing_ids:
                    continue

                passed, enriched = self.filter_service.evaluate_vacancy(item)
                if passed:
                    passed_vacancies.append(enriched)

            logger.info(f"Прошло фильтры подходящих вакансий: {len(passed_vacancies)}.")

            if not passed_vacancies:
                return 0

            # Sort by match score (highest first)
            passed_vacancies.sort(
                key=lambda x: x.get("match_score", 0),
                reverse=True
            )

            to_notify: List[Dict[str, Any]] = []
            if first_run:
                # First run: notify top N
                to_notify = passed_vacancies[:settings.INITIAL_VACANCIES_LIMIT]
                logger.info(f"Первый запуск: отправка топ-{len(to_notify)} лучших вакансий.")
            else:
                to_notify = passed_vacancies

            sent_count = 0
            for vac in to_notify:
                success = await self.notification_service.send_vacancy_notification(vac)
                if success:
                    sent_count += 1
                await asyncio.sleep(0.5)

            # Save all passed vacancies to DB to avoid duplicate notifications
            async with async_session_factory() as session:
                async with session.begin():
                    for vac in passed_vacancies:
                        await self.save_vacancy(session, vac)

            logger.info(f"Успешно отправлено {sent_count} уведомлений и сохранено {len(passed_vacancies)} вакансий в БД.")
            return sent_count

    async def scheduler_loop(self):
        logger.info(f"Фоновый планировщик запущен. Периодичность: {settings.CHECK_INTERVAL_SECONDS} секунд.")
        while True:
            try:
                await asyncio.sleep(settings.CHECK_INTERVAL_SECONDS)
                await self.run_check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле планировщика: {e}", exc_info=True)
                await asyncio.sleep(30)

    async def start(self):
        await init_db()
        logger.info("База данных SQLite инициализирована.")

        register_handlers(self.bot, self.run_check)

        # Send test greeting to verify connection
        try:
            await self.bot.send_message(
                chat_id=settings.CHAT_ID,
                text=(
                    "🚀 <b>HH-парсер запущен и активен!</b>\n\n"
                    "🔍 <b>Критерии поиска:</b>\n"
                    "• Санкт-Петербург (офис/гибрид) + Вся РФ (удалёнка)\n"
                    "• Стек: Python, FastAPI, SQLAlchemy, Docker, Git, CI/CD\n"
                    "• Зарплата: от 50 000 ₽ или по договорённости\n"
                    f"• Проверка каждые {settings.CHECK_INTERVAL_SECONDS // 60} минут\n\n"
                    "Выполняю первичный поиск актуальных вакансий..."
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить стартовое сообщение: {e}")

        # Run first check immediately
        try:
            await self.run_check()
        except Exception as e:
            logger.error(f"Ошибка при первом поиске: {e}", exc_info=True)

        logger.info("Запуск Telegram-бота и фонового планировщика...")
        await asyncio.gather(
            self.bot.infinity_polling(timeout=20, request_timeout=30),
            self.scheduler_loop()
        )


async def main():
    monitor = JobMonitor()
    await monitor.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Работа парсера завершена.")
