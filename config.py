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
    MAX_TEXT_LENGTH = int(os.getenv('MAX_TEXT_LENGTH', '500'))  # ✅ ДОБАВЛЕНО
    DEFAULT_TIMEZONE = os.getenv('DEFAULT_TIMEZONE', 'Europe/Moscow')
    
    # Настройки парсера времени
    MAX_FUTURE_DAYS = int(os.getenv('MAX_FUTURE_DAYS', '1825'))  # 5 лет
    
    # Настройки восстановления
    RECOVERY_CHECK_INTERVAL = int(os.getenv('RECOVERY_INTERVAL', '300'))  # 5 минут
    MISSED_REMINDERS_HOURS = int(os.getenv('MISSED_REMINDERS_HOURS', '24'))  # Проверять пропущенные за последние 24 часа
    
    # Настройки планировщика
    CHECK_INTERVAL_MINUTES = int(os.getenv('CHECK_INTERVAL', '1'))  # Проверять каждую минуту
    
    # Логирование
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', 'bot.log')
    LOG_MAX_SIZE = int(os.getenv('LOG_MAX_SIZE', '10485760'))  # 10MB
    LOG_BACKUP_COUNT = int(os.getenv('LOG_BACKUP_COUNT', '5'))
    
    # Системные настройки
    DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
    TEST_MODE = os.getenv('TEST_MODE', 'False').lower() == 'true'
    
    @classmethod
    def validate(cls):
        """Проверка конфигурации"""
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN не установлен в .env файле")
        
        if cls.DEBUG:
            print("🔧 Режим отладки включен")
            cls.LOG_LEVEL = 'DEBUG'
        
        print("✅ Конфигурация загружена успешно")
