import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Set
import httpx
from bs4 import BeautifulSoup
from src.config import settings

logger = logging.getLogger(__name__)


class HHClient:
    SEARCH_URL = "https://spb.hh.ru/search/vacancy"
    BASE_VACANCY_URL = "https://spb.hh.ru/vacancy"

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
        "Upgrade-Insecure-Requests": "1"
    }

    def __init__(self):
        self.headers = self.DEFAULT_HEADERS.copy()

    async def fetch_search_page(
        self,
        client: httpx.AsyncClient,
        text: str,
        area: Optional[int] = None,
        schedule: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetches vacancy cards from a single search page.
        """
        params = [
            ("text", text),
            ("order_by", "publication_time"),
            ("experience", "noExperience"),
            ("experience", "between1And3"),
        ]
        if area:
            params.append(("area", str(area)))
        if schedule:
            params.append(("schedule", schedule))

        try:
            response = await client.get(
                self.SEARCH_URL,
                params=params,
                headers=self.headers,
                follow_redirects=True,
                timeout=15.0
            )
            if response.status_code != 200:
                logger.warning(f"HH search returned status {response.status_code} for query '{text}'")
                return []

            soup = BeautifulSoup(response.text, "lxml")
            cards = soup.find_all(attrs={"data-qa": "vacancy-serp__vacancy"})
            results = []

            for card in cards:
                title_el = card.find("a", attrs={"data-qa": re.compile(r"serp-item__title")})
                if not title_el:
                    continue

                href = title_el.get("href", "")
                id_match = re.search(r"/vacancy/(\d+)", href)
                if not id_match:
                    continue

                vac_id = id_match.group(1)
                title = title_el.get_text(strip=True)

                # Company
                emp_el = card.find(attrs={"data-qa": re.compile(r"vacancy-serp__vacancy-employer")})
                company = emp_el.get_text(strip=True) if emp_el else "Не указана"

                # Card salary / compensation
                sal_el = card.find(attrs={"data-qa": re.compile(r"compensation|salary")})
                card_salary = sal_el.get_text(" ", strip=True) if sal_el else None

                # Address
                addr_el = card.find(attrs={"data-qa": re.compile(r"vacancy-serp__vacancy-address")})
                card_address = addr_el.get_text(" ", strip=True) if addr_el else ""

                results.append({
                    "id": vac_id,
                    "title": title,
                    "url": f"https://hh.ru/vacancy/{vac_id}",
                    "company": company,
                    "card_salary": card_salary,
                    "card_address": card_address
                })

            return results
        except Exception as e:
            logger.error(f"Error fetching search page for '{text}': {e}")
            return []

    async def fetch_vacancy_details(self, client: httpx.AsyncClient, vac_id: str) -> Dict[str, Any]:
        """
        Fetches complete details for a single vacancy page:
        description, key skills tags, exact salary, schedule/format.
        """
        url = f"{self.BASE_VACANCY_URL}/{vac_id}"
        try:
            response = await client.get(url, headers=self.headers, follow_redirects=True, timeout=12.0)
            if response.status_code != 200:
                logger.warning(f"Error {response.status_code} fetching details for vacancy {vac_id}")
                return {}

            soup = BeautifulSoup(response.text, "lxml")

            # Title
            title_el = soup.find("h1")
            title = title_el.get_text(strip=True) if title_el else ""

            # Company
            emp_el = soup.find(attrs={"data-qa": re.compile(r"vacancy-company-name")})
            company = emp_el.get_text(strip=True) if emp_el else ""

            # Salary
            sal_el = soup.find(attrs={"data-qa": re.compile(r"vacancy-salary")})
            salary_raw = sal_el.get_text(" ", strip=True) if sal_el else None

            # Description
            desc_el = soup.find(attrs={"data-qa": "vacancy-description"})
            description = desc_el.get_text("\n", strip=True) if desc_el else ""

            # Skills
            skills_elems = soup.find_all(attrs={"data-qa": re.compile(r"skills-element|bloko-tag")})
            key_skills = [s.get_text(strip=True) for s in skills_elems if s.get_text(strip=True)]

            # Location / Address / Metro
            addr_el = soup.find(attrs={"data-qa": re.compile(r"vacancy-view-raw-address|vacancy-address")})
            address = addr_el.get_text(" ", strip=True) if addr_el else ""

            # Employment / Schedule text
            emp_mode_el = soup.find(attrs={"data-qa": re.compile(r"common-employment-text|work-schedule")})
            employment_text = emp_mode_el.get_text(" ", strip=True) if emp_mode_el else ""

            return {
                "title": title,
                "company": company,
                "salary_raw": salary_raw,
                "description": description,
                "key_skills": key_skills,
                "address": address,
                "employment_text": employment_text
            }
        except Exception as e:
            logger.error(f"Error fetching vacancy details for {vac_id}: {e}")
            return {}

    async def get_all_target_vacancies(self, existing_ids: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
        """
        Fetches search results for both SPb and Remote.
        For newly discovered vacancies, fetches full details.
        """
        if existing_ids is None:
            existing_ids = set()

        search_configs = [
            # SPb (area 2)
            {"text": "python backend", "area": 2},
            {"text": "python разработчик", "area": 2},
            {"text": "fastapi OR sqlalchemy", "area": 2},
            {"text": "junior devops python OR сисадмин python", "area": 2},
            # Remote across Russia
            {"text": "python backend", "schedule": "remote"},
            {"text": "python разработчик", "schedule": "remote"},
            {"text": "fastapi OR sqlalchemy", "schedule": "remote"},
        ]

        raw_cards_by_id: Dict[str, Dict[str, Any]] = {}

        async with httpx.AsyncClient(headers=self.headers, follow_redirects=True, timeout=15.0) as client:
            for conf in search_configs:
                cards = await self.fetch_search_page(
                    client,
                    text=conf["text"],
                    area=conf.get("area"),
                    schedule=conf.get("schedule")
                )
                for c in cards:
                    raw_cards_by_id[c["id"]] = c
                # Small delay between search requests to be polite
                await asyncio.sleep(0.3)

            # Filter out already seen IDs before fetching full details
            candidate_cards = [
                c for c in raw_cards_by_id.values()
                if c["id"] not in existing_ids
            ]

            logger.info(f"Найдено {len(raw_cards_by_id)} карточек на поиске, новых кандидатов для детального анализа: {len(candidate_cards)}")

            # Fetch details for candidate vacancies (limit to max 30 per check to prevent timeouts)
            detailed_vacancies = []
            for card in candidate_cards[:30]:
                details = await self.fetch_vacancy_details(client, card["id"])
                # Merge card info with detail info
                merged = {
                    "id": card["id"],
                    "url": card["url"],
                    "title": details.get("title") or card["title"],
                    "company": details.get("company") or card["company"],
                    "salary_raw": details.get("salary_raw") or card["card_salary"],
                    "address": details.get("address") or card["card_address"],
                    "employment_text": details.get("employment_text", ""),
                    "description": details.get("description", ""),
                    "key_skills": details.get("key_skills", [])
                }
                detailed_vacancies.append(merged)
                await asyncio.sleep(0.3)

            return detailed_vacancies
