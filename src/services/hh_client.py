import asyncio
from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import httpx
from bs4 import BeautifulSoup
from src.config import settings

logger = logging.getLogger(__name__)


class HHClient:
    SEARCH_URL = "https://spb.hh.ru/search/vacancy"
    BASE_VACANCY_URL = "https://spb.hh.ru/vacancy"

    DEFAULT_HEADERS = {
        "User-Agent": settings.HH_USER_AGENT,
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
        """Fetches vacancy cards from a search page with publication timestamps."""
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
            results = []

            # 1. Primary: Extract rich JSON state from search template
            tmpl = soup.find("template", id="HH-Lux-InitialState")
            if tmpl:
                try:
                    data = json.loads(tmpl.string or tmpl.text)
                    items = data.get("vacancySearchResult", {}).get("vacancies", [])
                    for item in items:
                        vac_id = str(item.get("vacancyId", ""))
                        if not vac_id:
                            continue
                        name = item.get("name", "")
                        comp = item.get("compensation") or {}
                        sal_raw = None
                        if comp and not comp.get("noCompensation"):
                            sal_from = comp.get("from")
                            sal_to = comp.get("to")
                            cur = comp.get("currencyCode", "RUR")
                            gross = comp.get("gross", False)
                            tax_text = " (до вычета)" if gross else " (на руки)"
                            sym = {"RUR": "₽", "RUB": "₽", "USD": "$", "EUR": "€"}.get(cur, cur)
                            if sal_from and sal_to:
                                sal_raw = f"{sal_from:,} – {sal_to:,} {sym}{tax_text}".replace(",", " ")
                            elif sal_from:
                                sal_raw = f"от {sal_from:,} {sym}{tax_text}".replace(",", " ")
                            elif sal_to:
                                sal_raw = f"до {sal_to:,} {sym}{tax_text}".replace(",", " ")

                        pub = item.get("publicationTime") or {}
                        pub_iso = pub.get("$") if isinstance(pub, dict) else str(pub) if pub else None
                        pub_dt = None
                        if pub_iso:
                            try:
                                pub_dt = datetime.fromisoformat(pub_iso)
                            except Exception:
                                pass

                        company = item.get("company", {}).get("name", "Не указана") if isinstance(item.get("company"), dict) else "Не указана"
                        area_name = item.get("area", {}).get("name", "") if isinstance(item.get("area"), dict) else ""
                        formats = [f.get("name", "") for f in item.get("workFormats", []) if isinstance(f, dict)]
                        format_str = ", ".join(formats)

                        results.append({
                            "id": vac_id,
                            "title": name,
                            "url": f"https://hh.ru/vacancy/{vac_id}",
                            "company": company,
                            "card_salary": sal_raw,
                            "card_address": area_name,
                            "employment_text": format_str,
                            "published_at": pub_dt
                        })
                    if results:
                        return results
                except Exception as e:
                    logger.debug(f"JSON state search parse error: {e}")

            # 2. Fallback: Parse HTML cards
            cards = soup.find_all(attrs={"data-qa": "vacancy-serp__vacancy"})
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

                emp_el = card.find(attrs={"data-qa": re.compile(r"vacancy-serp__vacancy-employer")})
                company = emp_el.get_text(strip=True) if emp_el else "Не указана"

                sal_el = card.find(attrs={"data-qa": re.compile(r"compensation|salary")})
                card_salary = sal_el.get_text(" ", strip=True) if sal_el else None

                addr_el = card.find(attrs={"data-qa": re.compile(r"vacancy-serp__vacancy-address")})
                card_address = addr_el.get_text(" ", strip=True) if addr_el else ""

                results.append({
                    "id": vac_id,
                    "title": title,
                    "url": f"https://hh.ru/vacancy/{vac_id}",
                    "company": company,
                    "card_salary": card_salary,
                    "card_address": card_address,
                    "employment_text": "",
                    "published_at": None
                })

            return results
        except Exception as e:
            logger.error(f"Error fetching search page for '{text}': {e}")
            return []

    async def fetch_vacancy_details(self, client: httpx.AsyncClient, vac_id: str) -> Dict[str, Any]:
        """
        Fetches detailed info for a single vacancy:
        extracts clean data from HH-Lux-InitialState template (or falls back to HTML).
        """
        url = f"{self.BASE_VACANCY_URL}/{vac_id}"
        try:
            response = await client.get(url, headers=self.headers, follow_redirects=True, timeout=12.0)
            if response.status_code != 200:
                logger.warning(f"Error {response.status_code} fetching details for vacancy {vac_id}")
                return {}

            soup = BeautifulSoup(response.text, "lxml")

            # Try to read clean JSON state
            tmpl = soup.find("template", id="HH-Lux-InitialState")
            if tmpl:
                try:
                    data = json.loads(tmpl.string or tmpl.text)
                    v = data.get("vacancyView", {}).get("vacancyFull", {}).get("vacancy", {})
                    if v:
                        pub_iso = v.get("publicationTimeIso")
                        pub_dt = None
                        if pub_iso:
                            try:
                                pub_dt = datetime.fromisoformat(pub_iso)
                            except Exception:
                                pass

                        # Extract salary string
                        sal_raw = None
                        comp = v.get("compensation")
                        if comp:
                            sal_from = comp.get("from")
                            sal_to = comp.get("to")
                            cur = comp.get("currencyCode", "RUR")
                            gross = comp.get("gross", False)
                            tax_text = " (до вычета)" if gross else " (на руки)"
                            sym = {"RUR": "₽", "RUB": "₽", "USD": "$", "EUR": "€"}.get(cur, cur)
                            if sal_from and sal_to:
                                sal_raw = f"{sal_from:,} – {sal_to:,} {sym}{tax_text}".replace(",", " ")
                            elif sal_from:
                                sal_raw = f"от {sal_from:,} {sym}{tax_text}".replace(",", " ")
                            elif sal_to:
                                sal_raw = f"до {sal_to:,} {sym}{tax_text}".replace(",", " ")

                        # Work formats
                        formats = [f.get("name", "") for f in v.get("workFormats", []) if isinstance(f, dict)]
                        format_str = ", ".join(formats)

                        return {
                            "title": v.get("name", ""),
                            "company": v.get("company", {}).get("name", "") if isinstance(v.get("company"), dict) else "",
                            "salary_raw": sal_raw,
                            "description_html": v.get("description", ""),
                            "key_skills": v.get("keySkills", []),
                            "address": v.get("area", {}).get("name", "") if isinstance(v.get("area"), dict) else "",
                            "employment_text": format_str,
                            "published_at": pub_dt
                        }
                except Exception as e:
                    logger.debug(f"JSON state parse error: {e}")

            # Fallback to HTML tags
            title_el = soup.find("h1")
            title = title_el.get_text(strip=True) if title_el else ""

            emp_el = soup.find(attrs={"data-qa": re.compile(r"vacancy-company-name")})
            company = emp_el.get_text(strip=True) if emp_el else ""

            sal_el = soup.find(attrs={"data-qa": re.compile(r"vacancy-salary")})
            salary_raw = sal_el.get_text(" ", strip=True) if sal_el else None

            desc_el = soup.find(attrs={"data-qa": "vacancy-description"})
            description_html = str(desc_el) if desc_el else ""

            skills_elems = soup.find_all(attrs={"data-qa": re.compile(r"skills-element|bloko-tag")})
            key_skills = [s.get_text(strip=True) for s in skills_elems if s.get_text(strip=True)]

            addr_el = soup.find(attrs={"data-qa": re.compile(r"vacancy-view-raw-address|vacancy-address")})
            address = addr_el.get_text(" ", strip=True) if addr_el else ""

            return {
                "title": title,
                "company": company,
                "salary_raw": salary_raw,
                "description_html": description_html,
                "key_skills": key_skills,
                "address": address,
                "employment_text": "",
                "published_at": None
            }
        except Exception as e:
            logger.error(f"Error fetching vacancy details for {vac_id}: {e}")
            return {}

    async def get_all_target_vacancies(
        self,
        existing_ids: Optional[Set[str]] = None,
        max_details: int = 15
    ) -> Tuple[List[Dict[str, Any]], Set[str]]:
        """
        Fetches search results for Python positions (SPb & Remote).
        Returns:
            detailed_vacancies: List of detailed cards sorted by published_at DESC.
            all_search_ids: Set of all vacancy IDs seen across all search pages.
        """
        if existing_ids is None:
            existing_ids = set()

        search_configs = [
            # SPb (area 2)
            {"text": "python", "area": 2},
            {"text": "стажер python OR intern python", "area": 2},
            # Remote across Russia
            {"text": "python", "schedule": "remote"},
            {"text": "стажер python OR intern python", "schedule": "remote"},
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
                    cid = c["id"]
                    if cid not in raw_cards_by_id or (c.get("published_at") and not raw_cards_by_id[cid].get("published_at")):
                        raw_cards_by_id[cid] = c
                await asyncio.sleep(0.3)

            all_search_ids = set(raw_cards_by_id.keys())

            # Filter out already known IDs
            candidate_cards = [
                c for c in raw_cards_by_id.values()
                if c["id"] not in existing_ids
            ]

            def get_pub_key(c):
                dt = c.get("published_at")
                if isinstance(dt, datetime):
                    if dt.tzinfo is not None:
                        return dt.astimezone(timezone.utc).replace(tzinfo=None)
                    return dt
                return datetime.min

            # Strictly sort by real publication timestamp DESCENDING (newest first!)
            candidate_cards.sort(key=get_pub_key, reverse=True)

            logger.info(
                f"Найдено {len(raw_cards_by_id)} карточек на поиске, "
                f"новых кандидатов для детального анализа: {len(candidate_cards)}"
            )

            # Fetch details for candidate vacancies in order of newest first
            detailed_vacancies = []
            for card in candidate_cards[:max_details]:
                details = await self.fetch_vacancy_details(client, card["id"])
                if not details:
                    continue

                merged = {
                    "id": card["id"],
                    "url": card["url"],
                    "title": details.get("title") or card["title"],
                    "company": details.get("company") or card["company"],
                    "salary_raw": details.get("salary_raw") or card["card_salary"],
                    "address": details.get("address") or card["card_address"],
                    "employment_text": details.get("employment_text") or card.get("employment_text", ""),
                    "description_html": details.get("description_html", ""),
                    "key_skills": details.get("key_skills", []),
                    "published_at": details.get("published_at") or card.get("published_at")
                }
                detailed_vacancies.append(merged)
                await asyncio.sleep(0.3)

            return detailed_vacancies, all_search_ids
