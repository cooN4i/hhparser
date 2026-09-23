from datetime import datetime, timezone, timedelta
import re
from typing import Any, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
from src.config import settings


class FilterService:
    def __init__(self):
        self.min_salary = settings.MIN_SALARY_RUB
        self.title_stop_words = settings.TITLE_STOP_WORDS
        self.content_stop_words = settings.CONTENT_STOP_WORDS

    def parse_and_check_salary(self, text: Optional[str]) -> Tuple[bool, Optional[int], Optional[int], Optional[str], str]:
        """Parses salary and checks against MIN_SALARY_RUB."""
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

        if curr == "RUB":
            if sal_to and sal_to < self.min_salary:
                return False, sal_from, sal_to, curr, clean
            if sal_from and not sal_to and sal_from < self.min_salary:
                return False, sal_from, sal_to, curr, clean

        return True, sal_from, sal_to, curr, clean

    def check_location(self, address: str, employment_text: str, desc_text: str) -> Tuple[bool, str]:
        """Checks location: St. Petersburg or Remote."""
        combined = f"{address} {employment_text} {desc_text[:300]}".lower()

        is_spb = any(c in combined for c in ["санкт-петербург", "питер", "спб", "петербург"])
        is_remote = any(r in combined for r in ["удален", "дистанцион", "remote"])

        if is_spb and is_remote:
            return True, "📍 Санкт-Петербург (Удалённо / Гибрид)"
        elif is_spb:
            return True, f"📍 Санкт-Петербург ({address or 'Офис/Гибрид'})"
        elif is_remote:
            loc = address if address else "Вся РФ"
            return True, f"🌐 Удалённая работа ({loc})"

        return False, address or "Другой город"

    def check_title(self, title: str) -> bool:
        """
        Validates vacancy title:
        - Must NOT contain forbidden title keywords (pure sysadmin, 1C, hr, etc.) unless 'python' is in title.
        """
        lower = title.lower()

        for rej in self.title_stop_words:
            if rej in lower and "python" not in lower:
                return False

        return True

    def check_stop_words(self, title: str, key_skills: List[str], desc_html: str) -> bool:
        """
        Checks entire vacancy content for forbidden specific technologies:
        deep ML/math (pytorch, transformers, LLM, math stats),
        deep networking & hardware (OSI, BGP, Cisco, systemd admin),
        1C, Bitrix, mobile native apps.
        """
        soup = BeautifulSoup(desc_html, "html.parser")
        desc_text = soup.get_text(" ", strip=True).lower()
        full_text = f"{title} {' '.join(key_skills)} {desc_text}".lower()

        for stop in self.content_stop_words:
            if stop in full_text:
                return False

        return True

    def calculate_stack_match(self, title: str, key_skills: List[str], desc_html: str) -> Tuple[int, List[str]]:
        """
        Calculates honest stack match (%) based on Python as mandatory core
        plus any accessible generalist tooling:
        Web (FastAPI/Django/Flask), DB (SQL/PostgreSQL/SQLAlchemy), Pydantic,
        Docker, Git, CI/CD, Testing (pytest), Frontend (React/JS/HTML),
        Data (pandas/numpy/ETL), Asyncio, Linux/Bash.
        """
        soup = BeautifulSoup(desc_html, "html.parser")
        desc_text = soup.get_text(" ", strip=True).lower()
        full_text = f"{title} {' '.join(key_skills)} {desc_text}".lower()

        # Python is strictly mandatory
        has_python = bool(re.search(r"\bpython\b|\bпитон\b|\bпайтон\b", full_text))
        if not has_python:
            return 0, []

        matched: List[str] = ["Python"]
        score = 30

        # 1. Web Frameworks (FastAPI / Django / Flask / Aiohttp)
        if re.search(r"\bfastapi\b|\bfast-api\b", full_text):
            matched.append("FastAPI")
            score += 20
        elif re.search(r"\bdjango\b", full_text):
            matched.append("Django")
            score += 15
        elif re.search(r"\bflask\b", full_text):
            matched.append("Flask")
            score += 15
        elif re.search(r"\baiohttp\b", full_text):
            matched.append("Aiohttp")
            score += 15

        # 2. ORM, DB & SQL (SQLAlchemy, PostgreSQL, MySQL, Redis, SQL)
        if re.search(r"\bsqlalchemy\b|\balchemy\b", full_text):
            matched.append("SQLAlchemy")
            score += 15
        if re.search(r"\bpostgres\b|\bpostgresql\b|\bпостгрес\b", full_text):
            if "PostgreSQL" not in matched:
                matched.append("PostgreSQL")
                score += 10
        elif re.search(r"\bsql\b|\bреляционн", full_text):
            if "SQL" not in matched:
                matched.append("SQL")
                score += 10

        # 3. Pydantic
        if re.search(r"\bpydantic\b", full_text):
            matched.append("Pydantic")
            score += 15

        # 4. Containers & CI/CD
        if re.search(r"\bdocker\b|\bконтейнер", full_text):
            matched.append("Docker")
            score += 10

        if re.search(r"\bci/cd\b|\bcicd\b|\bgithub actions\b|\bgitlab ci\b", full_text):
            matched.append("CI/CD")
            score += 10

        # 5. Git
        if re.search(r"\bgit\b|\bгит\b|\bgitlab\b|\bgithub\b", full_text):
            matched.append("Git")
            score += 10

        # 6. Testing / QA (pytest, unittest, autotests) - Accepted Case 3
        if re.search(r"\bpytest\b|\bunittest\b|\bавтотест[а-я]*\b|\bqa auto\b|\bнаписание тестов\b|\bавтоматизац[а-я]* тестирован|\bunit-тест[а-я]*\b", full_text):
            matched.append("Testing/Pytest")
            score += 15

        # 7. Frontend / Fullstack (React, JS, TS, HTML, CSS) - Accepted Case 7
        if re.search(r"\breact\b|\btypescript\b|\bjavascript\b|\bjs\b|\bts\b|\bfrontend\b|\bверстк|\bhtml\b", full_text):
            matched.append("Frontend/Fullstack")
            score += 15

        # 8. Data / ETL / Basic ML (pandas, numpy, ETL) - Accepted Cases 1 & 6
        if re.search(r"\bpandas\b|\bnumpy\b|\betl\b|\bобработк[а-я]* данн", full_text):
            matched.append("Data/ETL")
            score += 15

        # 9. Asyncio
        if re.search(r"\basyncio\b|\bасинхрон", full_text):
            matched.append("Asyncio")
            score += 10

        # 10. Linux & REST API
        if re.search(r"\blinux\b|\bлинукс\b|\bbash\b", full_text):
            matched.append("Linux/Bash")
            score += 5

        if re.search(r"\brest\b|\brest api\b|\bapi\b", full_text):
            if "REST API" not in matched:
                matched.append("REST API")
                score += 5

        return min(score, 100), matched

    def extract_requirements(self, desc_html: str) -> str:
        """
        Accurately extracts candidate requirements list from HTML description.
        Finds sections like 'Требования:', 'От тебя мы ждем:', 'Ожидания:', 'Навыки:'
        and strictly stops BEFORE 'Мы предлагаем:', 'Условия:', 'Обязанности:',
        ensuring perks/benefits are NEVER extracted as requirements.
        """
        if not desc_html:
            return ""

        soup = BeautifulSoup(desc_html, "html.parser")

        req_headers = [
            "требования", "от тебя мы ждем", "от вас мы ждем",
            "мы ждем", "ожидания от кандидата", "ожидания",
            "что для нас важно", "наш идеальный кандидат",
            "навыки", "требуемый опыт", "требуемый стек"
        ]

        stop_headers = [
            "мы предлагаем", "что мы предлагаем", "условия", "условия работы",
            "бенефиты", "будет плюсом", "плюсом будет", "чем предстоит заниматься",
            "задачи", "обязанности", "что делать", "о компании"
        ]

        header_el = None
        for el in soup.find_all(["p", "div", "h2", "h3", "h4", "strong", "b"]):
            text = el.get_text(" ", strip=True).lower().rstrip(" :")
            if any(h in text for h in req_headers):
                header_el = el
                break

        if header_el:
            bullets = []
            curr = header_el
            if curr.parent and curr.parent.name in ["p", "div", "h2", "h3", "h4"]:
                curr = curr.parent

            for nxt in curr.find_next_siblings():
                t_lower = nxt.get_text(" ", strip=True).lower()
                if any(sh in t_lower for sh in stop_headers):
                    break

                if nxt.name in ["ul", "ol"]:
                    for li in nxt.find_all("li")[:6]:
                        txt = li.get_text(" ", strip=True)
                        if txt:
                            clean_li = re.sub(r"^[\s•\-*—–\d\.]+", "", txt).strip()
                            bullets.append(f"• {clean_li}")
                    if bullets:
                        break
                elif nxt.name in ["p", "div"]:
                    txt = nxt.get_text(" ", strip=True)
                    if re.match(r"^[\s•\-*—–\d\.]+", txt) and len(txt) > 5:
                        clean_txt = re.sub(r"^[\s•\-*—–\d\.]+", "", txt).strip()
                        if clean_txt:
                            bullets.append(f"• {clean_txt}")
                    elif len(txt) > 20:
                        bullets.append(f"• {txt}")

                if len(bullets) >= 5:
                    break

            if bullets:
                return "\n".join(bullets[:5])

        # Fallback: scan for any list that is NOT under "мы предлагаем" or "условия"
        for ul in soup.find_all(["ul", "ol"]):
            prev = ul.find_previous(["p", "div", "h2", "h3", "h4", "strong", "b"])
            if prev:
                prev_text = prev.get_text(" ", strip=True).lower()
                if any(sh in prev_text for sh in stop_headers):
                    continue
            lis = [li.get_text(" ", strip=True) for li in ul.find_all("li")[:5]]
            if lis:
                return "\n".join(f"• {re.sub(r'^[\s•\-*—–\d\.]+', '', li).strip()}" for li in lis if li)

        return ""

    def check_freshness(self, published_at: Optional[datetime]) -> bool:
        """Checks if vacancy is not older than MAX_VACANCY_AGE_DAYS."""
        if not published_at:
            return True

        now = datetime.now(timezone.utc)
        if published_at.tzinfo is None:
            pub_aware = published_at.replace(tzinfo=timezone.utc)
        else:
            pub_aware = published_at

        cutoff = now - timedelta(days=settings.MAX_VACANCY_AGE_DAYS)
        return pub_aware >= cutoff

    def evaluate_vacancy(self, item: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        title = item.get("title", "")
        key_skills = item.get("key_skills", [])
        desc_html = item.get("description_html", "")
        address = item.get("address", "")
        emp_text = item.get("employment_text", "")
        salary_raw = item.get("salary_raw")
        published_at = item.get("published_at")

        # 1. Freshness check: reject stale vacancies older than MAX_VACANCY_AGE_DAYS
        if not self.check_freshness(published_at):
            return False, {}

        # 2. Title check: must be developer/backend/python, reject sysadmins/support
        if not self.check_title(title):
            return False, {}

        # 3. Strict stop-words check: telecom hardware, Cisco, Mikrotik, Bitrix, 1C, ML, Frontend
        if not self.check_stop_words(title, key_skills, desc_html):
            return False, {}

        # 4. Location check: St. Petersburg or Remote
        soup = BeautifulSoup(desc_html, "html.parser")
        desc_text = soup.get_text(" ", strip=True)
        loc_passed, format_info = self.check_location(address, emp_text, desc_text)
        if not loc_passed:
            return False, {}

        # 5. Salary check: >= 50 000 RUB or unstated
        sal_passed, sal_from, sal_to, currency, sal_formatted = self.parse_and_check_salary(salary_raw)
        if not sal_passed:
            return False, {}

        # 6. Honest stack match: must be >= 50% (or >= 40% for explicit intern/junior)
        match_score, matched_skills = self.calculate_stack_match(title, key_skills, desc_html)
        is_intern = any(w in title.lower() for w in ["стажер", "стажёр", "intern", "junior", "младший", "trainee"])
        min_threshold = 40 if is_intern else 50

        if match_score < min_threshold:
            return False, {}

        requirements_snippet = self.extract_requirements(desc_html)

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
            "published_at": published_at
        }

        return True, enriched
