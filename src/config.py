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

    # Stop words for vacancy TITLE (irrelevant non-engineering roles or pure sysadmins)
    TITLE_STOP_WORDS: List[str] = [
        "системный администратор",
        "сисадмин",
        "сетевой инженер",
        "инженер связи",
        "инженер тп",
        "дежурный администратор",
        "администратор баз данных",
        "db administrator",
        "верстальщик",
        "1с",
        "1c",
        "битрикс",
        "bitrix",
        "wordpress",
        "вордпресс",
        "joomla",
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

    # Stop words for FULL CONTENT (forbidden deep specifics: math, transformers, networking, hardware, OS admin)
    CONTENT_STOP_WORDS: List[str] = [
        # 1. Deep ML / Data Science / Math specifics (Rejected Case 2)
        "pytorch",
        "tensorflow",
        "transformers",
        "llm",
        "rag",
        "huggingface",
        "cuda",
        "высшая математика",
        "высшей математики",
        "линейная алгебра",
        "линейной алгебры",
        "теория вероятностей",
        "теории вероятностей",
        "тервер",
        "матстат",
        "математическая статистика",
        "математической статистики",
        "компьютерное зрение",
        "computer vision",
        "deep learning",
        "глубокое обучение",
        # 2. Telecom, deep networking & hardware (Rejected Case 4)
        "модель osi",
        "маршрутизац",
        "коммутатор",
        "маршрутизатор",
        "bgp",
        "ospf",
        "mpls",
        "vlan",
        "ip-адресац",
        "wireshark",
        "tcpdump",
        "cisco",
        "mikrotik",
        "d-link",
        "juniper",
        "телефония",
        "атс",
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
        "заправка картридж",
        "плис",
        "vhdl",
        "verilog",
        "systemverilog",
        "fpga",
        "схемотехник",
        # 3. Pure OS-level sysadmin (Rejected Case 4)
        "systemd без gui",
        "разбор systemd",
        "rhel",
        "alt linux",
        "astra linux",
        "ред ос",
        # 4. Other ecosystems & CMS
        "битрикс",
        "bitrix",
        "1с-программист",
        "1с программирование",
        "wordpress",
        "вордпресс",
        "joomla",
        # 5. Mobile app frameworks
        "react native",
        "flutter"
    ]


settings = Settings()
