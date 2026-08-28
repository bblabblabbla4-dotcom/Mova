import asyncio
import logging
import sqlite3
from difflib import SequenceMatcher
from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import TelegramBadRequest
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

class EditDeckForm(StatesGroup):
    waiting_for_new_name = State()

class EditCardForm(StatesGroup):
    waiting_for_new_sk = State()
    waiting_for_new_ua = State()

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
    builder.button(text="⚙️ Управління наборами")
    builder.adjust(2, 2)
    
    await message.answer(
        "Привіт! Я твій помічник для вивчення словацької мови 🇸🇰\n"
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
    await message.answer("Крок 2/3: Напишіть слово <b>словацькою</b> мовою:", parse_mode="HTML")
    await state.set_state(CardForm.waiting_for_sk)

@dp.message(CardForm.waiting_for_sk)
async def process_sk(message: types.Message, state: FSMContext):
    await state.update_data(sk_word=message.text.strip())
    await message.answer("Крок 3/3: Напишіть переклад <b>українською</b> мовою:", parse_mode="HTML")
    await state.set_state(CardForm.waiting_for_ua)

@dp.message(CardForm.waiting_for_ua)
async def process_ua(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    deck_name = data["deck_name"]
    
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO cards (user_id, deck_name, photo_id, sk_word, ua_word) VALUES (?, ?, ?, ?, ?)",
        (user_id, deck_name, data["photo_id"], data["sk_word"], message.text.strip())
    )
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
    await call.message.answer(f"Набір: <b>{deck_name}</b>.\nНадішліть фотографію для нової картки:", parse_mode="HTML")
    await state.set_state(CardForm.waiting_for_photo)
    await call.answer()

@dp.callback_query(F.data == "finish_add")
async def finish_add_callback(call: types.CallbackQuery):
    await call.message.answer("Збереження завершено! Можете розпочати тренування у головному меню.")
    await call.answer()

# --- УПРАВЛІННЯ НАБОРАМИ ТА КАРТКАМИ ---
@dp.message(F.text == "⚙️ Управління наборами")
async def manage_decks(message: types.Message):
    user_id = message.from_user.id
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT deck_name FROM cards WHERE user_id = ?", (user_id,))
    decks = [row[0] for row in cursor.fetchall()]
    conn.close()

    if not decks:
        await message.answer("У вас поки немає створених наборів.")
        return

    builder = InlineKeyboardBuilder()
    for deck in decks:
        builder.button(text=f"📁 {deck}", callback_data=f"deck_menu:{deck}")
    builder.adjust(1)

    await message.answer("Оберіть набір для керування:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("deck_menu:"))
async def deck_menu_callback(call: types.CallbackQuery):
    deck_name = call.data.split(":")[1]
    builder = InlineKeyboardBuilder()
    builder.button(text="🎴 Список карток / Редагувати", callback_data=f"list_cards:{deck_name}")
    builder.button(text="➕ Додати картку в набір", callback_data=f"add_more:{deck_name}")
    builder.button(text="✏️ Перейменувати набір", callback_data=f"rename_deck:{deck_name}")
    builder.button(text="🗑 Видалити весь набір", callback_data=f"confirm_delete:{deck_name}")
    builder.button(text="⬅️ До списку наборів", callback_data="back_to_manage")
    builder.adjust(1)

    await call.message.edit_text(f"Керування набором <b>{deck_name}</b>:", parse_mode="HTML", reply_markup=builder.as_markup())
    await call.answer()

@dp.callback_query(F.data == "back_to_manage")
async def back_to_manage_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT deck_name FROM cards WHERE user_id = ?", (user_id,))
    decks = [row[0] for row in cursor.fetchall()]
    conn.close()

    builder = InlineKeyboardBuilder()
    for deck in decks:
        builder.button(text=f"📁 {deck}", callback_data=f"deck_menu:{deck}")
    builder.adjust(1)

    await call.message.edit_text("Оберіть набір для керування:", reply_markup=builder.as_markup())
    await call.answer()

# Список усіх карток набору
@dp.callback_query(F.data.startswith("list_cards:"))
async def list_cards_callback(call: types.CallbackQuery):
    deck_name = call.data.split(":")[1]
    user_id = call.from_user.id
    
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, sk_word, ua_word FROM cards WHERE user_id = ? AND deck_name = ?", (user_id, deck_name))
    cards = cursor.fetchall()
    conn.close()

    if not cards:
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data=f"deck_menu:{deck_name}")
        await call.message.edit_text(f"У наборі <b>{deck_name}</b> поки немає карток.", parse_mode="HTML", reply_markup=builder.as_markup())
        await call.answer()
        return

    builder = InlineKeyboardBuilder()
    for card_id, sk, ua in cards:
        builder.button(text=f"{ua} ↔️ {sk}", callback_data=f"card_menu:{card_id}")
    builder.button(text="⬅️ Назад", callback_data=f"deck_menu:{deck_name}")
    builder.adjust(1)

    await call.message.edit_text(f"Картки в наборі <b>{deck_name}</b> (натисніть на картку для дій):", parse_mode="HTML", reply_markup=builder.as_markup())
    await call.answer()

# Меню окремої картки (видалення / редагування)
@dp.callback_query(F.data.startswith("card_menu:"))
async def card_menu_callback(call: types.CallbackQuery):
    card_id = int(call.data.split(":")[1])
    
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT deck_name, sk_word, ua_word FROM cards WHERE id = ?", (card_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await call.answer("Картку не знайдено.")
        return

    deck_name, sk, ua = row
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Змінити словацький варіант", callback_data=f"edit_sk:{card_id}")
    builder.button(text="✏️ Змінити український варіант", callback_data=f"edit_ua:{card_id}")
    builder.button(text="🗑 Видалити цю картку", callback_data=f"delete_card:{card_id}")
    builder.button(text="⬅️ Назад до карток", callback_data=f"list_cards:{deck_name}")
    builder.adjust(1)

    await call.message.edit_text(
        f"Картка:\n🇺🇦 <b>{ua}</b>\n🇸🇰 <b>{sk}</b>\n\nОберіть дію:",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await call.answer()

# Редагування словацького слова
@dp.callback_query(F.data.startswith("edit_sk:"))
async def edit_sk_callback(call: types.CallbackQuery, state: FSMContext):
    card_id = int(call.data.split(":")[1])
    await state.update_data(edit_card_id=card_id)
    await call.message.answer("Введіть новий словацький варіант:")
    await state.set_state(EditCardForm.waiting_for_new_sk)
    await call.answer()

@dp.message(EditCardForm.waiting_for_new_sk)
async def process_new_sk(message: types.Message, state: FSMContext):
    data = await state.get_data()
    card_id = data["edit_card_id"]
    new_sk = message.text.strip()

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE cards SET sk_word = ? WHERE id = ?", (new_sk, card_id))
    conn.commit()
    conn.close()

    await message.answer(f"✅ Словацьке слово успішно змінено на <b>{new_sk}</b>!", parse_mode="HTML")
    await state.clear()

# Редагування українського перекладу
@dp.callback_query(F.data.startswith("edit_ua:"))
async def edit_ua_callback(call: types.CallbackQuery, state: FSMContext):
    card_id = int(call.data.split(":")[1])
    await state.update_data(edit_card_id=card_id)
    await call.message.answer("Введіть новий український переклад:")
    await state.set_state(EditCardForm.waiting_for_new_ua)
    await call.answer()

@dp.message(EditCardForm.waiting_for_new_ua)
async def process_new_ua(message: types.Message, state: FSMContext):
    data = await state.get_data()
    card_id = data["edit_card_id"]
    new_ua = message.text.strip()

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE cards SET ua_word = ? WHERE id = ?", (new_ua, card_id))
    conn.commit()
    conn.close()

    await message.answer(f"✅ Українське слово успішно змінено на <b>{new_ua}</b>!", parse_mode="HTML")
    await state.clear()

# Видалення окремої картки
@dp.callback_query(F.data.startswith("delete_card:"))
async def delete_card_callback(call: types.CallbackQuery):
    card_id = int(call.data.split(":")[1])

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT deck_name FROM cards WHERE id = ?", (card_id,))
    row = cursor.fetchone()
    if row:
        deck_name = row[0]
        cursor.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        conn.commit()
        conn.close()

        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад до списку карток", callback_data=f"list_cards:{deck_name}")
        await call.message.edit_text("🗑 Картку успішно видалено!", reply_markup=builder.as_markup())
    else:
        conn.close()
        await call.message.edit_text("Картку не знайдено.")
    await call.answer()

# Перейменування набору
@dp.callback_query(F.data.startswith("rename_deck:"))
async def rename_deck_callback(call: types.CallbackQuery, state: FSMContext):
    deck_name = call.data.split(":")[1]
    await state.update_data(old_deck_name=deck_name)
    await call.message.answer(f"Введіть нову назву для набору <b>{deck_name}</b>:", parse_mode="HTML")
    await state.set_state(EditDeckForm.waiting_for_new_name)
    await call.answer()

@dp.message(EditDeckForm.waiting_for_new_name)
async def process_rename_deck(message: types.Message, state: FSMContext):
    new_name = message.text.strip()
    data = await state.get_data()
    old_name = data["old_deck_name"]
    user_id = message.from_user.id

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE cards SET deck_name = ? WHERE user_id = ? AND deck_name = ?", (new_name, user_id, old_name))
    cursor.execute("UPDATE stats SET deck_name = ? WHERE user_id = ? AND deck_name = ?", (new_name, user_id, old_name))
    conn.commit()
    conn.close()

    await message.answer(f"✅ Набір <b>{old_name}</b> успішно перейменовано на <b>{new_name}</b>!", parse_mode="HTML")
    await state.clear()

# Видалення всього набору
@dp.callback_query(F.data.startswith("confirm_delete:"))
async def confirm_delete_callback(call: types.CallbackQuery):
    deck_name = call.data.split(":")[1]
    builder = InlineKeyboardBuilder()
    builder.button(text="🔥 Так, видалити весь набір", callback_data=f"delete_deck:{deck_name}")
    builder.button(text="❌ Скасувати", callback_data="back_to_manage")
    builder.adjust(1, 1)

    await call.message.edit_text(
        f"⚠️ Ви дійсно хочете видалити набір <b>{deck_name}</b> та всі його картки?",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await call.answer()

@dp.callback_query(F.data.startswith("delete_deck:"))
async def delete_deck_callback(call: types.CallbackQuery):
    deck_name = call.data.split(":")[1]
    user_id = call.from_user.id

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cards WHERE user_id = ? AND deck_name = ?", (user_id, deck_name))
    cursor.execute("DELETE FROM stats WHERE user_id = ? AND deck_name = ?", (user_id, deck_name))
    conn.commit()
    conn.close()

    await call.message.edit_text(f"🗑 Набір <b>{deck_name}</b> успішно видалено!", parse_mode="HTML")
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
        
    text = "📊 <b>Ваша статистика вивчення:</b>\n\n"
    for deck_name, learned, failed in rows:
        cursor.execute("SELECT COUNT(*) FROM cards WHERE user_id = ? AND deck_name = ?", (user_id, deck_name))
        total = cursor.fetchone()[0]
        text += f"📁 <b>Набір: <code>{deck_name}</code></b>\n" \
                f"  • Всього слів: {total}\n" \
                f"  • Знаю (успішно): {learned}\n" \
                f"  • Не знаю (помилки/здався): {failed}\n\n"
                      
    conn.close()
    await message.answer(text, parse_mode="HTML")
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

    caption = f"Перекладіть словацькою:\n<b>{card['ua']}</b> 🇺🇦\n\n<i>(Картка {idx + 1} з {len(cards)})</i>"

    await message.answer_photo(
        photo=card["photo_id"],
        caption=caption,
        parse_mode="HTML",
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
# --- ОНОВЛЕНИЙ ОБРОБНИК ВІДПОВІДЕЙ ТА ДОПОМІЖНІ ФУНКЦІЇ ---

def check_user_answer(user_input: str, correct_text: str):
    options = [opt.strip() for opt in correct_text.split('/') if opt.strip()]
    user_clean = user_input.strip().lower()

    for opt in options:
        similarity = get_similarity(user_clean, opt.lower())
        if similarity >= 0.8:
            return True, opt, options

    return False, None, options

@dp.message(StudyForm.answering)
async def check_answer(message: types.Message, state: FSMContext):
    # далі йде код перевірки...

    data = await state.get_data()
    cards = data["cards"]
    idx = data["current_idx"]
    card = cards[idx]
    deck_name = data["deck_name"]
    user_id = message.from_user.id

    user_ans = message.text.strip()
    correct_ans = card["sk"]

    is_correct, matched_opt, all_opts = check_user_answer(user_ans, correct_ans)

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    if is_correct:
        cursor.execute("UPDATE stats SET learned = learned + 1 WHERE user_id = ? AND deck_name = ?", (user_id, deck_name))
        conn.commit()
        conn.close()

        # Формуємо повідомлення
        msg = "✨ Правильно!"

        # Якщо варіантів декілька (були розділені '/'), нагадуємо інші варіанти
        if len(all_opts) > 1:
            other_opts = [opt for opt in all_opts if opt.lower() != matched_opt.lower()]
            if other_opts:
                msg += f"\n💡 <i>Нагадування: також можна вжити:</i> <b>{', '.join(other_opts)}</b>"

        await message.answer(msg, parse_mode="HTML")

        await state.update_data(current_idx=idx + 1)
        await send_next_card(message, state)
    else:
        cursor.execute("UPDATE stats SET failed = failed + 1 WHERE user_id = ? AND deck_name = ?", (user_id, deck_name))
        conn.commit()
        conn.close()

        failed_list = data.get("session_failed", [])
        if card not in failed_list:
            failed_list.append(card)
        await state.update_data(session_failed=failed_list)

        builder = InlineKeyboardBuilder()
        builder.button(text="🏳️ Не знаю (показати відповідь)", callback_data="give_up")

        hint = f"❌ Не зовсім так. Спробуйте ще раз."
        if len(all_opts) > 1:
            hint += f"\n(У цьому слові є {len(all_opts)} варіанти перекладу через '/')"

        await message.answer(hint, reply_markup=builder.as_markup())

@dp.callback_query(F.data == "give_up")
async def give_up_callback(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cards = data.get("cards", [])
    idx = data.get("current_idx", 0)

    if idx >= len(cards):
        await call.answer()
        return

    card = cards[idx]
    deck_name = data.get("deck_name", "")
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

    new_caption = f"Українською: <b>{card['ua']}</b> 🇺🇦\nСловацькою: <b>{card['sk']}</b> 🇸🇰"

    builder = InlineKeyboardBuilder()
    builder.button(text="Наступне слово ➡️", callback_data="next_card_after_reveal")

    try:
        await call.message.edit_caption(
            caption=new_caption,
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
    except TelegramBadRequest:
        pass

    await call.answer()

@dp.callback_query(F.data == "next_card_after_reveal")
async def next_card_after_reveal(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    idx = data.get("current_idx", 0)
    await state.update_data(current_idx=idx + 1)
    await call.answer()
    await send_next_card(call.message, state)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

