# Файл reset_db.py
import os
import sqlite3


# Удаляем старую БД
if os.path.exists('reminders.db'):
    os.remove('reminders.db')
    print("🗑️ Старая БД удалена")

# Создаем новую
from database import Database
db = Database()
print("✅ Новая БД создана")
