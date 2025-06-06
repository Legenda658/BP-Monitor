import os
import logging
import asyncio
import schedule
import time
from datetime import datetime, timedelta
import pandas as pd
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import pytz
import threading
import sys
load_dotenv()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
MOSCOW_TZ = pytz.timezone('Europe/Moscow')
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
def init_db():
    try:
        pressure_file = os.path.join(SCRIPT_DIR, 'pressure_data.csv')
        meds_file = os.path.join(SCRIPT_DIR, 'medications.csv')
        if not os.path.exists(pressure_file):
            df = pd.DataFrame(columns=['user_id', 'date', 'systolic', 'diastolic', 'pulse', 'notes'])
            df.to_csv(pressure_file, index=False)
            logger.info("Создан файл pressure_data.csv")
        if not os.path.exists(meds_file):
            df = pd.DataFrame(columns=['user_id', 'medication_name', 'time', 'frequency'])
            df.to_csv(meds_file, index=False)
            logger.info("Создан файл medications.csv")
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {e}")
        sys.exit(1)
class MedicationReminder:
    def __init__(self, bot_token):
        self.bot = Bot(token=bot_token)
        self.running = False
        self.loop = None
        self.thread = None
    async def send_reminder(self, user_id, medication_name, time_str):
        try:
            message = (
                f"⏰ Напоминание!\n\n"
                f"Пора принять лекарство:\n"
                f"💊 {medication_name}\n"
                f"🕒 Время (МСК): {time_str}"
            )
            await self.bot.send_message(chat_id=user_id, text=message)
            logger.info(f"Отправлено напоминание пользователю {user_id} о приеме {medication_name}")
        except Exception as e:
            logger.error(f"Ошибка отправки напоминания: {e}")
    def check_medications(self):
        try:
            current_time = datetime.now(MOSCOW_TZ).strftime('%H:%M')
            logger.info(f"Проверка напоминаний. Текущее время (МСК): {current_time}")
            meds_file = os.path.join(SCRIPT_DIR, 'medications.csv')
            df = pd.read_csv(meds_file)
            for _, row in df.iterrows():
                if row['time'] == current_time:
                    logger.info(f"Найдено напоминание для времени {current_time}")
                    asyncio.run_coroutine_threadsafe(
                        self.send_reminder(
                            row['user_id'],
                            row['medication_name'],
                            row['time']
                        ),
                        self.loop
                    )
        except Exception as e:
            logger.error(f"Ошибка проверки лекарств: {e}")
    def run_async_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self.run_async_loop)
        self.thread.daemon = True
        self.thread.start()
        schedule.every().minute.do(self.check_medications)
        logger.info("Сервис напоминаний запущен")
        while self.running:
            schedule.run_pending()
            time.sleep(1)
    def stop(self):
        self.running = False
        schedule.clear()
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread:
            self.thread.join()
        logger.info("Сервис напоминаний остановлен")
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "👋 Привет! Я бот для контроля давления и приема лекарств.\n\n"
        "Доступные команды:\n"
        "/pressure - Записать показатели давления\n"
        "/medication - Добавить лекарство и напоминание\n"
        "/history - Показать историю измерений\n"
        "/note - Добавить заметку к последнему измерению\n"
        "/stats - Показать статистику за неделю\n"
        "/export - Экспортировать данные в Excel\n"
        "/test - Проверить работоспособность бота"
    )
    await update.message.reply_text(help_text)
async def pressure_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Введите показатели давления в формате:\n"
        "систолическое диастолическое пульс\n"
        "Например: 120 80 72"
    )
async def medication_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Добавить лекарство", callback_data="med_add")],
        [InlineKeyboardButton("📋 Список лекарств", callback_data="med_list")],
        [InlineKeyboardButton("❌ Удалить лекарство", callback_data="med_delete")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "💊 Управление лекарствами:",
        reply_markup=reply_markup
    )
async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        df = pd.read_csv(os.path.join(SCRIPT_DIR, 'pressure_data.csv'))
        user_data = df[df['user_id'] == user_id].tail(10)
        if user_data.empty:
            await update.message.reply_text("У вас пока нет записей о давлении.")
            return
        message = "📊 Последние 10 измерений:\n\n"
        for _, row in user_data.iterrows():
            message += (
                f"Дата: {row['date']}\n"
                f"Давление: {row['systolic']}/{row['diastolic']}\n"
                f"Пульс: {row['pulse']}\n"
                f"Заметка: {row['notes'] if pd.notna(row['notes']) else 'Нет'}\n"
                f"-------------------\n"
            )
        await update.message.reply_text(message)
    except Exception as e:
        logger.error(f"Ошибка при получении истории: {e}")
        await update.message.reply_text("Произошла ошибка при получении истории.")
