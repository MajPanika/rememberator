import pytz
from datetime import datetime, timedelta
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)

class TimezoneHandler:
    # Карта смещений к часовым поясам
    OFFSET_TO_TIMEZONE = {
        -12: 'Etc/GMT+12',
        -11: 'Pacific/Midway',
        -10: 'Pacific/Honolulu',
        -9: 'America/Anchorage',
        -8: 'America/Los_Angeles',
        -7: 'America/Denver',
        -6: 'America/Chicago',
        -5: 'America/New_York',
        -4: 'America/Caracas',
        -3: 'America/Sao_Paulo',
        -2: 'Atlantic/South_Georgia',
        -1: 'Atlantic/Azores',
        0: 'UTC',
        1: 'Europe/London',
        2: 'Europe/Berlin',
        3: 'Europe/Moscow',      # Москва
        4: 'Asia/Dubai',
        5: 'Asia/Karachi',
        6: 'Asia/Dhaka',
        7: 'Asia/Bangkok',
        8: 'Asia/Shanghai',
        9: 'Asia/Tokyo',
        10: 'Australia/Sydney',
        11: 'Pacific/Noumea',
        12: 'Pacific/Auckland',
        13: 'Pacific/Tongatapu'
    }
    
    # Популярные часовые пояса
    POPULAR_TIMEZONES = [
        'Europe/Moscow',        # Москва
        'Europe/London',        # Лондон
        'America/New_York',     # Нью-Йорк
        'America/Los_Angeles',  # Лос-Анджелес
        'Asia/Tokyo',           # Токио
        'Asia/Shanghai',        # Шанхай
        'Australia/Sydney',     # Сидней
        'Europe/Berlin',        # Берлин
        'Asia/Dubai',           # Дубай
        'Asia/Kolkata',         # Индия
    ]
    
    @staticmethod
    def offset_to_timezone(offset_seconds: int) -> str:
        """Конвертировать смещение в секундах в часовой пояс"""
        offset_hours = offset_seconds // 3600
        
        # Ищем ближайший часовой пояс
        closest_offset = min(
            TimezoneHandler.OFFSET_TO_TIMEZONE.keys(),
            key=lambda x: abs(x - offset_hours)
        )
        
        return TimezoneHandler.OFFSET_TO_TIMEZONE.get(
            closest_offset, 
            'Europe/Moscow'  # По умолчанию
        )
    
    @staticmethod
    def get_user_timezone(user_data) -> Tuple[str, int]:
        """Получить часовой пояс пользователя из данных Telegram"""
        timezone_name = 'Europe/Moscow'
        offset_seconds = 10800  # UTC+3 по умолчанию
        
        # Пробуем получить offset из данных Telegram
        if hasattr(user_data, 'timezone_offset'):
            offset_seconds = user_data.timezone_offset
            timezone_name = TimezoneHandler.offset_to_timezone(offset_seconds)
            logger.debug(f"Detected timezone from offset {offset_seconds}: {timezone_name}")
        
        return timezone_name, offset_seconds
    
    @staticmethod
    def local_to_utc(local_time: datetime, timezone_name: str) -> datetime:
        """Конвертировать локальное время в UTC"""
        try:
            user_tz = pytz.timezone(timezone_name)
            
            # Если время уже с часовым поясом, конвертируем
            if local_time.tzinfo is not None:
                return local_time.astimezone(pytz.UTC)
            
            # Иначе считаем, что это локальное время в указанном часовом поясе
            localized = user_tz.localize(local_time)
            return localized.astimezone(pytz.UTC)
            
        except Exception as e:
            logger.error(f"Error converting local to UTC: {e}")
            # Возвращаем как есть, предполагая что это уже UTC
            return local_time
    
    @staticmethod
    def utc_to_local(utc_time: datetime, timezone_name: str) -> datetime:
        """Конвертировать UTC в локальное время"""
        try:
            utc_time = pytz.UTC.localize(utc_time) if utc_time.tzinfo is None else utc_time
            user_tz = pytz.timezone(timezone_name)
            return utc_time.astimezone(user_tz)
        except Exception as e:
            logger.error(f"Error converting UTC to local: {e}")
            return utc_time
    
    @staticmethod
    def format_local_time(dt: datetime, timezone_name: str, 
                         language: str = 'ru') -> str:
        """Отформатировать время для пользователя"""
        local_dt = TimezoneHandler.utc_to_local(dt, timezone_name)
        
        if language == 'ru':
            # Русский формат: 15 января 2024, 14:30
            months_ru = [
                'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
            ]
            month_name = months_ru[local_dt.month - 1]
            return f"{local_dt.day} {month_name} {local_dt.year}, {local_dt.strftime('%H:%M')}"
        else:
            # Английский формат: January 15, 2024, 2:30 PM
            return local_dt.strftime("%B %d, %Y, %I:%M %p")
    
    @staticmethod
    def get_timezone_display_name(timezone_name: str, language: str = 'ru') -> str:
        """Получить читаемое название часового пояса"""
        # Простое отображение, можно расширить
        tz_display = {
            'ru': {
                'Europe/Moscow': 'Москва (UTC+3)',
                'Europe/London': 'Лондон (UTC+0)',
                'America/New_York': 'Нью-Йорк (UTC-5)',
                'America/Los_Angeles': 'Лос-Анджелес (UTC-8)',
                'Asia/Tokyo': 'Токио (UTC+9)',
                'UTC': 'UTC (Всемирное время)',
            },
            'en': {
                'Europe/Moscow': 'Moscow (UTC+3)',
                'Europe/London': 'London (UTC+0)',
                'America/New_York': 'New York (UTC-5)',
                'America/Los_Angeles': 'Los Angeles (UTC-8)',
                'Asia/Tokyo': 'Tokyo (UTC+9)',
                'UTC': 'UTC (Universal Time)',
            }
        }
        
        return tz_display.get(language, {}).get(
            timezone_name, 
            f"{timezone_name.split('/')[-1].replace('_', ' ')}"
        )
    
    @staticmethod
    def validate_timezone(timezone_name: str) -> bool:
        """Проверить, существует ли часовой пояс"""
        try:
            pytz.timezone(timezone_name)
            return True
        except pytz.exceptions.UnknownTimeZoneError:
            return False
    
    @staticmethod
    def get_all_timezones() -> list:
        """Получить список всех часовых поясов"""
        return pytz.all_timezones
    
    @staticmethod
    def get_timezone_keyboard(language: str = 'ru') -> list:
        """Получить клавиатуру для выбора часового пояса"""
        from aiogram.types import InlineKeyboardButton
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        
        builder = InlineKeyboardBuilder()
        
        # Добавляем популярные часовые пояса
        for tz in TimezoneHandler.POPULAR_TIMEZONES[:8]:  # Первые 8
            display_name = TimezoneHandler.get_timezone_display_name(tz, language)
            builder.add(InlineKeyboardButton(
                text=display_name,
                callback_data=f"timezone_{tz}"
            ))
        
        builder.adjust(2)  # 2 кнопки в ряд
        
        # Кнопка для всех часовых поясов
        if language == 'ru':
            builder.row(InlineKeyboardButton(
                text="🌍 Все часовые пояса",
                callback_data="timezone_all"
            ))
        else:
            builder.row(InlineKeyboardButton(
                text="🌍 All timezones",
                callback_data="timezone_all"
            ))
        
        return builder.as_markup()
