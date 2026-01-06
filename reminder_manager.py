"""
Менеджер напоминаний для обработки повторяющихся напоминаний
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
import pytz
from database import Database

logger = logging.getLogger(__name__)

class ReminderManager:
    def __init__(self, db: Database):
        self.db = db
    
    def calculate_next_remind_time(self, reminder: Dict[str, Any]) -> datetime:
        """Рассчитать следующее время для повторяющегося напоминания"""
        current_time = datetime.fromisoformat(reminder['next_remind_time_utc'])
        
        if reminder['repeat_type'] == 'daily':
            # Ежедневное: добавляем 1 день
            return current_time + timedelta(days=1)
        
        elif reminder['repeat_type'] == 'weekly':
            # Еженедельное: следующий выбранный день
            days_list = [int(d) for d in reminder['repeat_days'].split(',')] if reminder['repeat_days'] else []
            if not days_list:
                return current_time + timedelta(days=7)
            
            # Находим следующий день
            current_weekday = current_time.weekday()
            future_days = []
            
            for day in days_list:
                days_ahead = day - current_weekday
                if days_ahead <= 0:
                    days_ahead += 7
                future_days.append(days_ahead)
            
            next_days = min(future_days)
            return current_time + timedelta(days=next_days)
        
        # Для разовых напоминаний или неизвестного типа
        return current_time
    
    def process_due_reminders(self, bot):
        """Обработать напоминания, которые нужно отправить"""
        try:
            due_reminders = self.db.get_due_reminders()
            
            if not due_reminders:
                return
            
            logger.info(f"Processing {len(due_reminders)} due reminders")
            
            for reminder in due_reminders:
                try:
                    # Отправляем напоминание (эта функция будет в bot.py)
                    from bot import send_reminder_notification
                    # Мы добавим эту функцию позже
                    
                    # Пока просто логируем
                    logger.info(f"Should send reminder {reminder['id']} to user {reminder['user_id']}")
                    
                    # Помечаем как отправленное и обновляем следующее время
                    self.db.mark_reminder_sent(reminder['id'])
                    
                    # Для повторяющихся обновляем следующее время
                    if reminder['repeat_type'] != 'once':
                        next_time = self.calculate_next_remind_time(reminder)
                        with self.db.get_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute('''
                                UPDATE reminders 
                                SET next_remind_time_utc = ?
                                WHERE id = ?
                            ''', (next_time.isoformat(), reminder['id']))
                    
                except Exception as e:
                    logger.error(f"Failed to process reminder {reminder['id']}: {e}")
                    # Увеличиваем счетчик ошибок
                    with self.db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute('''
                            UPDATE reminders 
                            SET error_count = error_count + 1 
                            WHERE id = ?
                        ''', (reminder['id'],))
            
        except Exception as e:
            logger.error(f"Error in process_due_reminders: {e}")
