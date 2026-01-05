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
        
        # Регулярные выражения для русского языка
        self.ru_patterns = {
            # Относительное время
            'relative_hours': r'через\s+(\d+)\s+(час|часа|часов)(?:\s+(\d+)\s+(минут|минуты|минуту))?',
            'relative_minutes': r'через\s+(\d+)\s+(минут|минуты|минуту)',
            'relative_days': r'через\s+(\d+)\s+(день|дня|дней)',
            'relative_weeks': r'через\s+(\d+)\s+(недел[юя]|недели|недель)',
            
            # Абсолютное время
            'today_time': r'сегодня\s+(?:в\s+)?(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            'tomorrow_time': r'завтра\s+(?:в\s+)?(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            'day_after_tomorrow': r'послезавтра\s+(?:в\s+)?(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            
            # Дни недели
            'weekday_time': r'(понедельник|вторник|сред[ау]|четверг|пятниц[ау]|суббот[ау]|воскресенье)\s+(?:в\s+)?(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            
            # Даты
            'date_dmy': r'(\d{1,2})[\.\/](\d{1,2})(?:[\.\/](\d{2,4}))?\s+(?:в\s+)?(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            'date_dmy_words': r'(\d{1,2})\s+(январ[яю]|феврал[яю]|март[ау]|апрел[яю]|ма[яю]|июн[яю]|июл[яю]|август[ау]|сентябр[яю]|октябр[яю]|ноябр[яю]|декабр[яю])(?:\s+(\d{4}))?\s+(?:в\s+)?(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?',
            
            # Просто время
            'time_only': r'^(\d{1,2})(?:[:\.](\d{2}))?\s*(утра|вечера|ночи|дня)?$',
        }
        
        # Регулярные выражения для английского языка
        self.en_patterns = {
            # Relative time
            'relative_hours': r'in\s+(\d+)\s+(hour|hours)(?:\s+and\s+(\d+)\s+(minute|minutes))?',
            'relative_minutes': r'in\s+(\d+)\s+(minute|minutes)',
            'relative_days': r'in\s+(\d+)\s+(day|days)',
            'relative_weeks': r'in\s+(\d+)\s+(week|weeks)',
            
            # Absolute time
            'today_time': r'today\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?',
            'tomorrow_time': r'tomorrow\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?',
            'day_after_tomorrow': r'day\s+after\s+tomorrow\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?',
            
            # Weekdays
            'weekday_time': r'(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?',
            'next_weekday': r'next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?',
            
            # Dates
            'date_mdy': r'(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?',
            'date_mdy_words': r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?',
            
            # Time only
            'time_only': r'^(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?$',
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
        
        # 6. "послезавтра ХХ:ХХ"
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
        
        return None, "not_parsed", {}
    
    def _adjust_hour_ru(self, hour: int, time_of_day: str) -> int:
        """Корректировка часа для русского языка"""
        if time_of_day:
            if time_of_day in ['дня', 'вечера'] and hour < 12:
                return hour + 12
            elif time_of_day == 'ночи' and hour < 12:
                return hour  # ночь уже считается как AM
        return hour
    
    def _adjust_hour_en(self, hour: int, am_pm: str) -> int:
        """Корректировка часа для английского языка (12-часовой формат)"""
        if am_pm:
            am_pm = am_pm.upper()
            if am_pm == 'AM':
                if hour == 12:
                    return 0  # 12 AM = 0:00
                return hour
            else:  # PM
                if hour == 12:
                    return 12  # 12 PM = 12:00
                return hour + 12
        return hour
    
    def _get_next_weekday(self, base_time: datetime, weekday: int) -> datetime:
        """Получить следующий день недели"""
        days_ahead = weekday - base_time.weekday()
        if days_ahead <= 0:  # Если день уже прошел на этой неделе
            days_ahead += 7
        return base_time + timedelta(days=days_ahead)
    
    def detect_repeat_pattern(self, time_str: str, language: str = 'ru') -> Dict[str, Any]:
        """
        Обнаружить паттерны повторения в строке
        
        Возвращает:
        - repeat_type: 'daily', 'weekly', 'monthly', 'yearly', 'none'
        - repeat_days: для weekly - список дней недели
        - repeat_interval: интервал повторения
        """
        time_str = time_str.lower()
        
        # Паттерны для русского языка
        ru_repeat_patterns = {
            'daily': [
                r'каждый день',
                r'ежедневно',
                r'каждое утро',
                r'каждый вечер',
                r'каждую ночь'
            ],
            'weekly': [
                r'каждую неделю',
                r'по понедельникам',
                r'по вторникам',
                r'по средам',
                r'по четвергам',
                r'по пятницам',
                r'по субботам',
                r'по воскресеньям',
                r'по будням',
                r'по выходным'
            ],
            'monthly': [
                r'каждый месяц',
                r'ежемесячно'
            ],
            'yearly': [
                r'каждый год',
                r'ежегодно'
            ]
        }
        
        # Паттерны для английского языка
        en_repeat_patterns = {
            'daily': [
                r'every day',
                r'daily',
                r'each day',
                r'every morning',
                r'every evening',
                r'every night'
            ],
            'weekly': [
                r'every week',
                r'weekly',
                r'every monday',
                r'every tuesday',
                r'every wednesday',
                r'every thursday',
                r'every friday',
                r'every saturday',
                r'every sunday',
                r'on weekdays',
                r'on weekends'
            ],
            'monthly': [
                r'every month',
                r'monthly',
                r'each month'
            ],
            'yearly': [
                r'every year',
                r'yearly',
                r'annually',
                r'each year'
            ]
        }
        
        patterns = ru_repeat_patterns if language == 'ru' else en_repeat_patterns
        
        for repeat_type, pattern_list in patterns.items():
            for pattern in pattern_list:
                if re.search(pattern, time_str):
                    # Для weekly определяем дни недели
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
                'будн': [0, 1, 2, 3, 4],  # будни
                'выходн': [5, 6]  # выходные
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
                'weekday': [0, 1, 2, 3, 4],  # будни
                'weekend': [5, 6]  # выходные
            }
        
        found_days = []
        for day_pattern, day_value in days_map.items():
            if re.search(day_pattern, time_str):
                if isinstance(day_value, list):
                    found_days.extend(day_value)
                else:
                    found_days.append(day_value)
        
        return sorted(set(found_days)) if found_days else None
    
    def extract_reminder_text(self, full_text: str, language: str = 'ru') -> Tuple[str, str]:
        """
        Извлечь текст напоминания и время из полной строки
        
        Пример:
        "Позвонить маме завтра в 10:30" → ("Позвонить маме", "завтра в 10:30")
        """
        # Пробуем найти время в строке
        time_part = None
        text_part = full_text
        
        if language == 'ru':
            # Паттерны для поиска времени в тексте
            time_patterns = [
                r'(\b(?:завтра|послезавтра|сегодня|через\s+\d+\s+\w+)\b.*)',
                r'(\b\d{1,2}[:\.]\d{2}\b.*)',
                r'(\b\d{1,2}[\.\/]\d{1,2}(?:[\.\/]\d{2,4})?\b.*)',
            ]
        else:
            time_patterns = [
                r'(\b(?:tomorrow|day after tomorrow|today|in\s+\d+\s+\w+)\b.*)',
                r'(\b\d{1,2}:\d{2}\s*(?:AM|PM)?\b.*)',
                r'(\b\d{1,2}[\/\-]\d{1,2}(?:[\/\-]\d{2,4})?\b.*)',
            ]
        
        for pattern in time_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                time_part = match.group(1).strip()
                # Вырезаем время из текста
                text_part = full_text[:match.start(1)].strip()
                break
        
        # Если не нашли явное время, вся строка - это текст
        if not time_part:
            return full_text, ""
        
        # Убираем предлоги в начале времени
        if language == 'ru':
            time_part = re.sub(r'^(?:в|на|по)\s+', '', time_part)
        else:
            time_part = re.sub(r'^(?:at|on|by)\s+', '', time_part)
        
        return text_part, time_part
    
    def validate_time(self, parsed_time: datetime, base_time: datetime = None) -> Tuple[bool, str]:
        """Проверить корректность распарсенного времени"""
        if base_time is None:
            base_time = datetime.now(pytz.UTC)
        
        if parsed_time is None:
            return False, "Не удалось распознать время"
        
        if parsed_time <= base_time:
            return False, "Время должно быть в будущем"
        
        # Проверяем, что время не слишком далеко в будущем (5 лет максимум)
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
                "Every day at 8 AM",
                "Every Monday at 10:00"
            ]
    
    def clear_cache(self):
        """Очистить кэш парсера"""
        self._cache.clear()