async def note_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        df = pd.read_csv(os.path.join(SCRIPT_DIR, 'pressure_data.csv'))
        user_data = df[df['user_id'] == user_id]
        if user_data.empty:
            await update.message.reply_text("У вас пока нет записей о давлении.")
            return
        last_record = user_data.iloc[-1]
        context.user_data['last_record'] = last_record
        await update.message.reply_text(
            f"Последнее измерение:\n"
            f"Дата: {last_record['date']}\n"
            f"Давление: {last_record['systolic']}/{last_record['diastolic']}\n"
            f"Пульс: {last_record['pulse']}\n\n"
            f"Введите вашу заметку:"
        )
    except Exception as e:
        logger.error(f"Ошибка при добавлении заметки: {e}")
        await update.message.reply_text("Произошла ошибка при добавлении заметки.")
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        df = pd.read_csv(os.path.join(SCRIPT_DIR, 'pressure_data.csv'))
        user_data = df[df['user_id'] == user_id]
        if user_data.empty:
            await update.message.reply_text("У вас пока нет записей о давлении.")
            return
        week_ago = datetime.now(MOSCOW_TZ) - timedelta(days=7)
        week_data = user_data[pd.to_datetime(user_data['date']) >= week_ago]
        if week_data.empty:
            await update.message.reply_text("За последнюю неделю нет записей о давлении.")
            return
        avg_systolic = week_data['systolic'].mean()
        avg_diastolic = week_data['diastolic'].mean()
        avg_pulse = week_data['pulse'].mean()
        message = (
            f"📊 Статистика за последние 7 дней:\n\n"
            f"Среднее систолическое: {avg_systolic:.1f}\n"
            f"Среднее диастолическое: {avg_diastolic:.1f}\n"
            f"Средний пульс: {avg_pulse:.1f}\n"
            f"Количество измерений: {len(week_data)}"
        )
        await update.message.reply_text(message)
    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        await update.message.reply_text("Произошла ошибка при получении статистики.")
async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        date = datetime.now(MOSCOW_TZ).strftime('%Y%m%d')
        pressure_df = pd.read_csv(os.path.join(SCRIPT_DIR, 'pressure_data.csv'))
        pressure_data = pressure_df[pressure_df['user_id'] == user_id].copy()
        meds_df = pd.read_csv(os.path.join(SCRIPT_DIR, 'medications.csv'))
        meds_data = meds_df[meds_df['user_id'] == user_id].copy()
        excel_file = os.path.join(SCRIPT_DIR, f'pressure_data_{user_id}_{date}.xlsx')
        pressure_data['date'] = pd.to_datetime(pressure_data['date'])
        pressure_data = pressure_data.sort_values('date')
        pressure_data['date'] = pressure_data['date'].dt.strftime('%Y-%m-%d %H:%M:%S')
        pressure_data.columns = ['ID пользователя', 'Дата и время', 'Систолическое', 'Диастолическое', 'Пульс', 'Заметки']
        with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
            pressure_data.to_excel(writer, sheet_name='Измерения давления', index=False)
            meds_data.to_excel(writer, sheet_name='Лекарства', index=False)
        await update.message.reply_document(
            document=open(excel_file, 'rb'),
            filename=f'pressure_data_{date}.xlsx',
            caption="📊 Ваши данные экспортированы в Excel файл."
        )
        os.remove(excel_file)
    except Exception as e:
        logger.error(f"Ошибка при экспорте данных: {e}")
        await update.message.reply_text("Произошла ошибка при экспорте данных.")
