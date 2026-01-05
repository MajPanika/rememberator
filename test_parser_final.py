#!/usr/bin/env python3
"""
Финальное тестирование исправленного парсера
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.time_parser_fixed import TimeParser
from datetime import datetime
import pytz

def test_final_parser():
    """Финальное тестирование парсера"""
    parser = TimeParser()
    
    print("=" * 70)
    print("ФИНАЛЬНОЕ ТЕСТИРОВАНИЕ ПАРСЕРА ВРЕМЕНИ")
    print("=" * 70)
    
    # Критические тесты
    critical_tests = [
        # Русский язык
        ("послезавтра в 15:45", "ru", "Europe/Moscow", "day_after_tomorrow"),
        ("завтра 10:30", "ru", "Europe/Moscow", "tomorrow"),
        ("сегодня в 18:00", "ru", "Europe/Moscow", "today"),
        ("в 8 утра", "ru", "Europe/Moscow", "simple_time"),
        ("8 вечера", "ru", "Europe/Moscow", "time_no_prep"),
        ("через 2 часа", "ru", "Europe/Moscow", "relative_hours"),
        
        # Английский язык
        ("day after tomorrow at 3:45 PM", "en", "America/New_York", "day_after_tomorrow"),
        ("tomorrow at 3 PM", "en", "America/New_York", "tomorrow"),
        ("today at 6:00 PM", "en", "America/New_York", "today"),
        ("at 8 AM", "en", "America/New_York", "simple_time"),
        ("8:00 PM", "en", "America/New_York", "time_ampm"),
        ("in 2 hours", "en", "America/New_York", "relative_hours"),
    ]
    
    print("\n🔍 КРИТИЧЕСКИЕ ТЕСТЫ:")
    print("-" * 70)
    
    all_passed = True
    for time_str, lang, tz, expected_type in critical_tests:
        parsed_time, parse_type, extra_info = parser.parse(time_str, lang, tz)
        
        if parsed_time:
            local_tz = pytz.timezone(tz)
            local_time = parsed_time.astimezone(local_tz)
            
            if lang == 'ru':
                time_format = local_time.strftime('%d.%m.%Y %H:%M')
            else:
                time_format = local_time.strftime('%m/%d/%Y %I:%M %p')
            
            status = "✅" if expected_type in parse_type else "❌"
            print(f"{status} '{time_str}'")
            print(f"   → {time_format} ({parse_type})")
            
            if expected_type not in parse_type:
                print(f"   ⚠️  Ожидался тип: {expected_type}")
                all_passed = False
            
            if extra_info.get('adjusted'):
                print(f"   🔄 Скорректировано на завтра")
        else:
            print(f"❌ '{time_str}' → не распознано")
            all_passed = False
    
    # Тест извлечения времени из текста
    print("\n📝 ИЗВЛЕЧЕНИЕ ВРЕМЕНИ ИЗ ТЕКСТА:")
    print("-" * 70)
    
    extraction_tests = [
        ("Pay bills on Monday at 9 AM", "en"),
        ("Meeting with John tomorrow at 3 PM", "en"),
        ("Call mom next Monday at 10 AM", "en"),
        ("Позвонить маме в понедельник в 10 утра", "ru"),
        ("Сходить в магазин завтра в 18:00", "ru"),
        ("Встреча послезавтра в 15:30", "ru"),
    ]
    
    for text, lang in extraction_tests:
        text_part, time_part = parser.extract_reminder_text(text, lang)
        print(f"📄 '{text}'")
        print(f"   Текст: '{text_part}'")
        print(f"   Время: '{time_part}'")
        
        if time_part:
            parsed_time, parse_type, _ = parser.parse(time_part, lang, 
                                                      'Europe/Moscow' if lang == 'ru' else 'America/New_York')
            if parsed_time:
                print(f"   ✅ Время распознано: {parse_type}")
            else:
                print(f"   ❌ Время не распознано")
        else:
            print(f"   ⚠️  Время не найдено")
        print()
    
    # Тест AM/PM коррекции
    print("\n🕐 ТЕСТ AM/PM КОРРЕКЦИИ:")
    print("-" * 70)
    
    ampm_tests = [
        ("6:00 PM", "en", 18),
        ("6:00 AM", "en", 6),
        ("12:00 PM", "en", 12),
        ("12:00 AM", "en", 0),
        ("6 вечера", "ru", 18),
        ("6 утра", "ru", 6),
        ("12 ночи", "ru", 0),
        ("12 дня", "ru", 12),
    ]
    
    for time_str, lang, expected_hour in ampm_tests:
        tz = 'Europe/Moscow' if lang == 'ru' else 'America/New_York'
        parsed_time, parse_type, _ = parser.parse(time_str, lang, tz)
        
        if parsed_time:
            hour = parsed_time.hour
            status = "✅" if hour == expected_hour else "❌"
            print(f"{status} '{time_str}' → {hour}:00 (ожидалось: {expected_hour}:00)")
            
            if hour != expected_hour:
                all_passed = False
        else:
            print(f"❌ '{time_str}' → не распознано")
            all_passed = False
    
    # Итог
    print("\n" + "=" * 70)
    if all_passed:
        print("🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
    else:
        print("⚠️  НЕКОТОРЫЕ ТЕСТЫ НЕ ПРОЙДЕНЫ")
    print("=" * 70)

if __name__ == "__main__":
    test_final_parser()
