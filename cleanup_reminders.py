#!/usr/bin/env python3
"""
Скрипт для очистки старых напоминаний и исправления БД
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database
from datetime import datetime, timedelta
import pytz

def cleanup_database():
    """Очистить старые напоминания и исправить данные"""
    db = Database()
    
    print("🧹 Начинаю очистку БД...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Деактивируем старые разовые напоминания, которые уже прошли
        cursor.execute('''
            UPDATE reminders 
            SET is_active = 0
            WHERE repeat_type = 'once'
            AND next_remind_time_utc < datetime('now', '-1 day')
            AND is_active = 1
        ''')
        print(f"✅ Деактивировано {cursor.rowcount} старых разовых напоминаний")
        
        # 2. Исправляем next_remind_time_utc для активных напоминаний
        cursor.execute('''
            SELECT id, remind_time_utc, repeat_type
            FROM reminders 
            WHERE is_active = 1 
            AND (next_remind_time_utc IS NULL OR next_remind_time_utc = '')
        ''')
        
        rows = cursor.fetchall()
        for row in rows:
            reminder_id = row['id']
            remind_time = row['remind_time_utc']
            repeat_type = row['repeat_type']
            
            # Если remind_time - datetime, конвертируем в строку
            if isinstance(remind_time, datetime):
                remind_time_str = remind_time.isoformat()
            else:
                remind_time_str = str(remind_time)
            
            # Устанавливаем next_remind_time_utc = remind_time_utc
            cursor.execute('''
                UPDATE reminders 
                SET next_remind_time_utc = ?
                WHERE id = ?
            ''', (remind_time_str, reminder_id))
        
        print(f"✅ Исправлено {len(rows)} напоминаний с пустым next_remind_time_utc")
        
        # 3. Удаляем совсем старые напоминания (старше 30 дней)
        cursor.execute('''
            DELETE FROM reminders 
            WHERE created_at < datetime('now', '-30 days')
            AND is_active = 0
        ''')
        print(f"✅ Удалено {cursor.rowcount} очень старых напоминаний")
        
        # 4. Проверяем и исправляем timezone пользователей
        cursor.execute('''
            UPDATE users 
            SET timezone = 'Europe/Moscow'
            WHERE timezone IS NULL OR timezone = ''
        ''')
        print(f"✅ Исправлено {cursor.rowcount} пользователей без timezone")
        
        conn.commit()
    
    print("🎉 Очистка БД завершена!")

if __name__ == "__main__":
    cleanup_database()
