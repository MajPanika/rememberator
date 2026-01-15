#!/usr/bin/env python3
"""
ИСПРАВЛЕННЫЙ парсер времени для бота-напоминалки
Фиксы:
1. Правильный часовой пояс Europe/Moscow (+03:00)
2. Исправлены регулярные выражения
3. Убраны точки как разделитель времени (только : или -)
4. Улучшено извлечение времени и текста
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
        
        # Регулярные выражения для русского языка (ИСПРАВЛЕННЫЕ)
        self.ru_patterns = {
            'relative_hours': r'через\s+(\d+)\s+(час|часа|часов)(?:\s+(\d+)\s+(минут|минуты|минуту))?',
            'relative_minutes': r'через\s+(\d+)\s+(минут|минуты|минуту)',
            'relative_days': r'через\s+(\d+)\s+(день|дня|дней)',
            
            # ВАЖНО: day_after_tomorrow ДО tomorrow
            'day_after_tomorrow': r'послезавтра(?:\s+(?:в\s+)?)?(\d{1,2})(?:[:\.-](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            'tomorrow_time': r'завтра(?:\s+(?:в\s+)?)?(\d{1,2})(?:[:\.-](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            'today_time': r'сегодня(?:\s+(?:в\s+)?)?(\d{1,2})(?:[:\.-](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            
            'weekday_time': r'(понедельник|вторник|сред[ау]|четверг|пятниц[ау]|суббот[ау]|воскресенье)(?:\s+(?:в\s+)?)?(\d{1,2})(?:[:\.-](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            
            'date_dmy': r'(\d{1,2})[\.\/](\d{1,2})(?:[\.\/](\d{2,4}))?(?:\s+(?:в\s+)?)?(\d{1,2})(?:[:\.-](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            'date_dmy_words': r'(\d{1,2})\s+(январ[яю]|феврал[яю]|март[ау]|апрел[яю]|ма[яю]|июн[яю]|июл[яю]|август[ау]|сентябр[яю]|октябр[яю]|ноябр[яю]|декабр[яю])(?:\s+(\d{4}))?(?:\s+(?:в\s+)?)?(\d{1,2})(?:[:\.-](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            
            'simple_time_ru': r'^в\s+(\d{1,2})(?:[:\.-](\d{2}))?\s*(утра|вечера|ночи|дня)?$',
            # УБИРАЕМ простой time_with_dash - он будет в отдельной обработке
            'time_no_prep': r'^(\d{1,2})\s+(утра|вечера|ночи|дня)$',
            'time_only': r'^(\d{1,2})(?:[:\.-](\d{2}))?\s*(утра|вечера|ночи|дня)?$',
        }
        
        # Регулярные выражения для английского языка (ИСПРАВЛЕННЫЕ)
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
        
        # Словари
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
                # Обнуляем микросекунды и секунды
                parsed = parsed.replace(microsecond=0, second=0)
                return parsed, "dateparser"
            
            dates = search_dates(time_str, languages=[language], settings=settings)
            if dates:
                result = dates[0][1]
                # Обнуляем микросекунды и секунды
                result = result.replace(microsecond=0, second=0)
                return result, "dateparser_search"
                    
        except Exception as e:
            logger.debug(f"Dateparser failed for '{time_str}': {e}")
        
        return None, "dateparser_failed"
    
    def parse(self, time_str: str, language: str = 'ru', 
              timezone: str = 'Europe/Moscow',
              base_time: datetime = None) -> Tuple[Optional[datetime], str, Dict[str, Any]]:
        """Парсинг строки времени"""
        if not time_str or not time_str.strip():
            return None, "empty", {}
        
        time_str = time_str.strip()
        
        cache_key = f"{time_str}_{language}_{timezone}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        if base_time is None:
            base_time = datetime.now(pytz.timezone(timezone))
        
        # 1. Сначала специальная обработка формата "8-39" и "16-00"
        # Заменяем тире на двоеточие для dateparser
        normalized_str = re.sub(r'(\d{1,2})-(\d{2})', r'\1:\2', time_str)
        
        # 2. Пробуем dateparser с нормализованной строкой
        result, parse_type = self._try_dateparser(normalized_str, language, timezone, base_time)
        
        # 3. Если dateparser не сработал, пробуем наши регулярки
        if result is None:
            if language == 'ru':
                result, parse_type, extra_info = self._parse_ru_fixed(time_str, base_time, timezone)
            else:
                result, parse_type, extra_info = self._parse_en_fixed(time_str, base_time, timezone)
        
        # 4. Проверяем, что время в будущем
        if result and result <= base_time:
            if result.date() == base_time.date():
                result += timedelta(days=1)
                extra_info = extra_info if 'extra_info' in locals() else {}
                extra_info['adjusted'] = 'tomorrow'
        
        # 5. Проверяем, что дата не слишком далеко в будущем
        if result:
            max_future = base_time + timedelta(days=5*365)
            if result > max_future:
                logger.warning(f"Date too far in future: {result}")
                return None, "too_far", {}

        # 6. ✅ ВАЖНО: Обнуляем микросекунды и секунды для всех результатов
        if result:
            result = result.replace(microsecond=0, second=0)
        
        extra_info = extra_info if 'extra_info' in locals() else {}
        self._cache[cache_key] = (result, parse_type, extra_info)
        return result, parse_type, extra_info
    
    def _parse_ru_fixed(self, time_str: str, base_time: datetime, timezone: str) -> Tuple[Optional[datetime], str, Dict]:
        """Исправленный парсинг для русского языка"""
        user_tz = pytz.timezone(timezone)
        time_str_lower = time_str.lower()
        
        # ВАЖНО: Специальная обработка для "8-39", "16-00" и т.д.
        # Сначала проверяем самый простой случай - только время с тире
        dash_time_match = re.match(r'^(\d{1,2})-(\d{2})$', time_str)
        if dash_time_match:
            hour = int(dash_time_match.group(1))
            minute = int(dash_time_match.group(2))
            
            # Создаем время на сегодня
            result = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            # Если время уже прошло, переносим на завтра
            if result > base_time:
                return result, "time_dash_today", {}
            else:
                result += timedelta(days=1)
                return result, "time_dash_tomorrow", {'adjusted': True}
        
        # 1. Даты со словами и временем: "11 января 16-00"
        match = re.search(r'(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)(?:\s+(\d{4}))?\s+(\d{1,2})[:\.-](\d{2})\s*(утра|вечера|ночи|дня)?', time_str_lower)
        if match:
            day = int(match.group(1))
            month_ru = match.group(2)
            year = int(match.group(3)) if match.group(3) else base_time.year
            hour = int(match.group(4))
            minute = int(match.group(5))
            time_of_day = match.group(6)
            
            month = self.ru_months.get(month_ru)
            if month:
                hour = self._adjust_hour_ru(hour, time_of_day)
                try:
                    result = datetime(year, month, day, hour, minute, tzinfo=user_tz)
                    return result, "date_words_with_time", {}
                except ValueError:
                    pass
        
        # 2. Числовые даты с временем: "11.01 16-00"
        match = re.search(r'(\d{1,2})[\.\/](\d{1,2})(?:[\.\/](\d{2,4}))?\s+(\d{1,2})[:\.-](\d{2})\s*(утра|вечера|ночи|дня)?', time_str_lower)
        if match:
            day = int(match.group(1))
            month = int(match.group(2))
            year = int(match.group(3)) if match.group(3) else base_time.year
            hour = int(match.group(4))
            minute = int(match.group(5))
            time_of_day = match.group(6)
            
            if year < 100:
                year += 2000
            
            hour = self._adjust_hour_ru(hour, time_of_day)
            
            try:
                result = datetime(year, month, day, hour, minute, tzinfo=user_tz)
                return result, "date_numeric_with_time", {}
            except ValueError:
                pass
        
        # 3. Относительное время
        match = re.search(self.ru_patterns['relative_hours'], time_str_lower)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(3)) if match.group(3) else 0
            result = base_time + timedelta(hours=hours, minutes=minutes)
            return result, "relative_hours", {}
        
        match = re.search(self.ru_patterns['relative_minutes'], time_str_lower)
        if match:
            minutes = int(match.group(1))
            result = base_time + timedelta(minutes=minutes)
            return result, "relative_minutes", {}
        
        match = re.search(self.ru_patterns['relative_days'], time_str_lower)
        if match:
            days = int(match.group(1))
            result = base_time + timedelta(days=days)
            return result, "relative_days", {}
        
        # 4. "послезавтра"
        match = re.search(self.ru_patterns['day_after_tomorrow'], time_str_lower)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            time_of_day = match.group(3)
            
            hour = self._adjust_hour_ru(hour, time_of_day)
            result = base_time + timedelta(days=2)
            result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result, "day_after_tomorrow", {}
        
        # 5. "завтра"
        match = re.search(self.ru_patterns['tomorrow_time'], time_str_lower)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            time_of_day = match.group(3)
            
            hour = self._adjust_hour_ru(hour, time_of_day)
            result = base_time + timedelta(days=1)
            result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result, "tomorrow", {}
        
        # 6. "сегодня"
        match = re.search(self.ru_patterns['today_time'], time_str_lower)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            time_of_day = match.group(3)
            
            hour = self._adjust_hour_ru(hour, time_of_day)
            result = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result, "today", {}
        
        # 7. Дни недели
        match = re.search(self.ru_patterns['weekday_time'], time_str_lower)
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
        
        # 8. Простое время с предлогом "в"
        match = re.search(self.ru_patterns['simple_time_ru'], time_str_lower)
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
        
        # 9. Время без предлога: "8 утра"
        match = re.search(self.ru_patterns['time_no_prep'], time_str_lower)
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
        
        # 10. Только время (последний вариант)
        match = re.search(self.ru_patterns['time_only'], time_str_lower)
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
        
        return None, "not_parsed", {}
    
    def _parse_en_fixed(self, time_str: str, base_time: datetime, timezone: str) -> Tuple[Optional[datetime], str, Dict]:
        """Исправленный парсинг для английского языка"""
        user_tz = pytz.timezone(timezone)
        time_str_lower = time_str.lower()
        
        # ВАЖНО: Специальная обработка для времени с тире
        dash_time_match = re.match(r'^(\d{1,2})-(\d{2})\s*(AM|PM|am|pm)?$', time_str, re.IGNORECASE)
        if dash_time_match:
            hour = int(dash_time_match.group(1))
            minute = int(dash_time_match.group(2))
            am_pm = dash_time_match.group(3)
            
            hour = self._adjust_hour_en(hour, am_pm)
            
            result = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if result > base_time:
                return result, "time_dash_today", {}
            else:
                result += timedelta(days=1)
                return result, "time_dash_tomorrow", {'adjusted': True}
        
        # 1. Dates with words and time
        match = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?\s+(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)?', time_str_lower, re.IGNORECASE)
        if match:
            month_en = match.group(1).lower()
            day = int(match.group(2))
            year = int(match.group(3)) if match.group(3) else base_time.year
            hour = int(match.group(4))
            minute = int(match.group(5))
            am_pm = match.group(6)
            
            month = self.en_months.get(month_en)
            if month:
                hour = self._adjust_hour_en(hour, am_pm)
                try:
                    result = datetime(year, month, day, hour, minute, tzinfo=user_tz)
                    return result, "date_words_with_time", {}
                except ValueError:
                    pass
        
        # 2. Numeric dates with time
        match = re.search(r'(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?\s+(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)?', time_str_lower, re.IGNORECASE)
        if match:
            month = int(match.group(1))
            day = int(match.group(2))
            year = int(match.group(3)) if match.group(3) else base_time.year
            hour = int(match.group(4))
            minute = int(match.group(5))
            am_pm = match.group(6)
            
            if year < 100:
                year += 2000
            
            hour = self._adjust_hour_en(hour, am_pm)
            
            try:
                result = datetime(year, month, day, hour, minute, tzinfo=user_tz)
                return result, "date_numeric_with_time", {}
            except ValueError:
                pass
        
        # 3. Relative time
        match = re.search(self.en_patterns['relative_hours'], time_str_lower, re.IGNORECASE)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(3)) if match.group(3) else 0
            result = base_time + timedelta(hours=hours, minutes=minutes)
            return result, "relative_hours", {}
        
        match = re.search(self.en_patterns['relative_minutes'], time_str_lower, re.IGNORECASE)
        if match:
            minutes = int(match.group(1))
            result = base_time + timedelta(minutes=minutes)
            return result, "relative_minutes", {}
        
        match = re.search(self.en_patterns['relative_days'], time_str_lower, re.IGNORECASE)
        if match:
            days = int(match.group(1))
            result = base_time + timedelta(days=days)
            return result, "relative_days", {}
        
        # 4. "day after tomorrow"
        match = re.search(self.en_patterns['day_after_tomorrow'], time_str_lower, re.IGNORECASE)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            am_pm = match.group(3)
            
            hour = self._adjust_hour_en(hour, am_pm)
            result = base_time + timedelta(days=2)
            result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result, "day_after_tomorrow", {}
        
        # 5. "tomorrow"
        match = re.search(self.en_patterns['tomorrow_time'], time_str_lower, re.IGNORECASE)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            am_pm = match.group(3)
            
            hour = self._adjust_hour_en(hour, am_pm)
            result = base_time + timedelta(days=1)
            result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result, "tomorrow", {}
        
        # 6. "today"
        match = re.search(self.en_patterns['today_time'], time_str_lower, re.IGNORECASE)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            am_pm = match.group(3)
            
            hour = self._adjust_hour_en(hour, am_pm)
            result = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result, "today", {}
        
        # 7. Weekdays
        match = re.search(self.en_patterns['weekday_time'], time_str_lower, re.IGNORECASE)
        if match:
            weekday_en = match.group(1).lower()
            hour = int(match.group(2))
            minute = int(match.group(3)) if match.group(3) else 0
            am_pm = match.group(4)
            
            weekday_num = self.en_weekdays.get(weekday_en)
            if weekday_num is not None:
                hour = self._adjust_hour_en(hour, am_pm)
                result = self._get_next_weekday(base_time, weekday_num)
                result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)
                return result, "weekday", {}
        
        # 8. Simple time with "at"
        match = re.search(self.en_patterns['simple_time_en'], time_str_lower, re.IGNORECASE)
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
        
        # 9. Time with AM/PM
        match = re.search(self.en_patterns['time_ampm'], time_str_lower, re.IGNORECASE)
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
        
        # 10. Time only
        match = re.search(self.en_patterns['time_only'], time_str_lower, re.IGNORECASE)
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
        
        return None, "not_parsed", {}
    
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
        return result.replace(microsecond=0, second=0)
    
    # Остальные методы оставляем без изменений
    def extract_time_and_text(self, full_text: str, language: str = 'ru') -> Tuple[str, str]:
        """
        Извлечь время и текст из полной строки.
        Упрощенная версия - ищет наиболее очевидное время.
        """
        if not full_text:
            return "", ""
        
        full_text = full_text.strip()
        
        # Сначала пробуем найти самое очевидное - время с тире или двоеточием
        # Ищем паттерн "ЧЧ-ММ" или "ЧЧ:ММ"
        time_pattern = r'(\d{1,2}[-:]\d{2})'
        time_match = re.search(time_pattern, full_text)
        
        if time_match:
            time_part = time_match.group(1)
            # Вырезаем найденное время из текста
            text_parts = re.split(time_pattern, full_text, maxsplit=1)
            if len(text_parts) >= 3:
                # text_parts[0] - текст до времени
                # text_parts[1] - само время (нам не нужно здесь)
                # text_parts[2] - текст после времени
                text_before = text_parts[0].strip()
                text_after = text_parts[2].strip()
                
                # Собираем текст без времени
                text_parts_clean = []
                if text_before:
                    text_parts_clean.append(text_before)
                if text_after:
                    text_parts_clean.append(text_after)
                
                text_part = " ".join(text_parts_clean).strip()
                
                # Очищаем от лишних предлогов
                if language == 'ru':
                    text_part = re.sub(r'^(?:в|на|с|у|о|об|про)\s+', '', text_part)
                else:
                    text_part = re.sub(r'^(?:at|on|in|for)\s+', '', text_part, flags=re.IGNORECASE)
                
                return time_part, text_part
        
        # Если не нашли время с разделителем, возвращаем весь текст как текст
        return "", full_text
    
    def extract_best_time_and_text(self, full_text: str, language: str = 'ru') -> Tuple[str, str]:
        """Улучшенное извлечение времени и текста"""
        # Пока используем простую версию
        return self.extract_time_and_text(full_text, language)
    
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
