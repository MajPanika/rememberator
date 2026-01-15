#!/usr/bin/env python3
"""
Тест парсера времени
"""

import sys
sys.path.append('.')

from utils.time_parser import TimeParser
import pytz
from datetime import datetime

parser = TimeParser()
timezone = 'Europe/Moscow'
base_time = datetime.now(pytz.timezone(timezone))

# Создаем тестовые даты для проверки
test_date = datetime(2024, 1, 11, 10, 0, tzinfo=pytz.timezone(timezone))

test_cases = [
    ("17.01 16-00 театр в 18-00", "17 января 16-00", "театр в 18-00"),
    ("16-00 17.01 театр в 18-00", "17 января 16-00", "театр в 18-00"),
    ("завтра 15:30 встреча", "завтра 15:30", "встреча"),
    ("сегодня 20-00 ужин", "сегодня 20-00", "ужин"),
    ("через 2 часа позвонить", "через 2 часа", "позвонить"),
    ("понедельник 9:00 совещание", "понедельник 9:00", "совещание"),
    ("17.01.2024 16:00 конференция", "17.01.2024 16:00", "конференция"),
    ("в 8 вечера кино", "8 вечера", "кино"),
    ("4 PM meeting tomorrow", "tomorrow 4 PM", "meeting"),
    ("in 3 hours call", "in 3 hours", "call"),
]

print("🔍 Тестирование парсера времени")
print("=" * 60)

all_passed = True

for test_input, expected_time, expected_text in test_cases:
    print(f"\n📝 Ввод: '{test_input}'")
    
    # Определяем язык
    language = 'ru' if any(cyr in test_input for cyr in 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя') else 'en'
    
    # Извлечение времени и текста
    time_part, text_part = parser.extract_best_time_and_text(test_input, language)
    print(f"   Язык: {language}")
    print(f"   Время: '{time_part}' (ожидалось: '{expected_time}')")
    print(f"   Текст: '{text_part}' (ожидалось: '{expected_text}')")
    
    # Проверяем корректность извлечения
    time_ok = time_part == expected_time
    text_ok = text_part == expected_text
    
    if not time_ok or not text_ok:
        print(f"   ❌ Ошибка извлечения!")
        all_passed = False
    
    # Парсинг времени
    if time_part:
        parsed_time, parse_type, extra = parser.parse(time_part, language, timezone, test_date)
        if parsed_time:
            print(f"   ✅ Распознано: {parsed_time} ({parse_type})")
        else:
            print(f"   ❌ Не распознано время: '{time_part}'")
            all_passed = False
    else:
        print(f"   ⚠️ Время не извлечено")

print("\n" + "=" * 60)
if all_passed:
    print("✅ Все тесты прошли успешно!")
else:
    print("❌ Есть проблемы с парсером!")
