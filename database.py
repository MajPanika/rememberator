import sqlite3
import json
import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any
import os
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_name: str = 'reminders.db'):
        self.db_name = db_name
        self.init_db()
    
    @contextmanager
    def get_connection(self):
        """Контекстный менеджер для соединения с БД"""
        conn = sqlite3.connect(self.db_name, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def init_db(self):
        """Инициализация таблиц БД"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    language_code TEXT DEFAULT 'ru',
                    timezone TEXT DEFAULT 'Europe/Moscow',
                    timezone_offset INTEGER,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reminder_count INTEGER DEFAULT 0
                )
            ''')
            
            # Таблица напоминаний
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    text TEXT NOT NULL,
                    remind_time_utc TIMESTAMP NOT NULL,
                    repeat_type TEXT DEFAULT 'once',
                    repeat_days TEXT,
                    repeat_interval INTEGER DEFAULT 1,
                    is_active BOOLEAN DEFAULT 1,
                    is_paused BOOLEAN DEFAULT 0,
                    notified_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    timezone TEXT,
                    next_remind_time_utc TIMESTAMP,
                    last_processed TIMESTAMP,
                    missed_count INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # Таблица админов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    level INTEGER DEFAULT 1
                )
            ''')
            
            # Таблица логов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bot_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    log_type TEXT,
                    user_id INTEGER,
                    message TEXT,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица настроек бота
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Индексы для производительности
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_reminders_time 
                ON reminders(remind_time_utc) 
                WHERE is_active = 1 AND is_paused = 0
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_reminders_user 
                ON reminders(user_id, is_active)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_users_active 
                ON users(last_active)
            ''')
            
            logger.info("✅ База данных инициализирована")
    
    # ===== МЕТОДЫ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ =====
    
    def add_user(self, user_id: int, username: str, first_name: str, 
                 last_name: str = None, language_code: str = 'ru',
                 timezone_offset: int = None):
        """Добавление нового пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO users 
                (user_id, username, first_name, last_name, language_code, timezone_offset)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name, language_code, timezone_offset))
            
            if cursor.rowcount > 0:
                logger.info(f"👤 Добавлен новый пользователь: {user_id}")
                return True
            else:
                # Обновляем время последней активности
                cursor.execute('''
                    UPDATE users 
                    SET last_active = CURRENT_TIMESTAMP 
                    WHERE user_id = ?
                ''', (user_id,))
                return False
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        """Получить информацию о пользователе"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update_user_timezone(self, user_id: int, timezone: str, offset: int = None):
        """Обновить часовой пояс пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if offset is not None:
                cursor.execute('''
                    UPDATE users 
                    SET timezone = ?, timezone_offset = ?
                    WHERE user_id = ?
                ''', (timezone, offset, user_id))
            else:
                cursor.execute('''
                    UPDATE users 
                    SET timezone = ?
                    WHERE user_id = ?
                ''', (timezone, user_id))
    
    def update_user_language(self, user_id: int, language_code: str):
        """Обновить язык пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users 
                SET language_code = ?
                WHERE user_id = ?
            ''', (language_code, user_id))
    
    def get_user_reminder_count(self, user_id: int) -> int:
        """Получить количество напоминаний пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM reminders 
                WHERE user_id = ? AND is_active = 1
            ''', (user_id,))
            return cursor.fetchone()[0]
    
    # ===== МЕТОДЫ ДЛЯ НАПОМИНАНИЙ =====
    
    def add_reminder(self, user_id: int, text: str, remind_time_utc: datetime,
                    repeat_type: str = 'once', repeat_days: str = None,
                    repeat_interval: int = 1, timezone: str = 'Europe/Moscow') -> int:
        """Добавить новое напоминание"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Проверяем лимит
            count = self.get_user_reminder_count(user_id)
            from config import Config
            if count >= Config.MAX_REMINDERS_PER_USER:
                raise ValueError(f"Достигнут лимит в {Config.MAX_REMINDERS_PER_USER} напоминаний")
            
            # Определяем следующее время для повторяющихся
            next_remind_time = remind_time_utc
            if repeat_type != 'once':
                next_remind_time = self._calculate_next_remind_time(
                    remind_time_utc, repeat_type, repeat_days, repeat_interval
                )
            
            cursor.execute('''
                INSERT INTO reminders 
                (user_id, text, remind_time_utc, repeat_type, repeat_days, 
                 repeat_interval, timezone, next_remind_time_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, text, remind_time_utc, repeat_type, repeat_days, 
                  repeat_interval, timezone, next_remind_time))
            
            reminder_id = cursor.lastrowid
            
            # Обновляем счетчик напоминаний пользователя
            cursor.execute('''
                UPDATE users 
                SET reminder_count = reminder_count + 1 
                WHERE user_id = ?
            ''', (user_id,))
            
            logger.info(f"🔔 Добавлено напоминание {reminder_id} для пользователя {user_id}")
            return reminder_id
    
    def get_user_reminders(self, user_id: int, active_only: bool = True) -> List[Dict]:
        """Получить напоминания пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if active_only:
                cursor.execute('''
                    SELECT * FROM reminders 
                    WHERE user_id = ? AND is_active = 1 AND is_paused = 0
                    ORDER BY next_remind_time_utc
                ''', (user_id,))
            else:
                cursor.execute('''
                    SELECT * FROM reminders 
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                ''', (user_id,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_due_reminders(self) -> List[Dict]:
        """Получить напоминания, которые нужно отправить сейчас"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT r.*, u.timezone, u.language_code 
                FROM reminders r
                JOIN users u ON r.user_id = u.user_id
                WHERE r.is_active = 1 
                AND r.is_paused = 0
                AND r.next_remind_time_utc <= datetime('now')
                ORDER BY r.next_remind_time_utc
            ''')
            return [dict(row) for row in cursor.fetchall()]
    
    def mark_reminder_sent(self, reminder_id: int):
        """Пометить напоминание как отправленное"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE reminders 
                SET notified_count = notified_count + 1,
                    last_processed = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (reminder_id,))
            
            # Для повторяющихся напоминаний рассчитываем следующее время
            cursor.execute('''
                SELECT repeat_type, repeat_days, repeat_interval, next_remind_time_utc
                FROM reminders 
                WHERE id = ?
            ''', (reminder_id,))
            
            row = cursor.fetchone()
            if row and row['repeat_type'] != 'once':
                next_time = self._calculate_next_remind_time(
                    row['next_remind_time_utc'],
                    row['repeat_type'],
                    row['repeat_days'],
                    row['repeat_interval']
                )
                cursor.execute('''
                    UPDATE reminders 
                    SET next_remind_time_utc = ?
                    WHERE id = ?
                ''', (next_time, reminder_id))
    
    def delete_reminder(self, reminder_id: int, user_id: int) -> bool:
        """Удалить напоминание"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM reminders 
                WHERE id = ? AND user_id = ?
            ''', (reminder_id, user_id))
            
            if cursor.rowcount > 0:
                cursor.execute('''
                    UPDATE users 
                    SET reminder_count = reminder_count - 1 
                    WHERE user_id = ?
                ''', (user_id,))
                return True
            return False
    
    def pause_reminder(self, reminder_id: int, user_id: int) -> bool:
        """Поставить напоминание на паузу"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE reminders 
                SET is_paused = 1 
                WHERE id = ? AND user_id = ?
            ''', (reminder_id, user_id))
            return cursor.rowcount > 0
    
    def resume_reminder(self, reminder_id: int, user_id: int) -> bool:
        """Возобновить напоминание"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE reminders 
                SET is_paused = 0 
                WHERE id = ? AND user_id = ?
            ''', (reminder_id, user_id))
            return cursor.rowcount > 0
    
    # ===== МЕТОДЫ ДЛЯ АДМИНОВ =====
    
    def add_admin(self, user_id: int, username: str = None, level: int = 1):
        """Добавить администратора"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO admins (user_id, username, level)
                VALUES (?, ?, ?)
            ''', (user_id, username, level))
    
    def is_admin(self, user_id: int) -> bool:
        """Проверить, является ли пользователь админом"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1 FROM admins WHERE user_id = ?', (user_id,))
            return cursor.fetchone() is not None
    
    def get_all_users(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Получить список всех пользователей"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM users 
                ORDER BY registered_at DESC 
                LIMIT ? OFFSET ?
            ''', (limit, offset))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_bot_statistics(self) -> Dict[str, Any]:
        """Получить статистику бота"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            stats = {}
            
            # Общая статистика
            cursor.execute('SELECT COUNT(*) FROM users')
            stats['total_users'] = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT COUNT(*) FROM users 
                WHERE last_active > datetime('now', '-7 days')
            ''')
            stats['active_week'] = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT COUNT(*) FROM users 
                WHERE registered_at > datetime('now', '-1 days')
            ''')
            stats['new_today'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM reminders')
            stats['total_reminders'] = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT COUNT(*) FROM reminders 
                WHERE is_active = 1 AND is_paused = 0
            ''')
            stats['active_reminders'] = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT COUNT(*) FROM reminders 
                WHERE repeat_type != 'once'
            ''')
            stats['repeating_reminders'] = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT COUNT(*) FROM reminders 
                WHERE is_paused = 1
            ''')
            stats['paused_reminders'] = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT COUNT(*) FROM reminders 
                WHERE created_at > datetime('now', '-1 days')
            ''')
            stats['created_today'] = cursor.fetchone()[0]
            
            return stats
    
    # ===== ВОССТАНОВЛЕНИЕ =====
    
    def get_missed_reminders(self, hours_back: int = 24) -> List[Dict]:
        """Получить пропущенные напоминания"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT r.*, u.timezone, u.language_code 
                FROM reminders r
                JOIN users u ON r.user_id = u.user_id
                WHERE r.is_active = 1 
                AND r.is_paused = 0
                AND r.next_remind_time_utc <= datetime('now')
                AND r.next_remind_time_utc >= datetime('now', ?)
                AND (r.last_processed IS NULL OR r.last_processed < r.next_remind_time_utc)
            ''', (f'-{hours_back} hours',))
            return [dict(row) for row in cursor.fetchall()]
    
    def mark_recovered(self, reminder_id: int):
        """Пометить напоминание как восстановленное"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE reminders 
                SET missed_count = missed_count + 1,
                    last_processed = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (reminder_id,))
    
    # ===== ЛОГИРОВАНИЕ =====
    
    def log_event(self, log_type: str, user_id: int = None, 
                  message: str = '', details: str = ''):
        """Записать событие в лог"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO bot_logs (log_type, user_id, message, details)
                VALUES (?, ?, ?, ?)
            ''', (log_type, user_id, message, details))
    
    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====
    
    def _calculate_next_remind_time(self, current_time, repeat_type, 
                                   repeat_days, repeat_interval):
        """Рассчитать следующее время для повторяющегося напоминания"""
        from datetime import datetime, timedelta
        
        if repeat_type == 'daily':
            return current_time + timedelta(days=repeat_interval)
        elif repeat_type == 'weekly':
            # current_time должен быть смещен на 7 дней
            return current_time + timedelta(days=7)
        else:
            return current_time
    
    def backup_database(self):
        """Создать резервную копию БД"""
        import shutil
        from datetime import datetime
        
        backup_dir = 'backups'
        os.makedirs(backup_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"{backup_dir}/reminders_backup_{timestamp}.db"
        
        shutil.copy2(self.db_name, backup_name)
        logger.info(f"✅ Создана резервная копия: {backup_name}")
        
        # Удаляем старые бэкапы (оставляем последние 10)
        backups = sorted([f for f in os.listdir(backup_dir) if f.endswith('.db')])
        if len(backups) > 10:
            for old_backup in backups[:-10]:
                os.remove(os.path.join(backup_dir, old_backup))
    
    def close(self):
        """Закрыть соединение с БД"""
        pass  # Используем контекстный менеджер, поэтому не нужно
