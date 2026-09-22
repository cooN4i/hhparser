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
    HH_USER_AGENT: str = "HH-Student-JobHunter/1.0 (contact: bagir-spb@t.me)"

    # Target stack for scoring and matching
    MY_STACK: List[str] = [
        "python",
        "fastapi",
        "sqlalchemy",
        "pydantic",
        "docker",
        "git",
        "ci/cd",
        "postgresql",
        "postgres",
        "asyncio",
        "linux",
        "rest api",
        "backend",
        "бэкенд"
    ]

    # Stop words / forbidden areas (lowercase)
    STOP_WORDS: List[str] = [
        # Data Science / ML / AI
        "data science",
        "data scientist",
        "machine learning",
        "ml engineer",
        "ml-инженер",
        "ml инженер",
        "ml-разработчик",
        "ml разработчик",
        "computer vision",
        "deep learning",
        "нейросети",
        "нейронных сетей",
        "нейросетей",
        "nlp",
        "машинного обучения",
        "машинному обучению",
        "data analyst",
        "аналитик данных",
        "ai engineer",
        "ии-инженер",
        "ai-прототипирование",
        "вайб-кодер",
        "ai-assisted",
        # 1C / Bitrix / PHP / CMS
        "1с",
        "1c",
        "битрикс",
        "bitrix",
        "php",
        "wordpress",
        "вордпресс",
        "crm-интегратор",
        # Frontend / Mobile
        "frontend",
        "фронтенд",
        "react native",
        "flutter",
        "ios developer",
        "android developer",
        "swift",
        # Non-tech roles
        "монтажер",
        "монтажёр",
        "видеомонтажер",
        "hr-менеджер",
        "talent acquisition",
        "рекрутер",
        "копирайтер",
        "дизайнер",
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


settings = Settings()
