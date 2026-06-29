#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
СТАТИСТИКА КЦ — ФИНАЛЬНЫЙ БОТ
Версия: 14.0 | Дозвон = среднее арифметическое
"""
import asyncio
import datetime
import json
import os
import sys
import signal
import logging
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.client.default import DefaultBotProperties
import pytz

# ═══════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════
BOT_TOKEN: str = "8797751286:AAFX5zjH9nFf_85MLFXZQawFhL1ckJJQNZo"
GROUP_CHAT_ID: int = -1001634187997
ADMIN_IDS: List[int] = [8619089602, 6143996239]

REMINDER_TIMES: List[Tuple[int, int]] = [
    (10, 15), (13, 50), (16, 15), (18, 15), (19, 0)
]

DATA_DIR: Path = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

MANAGERS_FILE: Path = DATA_DIR / "managers.json"
STATS_FILE: Path = DATA_DIR / "stats.json"
REQUESTS_FILE: Path = DATA_DIR / "requests.json"
ATTENDANCE_FILE: Path = DATA_DIR / "attendance.json"
HISTORY_FILE: Path = DATA_DIR / "history.json"
CLEANUP_DATE_FILE: Path = DATA_DIR / "last_cleanup.txt"

# ═══════════════════════════════════════════════════════════
# ИНИЦИАЛИЗАЦИЯ
# ═══════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

storage: MemoryStorage = MemoryStorage()
bot: Bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp: Dispatcher = Dispatcher(storage=storage)

MOSCOW_TZ: datetime.tzinfo = pytz.timezone('Europe/Moscow')

# ═══════════════════════════════════════════════════════════
# СОСТОЯНИЯ FSM
# ═══════════════════════════════════════════════════════════
class AdminState(StatesGroup):
    waiting_for_manager_name = State()
    waiting_for_rename = State()
    waiting_for_broadcast = State()

# ═══════════════════════════════════════════════════════════
# ГЛОБАЛЬНЫЕ ДАННЫЕ
# ═══════════════════════════════════════════════════════════
managers: Dict[int, Dict[str, Any]] = {}
stats: Dict[int, Dict[str, Any]] = {}
pending_requests: List[Dict[str, Any]] = []
attendance_log: Dict[int, Dict[str, Any]] = {}
history: Dict[str, Dict[str, Dict[str, Any]]] = {}
last_cleanup_date: str = ""

# ═══════════════════════════════════════════════════════════
# БЕЗОПАСНАЯ РАБОТА С JSON
# ═══════════════════════════════════════════════════════════
def safe_load_json(filepath: Path, default: Any = None) -> Any:
    if not filepath.exists():
        return default if default is not None else {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"❌ Ошибка чтения {filepath.name}: {e}")
        backup_path = filepath.with_suffix('.json.bak')
        if filepath.exists():
            try:
                filepath.rename(backup_path)
            except:
                pass
        return default if default is not None else {}

def safe_save_json(filepath: Path, data: Any) -> bool:
    tmp_path = filepath.with_suffix('.json.tmp')
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_path.replace(filepath)
        return True
    except IOError as e:
        logger.error(f"❌ Ошибка сохранения {filepath.name}: {e}")
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except:
                pass
        return False

def load_all_data() -> None:
    global managers, stats, pending_requests, attendance_log, history, last_cleanup_date
    
    managers_raw = safe_load_json(MANAGERS_FILE, {})
    managers = {int(k): v for k, v in managers_raw.items()}
    
    stats_raw = safe_load_json(STATS_FILE, {})
    stats = {int(k): v for k, v in stats_raw.items()}
    
    pending_requests = safe_load_json(REQUESTS_FILE, [])
    
    attendance_raw = safe_load_json(ATTENDANCE_FILE, {})
    attendance_log = {int(k): v for k, v in attendance_raw.items()}
    
    history = safe_load_json(HISTORY_FILE, {})
    
    if CLEANUP_DATE_FILE.exists():
        last_cleanup_date = CLEANUP_DATE_FILE.read_text().strip()
    else:
        last_cleanup_date = ""

def save_all_data() -> None:
    safe_save_json(MANAGERS_FILE, {str(k): v for k, v in managers.items()})
    safe_save_json(STATS_FILE, {str(k): v for k, v in stats.items()})
    safe_save_json(REQUESTS_FILE, pending_requests)
    safe_save_json(ATTENDANCE_FILE, {str(k): v for k, v in attendance_log.items()})
    safe_save_json(HISTORY_FILE, history)

def save_cleanup_date(date_str: str) -> None:
    global last_cleanup_date
    last_cleanup_date = date_str
    try:
        CLEANUP_DATE_FILE.write_text(date_str)
    except IOError as e:
        logger.error(f"❌ Ошибка сохранения даты очистки: {e}")

# ═══════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ
# ═══════════════════════════════════════════════════════════
def get_moscow_time() -> datetime.datetime:
    return datetime.datetime.now(MOSCOW_TZ)

def get_today_str() -> str:
    return get_moscow_time().strftime("%Y-%m-%d")

def get_time_str() -> str:
    return get_moscow_time().strftime("%H:%M:%S")

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def is_manager(user_id: int) -> bool:
    return user_id in managers and managers[user_id].get("approved", False)

def is_active_today(user_id: int) -> bool:
    if user_id not in managers:
        return False
    return managers[user_id].get("active", True)

def get_manager_name(user_id: int) -> str:
    return managers.get(user_id, {}).get("name", f"ID:{user_id}")

def has_pending_request(user_id: int) -> bool:
    return any(req.get('user_id') == user_id for req in pending_requests)

def get_default_stats() -> Dict[str, Any]:
    return {"zvonki": 0, "dozvon": 0, "sms": 0, "vkhodyashki": 0, "last_update": "никогда", "date": get_today_str()}

async def safe_send_message(user_id: int, text: str, **kwargs) -> bool:
    try:
        await bot.send_message(user_id, text, **kwargs)
        return True
    except TelegramForbiddenError:
        logger.warning(f"🚫 Пользователь {user_id} заблокировал бота")
        return False
    except TelegramBadRequest as e:
        logger.error(f"📛 Ошибка отправки {user_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"💥 Ошибка для {user_id}: {e}")
        return False

async def notify_admins(text: str, **kwargs) -> int:
    count = 0
    for admin_id in ADMIN_IDS:
        if await safe_send_message(admin_id, text, **kwargs):
            count += 1
    return count

async def notify_managers(text: str, only_active: bool = True, **kwargs) -> int:
    count = 0
    for user_id, info in managers.items():
        if info.get("approved", False):
            if only_active and not info.get("active", True):
                continue
            if await safe_send_message(user_id, text, **kwargs):
                count += 1
            await asyncio.sleep(0.2)
    return count

# ═══════════════════════════════════════════════════════════
# ОЧИСТКА СТАТИСТИКИ
# ═══════════════════════════════════════════════════════════
def archive_and_clear_stats() -> int:
    global last_cleanup_date
    today = get_today_str()
    yesterday = (get_moscow_time() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    
    if last_cleanup_date == today:
        return 0
    
    cleared_count = 0
    
    for user_id, data in list(stats.items()):
        stat_date = data.get('date', '')
        
        if stat_date == today:
            continue
        
        if stat_date and (data.get('zvonki', 0) > 0 or data.get('calls', 0) > 0):
            if stat_date not in history:
                history[stat_date] = {}
            history[stat_date][str(user_id)] = {
                "zvonki": data.get('zvonki', data.get('calls', 0)),
                "dozvon": data.get('dozvon', data.get('connect', 0)),
                "sms": data.get('sms', data.get('smart', 0)),
                "vkhodyashki": data.get('vkhodyashki', 0),
                "name": get_manager_name(user_id)
            }
        
        if stat_date == yesterday and (data.get('zvonki', 0) > 0 or data.get('calls', 0) > 0):
            if user_id not in attendance_log:
                attendance_log[user_id] = {"last_active_date": yesterday, "active_days": []}
            if yesterday not in attendance_log[user_id].get('active_days', []):
                attendance_log[user_id].setdefault('active_days', []).append(yesterday)
            attendance_log[user_id]['last_active_date'] = yesterday
        
        stats[user_id] = get_default_stats()
        cleared_count += 1
    
    for user_id in managers:
        managers[user_id]['active'] = True
    
    save_cleanup_date(today)
    save_all_data()
    logger.info(f"✅ Очищено {cleared_count} записей")
    return cleared_count

# ═══════════════════════════════════════════════════════════
# КЛАВИАТУРЫ
# ═══════════════════════════════════════════════════════════
def admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📤 Опубликовать")],
            [KeyboardButton(text="👥 Менеджеры"), KeyboardButton(text="📋 Запросы")],
            [KeyboardButton(text="✏️ Переименовать"), KeyboardButton(text="📅 Отсутствие")],
            [KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="📜 История")]
        ],
        resize_keyboard=True
    )

def manager_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📝 Отправить стату")]],
        resize_keyboard=True
    )

# ═══════════════════════════════════════════════════════════
# НАПОМИНАНИЯ
# ═══════════════════════════════════════════════════════════
async def remind_managers_task() -> None:
    active_managers = {
        uid: info for uid, info in managers.items()
        if info.get("approved") and info.get("active", True)
    }
    
    if not active_managers:
        await notify_admins("⚠️ Нет активных менеджеров")
        return
    
    reminder_text = (
        "🔔 <b>НАПОМИНАНИЕ!</b>\n\n"
        "Пожалуйста, обнови статистику:\n\n"
        "<code>Звонки Дозвон% СМС Входяшки</code>\n\n"
        "Пример: <code>213 54 10 5</code>\n\n"
        "Нажми кнопку <b>📝 Отправить стату</b>"
    )
    
    sent_to = []
    failed_for = []
    
    for user_id, info in active_managers.items():
        if await safe_send_message(user_id, reminder_text):
            sent_to.append(info['name'])
        else:
            failed_for.append(info['name'])
        await asyncio.sleep(0.3)
    
    time_str = get_time_str()
    msg = f"🔔 <b>Напоминание {time_str} МСК</b>\n✅ {len(sent_to)} менеджерам"
    if failed_for:
        msg += f"\n❌ Ошибки: {', '.join(failed_for)}"
    await notify_admins(msg)

async def reminder_scheduler() -> None:
    sent_today = set()
    last_date = ""
    
    while True:
        try:
            now = get_moscow_time()
            current_time = (now.hour, now.minute)
            current_date = now.strftime("%Y-%m-%d")
            
            if last_date != current_date:
                sent_today.clear()
                last_date = current_date
            
            for h, m in REMINDER_TIMES:
                if current_time == (h, m) and (h, m) not in sent_today:
                    logger.info(f"🔔 Напоминание: {h:02d}:{m:02d} МСК")
                    await remind_managers_task()
                    sent_today.add((h, m))
                    await asyncio.sleep(61)
                    break
            
            await asyncio.sleep(15)
        except Exception as e:
            logger.error(f"💥 reminder: {e}")
            await asyncio.sleep(30)

async def daily_reset_scheduler() -> None:
    global last_cleanup_date
    last_reset = last_cleanup_date
    
    while True:
        try:
            now = get_moscow_time()
            current_date = now.strftime("%Y-%m-%d")
            
            if now.hour == 0 and now.minute in (0, 1):
                if last_reset != current_date:
                    cleared = archive_and_clear_stats()
                    await notify_admins(f"🔄 Очистка\n🕐 {now.strftime('%H:%M')}\n📊 {cleared}")
                    last_reset = current_date
                    await asyncio.sleep(61)
            
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"💥 reset: {e}")
            await asyncio.sleep(60)

# ═══════════════════════════════════════════════════════════
# КОМАНДЫ
# ═══════════════════════════════════════════════════════════
@dp.message(Command("start"))
async def cmd_start(message: Message) -> None:
    user_id = message.from_user.id
    
    if is_admin(user_id):
        req_count = len(pending_requests)
        req_text = f"\n📋 Заявок: {req_count}" if req_count > 0 else ""
        
        await message.answer(
            f"👑 <b>Привет, Администратор!</b>{req_text}\n\n"
            "📊 Статистика | 📤 Опубликовать\n"
            "👥 Менеджеры | 📋 Запросы\n"
            "✏️ Переименовать | 📅 Отсутствие\n"
            "📢 Рассылка | 📜 История\n\n"
            "⏰ Напоминания: 10:15, 13:50, 16:15, 18:15, 19:00 МСК\n"
            "🔄 Очистка: 00:00 МСК",
            reply_markup=admin_keyboard()
        )
        return
    
    if is_manager(user_id):
        name = managers[user_id]['name']
        if is_active_today(user_id):
            await message.answer(
                f"👋 <b>Привет, {name}!</b>\n\n"
                f"Отправляй статистику:\n"
                f"<code>Звонки Дозвон% СМС Входяшки</code>\n\n"
                f"Пример: <code>213 54 10 5</code>",
                reply_markup=manager_keyboard()
            )
        else:
            await message.answer(
                f"👋 <b>Привет, {name}!</b>\n\n"
                f"⚠️ Ты отмечен как <b>отсутствующий</b> сегодня.\n"
                f"Завтра снова в строю! 💪",
                reply_markup=manager_keyboard()
            )
        return
    
    if has_pending_request(user_id):
        await message.answer("⏳ Заявка уже отправлена. Ожидайте!")
        return
    
    user = message.from_user
    pending_requests.append({
        "user_id": user_id,
        "full_name": user.full_name or "Неизвестный",
        "username": user.username or "нет",
        "date": get_moscow_time().strftime("%d.%m.%Y %H:%M")
    })
    safe_save_json(REQUESTS_FILE, pending_requests)
    
    await message.answer("📨 Заявка отправлена!")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_{user_id}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{user_id}")]
    ])
    
    for admin_id in ADMIN_IDS:
        await safe_send_message(
            admin_id,
            f"🔔 <b>НОВАЯ ЗАЯВКА!</b>\n👤 {user.full_name}\n🆔 @{user.username or 'нет'}\n🔢 ID: <code>{user_id}</code>",
            reply_markup=keyboard
        )

@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "🤖 <b>Бот статистики КЦ</b>\n\n"
        "<b>Менеджеры:</b>\n"
        "• <code>Звонки Дозвон% СМС Входяшки</code>\n"
        "• Пример: <code>213 54 10 5</code>\n\n"
        "<b>Админы:</b> кнопки меню\n\n"
        "⏰ Напоминания: 10:15, 13:50, 16:15, 18:15, 19:00 МСК\n"
        "🔄 Очистка: 00:00 МСК"
    )

# ═══════════════════════════════════════════════════════════
# ЗАЯВКИ
# ═══════════════════════════════════════════════════════════
@dp.callback_query(lambda c: c.data.startswith('accept_'))
async def accept_request(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    
    user_id = int(callback.data.split('_')[1])
    request = next((r for r in pending_requests if r.get('user_id') == user_id), None)
    
    if not request:
        await callback.answer("Обработана", show_alert=True)
        return
    
    await state.update_data(accept_user_id=user_id, request=request)
    await callback.message.answer(f"✏️ Введите <b>имя</b> для {request.get('full_name', '')}:")
    await state.set_state(AdminState.waiting_for_manager_name)
    await callback.answer()

@dp.message(StateFilter(AdminState.waiting_for_manager_name))
async def set_manager_name(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("❌ От 2 символов:")
        return
    
    data = await state.get_data()
    user_id = data['accept_user_id']
    request = data['request']
    
    managers[user_id] = {"name": name, "approved": True, "active": True}
    stats[user_id] = get_default_stats()
    save_all_data()
    
    if request in pending_requests:
        pending_requests.remove(request)
        safe_save_json(REQUESTS_FILE, pending_requests)
    
    await safe_send_message(user_id, f"🎉 <b>{name}, ты в команде!</b>\n/start")
    await message.answer(f"✅ <b>{name}</b> добавлен!", reply_markup=admin_keyboard())
    await state.clear()

@dp.callback_query(lambda c: c.data.startswith('reject_'))
async def reject_request(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔")
        return
    
    user_id = int(callback.data.split('_')[1])
    request = next((r for r in pending_requests if r.get('user_id') == user_id), None)
    if request:
        pending_requests.remove(request)
        safe_save_json(REQUESTS_FILE, pending_requests)
        await safe_send_message(user_id, "❌ Заявка отклонена.")
    await callback.message.edit_text(callback.message.text + "\n\n❌ <b>Отклонена</b>")
    await callback.answer("Отклонена")

# ═══════════════════════════════════════════════════════════
# ЗАПРОСЫ
# ═══════════════════════════════════════════════════════════
@dp.message(F.text == "📋 Запросы")
async def show_requests(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    
    if not pending_requests:
        await message.answer("📭 Нет заявок")
        return
    
    for i, req in enumerate(pending_requests, 1):
        user_id = req.get('user_id')
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_{user_id}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{user_id}")]
        ])
        await message.answer(
            f"📋 <b>ЗАЯВКА #{i}</b>\n"
            f"👤 {req.get('full_name')}\n"
            f"🆔 @{req.get('username')}\n"
            f"🔢 ID: <code>{user_id}</code>",
            reply_markup=keyboard
        )
        await asyncio.sleep(0.3)

# ═══════════════════════════════════════════════════════════
# АДМИН-ПАНЕЛЬ
# ═══════════════════════════════════════════════════════════
@dp.message(F.text == "📅 Отсутствие")
async def toggle_attendance_menu(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    
    approved = {uid: info for uid, info in managers.items() if info.get("approved")}
    if not approved:
        await message.answer("❌ Нет менеджеров")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for uid, info in approved.items():
        status = "✅" if info.get("active", True) else "❌"
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text=f"{status} {info['name']}", callback_data=f"toggle_{uid}")
        ])
    
    await message.answer(
        "📅 <b>Отметка присутствия</b>\n\n"
        "✅ — активен\n❌ — отсутствует\n\n"
        "<i>Сброс в 00:00 МСК</i>",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data.startswith('toggle_'))
async def toggle_attendance(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔")
        return
    
    user_id = int(callback.data.split('_')[1])
    if user_id not in managers:
        await callback.answer("Не найден")
        return
    
    current = managers[user_id].get("active", True)
    managers[user_id]["active"] = not current
    safe_save_json(MANAGERS_FILE, {str(k): v for k, v in managers.items()})
    
    name = managers[user_id]['name']
    status_text = "активен ✅" if not current else "отсутствует ❌"
    
    if not current:
        await safe_send_message(user_id, f"📅 <b>{name}, ты отмечен как отсутствующий.</b>")
    else:
        await safe_send_message(user_id, f"📅 <b>{name}, ты снова в строю!</b> 💪")
    
    await callback.answer(f"✅ {status_text}")

@dp.message(F.text == "✏️ Переименовать")
async def rename_menu(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    
    approved = {uid: info for uid, info in managers.items() if info.get("approved")}
    if not approved:
        await message.answer("❌ Нет менеджеров")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✏️ {info['name']}", callback_data=f"rename_{uid}")]
        for uid, info in approved.items()
    ])
    await message.answer("✏️ <b>Выберите:</b>", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data.startswith('rename_'))
async def rename_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔")
        return
    
    user_id = int(callback.data.split('_')[1])
    await state.update_data(rename_user_id=user_id)
    await callback.message.answer(f"Новое имя для <b>{managers[user_id]['name']}</b>:")
    await state.set_state(AdminState.waiting_for_rename)
    await callback.answer()

@dp.message(StateFilter(AdminState.waiting_for_rename))
async def process_rename(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    data = await state.get_data()
    user_id = data['rename_user_id']
    new_name = message.text.strip()
    if len(new_name) < 2:
        await message.answer("❌ От 2 символов")
        return
    
    old = managers[user_id]['name']
    managers[user_id]['name'] = new_name
    safe_save_json(MANAGERS_FILE, {str(k): v for k, v in managers.items()})
    await message.answer(f"✅ <b>{old}</b> → <b>{new_name}</b>", reply_markup=admin_keyboard())
    await safe_send_message(user_id, f"✏️ Твоё имя: <b>{new_name}</b>")
    await state.clear()

@dp.message(F.text == "👥 Менеджеры")
async def show_managers(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    
    approved = {uid: info for uid, info in managers.items() if info.get("approved")}
    if not approved:
        await message.answer("📭 Нет менеджеров")
        return
    
    text = "👥 <b>МЕНЕДЖЕРЫ:</b>\n\n"
    for uid, info in approved.items():
        status = "✅" if info.get("active", True) else "❌"
        data = stats.get(uid, {})
        zvonki = data.get('zvonki', data.get('calls', 0))
        dozvon = data.get('dozvon', data.get('connect', 0))
        sms = data.get('sms', data.get('smart', 0))
        vkhodyashki = data.get('vkhodyashki', 0)
        
        text += (
            f"{status} <b>{info['name']}</b>\n"
            f"   📞{zvonki} 📊{dozvon}% 📱{sms} 📥{vkhodyashki}\n"
            f"   🕐 {data.get('last_update', 'никогда')}\n\n"
        )
    
    await message.answer(text)

@dp.message(F.text == "📢 Рассылка")
async def broadcast_menu(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await message.answer("📢 Введите сообщение.\nОтмена: /cancel")
    await state.set_state(AdminState.waiting_for_broadcast)

@dp.message(StateFilter(AdminState.waiting_for_broadcast))
async def process_broadcast(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    if message.text == "/cancel":
        await message.answer("❌ Отменено", reply_markup=admin_keyboard())
        await state.clear()
        return
    
    count = await notify_managers(f"📢 <b>Сообщение:</b>\n\n{message.text}")
    await message.answer(f"✅ {count}", reply_markup=admin_keyboard())
    await state.clear()

@dp.message(F.text == "📜 История")
async def show_history(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    
    if not history:
        await message.answer("📭 Пусто")
        return
    
    for date in sorted(history.keys(), reverse=True)[:7]:
        text = f"📜 <b>{date}</b>\n\n"
        for uid_str, data in history[date].items():
            text += (
                f"👤 {data.get('name', uid_str)}\n"
                f"   📞{data.get('zvonki', 0)} 📊{data.get('dozvon', 0)}% 📱{data.get('sms', 0)} 📥{data.get('vkhodyashki', 0)}\n"
            )
        await message.answer(text)

# ═══════════════════════════════════════════════════════════
# СТАТИСТИКА
# ═══════════════════════════════════════════════════════════
@dp.message(F.text == "📝 Отправить стату")
async def send_stats_prompt(message: Message) -> None:
    if not is_manager(message.from_user.id):
        await message.answer("❌ /start")
        return
    
    if not is_active_today(message.from_user.id):
        await message.answer("⚠️ Отсутствующий сегодня")
        return
    
    await message.answer(
        "📊 <b>Отправьте статистику</b>\n\n"
        "Формат: <code>Звонки Дозвон% СМС Входяшки</code>\n\n"
        "Пример: <code>213 54 10 5</code>\n\n"
        "📞 Звонки | 📊 Дозвон% | 📱 СМС | 📥 Входяшки"
    )

@dp.message(
    F.text & ~F.text.startswith("/") & ~F.text.startswith("📊") & ~F.text.startswith("📤")
    & ~F.text.startswith("👥") & ~F.text.startswith("📋") & ~F.text.startswith("✏️")
    & ~F.text.startswith("📅") & ~F.text.startswith("📢") & ~F.text.startswith("📜")
)
async def handle_stats(message: Message) -> None:
    user_id = message.from_user.id
    
    if has_pending_request(user_id) and not is_manager(user_id):
        await message.answer("⏳ Заявка ещё не одобрена!")
        return
    
    if not is_manager(user_id):
        await message.answer("❌ /start")
        return
    
    if not is_active_today(user_id):
        await message.answer("⚠️ Отсутствующий сегодня")
        return
    
    parts = message.text.strip().split()
    if len(parts) != 4:
        await message.answer("❌ Формат: <code>Звонки Дозвон% СМС Входяшки</code>\nПример: <code>213 54 10 5</code>")
        return
    
    try:
        zvonki = int(parts[0])
        dozvon = int(parts[1])
        sms = int(parts[2])
        vkhodyashki = int(parts[3])
    except ValueError:
        await message.answer("❌ Только целые числа!")
        return
    
    if zvonki < 0 or dozvon < 0 or dozvon > 100 or sms < 0 or vkhodyashki < 0:
        await message.answer("❌ Звонки≥0, Дозвон 0-100%, СМС≥0, Входяшки≥0")
        return
    
    today = get_today_str()
    moscow_time = get_moscow_time()
    time_str = moscow_time.strftime("%d.%m.%Y %H:%M:%S")
    
    stats[user_id] = {
        "zvonki": zvonki,
        "dozvon": dozvon,
        "sms": sms,
        "vkhodyashki": vkhodyashki,
        "last_update": time_str,
        "date": today
    }
    safe_save_json(STATS_FILE, {str(k): v for k, v in stats.items()})
    
    name = get_manager_name(user_id)
    
    await message.answer(
        f"✅ <b>Сохранено!</b>\n\n"
        f"👤 <b>{name}</b>\n"
        f"📞 Звонки: <b>{zvonki}</b>\n"
        f"📊 Дозвон: <b>{dozvon}%</b>\n"
        f"📱 СМС: <b>{sms}</b>\n"
        f"📥 Входяшки: <b>{vkhodyashki}</b>\n\n"
        f"🕐 {time_str} МСК"
    )
    
    time_only = moscow_time.strftime("%H:%M:%S")
    for admin_id in ADMIN_IDS:
        await safe_send_message(
            admin_id,
            f"📝 <b>{name}</b> обновил:\n"
            f"📞{zvonki} 📊{dozvon}% 📱{sms} 📥{vkhodyashki}\n"
            f"🕐 {time_only} МСК"
        )

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("⛔")
        return
    
    approved = {uid: info for uid, info in managers.items() if info.get("approved")}
    if not approved:
        await message.answer("📭 Нет менеджеров")
        return
    
    text = "📊 <b>ТЕКУЩАЯ СТАТИСТИКА</b>\n\n"
    has_data = False
    
    total_zvonki = 0
    total_sms = 0
    total_vkhodyashki = 0
    dozvon_sum = 0
    dozvon_count = 0
    
    for uid, info in approved.items():
        data = stats.get(uid, {"zvonki": 0, "dozvon": 0, "sms": 0, "vkhodyashki": 0, "last_update": "никогда"})
        status = "✅" if info.get("active", True) else "❌"
        
        zvonki = data.get('zvonki', data.get('calls', 0))
        dozvon = data.get('dozvon', data.get('connect', 0))
        sms = data.get('sms', data.get('smart', 0))
        vkhodyashki = data.get('vkhodyashki', 0)
        
        text += (
            f"{status} <b>{info['name']}</b>\n"
            f"   📞{zvonki} 📊{dozvon}% 📱{sms} 📥{vkhodyashki}\n"
            f"   🕐 {data['last_update']}\n\n"
        )
        if zvonki > 0:
            has_data = True
            total_zvonki += zvonki
            total_sms += sms
            total_vkhodyashki += vkhodyashki
            dozvon_sum += dozvon
            dozvon_count += 1
    
    if has_data:
        avg_dozvon = round(dozvon_sum / dozvon_count, 1) if dozvon_count > 0 else 0
        text += "━━━━━━━━━━━━━━━━━━━━\n"
        text += "<b>📊 ВСЕГО:</b>\n"
        text += f"   📞{total_zvonki} 📊{avg_dozvon}% (среднее) 📱{total_sms} 📥{total_vkhodyashki}\n"
    
    if not has_data:
        text += "⚠️ <i>Нет данных сегодня</i>"
    
    await message.answer(text)

@dp.message(F.text == "📤 Опубликовать")
async def publish_stats(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("⛔")
        return
    
    text = "📢 <b>ОБЩАЯ СТАТИСТИКА КЦ</b>\n\n"
    has_data = False
    
    total_zvonki = 0
    total_sms = 0
    total_vkhodyashki = 0
    dozvon_sum = 0
    dozvon_count = 0
    
    for uid, data in stats.items():
        if not (uid in managers and managers[uid].get("approved") and managers[uid].get("active", True)):
            continue
        
        zvonki = data.get('zvonki', data.get('calls', 0))
        dozvon = data.get('dozvon', data.get('connect', 0))
        sms = data.get('sms', data.get('smart', 0))
        vkhodyashki = data.get('vkhodyashki', 0)
        
        if zvonki > 0:
            has_data = True
            name = managers[uid]['name']
            text += (
                f"👤 <b>{name}</b>\n"
                f"📞 Звонки: {zvonki}\n"
                f"📊 Дозвон: {dozvon}%\n"
                f"📱 СМС: {sms}\n"
                f"📥 Входяшки: {vkhodyashki}\n\n"
            )
            total_zvonki += zvonki
            total_sms += sms
            total_vkhodyashki += vkhodyashki
            dozvon_sum += dozvon
            dozvon_count += 1
    
    if not has_data:
        await message.answer("📭 Нет данных")
        return
    
    avg_dozvon = round(dozvon_sum / dozvon_count, 1) if dozvon_count > 0 else 0
    
    text += "━━━━━━━━━━━━━━━━━━━━\n"
    text += "<b>📊 ВСЕГО:</b>\n"
    text += f"📞 Звонки: <b>{total_zvonki}</b>\n"
    text += f"📊 Дозвон: <b>{avg_dozvon}%</b> (среднее)\n"
    text += f"📱 СМС: <b>{total_sms}</b>\n"
    text += f"📥 Входяшки: <b>{total_vkhodyashki}</b>\n"
    
    text += f"\n🕐 <i>{get_time_str()} МСК</i>"
    
    try:
        await bot.send_message(GROUP_CHAT_ID, text)
        await message.answer(f"✅ Опубликовано!\n🕐 {get_time_str()} МСК")
    except Exception as e:
        await message.answer(f"❌ {e}")

# ═══════════════════════════════════════════════════════════
# ЗАПУСК
# ═══════════════════════════════════════════════════════════
async def on_startup() -> None:
    global last_cleanup_date
    
    logger.info("🚀 Запуск...")
    load_all_data()
    
    today = get_today_str()
    
    if last_cleanup_date != today:
        old_data = any(
            data.get('date') != today and (data.get('zvonki', 0) > 0 or data.get('calls', 0) > 0)
            for data in stats.values()
        )
        if old_data:
            archive_and_clear_stats()
        else:
            save_cleanup_date(today)
    
    asyncio.create_task(reminder_scheduler())
    asyncio.create_task(daily_reset_scheduler())
    
    active_count = sum(1 for m in managers.values() if m.get("approved") and m.get("active", True))
    
    logger.info(f"✅ БОТ ЗАПУЩЕН! Менеджеров: {active_count}")
    
    await notify_admins(
        f"🟢 <b>Бот КЦ запущен!</b>\n"
        f"👥 Активных: {active_count}\n"
        f"🕐 {get_moscow_time().strftime('%H:%M:%S')} МСК"
    )

async def on_shutdown() -> None:
    save_all_data()
    await notify_admins("🔴 Бот остановлен.")

async def main() -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"💥 {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Остановлен")
    except Exception as e:
        logger.critical(f"💥 {e}")
        sys.exit(1)
