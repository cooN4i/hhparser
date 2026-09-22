from datetime import datetime
from telebot.async_telebot import AsyncTeleBot
from telebot.types import Message
from sqlalchemy import select, func
from src.database.session import async_session_factory
from src.database.models import Vacancy
from src.config import settings


def register_handlers(bot: AsyncTeleBot, run_check_callback):
    @bot.message_handler(commands=["start"])
    async def cmd_start(message: Message):
        text = (
            "👋 <b>Привет! Я персональный HH-парсер вакансий.</b>\n\n"
            "🔍 <b>Мои фильтры:</b>\n"
            "• <b>Локация:</b> Санкт-Петербург (офис/гибрид/удаленка) + Вся РФ (строго удалёнка)\n"
            "• <b>Опыт:</b> «Нет опыта» и «От 1 года до 3 лет»\n"
            "• <b>Стек:</b> Python, FastAPI, SQLAlchemy, Pydantic, Docker, Git, CI/CD\n"
            "• <b>Зарплата:</b> от 50 000 ₽ либо «по договорённости»\n"
            "• <b>Исключения:</b> 1C, Bitrix, PHP, Data Science/ML, Frontend\n"
            f"• <b>Период проверки:</b> каждые {settings.CHECK_INTERVAL_SECONDS // 60} минут\n\n"
            "⚙️ <b>Команды:</b>\n"
            "/check — Запустить поиск свежих вакансий прямо сейчас\n"
            "/status — Посмотреть статистику сохранённых вакансий и статус работы\n"
            "/help — Справка"
        )
        await bot.send_message(message.chat.id, text, parse_mode="HTML")

    @bot.message_handler(commands=["status"])
    async def cmd_status(message: Message):
        async with async_session_factory() as session:
            count_res = await session.execute(select(func.count(Vacancy.id)))
            total_count = count_res.scalar() or 0

            latest_res = await session.execute(
                select(Vacancy).order_by(Vacancy.created_at.desc()).limit(1)
            )
            latest = latest_res.scalar_one_or_none()

        latest_str = latest.created_at.strftime("%d.%m.%Y %H:%M:%S") if latest else "еще не было"
        text = (
            "📊 <b>Статус парсера:</b>\n\n"
            f"🟢 <b>Бот активен:</b> Да\n"
            f"📦 <b>Всего обработано вакансий:</b> <code>{total_count}</code>\n"
            f"⏱ <b>Интервал проверки:</b> каждые {settings.CHECK_INTERVAL_SECONDS // 60} минут\n"
            f"🕒 <b>Последнее сохранение:</b> {latest_str}\n"
        )
        await bot.send_message(message.chat.id, text, parse_mode="HTML")

    @bot.message_handler(commands=["check"])
    async def cmd_check(message: Message):
        await bot.send_message(message.chat.id, "🔄 Запускаю внеплановую проверку вакансий...")
        new_count = await run_check_callback()
        if new_count == 0:
            await bot.send_message(message.chat.id, "✨ Новых подходящих вакансий прямо сейчас не найдено. Следующая проверка по расписанию.")
        else:
            await bot.send_message(message.chat.id, f"✅ Проверка завершена! Найдено и отправлено новых вакансий: {new_count}")

    @bot.message_handler(commands=["help"])
    async def cmd_help(message: Message):
        text = (
            "💡 <b>Доступные команды:</b>\n"
            "/start — Описание бота и критериев поиска\n"
            "/check — Ручной запуск проверки вакансий\n"
            "/status — Статистика базы данных и проверок"
        )
        await bot.send_message(message.chat.id, text, parse_mode="HTML")
