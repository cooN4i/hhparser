import asyncio
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from telebot.async_telebot import AsyncTeleBot
from src.config import settings
from src.services.hh_client import HHClient
from src.services.filter_service import FilterService
from src.services.notification_service import NotificationService
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

    print("\n=== 3. Проверка поиска вакансий через HHClient ===")
    client = HHClient()
    filter_service = FilterService()
    try:
        vacancies, all_ids = await client.get_all_target_vacancies(max_details=10)
        print(f"✅ Найдено на поиске карточек: {len(all_ids)}, детально спарсено свежих: {len(vacancies)}")

        passed_count = 0
        for v in vacancies:
            passed, enriched = filter_service.evaluate_vacancy(v)
            if passed:
                passed_count += 1
                print(f"  [+] Подходит: {enriched['title']} | {enriched['company']}")
                print(f"      З/п: {enriched['salary_formatted']} | {enriched['format_info']}")
                print(f"      Стек: {enriched['match_score']}% {enriched['matched_skills']}")
                print(f"      Опубликовано: {enriched.get('published_at')}")
                if enriched['requirements_snippet']:
                    print(f"      Требования: {enriched['requirements_snippet'][:100]}...")
            else:
                print(f"  [-] Отклонена: {v.get('title')}")

        print(f"\nИз {len(vacancies)} проверенных подошло: {passed_count}")
    except Exception as e:
        print(f"❌ Ошибка при проверке парсера: {e}")
        return False
    finally:
        await bot.close_session()

    print("\n🎉 Все системы проверены и работают штатно!")
    return True


if __name__ == "__main__":
    success = asyncio.run(verify())
    if not success:
        sys.exit(1)
