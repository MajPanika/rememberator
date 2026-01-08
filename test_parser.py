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

test_cases = [
    "11 января 16-00 театр в 18-00",
    "16-00 11 января театр в 18-00", 
    "завтра 15:30",
    "сегодня 20.00",
    "через 2 часа",
    "понедельник 9:00",
    "11.01.2024 16:00",
    "в 8 вечера",
]

print("🔍 Тестирование парсера времени")
print("=" * 60)

for test in test_cases:
    print(f"\n📝 Ввод: '{test}'")
    
    # Извлечение времени и текста
    time_part, text_part = parser.extract_time_and_text(test, 'ru')
    print(f"   Время: '{time_part}'")
    print(f"   Текст: '{text_part}'")
    
    # Парсинг времени
    parsed_time, parse_type, extra = parser.parse(time_part, 'ru', timezone, base_time)
    if parsed_time:
        print(f"   Результат: {parsed_time} ({parse_type})")
    else:
        print(f"   ❌ Не распознано")
