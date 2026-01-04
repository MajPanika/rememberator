import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Токен бота
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    
    # Админы (через запятую)
    ADMINS = [int(admin_id) for admin_id in os.getenv('ADMINS', '').split(',') if admin_id]
    
    # Настройки БД
    DB_NAME = os.getenv('DB_NAME', 'reminders.db')
    DB_BACKUP_DIR = os.getenv('DB_BACKUP_DIR', 'backups')
    
    # Настройки бота
    MAX_REMINDERS_PER_USER = int(os.getenv('MAX_REMINDERS', '100'))
    DEFAULT_TIMEZONE = os.getenv('DEFAULT_TIMEZONE', 'Europe/Moscow')
    
    # Настройки восстановления
    RECOVERY_CHECK_INTERVAL = int(os.getenv('RECOVERY_INTERVAL', '300'))  # 5 минут
    
    # Логирование
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', 'bot.log')
    
    @classmethod
    def validate(cls):
        """Проверка конфигурации"""
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN не установлен в .env файле")
        print("✅ Конфигурация загружена успешно")
