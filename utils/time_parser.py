"""
ФИНАЛЬНЫЙ исправленный парсер времени для бота-напоминалки
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
        self._cache = {}
        
        # Регулярные выражения для русского языка (ФИНАЛЬНЫЕ)
        self.ru_patterns = {
            'relative_hours': r'через\s+(\d+)\s+(час|часа|часов)(?:\s+(\d+)\s+(минут|минуты|минуту))?',
            'relative_minutes': r'через\s+(\d+)\s+(минут|минуты|минуту)',
            'relative_days': r'через\s+(\d+)\s+(день|дня|дней)',
            
            # ВАЖНО: day_after_tomorrow ДО tomorrow
            'day_after_tomorrow': r'послезавтра(?:\s+(?:в\s+)?)?(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            'tomorrow_time': r'завтра(?:\s+(?:в\s+)?)?(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            'today_time': r'сегодня(?:\s+(?:в\s+)?)?(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            
            'weekday_time': r'(понедельник|вторник|сред[ау]|четверг|пятниц[ау]|суббот[ау]|воскресенье)(?:\s+(?:в\s+)?)?(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            
            'date_dmy': r'(\d{1,2})[\.\/](\d{1,2})(?:[\.\/](\d{2,4}))?(?:\s+(?:в\s+)?)?(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            'date_dmy_words': r'(\d{1,2})\s+(январ[яю]|феврал[яю]|март[ау]|апрел[яю]|ма[яю]|июн[яю]|июл[яю]|август[ау]|сентябр[яю]|октябр[яю]|ноябр[яю]|декабр[яю])(?:\s+(\d{4}))?(?:\s+(?:в\s+)?)?(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            
            'simple_time_ru': r'^в\s+(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?$',
            # ВАЖНО: time_no_prep ДО time_only
            'time_no_prep': r'^(\d{1,2})\s+(утра|вечера|ночи|дня)$',
            'time_only': r'^(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?$',
        }
        
        # Регулярные выражения для английского языка (ФИНАЛЬНЫЕ)
        self.en_patterns = {
            'relative_hours': r'in\s+(\d+)\s+(hour|hours)(?:\s+and\s+(\d+)\s+(minute|minutes))?',
            'relative_minutes': r'in\s+(\d+)\s+(minute|minutes)',
            'relative_days': r'in\s+(\d+)\s+(day|days)',
            
            # ВАЖНО: day_after_tomorrow ДО tomorrow
            'day_after_tomorrow': r'day\s+after\s+tomorrow(?:\s+(?:at\s+)?)?(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?',
            'tomorrow_time': r'tomorrow(?:\s+(?:at\s+)?)?(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?',
            'today_time': r'today(?:\s+(?:at\s+)?)?(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?',
            
            'weekday_time': r'(monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+(?:at\s+)?)?(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?',
            
            'date_mdy': r'(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?(?:\s+(?:at\s+)?)?(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?',
            'date_mdy_words': r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?(?:\s+(?:at\s+)?)?(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?',
            
            'simple_time_en': r'^at\s+(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?$',
            # ВАЖНО: time_ampm ДО time_only
            'time_ampm': r'^(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)$',
            'time_only': r'^(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?$',
        }
        
        # Словари (без изменений)
        self.ru_months = {
            'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5,
            'июня': 6, 'июля': 7, 'августа': 8, 'сентября': 9,
            'октября': 10, 'ноября': 11, 'декабря': 12
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
    
    def parse(self, time_str: str, language: str = 'ru', 
              timezone: str = 'Europe/Moscow',
              base_time: datetime = None) -> Tuple[Optional[datetime], str, Dict[str, Any]]:
        """Парсинг строки времени"""
        if not time_str or not time_str.strip():
            return None, "empty", {}
        
        time_str = time_str.strip().lower()
        
        cache_key = f"{time_str}_{language}_{timezone}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        if base_time is None:
            base_time = datetime.now(pytz.timezone(timezone))
        
        result = None
        parse_type = "unknown"
        extra_info = {}
        
        # 1. Пробуем dateparser
        result, parse_type = self._try_dateparser(time_str, language, timezone, base_time)
        
        # 2. Если dateparser не сработал, пробуем наши регулярки
        if result is None:
            if language == 'ru':
                result, parse_type, extra_info = self._parse_ru_fixed(time_str, base_time, timezone)
            else:
                result, parse_type, extra_info = self._parse_en_fixed(time_str, base_time, timezone)
        
        # 3. Проверяем, что время в будущем
        if result and result <= base_time:
            if result.date() == base_time.date():
                result += timedelta(days=1)
                extra_info['adjusted'] = 'tomorrow'
        
        # 4. Проверяем, что дата не слишком далеко в будущем
        if result:
            max_future = base_time + timedelta(days=5*365)
            if result > max_future:
                logger.warning(f"Date too far in future: {result}")
                return None, "too_far", {}

        # 5. ✅ ВАЖНО: Обнуляем микросекунды и секунды для всех результатов
        if result:
            result = result.replace(microsecond=0, second=0)
        
        self._cache[cache_key] = (result, parse_type, extra_info)
        return result, parse_type, extra_info
    
    def _parse_ru_fixed(self, time_str: str, base_time: datetime, timezone: str) -> Tuple[Optional[datetime], str, Dict]:
        """Исправленный парсинг для русского языка с правильным порядком"""
        user_tz = pytz.timezone(timezone)
        
        # 1. Относительное время
        match = re.search(self.ru_patterns['relative_hours'], time_str)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(3)) if match.group(3) else 0
            result = base_time + timedelta(hours=hours, minutes=minutes)
            return result, "relative_hours", {}
        
        match = re.search(self.ru_patterns['relative_minutes'], time_str)
        if match:
            minutes = int(match.group(1))
            result = base_time + timedelta(minutes=minutes)
            return result, "relative_minutes", {}
        
        match = re.search(self.ru_patterns['relative_days'], time_str)
        if match:
            days = int(match.group(1))
            result = base_time + timedelta(days=days)
            return result, "relative_days", {}
        
        # 2. "послезавтра" - ПЕРВЫМ!
        match = re.search(self.ru_patterns['day_after_tomorrow'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            time_of_day = match.group(3)
            
            hour = self._adjust_hour_ru(hour, time_of_day)
            result = base_time + timedelta(days=2)
            result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result, "day_after_tomorrow", {}
        
        # 3. "завтра"
        match = re.search(self.ru_patterns['tomorrow_time'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            time_of_day = match.group(3)
            
            hour = self._adjust_hour_ru(hour, time_of_day)
            result = base_time + timedelta(days=1)
            result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result, "tomorrow", {}
        
        # 4. "сегодня"
        match = re.search(self.ru_patterns['today_time'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            time_of_day = match.group(3)
            
            hour = self._adjust_hour_ru(hour, time_of_day)
            result = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result, "today", {}
        
        # 5. Дни недели
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
        
        # 6. Простое время с предлогом
        match = re.search(self.ru_patterns['simple_time_ru'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            time_of_day = match.group(3)
            
            hour = self._adjust_hour_ru(hour, time_of_day)
            
            result = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if result > base_time:
                return result, "simple_time_today", {}
            else:
                result += timedelta(days=1)
                return result, "simple_time_tomorrow", {'adjusted': True}
        
        # 7. Время без предлога: "8 утра" - ДО time_only
        match = re.search(self.ru_patterns['time_no_prep'], time_str)
        if match:
            hour = int(match.group(1))
            time_of_day = match.group(2)
            
            hour = self._adjust_hour_ru(hour, time_of_day)
            
            result = base_time.replace(hour=hour, minute=0, second=0, microsecond=0)
            if result > base_time:
                return result, "time_no_prep_today", {}
            else:
                result += timedelta(days=1)
                return result, "time_no_prep_tomorrow", {'adjusted': True}
        
        # 8. Только время
        match = re.search(self.ru_patterns['time_only'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            time_of_day = match.group(3)
            
            hour = self._adjust_hour_ru(hour, time_of_day)
            
            result = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if result > base_time:
                return result, "time_only_today", {}
            else:
                result += timedelta(days=1)
                return result, "time_only_tomorrow", {'adjusted': True}
        
        # 9. Даты (остаются в конце)
        match = re.search(self.ru_patterns['date_dmy'], time_str)
        if match:
            day = int(match.group(1))
            month = int(match.group(2))
            year = int(match.group(3)) if match.group(3) else base_time.year
            hour = int(match.group(4))
            minute = int(match.group(5)) if match.group(5) else 0
            time_of_day = match.group(6)
            
            if year < 100:
                year += 2000
            
            hour = self._adjust_hour_ru(hour, time_of_day)
            
            try:
                result = datetime(year, month, day, hour, minute, tzinfo=user_tz)
                return result, "date_dmy", {}
            except ValueError:
                pass
        
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
                except ValueError:
                    pass
        
        return None, "not_parsed", {}
    
    def _parse_en_fixed(self, time_str: str, base_time: datetime, timezone: str) -> Tuple[Optional[datetime], str, Dict]:
        """Исправленный парсинг для английского языка с правильным порядком"""
        user_tz = pytz.timezone(timezone)
        
        # 1. Relative time
        match = re.search(self.en_patterns['relative_hours'], time_str)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(3)) if match.group(3) else 0
            result = base_time + timedelta(hours=hours, minutes=minutes)
            return result, "relative_hours", {}
        
        match = re.search(self.en_patterns['relative_minutes'], time_str)
        if match:
            minutes = int(match.group(1))
            result = base_time + timedelta(minutes=minutes)
            return result, "relative_minutes", {}
        
        match = re.search(self.en_patterns['relative_days'], time_str)
        if match:
            days = int(match.group(1))
            result = base_time + timedelta(days=days)
            return result, "relative_days", {}
        
        # 2. "day after tomorrow" - ПЕРВЫМ!
        match = re.search(self.en_patterns['day_after_tomorrow'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            am_pm = match.group(3)
            
            hour = self._adjust_hour_en(hour, am_pm)
            result = base_time + timedelta(days=2)
            result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result, "day_after_tomorrow", {}
        
        # 3. "tomorrow"
        match = re.search(self.en_patterns['tomorrow_time'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            am_pm = match.group(3)
            
            hour = self._adjust_hour_en(hour, am_pm)
            result = base_time + timedelta(days=1)
            result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result, "tomorrow", {}
        
        # 4. "today"
        match = re.search(self.en_patterns['today_time'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            am_pm = match.group(3)
            
            hour = self._adjust_hour_en(hour, am_pm)
            result = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result, "today", {}
        
        # 5. Weekdays
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
        
        # 6. Simple time with "at"
        match = re.search(self.en_patterns['simple_time_en'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            am_pm = match.group(3)
            
            hour = self._adjust_hour_en(hour, am_pm)
            
            result = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if result > base_time:
                return result, "simple_time_today", {}
            else:
                result += timedelta(days=1)
                return result, "simple_time_tomorrow", {'adjusted': True}
        
        # 7. Time with AM/PM: "8:00 PM" - ДО time_only
        match = re.search(self.en_patterns['time_ampm'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            am_pm = match.group(3)
            
            hour = self._adjust_hour_en(hour, am_pm)
            
            result = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if result > base_time:
                return result, "time_ampm_today", {}
            else:
                result += timedelta(days=1)
                return result, "time_ampm_tomorrow", {'adjusted': True}
        
        # 8. Time only
        match = re.search(self.en_patterns['time_only'], time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            am_pm = match.group(3)
            
            hour = self._adjust_hour_en(hour, am_pm)
            
            result = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if result > base_time:
                return result, "time_only_today", {}
            else:
                result += timedelta(days=1)
                return result, "time_only_tomorrow", {'adjusted': True}
        
        # 9. Dates
        match = re.search(self.en_patterns['date_mdy'], time_str)
        if match:
            month = int(match.group(1))
            day = int(match.group(2))
            year = int(match.group(3)) if match.group(3) else base_time.year
            hour = int(match.group(4))
            minute = int(match.group(5)) if match.group(5) else 0
            am_pm = match.group(6)
            
            if year < 100:
                year += 2000
            
            hour = self._adjust_hour_en(hour, am_pm)
            
            try:
                result = datetime(year, month, day, hour, minute, tzinfo=user_tz)
                return result, "date_mdy", {}
            except ValueError:
                pass
        
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
                except ValueError:
                    pass
        
        return None, "not_parsed", {}
    
    # Остальные методы без изменений
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
            
            parsed = dateparser.parse(time_str, settings=settings)
            if parsed:
                parsed = parsed.replace(microsecond=0, second=0)
                return parsed, "dateparser"
            
            dates = search_dates(time_str, languages=[language], settings=settings)
            if dates:
                result = dates[0][1]
                # ✅ Обнуляем микросекунды и секунды
                result = result.replace(microsecond=0, second=0)
                return result, "dateparser_search"
                
        except Exception as e:
            logger.debug(f"Dateparser failed for '{time_str}': {e}")
        
        return None, "dateparser_failed"
    
    def _adjust_hour_ru(self, hour: int, time_of_day: str) -> int:
        """Корректировка часа для русского языка"""
        if time_of_day:
            time_of_day = time_of_day.lower()
            if time_of_day in ['дня', 'вечера']:
                if hour < 12:
                    return hour + 12
            elif time_of_day == 'ночи' and hour == 12:
                return 0
        return hour
    
    def _adjust_hour_en(self, hour: int, am_pm: str) -> int:
        """Корректировка часа для английского языка"""
        if am_pm:
            am_pm = am_pm.upper()
            if am_pm == 'AM':
                if hour == 12:
                    return 0
                return hour
            elif am_pm == 'PM':
                if hour == 12:
                    return 12
                return hour + 12
        
        if hour <= 12:
            return hour
        
        return hour
    
    def _get_next_weekday(self, base_time: datetime, weekday: int) -> datetime:
        """Получить следующий день недели"""
        days_ahead = weekday - base_time.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        result = base_time + timedelta(days=days_ahead)
        # ✅ Обнуляем микросекунды и секунды
        return result.replace(microsecond=0, second=0)
    
    def extract_time_and_text(self, full_text: str, language: str = 'ru') -> Tuple[str, str]:
        """
        Извлечь время и текст из полной строки (альтернативный метод).
        Ищет время в начале или конце строки.
        """
        if not full_text:
            return "", ""
        
        full_text = full_text.strip()
        
        # Пробуем найти время в начале строки
        if language == 'ru':
            time_patterns = [
                r'^(\d{1,2}[:\.]\d{2}\s*(?:утра|вечера|ночи|дня)?\s+)(.*)',
                r'^(\d{1,2}\s+(?:утра|вечера|ночи|дня)\s+)(.*)',
                r'^(завтра\s+\d+.*?\s+)(.*)',
                r'^(сегодня\s+\d+.*?\s+)(.*)',
                r'^(послезавтра\s+\d+.*?\s+)(.*)',
            ]
        else:
            time_patterns = [
                r'^(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\s+)(.*)',
                r'^(\d{1,2}\s*(?:AM|PM|am|pm)\s+)(.*)',
                r'^(tomorrow\s+\d+.*?\s+)(.*)',
                r'^(today\s+\d+.*?\s+)(.*)',
                r'^(day after tomorrow\s+\d+.*?\s+)(.*)',
            ]
        
        for pattern in time_patterns:
            match = re.match(pattern, full_text, re.IGNORECASE)
            if match:
                time_part = match.group(1).strip()
                text_part = match.group(2).strip()
                return time_part, text_part
        
        # Если время не в начале, возможно оно в конце
        if language == 'ru':
            time_patterns_end = [
                r'(.*\s)(\d{1,2}[:\.]\d{2}\s*(?:утра|вечера|ночи|дня)?)$',
                r'(.*\s)(\d{1,2}\s+(?:утра|вечера|ночи|дня))$',
            ]
        else:
            time_patterns_end = [
                r'(.*\s)(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)$',
                r'(.*\s)(\d{1,2}\s*(?:AM|PM|am|pm))$',
            ]
        
        for pattern in time_patterns_end:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                text_part = match.group(1).strip()
                time_part = match.group(2).strip()
                return time_part, text_part
        
        # Если не нашли - возвращаем весь текст как текст, время пустое
        return "", full_text
    
    # Остальные методы (detect_repeat_pattern, validate_time, get_examples, clear_cache)
    # остаются без изменений
    
    def detect_repeat_pattern(self, time_str: str, language: str = 'ru') -> Dict[str, Any]:
        """Обнаружить паттерны повторения в строке"""
        time_str = time_str.lower()
        
        ru_patterns = {
            'daily': [r'каждый день', r'ежедневно'],
            'weekly': [r'каждую неделю', r'по понедельникам', r'по вторникам', 
                      r'по средам', r'по четвергам', r'по пятницам', 
                      r'по субботам', r'по воскресеньям', r'по будням', r'по выходным'],
            'monthly': [r'каждый месяц', r'ежемесячно'],
            'yearly': [r'каждый год', r'ежегодно']
        }
        
        en_patterns = {
            'daily': [r'every day', r'daily'],
            'weekly': [r'every week', r'weekly', r'every monday', r'every tuesday',
                      r'every wednesday', r'every thursday', r'every friday',
                      r'every saturday', r'every sunday', r'on weekdays', r'on weekends'],
            'monthly': [r'every month', r'monthly'],
            'yearly': [r'every year', r'yearly']
        }
        
        patterns = ru_patterns if language == 'ru' else en_patterns
        
        for repeat_type, pattern_list in patterns.items():
            for pattern in pattern_list:
                if re.search(pattern, time_str):
                    repeat_days = None
                    if repeat_type == 'weekly':
                        repeat_days = self._extract_weekdays(time_str, language)
                    
                    return {
                        'repeat_type': repeat_type,
                        'repeat_days': repeat_days,
                        'repeat_interval': 1
                    }
        
        return {'repeat_type': 'none', 'repeat_days': None, 'repeat_interval': 1}
    
    def _extract_weekdays(self, time_str: str, language: str) -> list:
        """Извлечь дни недели из строки"""
        if language == 'ru':
            days_map = {
                'понедельник': 0, 'понедельникам': 0,
                'вторник': 1, 'вторникам': 1,
                'среда': 2, 'средам': 2,
                'четверг': 3, 'четвергам': 3,
                'пятница': 4, 'пятницам': 4,
                'суббота': 5, 'субботам': 5,
                'воскресенье': 6, 'воскресеньям': 6,
                'будн': [0, 1, 2, 3, 4],
                'выходн': [5, 6]
            }
        else:
            days_map = {
                'monday': 0, 'mondays': 0,
                'tuesday': 1, 'tuesdays': 1,
                'wednesday': 2, 'wednesdays': 2,
                'thursday': 3, 'thursdays': 3,
                'friday': 4, 'fridays': 4,
                'saturday': 5, 'saturdays': 5,
                'sunday': 6, 'sundays': 6,
                'weekday': [0, 1, 2, 3, 4],
                'weekend': [5, 6]
            }
        
        found_days = []
        for day_pattern, day_value in days_map.items():
            if re.search(day_pattern, time_str):
                if isinstance(day_value, list):
                    found_days.extend(day_value)
                else:
                    found_days.append(day_value)
        
        return sorted(set(found_days)) if found_days else None
    
    def validate_time(self, parsed_time: datetime, base_time: datetime = None) -> Tuple[bool, str]:
        """Проверить корректность распарсенного времени"""
        if base_time is None:
            base_time = datetime.now(pytz.UTC)
        
        if parsed_time is None:
            return False, "Не удалось распознать время"
        
        if parsed_time <= base_time:
            return False, "Время должно быть в будущем"
        
        max_future = base_time + timedelta(days=5*365)
        if parsed_time > max_future:
            return False, "Время слишком далеко в будущем (максимум 5 лет)"
        
        return True, "OK"
    
    def get_examples(self, language: str = 'ru') -> list:
        """Получить примеры форматов времени"""
        if language == 'ru':
            return [
                "Завтра 10:30",
                "Сегодня в 18:00",
                "Послезавтра в 15:45",
                "Через 2 часа",
                "Через 30 минут",
                "Понедельник в 9 утра",
                "31.12.2024 23:59",
                "15 января в 14:00",
                "20:00",
                "8 утра",
                "в 8 вечера",
                "Каждый день в 8 утра",
                "По понедельникам в 10:00"
            ]
        else:
            return [
                "Tomorrow 10:30 AM",
                "Today at 6:00 PM",
                "Day after tomorrow at 3:45 PM",
                "In 2 hours",
                "In 30 minutes",
                "Monday at 9 AM",
                "12/31/2024 11:59 PM",
                "January 15 at 2:00 PM",
                "8:00 PM",
                "at 8 AM",
                "Every day at 8 AM",
                "Every Monday at 10:00"
            ]
    
    def clear_cache(self):
        """Очистить кэш парсера"""
        self._cache.clear()
