#!/usr/bin/env python3
"""
Database module for Reminder Pro Bot
"""

import sqlite3
import json
import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any
import os
from contextlib import contextmanager

# ===== АДАПТЕРЫ ДЛЯ DATETIME =====
# Регистрируем адаптеры для корректной работы с datetime в SQLite

def adapt_datetime(dt: datetime) -> str:
    """Конвертируем datetime в строку ISO формата для SQLite"""
    return dt.isoformat()

def convert_datetime(text: bytes) -> datetime:
    """Конвертируем строку из SQLite обратно в datetime"""
    try:
        # Пробуем ISO формат
        text_str = text.decode('utf-8')
        return datetime.fromisoformat(text_str)
    except (ValueError, UnicodeDecodeError) as e:
        # Если не получается, логируем и возвращаем текущее время
        logging.warning(f"Cannot convert datetime: {text}, error: {e}")
        return datetime.now()

# Регистрируем конвертеры для SQLite
sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_converter("TIMESTAMP", convert_datetime)

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_name: str = 'reminders.db'):
        """Инициализация базы данных"""
        self.db_name = db_name
        self.init_db()
    
    @contextmanager
    def get_connection(self):
        """
        Контекстный менеджер для соединения с БД.
        Автоматически управляет открытием и закрытием соединения.
        """
        # Используем detect_types для автоматической конвертации TIMESTAMP
        conn = sqlite3.connect(
            self.db_name, 
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            timeout=10,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row  # Возвращаем строки как словари
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise e
        finally:
            conn.close()
    
    def init_db(self):
        """Инициализация всех таблиц базы данных"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # ===== ТАБЛИЦА ПОЛЬЗОВАТЕЛЕЙ =====
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
            
            # ===== ТАБЛИЦА НАПОМИНАНИЙ =====
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
            
            # ===== ТАБЛИЦА АДМИНИСТРАТОРОВ =====
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    level INTEGER DEFAULT 1
                )
            ''')
            
            # ===== ТАБЛИЦА ЛОГОВ =====
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
            
            # ===== ТАБЛИЦА НАСТРОЕК БОТА =====
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # ===== ИНДЕКСЫ ДЛЯ ПРОИЗВОДИТЕЛЬНОСТИ =====
            
            # Удаляем старые индексы если они есть (на случай пересоздания)
            cursor.execute('DROP INDEX IF EXISTS idx_reminders_time')
            cursor.execute('DROP INDEX IF EXISTS idx_reminders_user')
            cursor.execute('DROP INDEX IF EXISTS idx_users_active')
            
            # Индекс для быстрого поиска активных напоминаний по времени
            cursor.execute('''
                CREATE INDEX idx_reminders_time ON reminders(next_remind_time_utc)
                WHERE is_active = 1 AND is_paused = 0
            ''')
            
            # Индекс для поиска напоминаний пользователя
            cursor.execute('''
                CREATE INDEX idx_reminders_user ON reminders(user_id, is_active)
            ''')
            
            # Индекс для поиска активных пользователей
            cursor.execute('''
                CREATE INDEX idx_users_active ON users(last_active)
            ''')
            
            logger.info("✅ База данных инициализирована")
    
    # ===== МЕТОДЫ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ =====
    def get_all_admins(self):
        """Получить всех администраторов"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM admins ORDER BY added_at DESC
            ''')
            admins = cursor.fetchall()
            
            # Преобразуем в список словарей
            result = []
            for admin in admins:
                result.append({
                    'user_id': admin[0],
                    'username': admin[1],
                    'level': admin[2],
                    'added_at': admin[3],
                    'notes': admin[4]
                })
            return result
    
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
                # Обновляем время последней активности для существующего пользователя
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
            logger.info(f"🕒 Обновлен часовой пояс пользователя {user_id}: {timezone}")
    
    def update_user_language(self, user_id: int, language_code: str):
        """Обновить язык пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users 
                SET language_code = ?
                WHERE user_id = ?
            ''', (language_code, user_id))
            logger.info(f"🌐 Обновлен язык пользователя {user_id}: {language_code}")
    
    def get_user_reminder_count(self, user_id: int) -> int:
        """Получить количество активных напоминаний пользователя"""
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
            
            # ✅ ОБНУЛЯЕМ МИКРОСЕКУНДЫ ЕЩЕ РАЗ (на всякий случай)
            remind_time_utc = remind_time_utc.replace(microsecond=0)
            
            # Определяем следующее время для повторяющихся напоминаний
            next_remind_time = remind_time_utc
            if repeat_type != 'once':
                next_remind_time = self._calculate_next_remind_time(
                    remind_time_utc, repeat_type, repeat_days, repeat_interval
                )
                # ✅ И для следующего времени тоже обнуляем
                if next_remind_time:
                    next_remind_time = next_remind_time.replace(microsecond=0)
            
            # ✅ Сохраняем как строку БЕЗ часового пояса в формате SQLite
            # SQLite прекрасно работает с таким форматом
            remind_time_str = remind_time_utc.strftime('%Y-%m-%d %H:%M:%S')
            next_time_str = next_remind_time.strftime('%Y-%m-%d %H:%M:%S') if next_remind_time else remind_time_str
            
            # Добавляем напоминание в БД
            cursor.execute('''
                INSERT INTO reminders 
                (user_id, text, remind_time_utc, repeat_type, repeat_days, 
                 repeat_interval, timezone, next_remind_time_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, text, remind_time_str, repeat_type, repeat_days, 
                  repeat_interval, timezone, next_time_str))
            
            reminder_id = cursor.lastrowid
            
            # Обновляем счетчик напоминаний пользователя
            cursor.execute('''
                UPDATE users 
                SET reminder_count = reminder_count + 1 
                WHERE user_id = ?
            ''', (user_id,))
            
            logger.info(f"🔔 Добавлено напоминание {reminder_id} для пользователя {user_id}")
            logger.info(f"   Сохранено время (UTC, без микросекунд): {remind_time_str}")
            
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
            
            results = cursor.fetchall()
            
            # Конвертируем Row в dict
            reminders = [dict(row) for row in results]
            
            # Логируем для отладки
            if reminders:
                logger.info(f"📋 Найдено {len(reminders)} напоминаний для пользователя {user_id}")
            
            return reminders
    
    def get_due_reminders(self) -> List[Dict]:
        """Получить напоминания, которые нужно отправить сейчас"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Простой запрос - теперь времена в одном формате
            cursor.execute('''
                SELECT r.*, u.timezone, u.language_code 
                FROM reminders r
                JOIN users u ON r.user_id = u.user_id
                WHERE r.is_active = 1 
                AND r.is_paused = 0
                AND r.next_remind_time_utc <= datetime('now')
                ORDER BY r.next_remind_time_utc
            ''')
            
            results = cursor.fetchall()
            reminders = [dict(row) for row in results]
            
            if reminders:
                logger.info(f"🎯 Найдено {len(reminders)} напоминаний для отправки")
                for reminder in reminders:
                    logger.info(f"   • ID {reminder['id']}: {reminder['text'][:30]}... "
                              f"в {reminder.get('next_remind_time_utc')}")
            else:
                logger.info("📭 Нет напоминаний для отправки")
            
            return reminders
    
    def mark_reminder_sent(self, reminder_id: int):
        """Пометить напоминание как отправленное и обновить следующее время"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Сначала получаем информацию о напоминании
            cursor.execute('''
                SELECT repeat_type, next_remind_time_utc, remind_time_utc
                FROM reminders 
                WHERE id = ? AND is_active = 1
            ''', (reminder_id,))
            
            row = cursor.fetchone()
            if not row:
                logger.warning(f"⚠️ Напоминание {reminder_id} не найдено или не активно")
                return
            
            repeat_type = row['repeat_type']
            next_remind_time = row['next_remind_time_utc']
            
            # Для разовых напоминаний - деактивируем
            if repeat_type == 'once':
                cursor.execute('''
                    UPDATE reminders 
                    SET is_active = 0,
                        notified_count = notified_count + 1,
                        last_processed = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (reminder_id,))
                logger.info(f"✅ Разовое напоминание {reminder_id} выполнено и деактивировано")
            
            # Для повторяющихся - обновляем следующее время
            else:
                cursor.execute('''
                    SELECT repeat_type, repeat_days, repeat_interval
                    FROM reminders 
                    WHERE id = ?
                ''', (reminder_id,))
                
                repeat_info = cursor.fetchone()
                if repeat_info:
                    # Рассчитываем следующее время напоминания
                    next_time = self._calculate_next_remind_time(
                        next_remind_time,
                        repeat_info['repeat_type'],
                        repeat_info['repeat_days'],
                        repeat_info['repeat_interval']
                    )
                    
                    # Обновляем запись
                    cursor.execute('''
                        UPDATE reminders 
                        SET notified_count = notified_count + 1,
                            last_processed = CURRENT_TIMESTAMP,
                            next_remind_time_utc = ?
                        WHERE id = ?
                    ''', (next_time, reminder_id))
                    
                    logger.info(f"🔄 Обновлено повторяющееся напоминание {reminder_id}, "
                               f"следующее время: {next_time}")
    
    def delete_reminder(self, reminder_id: int, user_id: int) -> bool:
        """Удалить напоминание"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM reminders 
                WHERE id = ? AND user_id = ?
            ''', (reminder_id, user_id))
            
            if cursor.rowcount > 0:
                # Обновляем счетчик напоминаний пользователя
                cursor.execute('''
                    UPDATE users 
                    SET reminder_count = reminder_count - 1 
                    WHERE user_id = ?
                ''', (user_id,))
                logger.info(f"🗑️ Удалено напоминание {reminder_id} пользователя {user_id}")
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
            success = cursor.rowcount > 0
            if success:
                logger.info(f"⏸️ Напоминание {reminder_id} поставлено на паузу")
            return success
    
    def resume_reminder(self, reminder_id: int, user_id: int) -> bool:
        """Возобновить напоминание"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE reminders 
                SET is_paused = 0 
                WHERE id = ? AND user_id = ?
            ''', (reminder_id, user_id))
            success = cursor.rowcount > 0
            if success:
                logger.info(f"▶️ Напоминание {reminder_id} возобновлено")
            return success
    
    # ===== МЕТОДЫ ДЛЯ АДМИНИСТРАТОРОВ =====
    
    def add_admin(self, user_id: int, username: str = None, level: int = 1):
        """Добавить администратора"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO admins (user_id, username, level)
                VALUES (?, ?, ?)
            ''', (user_id, username, level))
            logger.info(f"👑 Добавлен администратор: {user_id}")
    
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
    
    # ===== ВОССТАНОВЛЕНИЕ ПОСЛЕ СБОЕВ =====
    
    def get_missed_reminders(self, hours_back: int = 24) -> List[Dict]:
        """Получить пропущенные напоминания за последние N часов"""
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
            ''', (f'-{hours_back} hours',))
            return [dict(row) for row in cursor.fetchall()]
    
    def mark_recovered(self, reminder_id: int):
        """Пометить напоминание как восстановленное после сбоя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE reminders 
                SET missed_count = missed_count + 1,
                    last_processed = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (reminder_id,))
            logger.info(f"🔄 Напоминание {reminder_id} помечено как восстановленное")
    
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
            logger.debug(f"📝 Логировано событие: {log_type}, пользователь: {user_id}")
    
    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====
    
    def _calculate_next_remind_time(self, current_time: datetime, repeat_type: str, 
                                   repeat_days: str, repeat_interval: int) -> datetime:
        """
        Рассчитать следующее время для повторяющегося напоминания.
        
        Args:
            current_time: Текущее время напоминания
            repeat_type: Тип повторения ('daily', 'weekly')
            repeat_days: Дни недели для еженедельных напоминаний (например, "0,2,4")
            repeat_interval: Интервал повторения (например, 2 для каждого второго дня)
            
        Returns:
            datetime: Следующее время напоминания
        """
        try:
            if repeat_type == 'daily':
                # Ежедневное: добавляем дни
                next_time = current_time + timedelta(days=repeat_interval)
                
            elif repeat_type == 'weekly':
                if repeat_days:
                    # Получаем список дней недели (0=понедельник, 6=воскресенье)
                    days_list = [int(d) for d in repeat_days.split(',')]
                    
                    # Текущий день недели
                    current_weekday = current_time.weekday()
                    
                    # Ищем следующий день из списка
                    next_day = None
                    for day in sorted(days_list):
                        if day > current_weekday:
                            next_day = day
                            break
                    
                    # Если не нашли в этой неделе, берем первый день следующей недели
                    if next_day is None:
                        next_day = min(days_list)
                        days_ahead = 7 - current_weekday + next_day
                    else:
                        days_ahead = next_day - current_weekday
                    
                    next_time = current_time + timedelta(days=days_ahead)
                else:
                    # Если дни не указаны, просто +7 дней
                    next_time = current_time + timedelta(days=7)
            
            else:
                # Для разовых или неизвестных типов возвращаем None
                return None
                
            next_time = next_time.replace(microsecond=0)
            return next_time
            
        except Exception as e:
            logger.error(f"Ошибка расчета следующего времени: {e}")
            # В случае ошибки возвращаем время через день
            return (current_time + timedelta(days=1)).replace(microsecond=0)
    
    def backup_database(self):
        """Создать резервную копию базы данных"""
        import shutil
        from datetime import datetime
        
        backup_dir = 'backups'
        os.makedirs(backup_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"{backup_dir}/reminders_backup_{timestamp}.db"
        
        try:
            shutil.copy2(self.db_name, backup_name)
            logger.info(f"💾 Создана резервная копия: {backup_name}")
            
            # Удаляем старые бэкапы (оставляем последние 10)
            backups = sorted([f for f in os.listdir(backup_dir) if f.endswith('.db')])
            if len(backups) > 10:
                for old_backup in backups[:-10]:
                    os.remove(os.path.join(backup_dir, old_backup))
                    logger.debug(f"🗑️ Удален старый бэкап: {old_backup}")
                    
        except Exception as e:
            logger.error(f"❌ Ошибка создания резервной копии: {e}")
    
    def close(self):
        """Закрыть соединение с БД (для совместимости)"""
        pass  # Используем контекстный менеджер, поэтому не нужно явно закрывать
