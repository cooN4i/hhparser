import html
from typing import Any, Dict
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton


class NotificationService:
    def __init__(self, bot: AsyncTeleBot, chat_id: int):
        self.bot = bot
        self.chat_id = chat_id

    def format_vacancy_card(self, vacancy: Dict[str, Any]) -> str:
        title = html.escape(vacancy.get("title", "Без названия"))
        company = html.escape(vacancy.get("company", "Не указана"))
        salary = html.escape(vacancy.get("salary_formatted", "Не указана"))
        format_info = html.escape(vacancy.get("format_info", ""))
        match_score = vacancy.get("match_score", 0)
        matched_skills = vacancy.get("matched_skills", [])
        req = html.escape(vacancy.get("requirements_snippet", "").strip())

        skills_str = ", ".join(matched_skills) if matched_skills else "Python, Backend"

        if match_score >= 80:
            score_emoji = "🎯🔥"
        elif match_score >= 60:
            score_emoji = "🎯"
        else:
            score_emoji = "✨"

        card = (
            f"<b>{score_emoji} {title}</b>\n\n"
            f"🏢 <b>Компания:</b> {company}\n"
            f"💰 <b>Зарплата:</b> {salary}\n"
            f"🗺 <b>Локация/Формат:</b> {format_info}\n"
            f"📊 <b>Совпадение со стеком:</b> <code>{match_score}%</code>\n"
            f"🛠 <b>Найденный стек:</b> <i>{html.escape(skills_str)}</i>\n"
        )

        if req:
            card += f"\n📋 <b>Требования к кандидату:</b>\n{req}\n"

        return card

    async def send_vacancy_notification(self, vacancy: Dict[str, Any]) -> bool:
        """Sends formatted vacancy card with inline button to Telegram."""
        text = self.format_vacancy_card(vacancy)
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton(
                text="🔗 Открыть вакансию на hh.ru",
                url=vacancy.get("url")
            )
        )

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=markup,
                disable_web_page_preview=True
            )
            return True
        except Exception as e:
            # Fallback text
            try:
                plain_text = (
                    f"🎯 {vacancy.get('title')}\n"
                    f"🏢 {vacancy.get('company')}\n"
                    f"💰 {vacancy.get('salary_formatted')}\n"
                    f"📍 {vacancy.get('format_info')}\n\n"
                    f"Ссылка: {vacancy.get('url')}"
                )
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=plain_text,
                    disable_web_page_preview=True
                )
                return True
            except Exception:
                return False
