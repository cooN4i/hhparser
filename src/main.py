import asyncio
from datetime import datetime, timezone, timedelta
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
from src.database.models import Vacancy, ProcessedVacancy
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

    async def get_processed_ids(self) -> set[str]:
        async with async_session_factory() as session:
            result = await session.execute(select(ProcessedVacancy.id))
            return set(result.scalars().all())

    async def is_first_run(self) -> bool:
        async with async_session_factory() as session:
            result = await session.execute(select(func.count(ProcessedVacancy.id)))
            count = result.scalar() or 0
            return count == 0

    async def save_vacancy(self, session, vac: Dict[str, Any]):
        pub_at = vac.get("published_at")
        if isinstance(pub_at, str):
            try:
                pub_datetime = datetime.fromisoformat(pub_at).replace(tzinfo=None)
            except Exception:
                pub_datetime = datetime.now(timezone.utc).replace(tzinfo=None)
        elif isinstance(pub_at, datetime):
            pub_datetime = pub_at.replace(tzinfo=None)
        else:
            pub_datetime = datetime.now(timezone.utc).replace(tzinfo=None)

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
            created_at=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        await session.merge(vacancy_record)

    async def run_check(self) -> int:
        async with self.lock:
            logger.info("Запуск проверки свежих вакансий на HeadHunter...")
            first_run = await self.is_first_run()
            processed_ids = await self.get_processed_ids()

            # get_all_target_vacancies returns (detailed_vacancies, all_search_ids)
            # detailed_vacancies are already sorted by published_at DESC!
            detailed_items, all_search_ids = await self.hh_client.get_all_target_vacancies(
                existing_ids=processed_ids,
                max_details=15
            )

            # 1. Первый запуск: фиксируем baseline
            if first_run:
                logger.info(
                    f"Первый запуск бота: зафиксировано {len(all_search_ids)} объявлений на HH. "
                    "Устанавливаю baseline..."
                )

                # Ищем самую свежую вакансию, опубликованную за последние 3 часа
                now = datetime.now(timezone.utc)
                cutoff = now - timedelta(hours=3)

                fresh_candidates = []
                for item in detailed_items:
                    pub = item.get("published_at")
                    if pub:
                        pub_aware = pub if pub.tzinfo is not None else pub.replace(tzinfo=timezone.utc)
                        if pub_aware >= cutoff:
                            fresh_candidates.append(item)

                passed_baseline = []
                for item in fresh_candidates:
                    passed, enriched = self.filter_service.evaluate_vacancy(item)
                    if passed:
                        passed_baseline.append(enriched)

                # Записываем все найденные ID как baseline в processed_vacancies
                async with async_session_factory() as session:
                    async with session.begin():
                        for vid in all_search_ids:
                            await session.merge(ProcessedVacancy(id=vid, status="baseline"))

                if passed_baseline:
                    newest = passed_baseline[0]
                    logger.info(
                        f"Первый запуск: отправляю свежую вакансию ID {newest['id']} "
                        f"('{newest['title']}', {newest.get('published_at')})"
                    )
                    success = await self.notification_service.send_vacancy_notification(newest)
                    async with async_session_factory() as session:
                        async with session.begin():
                            await self.save_vacancy(session, newest)
                            await session.merge(ProcessedVacancy(id=str(newest["id"]), status="sent"))
                    return 1 if success else 0
                else:
                    logger.info("Первый запуск: подходящих вакансий за последние 3 часа нет. Baseline зафиксирован.")
                    return 0

            # 2. Регулярная проверка (каждые 5 минут):
            # detailed_items содержат только вакансии, которых ещё не было в базе (новые)
            if not detailed_items:
                logger.info("Новых объявлений на HH не обнаружено. Ожидание следующего цикла.")
                return 0

            logger.info(f"Найдено {len(detailed_items)} новых объявлений на HH. Анализирую от самых свежих...")

            newest_matched = None
            eval_results = []

            for item in detailed_items:
                vid = str(item["id"])
                passed, enriched = self.filter_service.evaluate_vacancy(item)
                if passed:
                    status = "sent" if newest_matched is None else "matched_queued"
                    eval_results.append((vid, status, enriched))
                    if newest_matched is None:
                        newest_matched = enriched
                else:
                    eval_results.append((vid, "rejected", None))

            # Фиксируем все проверенные ID в базе, чтобы никогда не проверять их повторно
            async with async_session_factory() as session:
                async with session.begin():
                    for vid, status, _ in eval_results:
                        await session.merge(ProcessedVacancy(id=vid, status=status))

            if newest_matched:
                pub_time = newest_matched.get("published_at")
                logger.info(
                    f"Найдена свежая подходящая вакансия ID {newest_matched['id']} "
                    f"('{newest_matched['title']}', {pub_time}). Отправляю уведомление пользователю..."
                )
                success = await self.notification_service.send_vacancy_notification(newest_matched)
                async with async_session_factory() as session:
                    async with session.begin():
                        await self.save_vacancy(session, newest_matched)
                sent_count = 1 if success else 0
                logger.info(f"Уведомление отправлено (ID: {newest_matched['id']}).")
                return sent_count
            else:
                logger.info(f"Все {len(detailed_items)} новых объявлений были отклонены фильтрами.")
                return 0

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
