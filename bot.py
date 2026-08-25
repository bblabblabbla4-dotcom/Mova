import asyncio
import logging
import sqlite3
from difflib import SequenceMatcher
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

BOT_TOKEN = "8921893085:AAGUx1KDGs7wrH9fjkOLfrP7rT96Dp_TpjA"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- ІНІЦІАЛІЗАЦІЯ БАЗИ ДАНИХ SQLite ---
def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    # Таблиця карток
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            deck_name TEXT,
            photo_id TEXT,
            sk_word TEXT,
            ua_word TEXT
        )
    """)
    # Таблиця статистики користувачів по наборах
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            user_id INTEGER,
            deck_name TEXT,
            learned INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, deck_name)
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- FSM (Стани) ---
class CardForm(StatesGroup):
    waiting_for_deck_name = State()
    waiting_for_photo = State()
    waiting_for_sk = State()
    waiting_for_ua = State()

class StudyForm(StatesGroup):
    answering = State()

def get_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()

# --- ГОЛОВНЕ МЕНЮ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Створити / Додати в набір")
    builder.button(text="🧠 Вчити слова")
    builder.button(text="📊 Статистика наборів")
    builder.adjust(2, 1)
    
    await message.answer(
        "Привіт! Я твій розширений помічник для вивчення словацької мови 🇸🇰\n"
        "Обери потрібну дію на клавіатурі нижче:",
        reply_markup=builder.as_markup(resize_keyboard=True)
    )

# --- ДОДАВАННЯ КАРТОК ---
@dp.message(F.text == "➕ Створити / Додати в набір")
async def start_add_card(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT deck_name FROM cards WHERE user_id = ?", (user_id,))
    decks = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    msg = "Введіть назву набору (існуючого або нового):"
    if decks:
        msg += f"\nВаші існуючі набори: {', '.join(decks)}"
        
    await message.answer(msg)
    await state.set_state(CardForm.waiting_for_deck_name)

@dp.message(CardForm.waiting_for_deck_name)
async def process_deck_name(message: types.Message, state: FSMContext):
    await state.update_data(deck_name=message.text.strip())
    await message.answer("Крок 1/3: Надішліть фотографію для картки:")
    await state.set_state(CardForm.waiting_for_photo)

@dp.message(CardForm.waiting_for_photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await message.answer("Крок 2/3: Напишіть слово **словацькою** мовою:")
    await state.set_state(CardForm.waiting_for_sk)

@dp.message(CardForm.waiting_for_sk)
async def process_sk(message: types.Message, state: FSMContext):
    await state.update_data(sk_word=message.text.strip())
    await message.answer("Крок 3/3: Напишіть переклад **українською** мовою:")
    await state.set_state(CardForm.waiting_for_ua)

@dp.message(CardForm.waiting_for_ua)
async def process_ua(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    deck_name = data["deck_name"]
    
    # Зберігаємо в базу даних
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO cards (user_id, deck_name, photo_id, sk_word, ua_word) VALUES (?, ?, ?, ?, ?)",
        (user_id, deck_name, data["photo_id"], data["sk_word"], message.text.strip())
    )
    # Ініціалізуємо статистику, якщо її ще немає
    cursor.execute(
        "INSERT OR IGNORE INTO stats (user_id, deck_name, learned, failed) VALUES (?, ?, 0, 0)",
        (user_id, deck_name)
    )
    conn.commit()
    conn.close()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Додати ще картку", callback_data=f"add_more:{deck_name}")
    builder.button(text="✅ Завершити", callback_data="finish_add")
    
    await message.answer(f"✅ Картку успішно додано до набору '{deck_name}'!", reply_markup=builder.as_markup())
    await state.clear()

@dp.callback_query(F.data.startswith("add_more:"))
async def add_more_callback(call: types.CallbackQuery, state: FSMContext):
    deck_name = call.data.split(":")[1]
    await state.update_data(deck_name=deck_name)
    await call.message.answer(f"Набір: **{deck_name}**.\nНадішліть фотографію для нової картки:")
    await state.set_state(CardForm.waiting_for_photo)
    await call.answer()

@dp.callback_query(F.data == "finish_add")
async def finish_add_callback(call: types.CallbackQuery):
    await call.message.answer("Збереження завершено! Можете розпочати тренування у головному меню.")
    await call.answer()

# --- СТАТИСТИКА ---
@dp.message(F.text == "📊 Статистика наборів")
async def show_statistics(message: types.Message):
    user_id = message.from_user.id
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT deck_name, learned, failed FROM stats WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    
    if not rows:
        conn.close()
        await message.answer("У вас поки немає статистики. Створіть набір та почніть навчання!")
        return
        
    text = "📊 **Ваша статистика вивчення:**\n\n"
    for deck_name, learned, failed in rows:
        cursor.execute("SELECT COUNT(*) FROM cards WHERE user_id = ? AND deck_name = ?", (user_id, deck_name))
        total = cursor.fetchone()[0]
        text = text + f"📁 **Набір: `{deck_name}`\n" \
                      f"  • Всього слів: {total}\n" \
                      f"  • Знаю (успішно): {learned}\n" \
                      f"  • Не знаю (помилки/здався): {failed}\n\n"
                      
    conn.close()
    await message.answer(text, parse_mode="Markdown")

# --- ВИВЧЕННЯ СЛІВ ---
@dp.message(F.text == "🧠 Вчити слова")
async def start_study(message: types.Message):
    user_id = message.from_user.id
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT deck_name FROM cards WHERE user_id = ?", (user_id,))
    decks = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    if not decks:
        await message.answer("У вас ще немає створених наборів. Спочатку додайте картки!")
        return
        
    builder = InlineKeyboardBuilder()
    for deck in decks:
        builder.button(text=deck, callback_data=f"study_deck:{deck}")
    builder.adjust(1)
    
    await message.answer("Оберіть набір для тренування:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("study_deck:"))
async def process_study_deck(call: types.CallbackQuery, state: FSMContext):
    deck_name = call.data.split(":")[1]
    user_id = call.from_user.id
    
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, photo_id, sk_word, ua_word FROM cards WHERE user_id = ? AND deck_name = ?", (user_id, deck_name))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        await call.message.answer("Цей набір порожній.")
        await call.answer()
        return
        
    cards = [{"id": r[0], "photo_id": r[1], "sk": r[2], "ua": r[3]} for r in rows]
    
    await state.update_data(cards=cards, current_idx=0, deck_name=deck_name, session_failed=[])
    await call.answer()
    await send_next_card(call.message, state)

async def send_next_card(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cards = data["cards"]
    idx = data["current_idx"]
    
    if idx >= len(cards):
        failed_cards = data.get("session_failed", [])
        if failed_cards:
            builder = InlineKeyboardBuilder()
            builder.button(text="🔄 Повторити невивчені слова", callback_data="retry_failed")
            builder.button(text="🏠 Головне меню", callback_data="go_home")
            await message.answer(
                f"🎉 Ви пройшли коло!\nАле є слова, які ви не вгадали ({len(failed_cards)} шт.). Хочете повторити їх?",
                reply_markup=builder.as_markup()
            )
        else:
            await message.answer("🏆 Вітаю! Ви ідеально пройшли всі картки цього набору без помилок!")
            await state.clear()
        return
        
    card = cards[idx]
    builder = InlineKeyboardBuilder()
    builder.button(text="🏳️ Не знаю (показати відповідь)", callback_data="give_up")
    
    caption = f"Перекладіть словацькою:\n**\n\n*(Картка {idx + 1} з {len(cards)})*"
    
    await message.answer_photo(
        photo=card["photo_id"],
        caption=caption,
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )
    await state.set_state(StudyForm.answering)

@dp.callback_query(F.data == "retry_failed")
async def retry_failed_callback(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    failed = data.get("session_failed", [])
    await state.update_data(cards=failed, current_idx=0, session_failed=[])
    await call.answer()
    await send_next_card(call.message, state)

@dp.callback_query(F.data == "go_home")
async def go_home_callback(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("Повертаємось у головне меню. Оберіть дію нижче.")
    await call.answer()

@dp.message(StudyForm.answering)
async def check_answer(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cards = data["cards"]
    idx = data["current_idx"]
    card = cards[idx]
    deck_name = data["deck_name"]
    user_id = message.from_user.id
    
    user_ans = message.text.strip()
    correct_ans = card["sk"]
    
    similarity = get_similarity(user_ans, correct_ans)
    
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    
    if similarity >= 0.8:
        cursor.execute("UPDATE stats SET learned = learned + 1 WHERE user_id = ? AND deck_name = ?", (user_id, deck_name))
        conn.commit()
        conn.close()
        
        if similarity == 1.0:
            await message.answer("✨ Ідеально правильно!")
        else:
            await message.answer(f"✅ Зараховано! (Правильне написання: **{correct_ans})")
            
        await state.update_data(current_idx=idx + 1)
        await send_next_card(message, state)
    else:
        cursor.execute("UPDATE stats SET failed = failed + 1 WHERE user_id = ? AND deck_name = ?", (user_id, deck_name))
        conn.commit()
        conn.close()
        
        # Додаємо у список на переповторення в поточному сеансі
        failed_list = data.get("session_failed", [])
        if card not in failed_list:
            failed_list.append(card)
        await state.update_data(session_failed=failed_list)
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🏳️ Не знаю (показати відповідь)", callback_data="give_up")
        await message.answer("❌ Не зовсім так. Спробуйте ще раз або натисніть кнопку нижче:", reply_markup=builder.as_markup())

@dp.callback_query(StudyForm.answering, F.data == "give_up")
async def give_up_callback(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cards = data["cards"]
    idx = data["current_idx"]
    card = cards[idx]
    deck_name = data["deck_name"]
    user_id = call.from_user.id
    
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE stats SET failed = failed + 1 WHERE user_id = ? AND deck_name = ?", (user_id, deck_name))
    conn.commit()
    conn.close()
    
    failed_list = data.get("session_failed", [])
    if card not in failed_list:
        failed_list.append(card)
    await state.update_data(session_failed=failed_list)
    
    await call.message.answer(f"Правильна відповідь: **")
    await state.update_data(current_idx=idx + 1)
    await call.answer()
    await send_next_card(call.message, state)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
