import re
from typing import Any, Dict, List, Optional, Tuple
from src.config import settings


class FilterService:
    def __init__(self):
        self.min_salary = settings.MIN_SALARY_RUB
        self.stop_words = settings.STOP_WORDS

    def parse_and_check_salary(self, text: Optional[str]) -> Tuple[bool, Optional[int], Optional[int], Optional[str], str]:
        """
        Parses salary string and checks against MIN_SALARY_RUB:
        - If not specified: PASS
        - If specified in RUB: must not be strictly < MIN_SALARY_RUB
        - If foreign currency (USD, EUR): PASS
        Returns (is_passed, sal_from, sal_to, currency, formatted_string)
        """
        if not text:
            return True, None, None, None, "Не указана (по договорённости)"

        clean = text.replace("\xa0", " ").strip()
        lower_c = clean.lower()

        if "не указана" in lower_c or "договор" in lower_c:
            return True, None, None, None, "Не указана (по договорённости)"

        curr = "RUB"
        if "$" in clean or "usd" in lower_c:
            curr = "USD"
        elif "€" in clean or "eur" in lower_c:
            curr = "EUR"

        raw_nums = re.findall(r"\d+(?:[\s\xa0]\d+)*", clean)
        nums = [int(n.replace(" ", "").replace("\xa0", "")) for n in raw_nums if len(n.replace(" ", "")) >= 2]

        sal_from, sal_to = None, None
        if "от" in lower_c and "до" in lower_c and len(nums) >= 2:
            sal_from, sal_to = nums[0], nums[1]
        elif "от" in lower_c and len(nums) >= 1:
            sal_from = nums[0]
        elif "до" in lower_c and len(nums) >= 1:
            sal_to = nums[0]
        elif len(nums) >= 2:
            sal_from, sal_to = nums[0], nums[1]
        elif len(nums) == 1:
            sal_from = nums[0]

        # Check threshold
        if curr == "RUB":
            if sal_to and sal_to < self.min_salary:
                return False, sal_from, sal_to, curr, clean
            if sal_from and not sal_to and sal_from < self.min_salary:
                return False, sal_from, sal_to, curr, clean

        return True, sal_from, sal_to, curr, clean

    def check_location(self, address: str, employment_text: str, description: str) -> Tuple[bool, str]:
        """
        Checks location:
        - Either St. Petersburg (any format: office, hybrid, remote)
        - Or Remote anywhere
        Rejects office in other cities (Moscow, Novosibirsk, etc.).
        """
        combined = f"{address} {employment_text} {description[:200]}".lower()

        is_spb = any(c in combined for c in ["санкт-петербург", "питер", "спб", "петербург"])
        is_remote = any(r in combined for r in ["удален", "дистанцион", "remote"])

        if is_spb and is_remote:
            return True, f"📍 Санкт-Петербург (Удалённо / Гибрид)"
        elif is_spb:
            return True, f"📍 Санкт-Петербург ({address or 'Офис/Гибрид'})"
        elif is_remote:
            loc = address if address else "Вся РФ"
            return True, f"🌐 Удалённая работа ({loc})"

        # If it's an office outside SPb without remote option
        return False, address or "Другой город"

    def check_stop_words(self, title: str, key_skills: List[str], description: str) -> bool:
        """
        Returns False if any stop word is present or if the title is non-technical.
        """
        title_lower = title.lower()
        skills_lower = [s.lower() for s in key_skills]
        desc_lower = description[:500].lower()

        # 1. Title must be related to developer, sysadmin, devops, engineer, QA auto, intern
        technical_keywords = [
            "python", "питон", "пайтон", "backend", "бэкенд", "бэкэнд",
            "разработчик", "developer", "программист", "devops", "девопс",
            "сисадмин", "системный администратор", "инженер", "engineer",
            "стажер", "стажёр", "intern", "junior", "qa auto", "автоматизатор",
            "тестировщик-автоматизатор", "qa-инженер"
        ]
        if not any(k in title_lower for k in technical_keywords):
            return False

        # 2. Strict title check against stop words
        for stop in self.stop_words:
            if stop in title_lower:
                return False

        # 3. Key skills check
        critical_skills = [
            "1с", "1c", "bitrix", "битрикс", "php", "wordpress", "flutter",
            "react native", "swift", "data science", "machine learning",
            "computer vision", "nlp", "vue", "react", "angular", "manual qa"
        ]
        for skill in skills_lower:
            for crit in critical_skills:
                if crit in skill:
                    return False

        # 4. Check description snippet
        for stop in ["1с-программист", "битрикс", "data scientist", "машинному обучению", "видеомонтаж"]:
            if stop in desc_lower:
                return False

        return True

    def calculate_stack_match(self, title: str, key_skills: List[str], description: str) -> Tuple[int, List[str]]:
        """
        Calculates match score (%) against user's stack and returns matched technologies.
        Stack: Python, FastAPI, SQLAlchemy, Pydantic, Git, Docker, CI/CD, PostgreSQL, Asyncio, Linux.
        """
        full_text = f"{title} {' '.join(key_skills)} {description}".lower()

        core_techs = [
            ("Python", [r"\bpython\b", r"\bпайтон\b", r"\bпитон\b"]),
            ("FastAPI", [r"\bfastapi\b", r"\bfast-api\b"]),
            ("SQLAlchemy", [r"\bsqlalchemy\b", r"\balchemy\b"]),
            ("Pydantic", [r"\bpydantic\b"]),
            ("Docker", [r"\bdocker\b", r"\bконтейнер"]),
            ("Git", [r"\bgit\b", r"\bгит\b", r"\bgitlab\b", r"\bgithub\b"]),
            ("CI/CD", [r"\bci/cd\b", r"\bcicd\b"]),
            ("PostgreSQL", [r"\bpostgres\b", r"\bpostgresql\b", r"\bпостгрес\b", r"\bsql\b"]),
            ("Asyncio", [r"\basyncio\b", r"\basync\b", r"\bасинхрон"]),
            ("Linux", [r"\blinux\b", r"\bлинукс\b", r"\bbash\b"]),
            ("REST API", [r"\brest\b", r"\brest api\b", r"\bapi\b"]),
            ("Backend", [r"\bbackend\b", r"\bбэкенд\b", r"\bбэкэнд\b"])
        ]

        matched = []
        for tech_name, patterns in core_techs:
            for pattern in patterns:
                if re.search(pattern, full_text):
                    matched.append(tech_name)
                    break

        if "Python" in matched or "Backend" in matched:
            base_score = 45
            extra_score = min(55, int((len(matched) / len(core_techs)) * 75))
            score = base_score + extra_score
        else:
            if any(role in title.lower() for role in ["devops", "системный администратор", "сисадмин", "linux"]):
                score = 50 + min(40, len(matched) * 10)
            else:
                score = min(40, len(matched) * 10)

        return min(score, 100), matched

    def extract_requirements_snippet(self, description: str) -> str:
        """Extracts candidate requirements block from description."""
        lines = description.split("\n")
        req_lines = []
        is_capturing = False

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            lower_l = line_str.lower()
            if any(h in lower_l for h in ["требования", "мы ждем", "ждем от вас", "наш идеальный кандидат", "что нужно знать"]):
                is_capturing = True
                continue

            if is_capturing:
                if any(h in lower_l for h in ["обязанности", "условия", "мы предлагаем", "будет плюсом", "задачи"]):
                    break
                req_lines.append(line_str)
                if len(req_lines) >= 4:
                    break

        if req_lines:
            return "\n".join(f"• {l.lstrip('•-* ')}" for l in req_lines)

        # Fallback: first 2 non-empty lines
        clean_lines = [l.strip() for l in lines if len(l.strip()) > 20]
        return "\n".join(clean_lines[:2]) if clean_lines else ""

    def evaluate_vacancy(self, item: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        title = item.get("title", "")
        key_skills = item.get("key_skills", [])
        description = item.get("description", "")
        address = item.get("address", "")
        emp_text = item.get("employment_text", "")
        salary_raw = item.get("salary_raw")

        # 1. Location
        loc_passed, format_info = self.check_location(address, emp_text, description)
        if not loc_passed:
            return False, {}

        # 2. Stop-words
        if not self.check_stop_words(title, key_skills, description):
            return False, {}

        # 3. Salary
        sal_passed, sal_from, sal_to, currency, sal_formatted = self.parse_and_check_salary(salary_raw)
        if not sal_passed:
            return False, {}

        # 4. Stack match
        match_score, matched_skills = self.calculate_stack_match(title, key_skills, description)
        if match_score < 45:
            return False, {}

        requirements_snippet = self.extract_requirements_snippet(description)

        enriched = {
            "id": str(item.get("id")),
            "title": title,
            "company": item.get("company", "Не указана"),
            "salary_formatted": sal_formatted,
            "salary_from": sal_from,
            "salary_to": sal_to,
            "currency": currency,
            "url": item.get("url"),
            "area_name": address,
            "schedule_name": emp_text,
            "format_info": format_info,
            "match_score": match_score,
            "matched_skills": matched_skills,
            "requirements_snippet": requirements_snippet,
            "published_at": item.get("published_at")
        }

        return True, enriched
