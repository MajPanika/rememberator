"""
Парсер времени для бота-напоминалки
Поддержка русского и английского языков
"""

import re
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any
import dateparser
import pytz
from dateparser.search import search_dates
import logging

logger = logging.getLogger(__name__)

class TimeParser:
    def __init__(self):
        # Кэш для ускорения работы
        self._cache = {}
        
        # Регулярные выражения для русского языка (ИСПРАВЛЕННЫЕ)
        self.ru_patterns = {
            # Относительное время
            'relative_hours': r'через\s+(\d+)\s+(час|часа|часов)(?:\s+(\d+)\s+(минут|минуты|минуту))?',
            'relative_minutes': r'через\s+(\d+)\s+(минут|минуты|минуту)',
            'relative_days': r'через\s+(\d+)\s+(день|дня|дней)',
            'relative_weeks': r'через\s+(\d+)\s+(недел[юя]|недели|недель)',
            
            # Абсолютное время
            'today_time': r'сегодня(?:\s+в)?\s+(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            'tomorrow_time': r'завтра(?:\s+в)?\s+(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            'day_after_tomorrow': r'послезавтра(?:\s+в)?\s+(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            
            # Дни недели
            'weekday_time': r'(понедельник|вторник|сред[ау]|четверг|пятниц[ау]|суббот[ау]|воскресенье)(?:\s+в)?\s+(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            
            # Даты
            'date_dmy': r'(\d{1,2})[\.\/](\d{1,2})(?:[\.\/](\d{2,4}))?(?:\s+в)?\s+(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            'date_dmy_words': r'(\d{1,2})\s+(январ[яю]|феврал[яю]|март[ау]|апрел[яю]|ма[яю]|июн[яю]|июл[яю]|август[ау]|сентябр[яю]|октябр[яю]|ноябр[яю]|декабр[яю])(?:\s+(\d{4}))?(?:\s+в)?\s+(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            
            # Просто время
            'time_only': r'^(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?$',
            
            # Простое время с предлогом (ДОБАВЛЕНО)
            'simple_time_ru': r'^в\s+(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?$',
        }
        
        # Регулярные выражения для английского языка (ИСПРАВЛЕННЫЕ)
        self.en_patterns = {
            # Relative time
            'relative_hours': r'in\s+(\d+)\s+(hour|hours)(?:\s+and\s+(\d+)\s+(minute|minutes))?',
            'relative_minutes': r'in\s+(\d+)\s+(minute|minutes)',
            'relative_days': r'in\s+(\d+)\s+(day|days)',
            'relative_weeks': r'in\s+(\d+)\s+(week|weeks)',
            
            # Absolute time
            'today_time': r'today(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?',
            'tomorrow_time': r'tomorrow(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?',
            'day_after_tomorrow': r'day\s+after\s+tomorrow(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?',
            
            # Weekdays
            'weekday_time': r'(monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?',
            'next_weekday': r'next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?',
            
            # Dates
            'date_mdy': r'(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?',
            'date_mdy_words': r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?',
            
            # Time only
            'time_only': r'^(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?$',
            
            # Simple time with "at" (ДОБАВЛЕНО)
            'simple_time_en': r'^at\s+(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?$',
            'simple_time_no_at': r'^(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?$',
        }
        
        # Словари для конвертации
        self.ru_months = {
            'января': 1, 'январю': 1,
            'февраля': 2, 'февралю': 2,
            'марта': 3, 'марту': 3,
            'апреля': 4, 'апрелю': 4,
            'мая': 5, 'маю': 5,
            'июня': 6, 'июню': 6,
            'июля': 7, 'июлю': 7,
            'августа': 8, 'августу': 8,
            'сентября': 9, 'сентябрю': 9,
            'октября': 10, 'октябрю': 10,
            'ноября': 11, 'ноябрю': 11,
            'декабря': 12, 'декабрю': 12
        }
        
        self.en_months = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4,
            'may': 5, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12
        }
        
        self.ru_weekdays = {
            'понедельник': 0, 'вторник': 1, 'среду': 2, 'среда': 2,
            'четверг': 3, 'пятницу': 4, 'пятница': 4,
            'субботу': 5, 'суббота': 5, 'воскресенье': 6
        }
        
        self.en_weekdays = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2,
            'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6
        }
        
        self.ru_time_of_day = {
            'утра': 'am',
            'дня': 'pm',
            'вечера': 'pm',
            'ночи': 'am'
        }
    
    def parse(self, time_str: str, language: str = 'ru', 
              timezone: str = 'Europe/Moscow',
              base_time: datetime = None) -> Tuple[Optional[datetime], str, Dict[str, Any]]:
        """
        Парсинг строки времени
        
        Возвращает:
        - datetime: распарсенное время (или None если не удалось)
        - str: тип распознанного времени (для отладки)
        - dict: дополнительная информация (повторения и т.д.)
        """
        if not time_str or not time_str.strip():
            return None, "empty", {}
        
        time_str = time_str.strip().lower()
        
        # Проверяем кэш
        cache_key = f"{time_str}_{language}_{timezone}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        if base_time is None:
            base_time = datetime.now(pytz.timezone(timezone))
        
        # Пробуем разные методы парсинга
        result = None
        parse_type = "unknown"
        extra_info = {}
        
        # 1. Пробуем dateparser (основной метод)
        result, parse_type = self._try_dateparser(time_str, language, timezone, base_time)
        
        # 2. Если dateparser не сработал, пробуем наши регулярки
        if result is None:
            if language == 'ru':
                result, parse_type, extra_info = self._parse_ru(time_str, base_time, timezone)
            else:
                result, parse_type, extra_info = self._parse_en(time_str, base_time, timezone)
        
        # 3. Проверяем, что время в будущем
        if result and result <= base_time:
            # Если время сегодня уже прошло, переносим на завтра
            if result.date() == base_time.date():
                result += timedelta(days=1)
                extra_info['adjusted'] = 'tomorrow'
        
        # 4. Проверяем, что дата не слишком далеко в будущем (максимум 5 лет)
        if result:
            max_future = base_time + timedelta(days=5*365)
            if result > max_future:
                logger.warning(f"Date too far in future: {result}")
                return None, "too_far", {}
        
        # Сохраняем в кэш
        self._cache[cache_key] = (result, parse_type, extra_info)
        
        return result, parse_type, extra_info
    
    def _try_dateparser(self, time_str: str, language: str, 
                       timezone: str, base_time: datetime) -> Tuple[Optional[datetime], str]:
        """Попытка парсинга с помощью dateparser"""
        try:
            settings = {
                'TIMEZONE': timezone,
                'RETURN_AS_TIMEZONE_AWARE': True,
                'LANGUAGES': [language],
                'RELATIVE_BASE': base_time,
                'PREFER_DATES_FROM': 'future'
            }
            
            # Пробуем стандартный парсинг
            parsed = dateparser.parse(time_str, settings=settings)
            if parsed:
                return parsed, "dateparser"
            
            # Пробуем поиск дат в тексте
            dates = search_dates(time_str, languages=[language], settings=settings)
            if dates:
                # Берем первую найденную дату
                return dates[0][1], "dateparser_search"
                
        except Exception as e:
            logger.debug(f"Dateparser failed for '{time_str}': {e}")
        
        return None, "dateparser_failed"
    
    def _parse_ru(self, time_str: str, base_time: datetime, timezone: str) -> Tuple[Optional[datetime], str, Dict]:
        """Парсинг для русского языка с использованием регулярных выражений"""
        user_tz = pytz.timezone(timezone)
        
        # 1. Относительное время: "через X часов Y минут"
        match = re.search(self.ru_patterns['relative_hours'], time_str)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(3)) if match.group(3) else 0
            result = base_time + timedelta(hours=hours, minutes=minutes)
            return result, "relative_hours", {}
        
        # 2. Относительное время: "через X минут"
        match = re.search(self.ru_patterns['relative_minutes'], time_str)
        if match:
            minutes = int(match.group(1))
            result = base_time + timedelta(minutes=minutes)
            return result, "relative_minutes", {}
        
        # 3. Относительное время: "через X дней"
        match = re.search(self.ru_patterns['relative_days'], time_str)
        if match:
            days = int(match.group(1))
            result = base_time + timedelta(days=days)
            return result, "relative_days", {}
        
        # 4. "сегодня ХХ:ХХ"
        match = re.search(self.ru_patterns['today_time'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            time_of_day = match.group(3)
            
            hour = self._adjust_hour_ru(hour, time_of_day)
            result = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result, "today", {}
        
        # 5. "завтра ХХ:ХХ"
        match = re.search(self.ru_patterns['tomorrow_time'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            time_of_day = match.group(3)
            
            hour = self._adjust_hour_ru(hour, time_of_day)
            result = base_time + timedelta(days=1)
            result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result, "tomorrow", {}
        
        # 6. "послезавтра ХХ:ХХ" (ИСПРАВЛЕНО)
        match = re.search(self.ru_patterns['day_after_tomorrow'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            time_of_day = match.group(3)
            
            hour = self._adjust_hour_ru(hour, time_of_day)
            result = base_time + timedelta(days=2)
            result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result, "day_after_tomorrow", {}
        
        # 7. День недели: "понедельник ХХ:ХХ"
        match = re.search(self.ru_patterns['weekday_time'], time_str)
        if match:
            weekday_ru = match.group(1)
            hour = int(match.group(2))
            minute = int(match.group(3)) if match.group(3) else 0
            time_of_day = match.group(4)
            
            weekday_num = self.ru_weekdays.get(weekday_ru)
            if weekday_num is not None:
                hour = self._adjust_hour_ru(hour, time_of_day)
                result = self._get_next_weekday(base_time, weekday_num)
                result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)
                return result, "weekday", {}
        
        # 8. Дата: "ДД.ММ.ГГГГ ХХ:ХХ"
        match = re.search(self.ru_patterns['date_dmy'], time_str)
        if match:
            day = int(match.group(1))
            month = int(match.group(2))
            year = int(match.group(3)) if match.group(3) else base_time.year
            hour = int(match.group(4))
            minute = int(match.group(5)) if match.group(5) else 0
            time_of_day = match.group(6)
            
            # Корректируем год если указан коротко
            if year < 100:
                year += 2000
            
            hour = self._adjust_hour_ru(hour, time_of_day)
            
            try:
                result = datetime(year, month, day, hour, minute, tzinfo=user_tz)
                return result, "date_dmy", {}
            except ValueError as e:
                logger.debug(f"Invalid date: {e}")
        
        # 9. Дата словами: "15 января ХХ:ХХ"
        match = re.search(self.ru_patterns['date_dmy_words'], time_str)
        if match:
            day = int(match.group(1))
            month_ru = match.group(2)
            year = int(match.group(3)) if match.group(3) else base_time.year
            hour = int(match.group(4))
            minute = int(match.group(5)) if match.group(5) else 0
            time_of_day = match.group(6)
            
            month = self.ru_months.get(month_ru)
            if month:
                hour = self._adjust_hour_ru(hour, time_of_day)
                
                try:
                    result = datetime(year, month, day, hour, minute, tzinfo=user_tz)
                    return result, "date_dmy_words", {}
                except ValueError as e:
                    logger.debug(f"Invalid date: {e}")
        
        # 10. Только время: "ХХ:ХХ"
        match = re.search(self.ru_patterns['time_only'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            time_of_day = match.group(3)
            
            hour = self._adjust_hour_ru(hour, time_of_day)
            
            # Проверяем, если это время сегодня еще не наступило
            result = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if result > base_time:
                return result, "time_only_today", {}
            else:
                # Иначе переносим на завтра
                result += timedelta(days=1)
                return result, "time_only_tomorrow", {'adjusted': True}
        
        # 11. Простое время с предлогом: "в 8 утра" (ДОБАВЛЕНО)
        match = re.search(self.ru_patterns['simple_time_ru'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            time_of_day = match.group(3)
            
            hour = self._adjust_hour_ru(hour, time_of_day)
            
            # Проверяем, если это время сегодня еще не наступило
            result = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if result > base_time:
                return result, "simple_time_today", {}
            else:
                # Иначе переносим на завтра
                result += timedelta(days=1)
                return result, "simple_time_tomorrow", {'adjusted': True}
        
        return None, "not_parsed", {}
    
    def _parse_en(self, time_str: str, base_time: datetime, timezone: str) -> Tuple[Optional[datetime], str, Dict]:
        """Парсинг для английского языка с использованием регулярных выражений"""
        user_tz = pytz.timezone(timezone)
        
        # 1. Relative time: "in X hours and Y minutes"
        match = re.search(self.en_patterns['relative_hours'], time_str)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(3)) if match.group(3) else 0
            result = base_time + timedelta(hours=hours, minutes=minutes)
            return result, "relative_hours", {}
        
        # 2. Relative time: "in X minutes"
        match = re.search(self.en_patterns['relative_minutes'], time_str)
        if match:
            minutes = int(match.group(1))
            result = base_time + timedelta(minutes=minutes)
            return result, "relative_minutes", {}
        
        # 3. "today at XX:XX AM/PM"
        match = re.search(self.en_patterns['today_time'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            am_pm = match.group(3)
            
            hour = self._adjust_hour_en(hour, am_pm)
            result = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result, "today", {}
        
        # 4. "tomorrow at XX:XX AM/PM"
        match = re.search(self.en_patterns['tomorrow_time'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            am_pm = match.group(3)
            
            hour = self._adjust_hour_en(hour, am_pm)
            result = base_time + timedelta(days=1)
            result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result, "tomorrow", {}
        
        # 5. "day after tomorrow at XX:XX AM/PM"
        match = re.search(self.en_patterns['day_after_tomorrow'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            am_pm = match.group(3)
            
            hour = self._adjust_hour_en(hour, am_pm)
            result = base_time + timedelta(days=2)
            result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result, "day_after_tomorrow", {}
        
        # 6. Weekday: "monday at XX:XX AM/PM"
        match = re.search(self.en_patterns['weekday_time'], time_str)
        if match:
            weekday_en = match.group(1)
            hour = int(match.group(2))
            minute = int(match.group(3)) if match.group(3) else 0
            am_pm = match.group(4)
            
            weekday_num = self.en_weekdays.get(weekday_en)
            if weekday_num is not None:
                hour = self._adjust_hour_en(hour, am_pm)
                result = self._get_next_weekday(base_time, weekday_num)
                result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)
                return result, "weekday", {}
        
        # 7. "next monday at XX:XX AM/PM"
        match = re.search(self.en_patterns['next_weekday'], time_str)
        if match:
            weekday_en = match.group(1)
            hour = int(match.group(2))
            minute = int(match.group(3)) if match.group(3) else 0
            am_pm = match.group(4)
            
            weekday_num = self.en_weekdays.get(weekday_en)
            if weekday_num is not None:
                hour = self._adjust_hour_en(hour, am_pm)
                result = self._get_next_weekday(base_time, weekday_num)
                # "next monday" значит не сегодняшний понедельник, а следующий
                if result.weekday() == base_time.weekday() and result.date() == base_time.date():
                    result += timedelta(days=7)
                result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)
                return result, "next_weekday", {}
        
        # 8. Date: "MM/DD/YYYY at XX:XX AM/PM"
        match = re.search(self.en_patterns['date_mdy'], time_str)
        if match:
            month = int(match.group(1))
            day = int(match.group(2))
            year = int(match.group(3)) if match.group(3) else base_time.year
            hour = int(match.group(4))
            minute = int(match.group(5)) if match.group(5) else 0
            am_pm = match.group(6)
            
            # Adjust year if short
            if year < 100:
                year += 2000
            
            hour = self._adjust_hour_en(hour, am_pm)
            
            try:
                result = datetime(year, month, day, hour, minute, tzinfo=user_tz)
                return result, "date_mdy", {}
            except ValueError as e:
                logger.debug(f"Invalid date: {e}")
        
        # 9. Date words: "January 15 at XX:XX AM/PM"
        match = re.search(self.en_patterns['date_mdy_words'], time_str)
        if match:
            month_en = match.group(1)
            day = int(match.group(2))
            year = int(match.group(3)) if match.group(3) else base_time.year
            hour = int(match.group(4))
            minute = int(match.group(5)) if match.group(5) else 0
            am_pm = match.group(6)
            
            month = self.en_months.get(month_en)
            if month:
                hour = self._adjust_hour_en(hour, am_pm)
                
                try:
                    result = datetime(year, month, day, hour, minute, tzinfo=user_tz)
                    return result, "date_mdy_words", {}
                except ValueError as e:
                    logger.debug(f"Invalid date: {e}")
        
        # 10. Time only: "XX:XX AM/PM"
        match = re.search(self.en_patterns['time_only'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            am_pm = match.group(3)
            
            hour = self._adjust_hour_en(hour, am_pm)
            
            # Check if this time is still today
            result = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if result > base_time:
                return result, "time_only_today", {}
            else:
                # Otherwise move to tomorrow
                result += timedelta(days=1)
                return result, "time_only_tomorrow", {'adjusted': True}
        
        # 11. Simple time with "at": "at 8 AM" (ДОБАВЛЕНО)
        match = re.search(self.en_patterns['simple_time_en'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            am_pm = match.group(3)
            
            hour = self._adjust_hour_en(hour, am_pm)
            
            # Check if this time is still today
            result = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if result > base_time:
                return result, "simple_time_today", {}
            else:
                # Otherwise move to tomorrow
                result += timedelta(days=1)
                return result, "simple_time_tomorrow", {'adjusted': True}
        
        # 12. Simple time without "at": "8:00 PM" (ДОБАВЛЕНО)
        match = re.search(self.en_patterns['simple_time_no_at'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            am_pm = match.group(3)
            
            hour = self._adjust_hour_en(hour, am_pm)
            
            # Check if this time is still today
            result = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if result > base_time:
                return result, "time_only_today", {}
            else:
                # Otherwise move to tomorrow
                result += timedelta(days=1)
                return result, "time_only_tomorrow", {'adjusted': True}
        
        return None, "not_parsed", {}
    
    def _adjust_hour_ru(self, hour: int, time_of_day: str) -> int:
        """Корректировка часа для русского языка"""
        if time_of_day:
            time_of_day = time_of_day.lower()
            if time_of_day in ['дня', 'вечера']:
                if hour < 12:
                    return hour + 12
            elif time_of_day == 'ночи' and hour == 12:
                return 0  # 12 ночи = 0:00
        return hour
    
    def _adjust_hour_en(self, hour: int, am_pm: str) -> int:
        """Корректировка часа для английского языка (12-часовой формат)"""
        if am_pm:
            am_pm = am_pm.upper()
            if am_pm == 'AM':
                if hour == 12:
                    return 0  # 12 AM = 0:00
                return hour
            elif am_pm == 'PM':
                if hour == 12:
                    return 12  # 12 PM = 12:00
                return hour + 12
        
        # Если AM/PM не указано, но час < 12, предполагаем AM
        # Если час >= 12, оставляем как есть (уже в 24-часовом формате)
        if hour <= 12:
            return hour  # Предполагаем AM или уже правильный формат
        
        return hour
    
    def _get_next_weekday(self, base_time: datetime, weekday: int) -> datetime:
        """Получить следующий день недели"""
        days_ahead = weekday - base_time.weekday()
        if days_ahead <= 0:  # Если день уже прошел на этой неделе
            days_ahead += 7
        return base_time + timedelta(days=days_ahead)
    
    # Остальные методы остаются без изменений...
    # (detect_repeat_pattern, extract_reminder_text, validate_time, get_examples, clear_cache)
    
    def detect_repeat_pattern(self, time_str: str, language: str = 'ru') -> Dict[str, Any]:
        """Обнаружить паттерны повторения в строке"""
        # Реализация без изменений...
        pass
    
    def extract_reminder_text(self, full_text: str, language: str = 'ru') -> Tuple[str, str]:
        """Извлечь текст напоминания и время из полной строки"""
        # Реализация без изменений...
        pass
    
    def validate_time(self, parsed_time: datetime, base_time: datetime = None) -> Tuple[bool, str]:
        """Проверить корректность распарсенного времени"""
        # Реализация без изменений...
        pass
    
    def get_examples(self, language: str = 'ru') -> list:
        """Получить примеры форматов времени"""
        # Реализация без изменений...
        pass
    
    def clear_cache(self):
        """Очистить кэш парсера"""
        self._cache.clear()
