from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Telegram
    BOT_TOKEN: str
    CHAT_ID: int

    # Parser
    CHECK_INTERVAL_SECONDS: int = 300
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/vacancies.db"
    MIN_SALARY_RUB: int = 50000
    MAX_VACANCY_AGE_DAYS: int = 7  # Maximum age in days (covers weekend postings)
    HH_USER_AGENT: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

    # User stack
    MY_STACK: List[str] = [
        "python",
        "fastapi",
        "sqlalchemy",
        "pydantic",
        "docker",
        "git",
        "ci/cd",
        "postgresql",
        "asyncio",
        "linux",
        "rest api",
        "backend"
    ]

    # Stop words for vacancy TITLE (irrelevant roles)
    TITLE_STOP_WORDS: List[str] = [
        "системный администратор",
        "сисадмин",
        "сетевой инженер",
        "инженер связи",
        "инженер тп",
        "дежурный администратор",
        "frontend",
        "фронтенд",
        "верстальщик",
        "unreal engine",
        "unity",
        "gamedev",
        "геймдев",
        "1с",
        "1c",
        "битрикс",
        "bitrix",
        "php",
        "wordpress",
        "вордпресс",
        "data scientist",
        "data analyst",
        "аналитик данных",
        "ml engineer",
        "ml-инженер",
        "ml инженер",
        "монтажер",
        "монтажёр",
        "дизайнер",
        "рекрутер",
        "hr-менеджер",
        "talent acquisition",
        "копирайтер",
        "экономист",
        "бухгалтер",
        "юрист",
        "маркетолог",
        "таргетолог",
        "manual qa",
        "ручной тестировщик",
        "менеджер по продажам",
        "продавец",
        "оператор колл-центра",
        "оператор call-центра"
    ]

    # Stop words for FULL CONTENT (forbidden technologies / hardware)
    CONTENT_STOP_WORDS: List[str] = [
        # Telecom & Network hardware (pure admin/NOC, NOT programming)
        "cisco",
        "mikrotik",
        "d-link",
        "ospf",
        "bgp",
        "телефония",
        "атс",
        "коммутатор",
        "маршрутизатор",
        "видеонаблюдение",
        "эникей",
        "helpdesk",
        "1-я линия",
        "первая линия",
        "монтаж сетей",
        "монтаж кабельных",
        "прокладка сетей",
        "скс",
        "freebsd",
        "postfix",
        "exim",
        "пайка",
        "ремонт пк",
        "сборка пк",
        # CMS & other languages
        "битрикс",
        "bitrix",
        "1с-программист",
        "1с программирование",
        "wordpress",
        "вордпресс",
        "joomla",
        # Mobile frameworks
        "react native",
        "flutter"
    ]


settings = Settings()
