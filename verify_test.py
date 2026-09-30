import asyncio
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from telebot.async_telebot import AsyncTeleBot
from src.config import settings
from src.services.hh_client import HHClient
from src.services.filter_service import FilterService
from src.services.groq_service import GroqService
from src.database.session import init_db


async def verify():
    print("=== 1. Проверка Telegram Bot Token ===")
    bot = AsyncTeleBot(settings.BOT_TOKEN)
    try:
        me = await bot.get_me()
        print(f"✅ Бот успешно авторизован: @{me.username} (ID: {me.id}, Имя: {me.first_name})")
    except Exception as e:
        print(f"❌ Ошибка подключения к Telegram Bot: {e}")
        return False

    print("\n=== 2. Проверка базы данных SQLite ===")
    try:
        await init_db()
        print("✅ Таблицы SQLite успешно инициализированы!")
    except Exception as e:
        print(f"❌ Ошибка инициализации БД: {e}")
        return False

    print("\n=== 3. Проверка Groq AI Service ===")
    groq_service = GroqService()
    try:
        test_vac = {
            "title": "Junior Backend Python Developer",
            "company": "Tech Solutions",
            "description": "Ищем начинающего Python-разработчика со знанием FastAPI, PostgreSQL и Docker. Готовы обучать.",
            "requirements": "Базовые знания Python, FastAPI, SQL. Желание учиться.",
            "key_skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
            "experience": "noExperience",
            "employment": "full",
            "schedule": "remote",
            "salary_from": 70000,
            "salary_to": 90000,
            "salary_currency": "RUR",
            "city": "Санкт-Петербург"
        }
        is_suitable, enriched = await groq_service.evaluate_vacancy(test_vac)
        if is_suitable:
            print(f"✅ Groq AI успешно проанализировал тестовую вакансию!")
            print(f"   Подходит: {is_suitable}, Оценка стека: {enriched.get('match_score')}%")
            print(f"   Причина: {enriched.get('ai_reason')}")
        else:
            print(f"⚠️ Groq вернул ответ, но результат: is_suitable={is_suitable}")
    except Exception as e:
        print(f"❌ Ошибка при проверке Groq AI: {e}")
        return False

    print("\n=== 4. Проверка поиска вакансий через HHClient ===")
    client = HHClient()
    try:
        vacancies, all_ids = await client.get_all_target_vacancies(max_details=5)
        print(f"✅ Найдено на поиске карточек: {len(all_ids)}, спарсено свежих: {len(vacancies)}")
        if vacancies:
            v = vacancies[0]
            print(f"   Проверяем первую найденную вакансию: {v.get('title')} ({v.get('company')})")
            ai_pass, ai_res = await groq_service.evaluate_vacancy(v)
            print(f"   AI вердикт: suitable={ai_pass}, score={ai_res.get('match_score')}%, reason='{ai_res.get('ai_reason')}'")
    except Exception as e:
        print(f"❌ Ошибка при проверке парсера HH: {e}")
        return False
    finally:
        await bot.close_session()

    print("\n🎉 Все системы проверены и работают штатно!")
    return True


if __name__ == "__main__":
    success = asyncio.run(verify())
    if not success:
        sys.exit(1)
