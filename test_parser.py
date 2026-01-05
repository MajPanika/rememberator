#!/usr/bin/env python3
"""
Тестирование парсера времени
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.time_parser import TimeParser
from datetime import datetime
import pytz

def test_parser():
    """Запуск тестов парсера"""
    parser = TimeParser()
    
    # Тестовые данные
    test_cases_ru = [
        ("завтра 10:30", "ru", "Europe/Moscow"),
        ("сегодня в 18:00", "ru", "Europe/Moscow"),
        ("послезавтра в 15:45", "ru", "Europe/Moscow"),
        ("через 2 часа", "ru", "Europe/Moscow"),
        ("через 30 минут", "ru", "Europe/Moscow"),
        ("понедельник в 9 утра", "ru", "Europe/Moscow"),
        ("31.12.2024 23:59", "ru", "Europe/Moscow"),
        ("15 января в 14:00", "ru", "Europe/Moscow"),
        ("20:00", "ru", "Europe/Moscow"),
        ("в 8 утра", "ru", "Europe/Moscow"),
        ("в 8 вечера", "ru", "Europe/Moscow"),
    ]
    
    test_cases_en = [
        ("tomorrow 10:30 AM", "en", "America/New_York"),
        ("today at 6:00 PM", "en", "America/New_York"),
        ("day after tomorrow at 3:45 PM", "en", "America/New_York"),
        ("in 2 hours", "en", "America/New_York"),
        ("in 30 minutes", "en", "America/New_York"),
        ("monday at 9 AM", "en", "America/New_York"),
        ("12/31/2024 11:59 PM", "en", "America/New_York"),
        ("january 15 at 2:00 PM", "en", "America/New_York"),
        ("8:00 PM", "en", "America/New_York"),
        ("at 8 AM", "en", "America/New_York"),
    ]
    
    print("=" * 60)
    print("ТЕСТИРОВАНИЕ ПАРСЕРА ВРЕМЕНИ")
    print("=" * 60)
    
    # Тестируем русский язык
    print("\n🇷🇺 РУССКИЙ ЯЗЫК:")
    print("-" * 40)
    
    for time_str, lang, tz in test_cases_ru:
        parsed_time, parse_type, extra_info = parser.parse(time_str, lang, tz)
        
        if parsed_time:
            local_tz = pytz.timezone(tz)
            local_time = parsed_time.astimezone(local_tz)
            print(f"✅ '{time_str}' → {local_time.strftime('%d.%m.%Y %H:%M')} ({parse_type})")
        else:
            print(f"❌ '{time_str}' → не распознано")
    
    # Тестируем английский язык
    print("\n🇬🇧 АНГЛИЙСКИЙ ЯЗЫК:")
    print("-" * 40)
    
    for time_str, lang, tz in test_cases_en:
        parsed_time, parse_type, extra_info = parser.parse(time_str, lang, tz)
        
        if parsed_time:
            local_tz = pytz.timezone(tz)
            local_time = parsed_time.astimezone(local_tz)
            print(f"✅ '{time_str}' → {local_time.strftime('%m/%d/%Y %I:%M %p')} ({parse_type})")
        else:
            print(f"❌ '{time_str}' → не распознано")
    
    # Тестируем извлечение текста и времени
    print("\n📝 ИЗВЛЕЧЕНИЕ ТЕКСТА И ВРЕМЕНИ:")
    print("-" * 40)
    
    test_texts = [
        "Позвонить маме завтра в 10:30",
        "Meeting with John tomorrow at 3 PM",
        "Сходить в магазин сегодня вечером",
        "Pay bills on Monday at 9 AM"
    ]
    
    for text in test_texts:
        lang = 'ru' if any(c in text for c in 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя') else 'en'
        text_part, time_part = parser.extract_reminder_text(text, lang)
        print(f"📄 '{text}'")
        print(f"  Текст: '{text_part}'")
        print(f"  Время: '{time_part}'")
        print()
    
    # Тестируем обнаружение повторений
    print("\n🔄 ОБНАРУЖЕНИЕ ПОВТОРЕНИЙ:")
    print("-" * 40)
    
    repeat_tests = [
        ("Каждый день в 8 утра", "ru"),
        ("Every Monday at 10 AM", "en"),
        ("По будням в 9:00", "ru"),
        ("On weekends at 11:00", "en"),
        ("Ежемесячно 1 числа", "ru"),
        ("Yearly on January 1", "en")
    ]
    
    for text, lang in repeat_tests:
        repeat_info = parser.detect_repeat_pattern(text, lang)
        print(f"🔁 '{text}' → {repeat_info['repeat_type']}")
        if repeat_info['repeat_days']:
            print(f"    Дни: {repeat_info['repeat_days']}")
    
    print("\n" + "=" * 60)
    print("ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    print("=" * 60)

if __name__ == "__main__":
    test_parser()
