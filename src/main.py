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
from src.services.groq_service import GroqService
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
        self.groq_service = GroqService()
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
            logger.info("Запуск проверки свежих IT-вакансий на HeadHunter...")
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

                # Записываем все найденные ID как baseline в processed_vacancies
                async with async_session_factory() as session:
                    async with session.begin():
                        for vid in all_search_ids:
                            await session.merge(ProcessedVacancy(id=vid, status="baseline"))

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

                sent_count = 0
                for item in fresh_candidates:
                    vid = str(item["id"])
                    # Быстрый локальный пре-фильтр локации и зарплаты
                    loc_ok, _ = self.filter_service.check_location(
                        item.get("address", ""), item.get("employment_text", ""), item.get("description_html", "")
                    )
                    sal_ok, _, _, _, _ = self.filter_service.parse_and_check_salary(item.get("salary_raw"))
                    if not (loc_ok and sal_ok):
                        continue

                    # Оценка через Groq AI
                    is_suitable, enriched = await self.groq_service.evaluate_vacancy(item)
                    await asyncio.sleep(1.5)

                    if is_suitable:
                        logger.info(
                            f"Первый запуск: отправляю свежую вакансию ID {enriched['id']} "
                            f"('{enriched['title']}', {enriched.get('published_at')})"
                        )
                        success = await self.notification_service.send_vacancy_notification(enriched)
                        async with async_session_factory() as session:
                            async with session.begin():
                                await self.save_vacancy(session, enriched)
                                await session.merge(ProcessedVacancy(id=vid, status="sent"))
                        if success:
                            sent_count += 1
                        break  # При первом запуске отправляем только 1 самую свежую

                if sent_count == 0:
                    logger.info("Первый запуск: подходящих вакансий за последние 3 часа нет. Baseline зафиксирован.")
                return sent_count

            # 2. Регулярная проверка (каждые 5 минут):
            # detailed_items содержат только вакансии, которых ещё не было в базе (новые)
            if not detailed_items:
                logger.info("Новых объявлений на HH не обнаружено. Ожидание следующего цикла.")
                return 0

            logger.info(f"Найдено {len(detailed_items)} новых объявлений на HH. Анализирую через Groq AI...")
            sent_count = 0

            for item in detailed_items:
                vid = str(item["id"])

                # Шаг 1: Быстрый локальный пре-чек локации и минимальной зарплаты
                # (сберегает вызовы Groq от очевидных офисов в других городах или вакансий < 60к)
                loc_ok, _ = self.filter_service.check_location(
                    item.get("address", ""), item.get("employment_text", ""), item.get("description_html", "")
                )
                sal_ok, _, _, _, _ = self.filter_service.parse_and_check_salary(item.get("salary_raw"))

                if not (loc_ok and sal_ok):
                    logger.debug(f"Вакансия {vid} отсеяна пре-фильтром локации/зарплаты.")
                    async with async_session_factory() as session:
                        async with session.begin():
                            await session.merge(ProcessedVacancy(id=vid, status="rejected"))
                    continue

                # Шаг 2: Семантическая оценка через Groq AI
                is_suitable, enriched = await self.groq_service.evaluate_vacancy(item)
                await asyncio.sleep(1.5)

                if is_suitable:
                    pub_time = enriched.get("published_at")
                    logger.info(
                        f"Найдена подходящая вакансия ID {enriched['id']} "
                        f"('{enriched['title']}', {pub_time}). Отправляю уведомление пользователю..."
                    )
                    success = await self.notification_service.send_vacancy_notification(enriched)
                    async with async_session_factory() as session:
                        async with session.begin():
                            await self.save_vacancy(session, enriched)
                            await session.merge(ProcessedVacancy(id=vid, status="sent"))
                    if success:
                        sent_count += 1
                    # Пауза между отправками нескольких сообщений в Telegram
                    await asyncio.sleep(1.5)
                elif enriched:
                    async with async_session_factory() as session:
                        async with session.begin():
                            await session.merge(ProcessedVacancy(id=vid, status="rejected"))
                else:
                    # В случае редкой невосстановимой ошибки Groq помечаем failed_skip,
                    # чтобы вакансия не блокировала очередь
                    async with async_session_factory() as session:
                        async with session.begin():
                            await session.merge(ProcessedVacancy(id=vid, status="failed_skip"))

            logger.info(f"Цикл проверки завершён. Отправлено новых вакансий: {sent_count}.")
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