async def test_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Бот работает корректно!")
async def handle_frequency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    frequency = query.data.split('_')[1]
    medication_name = context.user_data['medication_name']
    keyboard = []
    for hour in range(24):
        for minute in ['00', '30']:
            time_str = f"{hour:02d}:{minute}"
            keyboard.append([InlineKeyboardButton(time_str, callback_data=f"time_{time_str}")])
    await query.message.reply_text(
        f"Выберите время для приема {medication_name} ({frequency}):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
async def handle_medication_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.split('_')[1]
    if action == 'add':
        await query.message.reply_text("Введите название лекарства:")
    elif action == 'list':
        try:
            user_id = query.from_user.id
            df = pd.read_csv(os.path.join(SCRIPT_DIR, 'medications.csv'))
            user_meds = df[df['user_id'] == user_id]
            if user_meds.empty:
                await query.message.reply_text("У вас пока нет добавленных лекарств.")
                return
            message = "📋 Ваши лекарства:\n\n"
            for _, row in user_meds.iterrows():
                message += (
                    f"💊 {row['medication_name']}\n"
                    f"🕒 Время: {row['time']}\n"
                    f"📅 Частота: {row['frequency']}\n"
                    f"-------------------\n"
                )
            await query.message.reply_text(message)
        except Exception as e:
            logger.error(f"Ошибка при получении списка лекарств: {e}")
            await query.message.reply_text("Произошла ошибка при получении списка лекарств.")
    elif action == 'delete':
        try:
            user_id = query.from_user.id
            df = pd.read_csv(os.path.join(SCRIPT_DIR, 'medications.csv'))
            user_meds = df[df['user_id'] == user_id]
            if user_meds.empty:
                await query.message.reply_text("У вас пока нет добавленных лекарств.")
                return
            keyboard = []
            for _, row in user_meds.iterrows():
                keyboard.append([
                    InlineKeyboardButton(
                        f"❌ {row['medication_name']} ({row['time']})",
                        callback_data=f"delete_med_{row['medication_name']}_{row['time']}"
                    )
                ])
            await query.message.reply_text(
                "Выберите лекарство для удаления:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Ошибка при удалении лекарства: {e}")
            await query.message.reply_text("Произошла ошибка при удалении лекарства.")
async def handle_medication_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, _, medication_name, time = query.data.split('_')
    user_id = query.from_user.id
    df = pd.read_csv(os.path.join(SCRIPT_DIR, 'medications.csv'))
    df = df[
        ~((df['user_id'] == user_id) & 
          (df['medication_name'] == medication_name) & 
          (df['time'] == time))
    ]
    df.to_csv(os.path.join(SCRIPT_DIR, 'medications.csv'), index=False)
    await query.message.reply_text(
        f"✅ Лекарство {medication_name} успешно удалено!"
    )
async def handle_pressure_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.split('_')[1]
    if action == 'delete':
        try:
            user_id = query.from_user.id
            df = pd.read_csv(os.path.join(SCRIPT_DIR, 'pressure_data.csv'))
            user_data = df[df['user_id'] == user_id]
            if user_data.empty:
                await query.message.reply_text("У вас пока нет записей о давлении.")
                return
            df = df.drop(user_data.index[-1])
            df.to_csv(os.path.join(SCRIPT_DIR, 'pressure_data.csv'), index=False)
            await query.message.reply_text("✅ Последнее измерение успешно удалено!")
        except Exception as e:
            logger.error(f"Ошибка при удалении измерения: {e}")
            await query.message.reply_text("Произошла ошибка при удалении измерения.")
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text
        user_id = update.effective_user.id
        if 'last_record' in context.user_data:
            note = text
            last_record = context.user_data['last_record']
            df = pd.read_csv(os.path.join(SCRIPT_DIR, 'pressure_data.csv'))
            df.loc[df['date'] == last_record['date'], 'notes'] = note
            df.to_csv(os.path.join(SCRIPT_DIR, 'pressure_data.csv'), index=False)
            await update.message.reply_text("✅ Заметка успешно добавлена!")
            return
        if 'medication_name' not in context.user_data:
            try:
                systolic, diastolic, pulse = map(int, text.split())
                date = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d %H:%M:%S')
                df = pd.read_csv(os.path.join(SCRIPT_DIR, 'pressure_data.csv'))
                new_row = pd.DataFrame({
                    'user_id': [user_id],
                    'date': [date],
                    'systolic': [systolic],
                    'diastolic': [diastolic],
                    'pulse': [pulse],
                    'notes': ['']
                })
                df = pd.concat([df, new_row], ignore_index=True)
                df.to_csv(os.path.join(SCRIPT_DIR, 'pressure_data.csv'), index=False)
                keyboard = [
                    [InlineKeyboardButton("❌ Удалить измерение", callback_data="pressure_delete")],
                    [InlineKeyboardButton("📝 Добавить заметку", callback_data="pressure_note")]
                ]
                await update.message.reply_text(
                    f"✅ Показатели успешно сохранены!\n\n"
                    f"Дата: {date}\n"
                    f"Давление: {systolic}/{diastolic}\n"
                    f"Пульс: {pulse}",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except ValueError:
                await update.message.reply_text(
                    "❌ Неверный формат. Пожалуйста, введите три числа через пробел:\n"
                    "систолическое диастолическое пульс"
                )
        else:
            medication_name = text
            context.user_data['medication_name'] = medication_name
            keyboard = [
                [InlineKeyboardButton("Раз в день", callback_data="frequency_daily")],
                [InlineKeyboardButton("Два раза в день", callback_data="frequency_twice")],
                [InlineKeyboardButton("Три раза в день", callback_data="frequency_thrice")]
            ]
            await update.message.reply_text(
                f"Выберите частоту приема {medication_name}:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}")
        await update.message.reply_text("Произошла ошибка при обработке сообщения.")
def main():
    try:
        init_db()
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not token:
            logger.error("Не найден токен бота. Убедитесь, что он указан в файле .env")
            return
        application = Application.builder().token(token).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("pressure", pressure_command))
        application.add_handler(CommandHandler("medication", medication_command))
        application.add_handler(CommandHandler("history", history_command))
        application.add_handler(CommandHandler("note", note_command))
        application.add_handler(CommandHandler("stats", stats_command))
        application.add_handler(CommandHandler("export", export_data))
        application.add_handler(CommandHandler("test", test_bot))
        application.add_handler(CallbackQueryHandler(handle_frequency, pattern='^frequency_\d+$'))
        application.add_handler(CallbackQueryHandler(handle_medication_action, pattern='^med_'))
        application.add_handler(CallbackQueryHandler(handle_medication_delete, pattern='^delete_med_'))
        application.add_handler(CallbackQueryHandler(handle_pressure_action, pattern='^pressure_'))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        reminder_service = MedicationReminder(token)
        reminder_thread = threading.Thread(target=reminder_service.start)
        reminder_thread.daemon = True
        reminder_thread.start()
        logger.info("Бот запущен")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        sys.exit(1)
if __name__ == '__main__':
    main() 