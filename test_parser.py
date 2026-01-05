#!/usr/bin/env python3
"""
Тестирование исправленного парсера времени
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
    
    print("=" * 60)
    print("ТЕСТИРОВАНИЕ ИСПРАВЛЕННОГО ПАРСЕРА ВРЕМЕНИ")
    print("=" * 60)
    
    # Тест проблемных случаев из предыдущего теста
    problem_cases = [
        # Русский язык
        ("послезавтра в 15:45", "ru", "Europe/Moscow"),
        ("в 8 утра", "ru", "Europe/Moscow"),
        ("в 8 вечера", "ru", "Europe/Moscow"),
        ("в 20:00", "ru", "Europe/Moscow"),
        
        # Английский язык
        ("8:00 PM", "en", "America/New_York"),
        ("at 8 AM", "en", "America/New_York"),
        ("at 6:00 PM", "en", "America/New_York"),
        ("today at 6:00 PM", "en", "America/New_York"),
        ("tomorrow at 3 PM", "en", "America/New_York"),
        ("day after tomorrow at 3:45 PM", "en", "America/New_York"),
    ]
    
    print("\n🔧 ПРОВЕРКА ПРОБЛЕМНЫХ СЛУЧАЕВ:")
    print("-" * 40)
    
    for time_str, lang, tz in problem_cases:
        parsed_time, parse_type, extra_info = parser.parse(time_str, lang, tz)
        
        if parsed_time:
            local_tz = pytz.timezone(tz)
            local_time = parsed_time.astimezone(local_tz)
            
            if lang == 'ru':
                time_format = local_time.strftime('%d.%m.%Y %H:%M')
            else:
                time_format = local_time.strftime('%m/%d/%Y %I:%M %p')
            
            print(f"✅ '{time_str}' → {time_format} ({parse_type})")
            if extra_info.get('adjusted'):
                print(f"   ⚠️  Скорректировано на завтра")
        else:
            print(f"❌ '{time_str}' → не распознано")
    
    # Тест извлечения времени из текста
    print("\n📝 ИЗВЛЕЧЕНИЕ ИЗ ТЕКСТА (исправленное):")
    print("-" * 40)
    
    test_texts = [
        "Pay bills on Monday at 9 AM",
        "Meeting with John tomorrow at 3 PM",
        "Call mom next Monday at 10 AM",
        "Позвонить маме в понедельник в 10 утра",
    ]
    
    for text in test_texts:
        lang = 'ru' if any(c in text for c in 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя') else 'en'
        text_part, time_part = parser.extract_reminder_text(text, lang)
        print(f"📄 '{text}'")
        print(f"  Текст: '{text_part}'")
        print(f"  Время: '{time_part}'")
        
        # Пробуем распарсить извлеченное время
        if time_part:
            parsed_time, parse_type, _ = parser.parse(time_part, lang, 'Europe/Moscow' if lang == 'ru' else 'America/New_York')
            if parsed_time:
                print(f"  ✅ Время распознано: {parse_type}")
            else:
                print(f"  ❌ Время не распознано")
        print()
    
    # Тест AM/PM коррекции
    print("\n🕐 ТЕСТ AM/PM КОРРЕКЦИИ:")
    print("-" * 40)
    
    ampm_tests = [
        ("6:00 PM", "en", "America/New_York"),
        ("6:00 AM", "en", "America/New_York"),
        ("12:00 PM", "en", "America/New_York"),
        ("12:00 AM", "en", "America/New_York"),
        ("8 вечера", "ru", "Europe/Moscow"),
        ("8 утра", "ru", "Europe/Moscow"),
    ]
    
    for time_str, lang, tz in ampm_tests:
        parsed_time, parse_type, _ = parser.parse(time_str, lang, tz)
        if parsed_time:
            hour = parsed_time.hour
            expected_hour = {
                "6:00 PM": 18,
                "6:00 AM": 6,
                "12:00 PM": 12,
                "12:00 AM": 0,
                "8 вечера": 20,
                "8 утра": 8,
            }.get(time_str)
            
            status = "✅" if hour == expected_hour else "❌"
            print(f"{status} '{time_str}' → {hour}:00 (ожидалось: {expected_hour}:00)")
    
    print("\n" + "=" * 60)
    print("ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    print("=" * 60)

if __name__ == "__main__":
    test_parser()
