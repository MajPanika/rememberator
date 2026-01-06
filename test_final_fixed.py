#!/usr/bin/env python3
"""
ФИНАЛЬНЫЙ тест парсера после исправлений
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.time_parser_final import TimeParser
from datetime import datetime
import pytz

def run_final_test():
    """Финальный тест"""
    parser = TimeParser()
    
    print("=" * 70)
    print("🎯 ФИНАЛЬНЫЙ ТЕСТ ПАРСЕРА (после исправлений)")
    print("=" * 70)
    
    # Критические тесты с ожидаемыми типами
    tests = [
        # (строка, язык, таймзона, ожидаемый_тип)
        ("послезавтра в 15:45", "ru", "Europe/Moscow", "day_after_tomorrow"),
        ("day after tomorrow at 3:45 PM", "en", "America/New_York", "day_after_tomorrow"),
        ("завтра 10:30", "ru", "Europe/Moscow", "tomorrow"),
        ("tomorrow at 3 PM", "en", "America/New_York", "tomorrow"),
        ("8 вечера", "ru", "Europe/Moscow", "time_no_prep"),
        ("8:00 PM", "en", "America/New_York", "time_ampm"),
    ]
    
    print("\n🔍 КРИТИЧЕСКИЕ ИСПРАВЛЕНИЯ:")
    print("-" * 70)
    
    passed = 0
    total = len(tests)
    
    for time_str, lang, tz, expected_type in tests:
        parsed_time, parse_type, extra_info = parser.parse(time_str, lang, tz)
        
        if parsed_time:
            local_tz = pytz.timezone(tz)
            local_time = parsed_time.astimezone(local_tz)
            
            if lang == 'ru':
                time_format = local_time.strftime('%d.%m.%Y %H:%M')
            else:
                time_format = local_time.strftime('%m/%d/%Y %I:%M %p')
            
            if expected_type in parse_type:
                print(f"✅ ПРОЙДЕНО: '{time_str}' → {time_format} ({parse_type})")
                passed += 1
            else:
                print(f"❌ НЕ ПРОЙДЕНО: '{time_str}'")
                print(f"   Получено: {parse_type}, Ожидалось: {expected_type}")
        else:
            print(f"❌ НЕ ПРОЙДЕНО: '{time_str}' → не распознано")
    
    print(f"\n📊 ИТОГ: {passed}/{total} тестов пройдено")
    
    # Тест извлечения
    print("\n📝 ТЕСТ ИЗВЛЕЧЕНИЯ:")
    print("-" * 70)
    
    extraction_tests = [
        ("Pay bills on Monday at 9 AM", "en", "Monday at 9 AM"),
        ("Meeting with John tomorrow at 3 PM", "en", "tomorrow at 3 PM"),
        ("Позвонить маме в понедельник в 10 утра", "ru", "понедельник в 10 утра"),
        ("Сходить в магазин завтра в 18:00", "ru", "завтра в 18:00"),
    ]
    
    for text, lang, expected_time in extraction_tests:
        text_part, time_part = parser.extract_reminder_text(text, lang)
        print(f"📄 '{text}'")
        print(f"   Текст: '{text_part}'")
        print(f"   Время: '{time_part}'")
        
        if time_part == expected_time:
            print(f"   ✅ Время извлечено корректно")
        else:
            print(f"   ⚠️  Ожидалось: '{expected_time}'")
    
    print("\n" + "=" * 70)
    if passed == total:
        print("🎉 ВСЕ КРИТИЧЕСКИЕ ТЕСТЫ ПРОЙДЕНЫ! ПАРСЕР ГОТОВ!")
    else:
        print(f"⚠️  ПРОЙДЕНО {passed}/{total} ТЕСТОВ")
    print("=" * 70)

if __name__ == "__main__":
    run_final_test()
