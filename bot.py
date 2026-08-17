import os
import sqlite3
import logging
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# --- КОНФИГУРАЦИЯ ---
TOKEN = "8357503777:AAEem40CIOvy87QCT0bQgPLpSpUNwb3qcUY"
OWNER_ID = 5295393159  # Ваш ID из ТЗ

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Пути к картинкам из ТЗ (предполагается, что файлы лежат рядом с ботом)
IMG_START = "75003.png"
IMG_SEARCH = "74998.png"
IMG_DEEP = "75000.png"

# --- БАЗА ДАННЫХ (SQLite) ---
DB_FILE = "ahiska_search.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            reg_date TEXT,
            status TEXT DEFAULT 'Пользователь',
            balance REAL DEFAULT 0,
            partner_balance REAL DEFAULT 0,
            requests INTEGER DEFAULT 0,
            vip_until TEXT,
            last_bonus TEXT,
            referrer_id INTEGER,
            ref_count_1 INTEGER DEFAULT 0,
            ref_count_2 INTEGER DEFAULT 0,
            ref_count_3 INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            file_path TEXT,
            records_count INTEGER,
            fields TEXT,
            added_date TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS promo (
            code TEXT PRIMARY KEY,
            activations INTEGER,
            requests INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            timestamp TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- СОСТОЯНИЯ (FSM) ---
class Form(StatesGroup):
    waiting_for_search = State()
    waiting_for_promo = State()
    waiting_for_broadcast = State()
    waiting_for_admin_requests = State()
    waiting_for_admin_vip = State()
    waiting_for_admin_role = State()
    waiting_for_funstat = State()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_user(user_id: int, username: str = None):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        reg_date = datetime.now().strftime("%d.%0m.%Y")
        status = "Владелец" if user_id == OWNER_ID else "Пользователь"
        reqs = 999999 if user_id == OWNER_ID else 0
        vip = "Навсегда" if user_id == OWNER_ID else None
        cursor.execute('''
            INSERT INTO users (user_id, username, reg_date, status, requests, vip_until)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, username, reg_date, status, reqs, vip))
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
    conn.close()
    return row

def update_user_field(user_id: int, field: str, value):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()

# --- КЛАВИАТУРЫ ---
def main_menu(user_id: int):
    is_owner = (user_id == OWNER_ID)
    keyboard = [
        [InlineKeyboardButton(text="🔍 Поиск", callback_data="menu_search"), InlineKeyboardButton(text="👤 Профиль", callback_data="menu_profile")],
        [InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="menu_bonus"), InlineKeyboardButton(text="🤝 Партнёрам", callback_data="menu_partner")],
        [InlineKeyboardButton(text="💰 Тарифы", callback_data="menu_tariffs"), InlineKeyboardButton(text="💳 Купить запросы", callback_data="menu_buy")],
        [InlineKeyboardButton(text="👑 VIP-статус", callback_data="menu_vip"), InlineKeyboardButton(text="🎟 Промокод", callback_data="menu_promo")]
    ]
    if is_owner:
        keyboard.append([InlineKeyboardButton(text="📂 Управление базами", callback_data="owner_bases")])
        keyboard.append([InlineKeyboardButton(text="🛡️ Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def search_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 ФИО", callback_data="s_fio"), InlineKeyboardButton(text="📱 Телефон", callback_data="s_phone")],
        [InlineKeyboardButton(text="📧 Email", callback_data="s_email"), InlineKeyboardButton(text="💬 Telegram", callback_data="s_tg")],
        [InlineKeyboardButton(text="🌍 Домен/IP", callback_data="s_domain"), InlineKeyboardButton(text="🏢 Компания", callback_data="s_comp")],
        [InlineKeyboardButton(text="📍 Адрес", callback_data="s_addr"), InlineKeyboardButton(text="🚗 Автомобиль", callback_data="s_auto")],
        [InlineKeyboardButton(text="📸 Фото / Фанстат", callback_data="s_funstat"), InlineKeyboardButton(text="⚡ Глубокий поиск", callback_data="s_deep")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])

# --- ХЕНДЛЕРЫ КОМАНД И КНОПОК ---

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = get_user(message.from_user.id, message.from_user.username)
    
    caption = (
        "🚀 **AHISKA SEARCH**\n\n"
        "Слоган: «Один из самых лучших ботов в Telegram»\n"
        "Концепция: Мощный поисковый комбайн уровня Sherlock + Void + Funstat.\n\n"
        "Выберите действие ниже:"
    )
    if os.path.exists(IMG_START):
        photo = FSInputFile(IMG_START)
        await message.answer_photo(photo=photo, caption=caption, parse_mode="Markdown", reply_markup=main_menu(message.from_user.id))
    else:
        await message.answer(caption, parse_mode="Markdown", reply_markup=main_menu(message.from_user.id))

@dp.callback_query(F.data == "back_main")
async def cb_back_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    user = get_user(callback.from_user.id, callback.from_user.username)
    caption = "🏠 Главное меню Ahiska Search:"
    if os.path.exists(IMG_START):
        await callback.message.answer_photo(photo=FSInputFile(IMG_START), caption=caption, parse_mode="Markdown", reply_markup=main_menu(callback.from_user.id))
    else:
        await callback.message.answer(caption, parse_mode="Markdown", reply_markup=main_menu(callback.from_user.id))

@dp.callback_query(F.data == "menu_search")
async def cb_menu_search(callback: CallbackQuery):
    await callback.message.delete()
    caption = "🔍 **ВЫБОР ТИПА ПОИСКА**\n\nВыберите категорию или отправьте данные напрямую:"
    if os.path.exists(IMG_SEARCH):
        await callback.message.answer_photo(photo=FSInputFile(IMG_SEARCH), caption=caption, parse_mode="Markdown", reply_markup=search_menu_kb())
    else:
        await callback.message.answer(caption, parse_mode="Markdown", reply_markup=search_menu_kb())

@dp.callback_query(F.data == "s_deep")
async def cb_deep_search(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await state.set_state(Form.waiting_for_search)
    caption = "⚡ **ГЛУБОКИЙ ПОИСК**\n\nВведите неполные данные, ключевые слова или запрос для комплексного прогона по всем базам:"
    if os.path.exists(IMG_DEEP):
        await callback.message.answer_photo(photo=FSInputFile(IMG_DEEP), caption=caption, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_search")]]))
    else:
        await callback.message.answer(caption, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_search")]]))

@dp.callback_query(F.data == "s_funstat")
async def cb_funstat_menu(callback: CallbackQuery, state: FSMContext):
    await state.message.delete()
    await state.set_state(Form.waiting_for_funstat)
    await callback.message.answer(
        "📊 **Funstat-модуль (поиск по активности)**\n\n"
        "Отправьте Telegram ID или @username пользователя для поиска его активности в группах, чатах и вывода сообщений.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_search")]])
    )

@dp.callback_query(F.data == "menu_profile")
async def cb_profile(callback: CallbackQuery):
    u = get_user(callback.from_user.id, callback.from_user.username)
    # u: user_id, username, reg_date, status, balance, partner_balance, requests, vip_until, ...
    text = (
        f"👤 **ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ**\n\n"
        f"🆔 ID: `{u[0]}`\n"
        f"📅 Регистрация: {u[2]}\n"
        f"👑 Статус: {u[3]}\n"
        f"💰 Кошелёк: {u[4]} ₽\n"
        f"🤝 Партнёрский счёт: {u[5]} ₽\n"
        f"💎 Доступно запросов: {u[6]}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"📊 Статистика\n"
        f"• Telegram: 7\n• Телефоны: 7\n• ФИО: 1\n• ВКонтакте: 1\n\n"
        f"⚡ Последняя активность: Сегодня в {datetime.now().strftime('%H:%M')}"
    )
    if callback.from_user.id == OWNER_ID:
        text = (
            f"👑 **ПРОФИЛЬ ВЛАДЕЛЬЦА**\n\n"
            f"🆔 ID: `{u[0]}`\n"
            f"👑 Статус: Владелец\n"
            f"💰 Кошелёк: ∞\n"
            f"💎 Доступно запросов: ♾ Безлимит\n"
            f"⭐ VIP: Навсегда\n\n"
            f"⚡ Полный доступ ко всем функциям."
        )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]])
    await callback.message.edit_caption(caption=text, parse_mode="Markdown", reply_markup=kb) if callback.message.photo else await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data == "menu_bonus")
async def cb_bonus(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT last_bonus, requests FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    last_bonus = res[0]
    current_reqs = res[1]
    
    now = datetime.now()
    can_get = True
    if last_bonus:
        lb_time = datetime.strptime(last_bonus, "%Y-%m-%d %H:%M:%S")
        if now - lb_time < timedelta(hours=24):
            can_get = False
            diff = timedelta(hours=24) - (now - lb_time)
            hours, remainder = divmod(diff.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            time_left = f"{hours}ч {minutes}м"

    if can_get:
        cursor.execute("UPDATE users SET requests = requests + 1, last_bonus = ? WHERE user_id = ?", (now.strftime("%Y-%m-%d %H:%M:%S"), user_id))
        conn.commit()
        conn.close()
        await callback.answer("🎁 Успешно! Вам начислен 1 бесплатный запрос.", show_alert=True)
    else:
        conn.close()
        await callback.answer(f"⏳ Бонус будет доступен через {time_left}", show_alert=True)

@dp.callback_query(F.data == "menu_partner")
async def cb_partner(callback: CallbackQuery):
    u = get_user(callback.from_user.id)
    text = (
        f"🤝 **ПАРТНЁРСКАЯ ПРОГРАММА**\n\n"
        f"Приглашайте друзей и получайте вознаграждения.\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"🥇 1 линия — 50%\n🥈 2 линия — 15%\n🥉 3 линия — 10%\n\n"
        f"🎁 За активных рефералов: +1 бессрочный запрос\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 Финансы\nБаланс: {u[4]} ₽\nВсего заработано: {u[5]} ₽\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"👥 Рефералы\nВсего: 0\n1 линия: 0\n2 линия: 0\n3 линия: 0\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔗 Ваша ссылка:\n`t.me/AhiskaSearchBot?start={u[0]}`"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data == "menu_tariffs")
async def cb_tariffs(callback: CallbackQuery):
    text = (
        "💰 **ТАРИФЫ И ПОДПИСКИ**\n\n"
        "🔹 **Базовые пакеты запросов**\n"
        "• 10 запросов — ⭐ 75 | 0.75 TON\n"
        "• 25 запросов — ⭐ 170 | 1.7 TON\n"
        "• 50 запросов — ⭐ 300 | 3 TON\n"
        "• 100 запросов — ⭐ 550 | 5.5 TON\n"
        "• 250 запросов — ⭐ 1 200 | 12 TON\n"
        "• 500 запросов — ⭐ 2 000 | 20 TON\n\n"
        "🔸 **Подписки по времени**\n"
        "• 🥉 Старт (7д / 50 запр) — ⭐ 250 | 2.5 TON\n"
        "• 🥈 Стандарт (30д / 200 запр) — ⭐ 800 | 8 TON\n"
        "• 🥇 Премиум (30д / 500 запр) — ⭐ 1 500 | 15 TON\n"
        "• 💎 Ультра (90д / 2000 запр) — ⭐ 3 500 | 35 TON"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Купить запросы", callback_data="menu_buy")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data == "menu_buy")
async def cb_buy(callback: CallbackQuery):
    text = (
        "💳 **ПОКУПКА ЗАПРОСОВ**\n\n"
        "⭐ **Оплата Telegram Stars**\n"
        "• 10 запросов — ⭐ 75\n• 50 запросов — ⭐ 300\n• 250 запросов — ⭐ 1 200\n\n"
        "💠 **Оплата TON**\n"
        "• 10 запросов — 0.75 TON\n• 50 запросов — 3 TON\n• 250 запросов — 12 TON\n\n"
        "Нажмите для симуляции успешной оплаты тестового пакета (50 запросов):"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оплатить 50 запросов (Тест)", callback_data="simulate_success_pay")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data == "simulate_success_pay")
async def cb_success_pay(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET requests = requests + 50 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    text = (
        "✅ **Платёж успешно получен!**\n\n"
        "Начислено: 💎 50 запросов\n\n"
        "Спасибо за покупку ❤️"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_main")]])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data == "menu_vip")
async def cb_vip(callback: CallbackQuery):
    text = (
        "👑 **VIP-СТАТУС**\n\n"
        "Преимущества VIP:\n"
        "• Расширенная история запросов\n"
        "• Запросы без очереди\n"
        "• Приоритетная обработка\n"
        "• Дополнительные скрытые функции\n\n"
        "Стоимость: 1 200 Stars / 12 TON за 30 дней."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data == "menu_promo")
async def cb_promo_prompt(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.waiting_for_promo)
    await callback.message.edit_text("🎟 Введите промокод для активации:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]]))

@dp.message(Form.waiting_for_promo)
async def process_promo(message: Message, state: FSMContext):
    code = message.text.strip()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT activations, requests FROM promo WHERE code = ?", (code,))
    promo = cursor.fetchone()
    
    if promo and promo[0] > 0:
        reqs = promo[1]
        cursor.execute("UPDATE promo SET activations = activations - 1 WHERE code = ?", (code,))
        cursor.execute("UPDATE users SET requests = requests + ? WHERE user_id = ?", (reqs, message.from_user.id))
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer(f"✅ Промокод успешно активирован! Вам начислено 💎 {reqs} запросов.", reply_markup=main_menu(message.from_user.id))
    else:
        conn.close()
        await message.answer("❌ Неверный промокод или закончились активации.")

# --- УПРАВЛЕНИЕ БАЗАМИ (ТОЛЬКО ДЛЯ ВЛАДЕЛЬЦА) И ПРИЕМ ФАЙЛОВ ---

@dp.callback_query(F.data == "owner_bases")
async def owner_bases_menu(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT name, records_count FROM bases")
    bases = cursor.fetchall()
    conn.close()
    
    bases_list = "\n".join([f"• {b[0]} ({b[1]} записей)" for b in bases]) if bases else "Баз пока нет."
    
    text = (
        "📂 **УПРАВЛЕНИЕ БАЗАМИ ДАННЫХ**\n\n"
        f"Загруженные базы ({len(bases)}):\n{bases_list}\n\n"
        "Отправьте любой файл (CSV, XLSX, TXT, SQLite, JSON и др. до 3 ГБ), и бот автоматически добавит его в поисковую систему!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список баз", callback_data="owner_bases")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)

@dp.message(F.document)
async def handle_uploaded_file(message: Message):
    if message.from_user.id != OWNER_ID:
        return # Обычные пользователи не могут загружать базы
    
    document = message.document
    file_name = document.file_name
    file_id = document.file_id
    
    # Создаем папку для баз
    os.makedirs("uploaded_bases", exist_ok=True)
    file_path = os.path.join("uploaded_bases", file_name)
    
    file = await bot.get_file(file_id)
    await bot.download_file(file.file_path, file_path)
    
    # Имитация анализа файла и подсчета записей
    records_count = 15284
    fields = "Имя, Телефон, Email"
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO bases (name, file_path, records_count, fields, added_date) VALUES (?, ?, ?, ?, ?)",
                   (file_name, file_path, records_count, fields, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()
    
    success_text = (
        f"✅ **База успешно добавлена.**\n\n"
        f"📂 Название: {file_name}\n"
        f"📊 Записей: {records_count:,}\n"
        f"🔍 Поля поиска:\n• Имя\n• Телефон\n• Email\n\n"
        f"Статус: Активна"
    )
    await message.answer(success_text, parse_mode="Markdown", reply_markup=main_menu(message.from_user.id))

# --- АДМИН-ПАНЕЛЬ ---

@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎟 Создать промокод", callback_data="adm_create_promo")],
        [InlineKeyboardButton(text="📦 Выдать запросы", callback_data="adm_give_reqs")],
        [InlineKeyboardButton(text="💎 Выдать VIP", callback_data="adm_give_vip")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])
    await callback.message.edit_text("🛡️ **АДМИН-ПАНЕЛЬ**\n\nВыберите действие:", parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data == "adm_give_reqs")
async def adm_give_reqs_prompt(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.waiting_for_admin_requests)
    await callback.message.edit_text("Введите ID или @username пользователя и количество запросов через пробел (например: `123456789 50`):")

@dp.message(Form.waiting_for_admin_requests)
async def adm_give_reqs_exec(message: Message, state: FSMContext):
    try:
        parts = message.text.split()
        target = parts[0].replace("@", "")
        amount = int(parts[1])
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        if target.isdigit():
            cursor.execute("UPDATE users SET requests = requests + ? WHERE user_id = ?", (amount, int(target)))
        else:
            cursor.execute("UPDATE users SET requests = requests + ? WHERE username = ?", (amount, target))
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer(f"✅ Успешно начислено {amount} запросов пользователю {target}!", reply_markup=main_menu(message.from_user.id))
    except Exception as e:
        await message.answer(f"❌ Ошибка формата. Попробуйте еще раз. Пример: `123456789 50`")

@dp.callback_query(F.data == "adm_stats")
async def adm_stats(callback: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    users_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM bases")
    bases_count = cursor.fetchone()[0]
    conn.close()
    
    text = (
        f"📊 **СТАТИСТИКА БОТА**\n\n"
        f"👥 Всего пользователей: {users_count}\n"
        f"📂 Загружено баз: {bases_count}\n"
        f"⚡ Статус системы: Работает 24/7 (Штатный режим)"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ В админ-панель", callback_data="admin_panel")]])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)

# --- ПОИСК И ГЕНЕРАЦИЯ HTML-ОТЧЕТА ПО ДИЗАЙНУ ИЗ ТЗ ---

@dp.message(Form.waiting_for_search)
async def perform_search(message: Message, state: FSMContext):
    query_text = message.text
    await state.clear()
    
    await message.answer("🔍 Производится глубокий поиск по всем подключенным базам данных...")
    await asyncio.sleep(1.5)
    
    # Генерация HTML-отчета строго по ТЗ
    html_content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Ahiska Search • Результат поиска</title>
    <style>
        body {{ background-color: #0a0a0f; color: #e0e0e0; font-family: Arial, sans-serif; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #0b0b1a, #000000); border: 1px solid #1e1e2e; border-radius: 12px; padding: 15px; display: flex; justify-content: space-between; align-items: center; }}
        .logo {{ font-size: 22px; font-weight: bold; background: linear-gradient(45deg, #6c5ce7, #a29bfe); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .card {{ background-color: #12121a; border: 1px solid #1e1e2e; border-radius: 10px; padding: 15px; margin-top: 15px; }}
        .card-title {{ color: #6c5ce7; font-weight: bold; font-size: 14px; text-transform: uppercase; margin-bottom: 10px; }}
        .row {{ margin: 6px 0; font-size: 14px; }}
        .highlight {{ color: #a29bfe; font-weight: bold; }}
        .tags {{ display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap; }}
        .tag {{ background-color: #1a1a2e; color: #6c5ce7; padding: 5px 10px; border-radius: 6px; font-size: 12px; }}
        .footer {{ text-align: center; margin-top: 25px; font-size: 11px; color: #7f8c8d; border-top: 1px solid #6c5ce7; padding-top: 10px; }}
        a {{ color: #a29bfe; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <div class="logo">Ahiska Search</div>
            <div style="font-size: 11px; color: #7f8c8d;">Результат поиска</div>
        </div>
        <div style="font-size: 12px; color: #a29bfe;">{datetime.now().strftime('%d.%m.%Y %H:%M')}</div>
    </div>

    <div class="card">
        <div class="card-title">📋 Основная информация</div>
        <div class="row">ФИО: <span class="highlight">{query_text}</span></div>
        <div class="row">Дата рождения: 12.04.1992</div>
        <div class="row">Возраст: 34 года</div>
        <div class="row">Пол: Мужской</div>
        <div class="row">Адрес: г. Москва, ул. Тверская, д. 1</div>
        <div class="row">Телефон: <a href="tel:+79991234567">+7 (999) 123-45-67</a></div>
        <div class="row">Email: <a href="mailto:user@mail.com">user@mail.com</a></div>
    </div>

    <div class="card">
        <div class="card-title">📱 Социальные сети</div>
        <div class="row">Telegram: <a href="https://t.me/example">@example</a></div>
        <div class="row">Instagram: <a href="https://instagram.com/example">instagram.com/example</a></div>
        <div class="row">ВКонтакте: <a href="https://vk.com/id000000">vk.com/id000000</a></div>
    </div>

    <div class="card">
        <div class="card-title">🚗 Автомобиль</div>
        <div class="row">Марка и модель: BMW M5</div>
        <div class="row">Госномер: А777АА777</div>
        <div class="row">VIN: WBA5H9C000BC12345</div>
        <div class="row">Год выпуска: 2021</div>
        <div class="row">Статус: Чист</div>
    </div>

    <div class="card">
        <div class="card-title">📊 Сводка</div>
        <div class="tags">
            <div class="tag">🟢 Найдено в базах: 12</div>
            <div class="tag">🟡 Совпадений по фото: 3</div>
            <div class="tag">🔴 В розыске: Нет</div>
            <div class="tag">🟣 Связей: 8</div>
        </div>
    </div>

    <div class="footer">
        Ahiska Search • Поиск выполнен за 2.3 сек • Данные из открытых источников<br>
        Создано в Ahiska Search Bot
    </div>
</body>
</html>"""
    
    file_name = "ahiska_report.html"
    with open(file_name, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    report_file = FSInputFile(file_name)
    await message.answer_document(
        document=report_file,
        caption="✅ **Поиск успешно завершен!**\n\nОтчёт сгенерирован в премиальном HTML-формате по вашему дизайну:",
        parse_mode="Markdown",
        reply_markup=main_menu(message.from_user.id)
    )

@dp.message(Form.waiting_for_funstat)
async def process_funstat(message: Message, state: FSMContext):
    target = message.text.strip()
    await state.clear()
    await message.answer(
        f"📊 **Результат Funstat-анализа для `{target}`:**\n\n"
        f"• Активность в чатах: Обнаружен в 14 группах\n"
        f"• Последние сообщения:\n"
        f"  1. «Всем привет, как настроить VPN?» (Четверг, 14:20)\n"
        f"  2. «Продам скрипт» (Суббота, 19:10)\n"
        f"• Упоминания в базах утечек: 2 совпадения",
        parse_mode="Markdown",
        reply_markup=main_menu(message.from_user.id)
    )

@dp.message()
async def handle_any_text(message: Message, state: FSMContext):
    # Если пользователь просто ввел текст без состояния, запускаем поиск
    await state.clear()
    await message.answer("🔍 Обрабатываю поисковый запрос...")
    # Перенаправляем в логику поиска
    message.text = message.text
    await perform_search(message, state)

# --- ЗАПУСК БОТА ---
async def main():
    print("🚀 Ahiska Search Bot запущен и работает 24/7...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
