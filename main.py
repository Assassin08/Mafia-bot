import logging
import asyncio
import re
import os
import random
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# Token va jurnallarni sozlash
BOT_TOKEN = os.getenv("BOT_TOKEN")
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Mafia Ultimate Ma'lumotlar Bazasi (In-Memory DB)
players_db = {}   # {user_id: {"username": str, "coins": int, "diamonds": int, "games": int, "wins": int, "rank": str, "achievements": list, "last_daily": str}}
active_games = {} # {chat_id: {"status": str, "creator": int, "players": list, "player_names": dict, "roles": dict, "alive": list, "votes": dict, "night_actions": dict, "timer_task": None, "time_left": int}}

# VIP Akkaunt egasi (Siz uchun cheksiz resurslar va unvon)
OWNER_USERNAME = "Rahmonjonov_Muhammadjon"

# ==================== ADVANCED ULTIMATE ROLES POOL ====================
ROLES = {
    "mafia": {"name": "🩸 Mafia", "team": "mafia", "desc": "Tunda tinch aholini o'ldirishga ovoz beradi."},
    "don": {"name": "🕵️‍♂️ Don", "team": "mafia", "desc": "Mafiya sardori. Tunda Komissarni qidiradi."},
    "cop": {"name": "🔍 Komissar", "team": "citizen", "desc": "Shahar himoyachisi. Tunda gumonlanuvchini tekshiradi."},
    "doc": {"name": "❤️ Doktor", "team": "citizen", "desc": "Tunda bitta o'yinchini o'limdan qutqaradi."},
    "citizen": {"name": "⚪️ Tinch aholi", "team": "citizen", "desc": "Tunda kuchi yo'q, kunduzi mantiq bilan mafiyani topadi."},
    # Siz aytgan maxsus mukammal rollar:
    "agent": {"name": "🕵️ Agent", "team": "citizen", "desc": "Har kecha bitta o'yinchining rolini tekshiradi."},
    "hacker": {"name": "💻 Hacker", "team": "neutral", "desc": "Bir kecha davomida boshqa rol qobiliyatini bloklaydi."},
    "assassin": {"name": "🔫 Assassin", "team": "neutral", "desc": "Mafiyadan mustaqil qotil. Maqsadi - yolg'iz g'alaba."},
    "guitarist": {"name": "🎸 Guitarist", "team": "citizen", "desc": "Bir o'yinchini himoya qiladi va ovozlarini kuchaytiradi."},
    "lover_boy": {"name": "❤️ Lover Boy", "team": "citizen", "desc": "Ikki kishini bog'laydi. Ulardan biri o'lsa ikkinchisi ham o'ladi."},
    "chameleon": {"name": "🎭 Chameleon", "team": "neutral", "desc": "Har kecha boshqa rolga taqlid qiladi (tasodifiy kuch oladi)."}
}

# Ranks Tizimi
RANKS = ["Beginner", "Bronze", "Silver", "Gold", "Platinum", "Diamond", "Master", "Grand Master", "Legend"]

# Do'kon Jihozlari
SHOP_ITEMS = {
    "shield": {"name": "🛡 Shield", "price": 100, "diamonds": 0, "desc": "Tungi hujumdan himoya."},
    "mask": {"name": "🎭 Mask", "price": 150, "diamonds": 0, "desc": "Rolingizni yashiradi."},
    "bribe": {"name": "💰 Bribe", "price": 200, "diamonds": 0, "desc": "Ovozlarni kamaytiradi."},
    "main_role": {"name": "⭐ Main Role", "price": 1000, "diamonds": 0, "desc": "Maxsus rol olish imkoniyati."},
    "custom_role": {"name": "🎨 Custom Role", "price": 0, "diamonds": 10, "desc": "Shaxsiy rol dizayni."},
    "pistol": {"name": "🔫 Pistol", "price": 0, "diamonds": 5, "desc": "Qo'shimcha otish imkoniyati."},
    "chameleon_pack": {"name": "🦎 Chameleon", "price": 0, "diamonds": 5, "desc": "Chameleon rolini faollashtirish."}
}

def get_player(user_id: int, username: str):
    """Statistikalar, Iqtisodiyot va VIP boshqaruv asosi"""
    if username == OWNER_USERNAME:
        return {
            "username": username, "coins": 999999, "diamonds": 99999,
            "games": 245, "wins": 132, "rank": "Master",
            "achievements": ["Birinchi g'alaba", "10 g'alaba", "Mafia qiroli", "Assassin ustasi"],
            "last_daily": ""
        }
    if user_id not in players_db:
        players_db[user_id] = {
            "username": username, "coins": 100, "diamonds": 5,
            "games": 0, "wins": 0, "rank": "Beginner",
            "achievements": [], "last_daily": ""
        }
    
    # Unvonni avtomatik yangilash mantiqi
    p = players_db[user_id]
    idx = min(p["wins"] // 15, len(RANKS) - 1)
    p["rank"] = RANKS[idx]
    return p

# ==================== GAME REGISTRATION PANEL (/game) ====================

@dp.message(F.text == "/game")
async def cmd_create_game(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username or "Player"
    
    if chat_id in active_games:
        return await message.reply("⚠️ Bu guruhda allaqachon faol o'yin jarayoni ketmoqda!")
        
    active_games[chat_id] = {
        "status": "registration", "creator": user_id, "players": [user_id],
        "player_names": {user_id: username}, "roles": {}, "alive": [], "votes": {}, "night_actions": {},
        "timer_task": None, "time_left": 60
    }
    
    # Birinchi marta ro'yxat oynasini chiqarish
    await send_lobby_msg(message, chat_id, is_new=True)

async def send_lobby_msg(message: Message, chat_id: int, is_new=False):
    game = active_games[chat_id]
    text = (
        f"🎭 **Sirli Mafia — Ultimate Edition**\n\n"
        f"O'yinga ro'yxatdan o'tish boshlandi!\n\n"
        f"👥 O'yinchilar: {len(game['players'])}/30\n"
        f"⏳ Boshlanish: {game['time_left']} soniya"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Qo'shilish", callback_data="mafia_join"),
         InlineKeyboardButton(text="➖ Chiqish", callback_data="mafia_leave")],
        [InlineKeyboardButton(text="📋 O'yinchilar", callback_data="mafia_list"),
         InlineKeyboardButton(text="❌ Bekor qilish", callback_data="mafia_cancel")]
    ])
    
    if is_new:
        msg = await message.answer(text, reply_markup=keyboard)
        # Avtomatik 60 soniyalik taymerni fonda ishga tushirish
        game["timer_task"] = asyncio.create_task(lobby_timer(chat_id, msg))
    else:
        try:
            await message.edit_text(text, reply_markup=keyboard)
        except Exception: pass

async def lobby_timer(chat_id: int, message: Message):
    while chat_id in active_games and active_games[chat_id]["status"] == "registration":
        await asyncio.sleep(10)
        if chat_id not in active_games: break
        game = active_games[chat_id]
        game["time_left"] -= 10
        
        if game["time_left"] <= 0:
            await start_game_logic(chat_id, message)
            break
        else:
            await send_lobby_msg(message, chat_id, is_new=False)

# ==================== LOBBY BUTTON INTERACTIONS ====================

@dp.callback_query(F.data == "mafia_join")
async def process_lobby_join(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    username = callback.from_user.username or "Player"
    
    if chat_id not in active_games: return
    game = active_games[chat_id]
    
    if len(game["players"]) >= 30: return await callback.answer("❌ Xona to'la! (Maksimal 30 o'yinchi)", show_alert=True)
    if user_id in game["players"]: return await callback.answer("⚠️ Siz allaqachon ro'yxatdasiz!", show_alert=True)
    
    game["players"].append(user_id)
    game["player_names"][user_id] = username
    await callback.answer("✅ Siz muvaffaqiyatli qo'shildingiz!")
    await send_lobby_msg(callback.message, chat_id)

@dp.callback_query(F.data == "mafia_leave")
async def process_lobby_leave(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    if chat_id not in active_games: return
    game = active_games[chat_id]
    
    if user_id not in game["players"]: return await callback.answer("❌ Siz bu o'yinda yo'qsiz.", show_alert=True)
    
    game["players"].remove(user_id)
    game["player_names"].pop(user_id, None)
    await callback.answer("🚪 Siz o'yinni tark etdingiz.")
    await send_lobby_msg(callback.message, chat_id)

@dp.callback_query(F.data == "mafia_list")
async def process_lobby_list(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    if chat_id not in active_games: return
    game = active_games[chat_id]
    
    players_text = "\n".join([f"🔹 @{name}" for name in game["player_names"].values()])
    await callback.answer(f"📋 Ro'yxat:\n{players_text if players_text else 'Hali hech kim yoq'}", show_alert=True)

@dp.callback_query(F.data == "mafia_cancel")
async def process_lobby_cancel(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    if chat_id not in active_games: return
    game = active_games[chat_id]
    
    if callback.from_user.id != game["creator"]:
        return await callback.answer("❌ Faqat o'yinni yaratgan odam bekor qila oladi!", show_alert=True)
        
    if game["timer_task"]: game["timer_task"].cancel()
    active_games.pop(chat_id, None)
    await callback.message.edit_text("❌ O'yin yaratuvchi tomonidan bekor qilindi.", reply_markup=None)

# ==================== ADVANCED GAME ENGINE & CYCLES ====================

async def start_game_logic(chat_id: int, message: Message):
    game = active_games[chat_id]
    if len(game["players"]) < 4:
        active_games.pop(chat_id, None)
        return await message.edit_text("❌ O'yin bekor qilindi. Minimal 4 ta o'yinchi yig'ilmadi!", reply_markup=None)
        
    players = game["players"]
    random.shuffle(players)
    
    # Avtomatik rollar ketma-ketligi (Ishtirokchilar soniga qarab)
    role_keys = ["don", "mafia", "cop", "doc", "agent", "hacker", "assassin", "guitarist", "lover_boy", "chameleon"]
    available_roles = [r for r in role_keys if role_keys.index(r) < len(players)]
    while len(available_roles) < len(players):
        available_roles.append("citizen")
        
    random.shuffle(available_roles)
    game_roles = {}
    
    for idx, p_id in enumerate(players):
        r_key = available_roles[idx]
        game_roles[p_id] = r_key
        
        # Profil statistikalarini yangilash
    import os
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.webhook.aiohttp_impl import SimpleRequestHandler, setup_application

# --- BOT SOZLAMALARI ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
OWNER_USERNAME = "Admin_Uz"
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- GLOBAL MA'LUMOTLAR OMBORI (Xotirada saqlash uchun) ---
active_games = {}
players_db = {}  # Haqiqiy loyihada bu yerda ma'lumotlar bazasi (DB) bo'ladi

ROLES = {
    "mafia": {"name": "Mafiya 🕶️", "team": "mafia", "desc": "Tunda shahar aholisini yo'q qiling."},
    "doctor": {"name": "Doktor 🥼", "team": "citizens", "desc": "Tunda biror kishini o'limdan qutqaring."},
    "citizen": {"name": "Oddiy Fuqaro 🧑‍🌾", "team": "citizens", "desc": "Mafiyani toping va ovoz bering."}
}

# --- YORDAMCHI FUNKSIYALAR ---
def get_player(p_id: int, username: str) -> dict:
    """O'yinchi profilini bazadan olish yoki yangi yaratish"""
    if p_id not in players_db:
        players_db[p_id] = {
            "games": 0, "wins": 0, "coins": 0, "diamonds": 0,
            "rank": "Bronze 🥉", "achievements": []
        }
    return players_db[p_id]

# --- 1. KECHA BOSQICHI ---
async def start_night_phase(chat_id: int, message: Message, players: list, game_roles: dict):
    game = active_games[chat_id]
    
    for p_id in players:
        p_data = get_player(p_id, game["player_names"].get(p_id, "Player"))
        p_data["games"] += 1
        
        r_key = game_roles.get(p_id, "citizen")
        
        # Shaxsiy xabarda rol va tugmalarni yuborish
        try:
            text = (
                f"🌙 Kecha boshlandi\n\n"
                f"Sizning maxfiy rolingiz: {ROLES[r_key]['name']}\n"
                f"Guruh: {ROLES[r_key]['team'].upper()}\n"
                f"ℹ️ Vazifa: {ROLES[r_key]['desc']}\n\n"
                f"Tunda kimni tanlaysiz? Inline tugmalar orqali nishon belgilang! 🤫"
            )
            await bot.send_message(chat_id=p_id, text=text)
        except Exception:
            pass  # Agar foydalanuvchi botni bloklagan bo'lsa

    game["status"] = "night"
    game["roles"] = game_roles
    game["alive"] = list(players)
    game["votes"] = {}

    await message.edit_text(
        "🌙 Kecha bosqichi boshlandi\n\n"
        "Bot barcha maxsus rollarga shaxsiy xabarda (lichka) inline tugmalar yubordi. "
        "Barcha harakatlar uchun 60 soniya vaqt berildi! 🤐",
        reply_markup=None
    )

    await asyncio.sleep(60)
    if chat_id in active_games and active_games[chat_id]["status"] == "night":
        await trigger_day_phase(chat_id, message)

# --- 2. TONG BOSQICHI ---
async def trigger_day_phase(chat_id: int, message: Message):
    game = active_games[chat_id]
    game["status"] = "day"
    
    text = (
        f"☀️ Tong otdi\n\n"
        f"💀 Kecha hech kim o'ldirilmadi (yoki Doktor va Guitarist himoyasi mukammal ishladi)!\n\n"
        f"⏳ Muhokama uchun: 2 daqiqa\n"
        f"O'zaro suhbatlashing va ovoz berish uchun tayyorlaning!"
    )
    await message.answer(text)

    await asyncio.sleep(120)
    if chat_id in active_games and active_games[chat_id]["status"] == "day":
        await trigger_voting_phase(chat_id, message)

# --- 3. OVOZ BERISH BOSQICHI ---
async def trigger_voting_phase(chat_id: int, message: Message):
    game = active_games[chat_id]
    text = "🗳️ Ovoz berish boshlandi!\n\nKimni guruhdan chiqaramiz?\nTugmalar yordamida yashirin ovoz bering:"
    
    buttons = []
    for p_id in game["alive"]:
        name = game["player_names"].get(p_id, "Player")
        buttons.append([InlineKeyboardButton(text=f"🗳️ {name}", callback_data=f"vote_{p_id}")])
    
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("vote_"))
async def process_user_vote(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    if chat_id not in active_games or active_games[chat_id]["status"] != "day": 
        return
        
    target_id = int(callback.data.split("_")[1])
    voter_id = callback.from_user.id
    game = active_games[chat_id]
    
    if voter_id not in game["alive"]:
        return await callback.answer("❌ O'liklar yoki tomoshabinlar ovoz bera olmaydi!", show_alert=True)
        
    game["votes"][voter_id] = target_id
    await callback.answer("✅ Ovozingiz yashirincha qabul qilindi!")

    if len(game["votes"]) >= len(game["alive"]):
        await calculate_voting_results(chat_id, callback.message)

# --- 4. NATIJALARNI HISOBLASH ---
async def calculate_voting_results(chat_id: int, message: Message):
    game = active_games[chat_id]
    vote_counts = {}
    
    for target in game["votes"].values():
        vote_counts[target] = vote_counts.get(target, 0) + 1
        
    if not vote_counts: 
        return

    evicted_id = max(vote_counts, key=vote_counts.get)
    evicted_name = game["player_names"].get(evicted_id, "Player")
    role_key = game["roles"].get(evicted_id, "citizen")
    role_name = ROLES.get(role_key, ROLES["citizen"])["name"]

    stat_text = "📊 Ovozlar:\n\n"
    for p_id, count in vote_counts.items():
        stat_text += f"🔹 {game['player_names'].get(p_id, 'Player')} - {count}\n"
        
    stat_text += f"\n❌ {evicted_name} guruhdan chiqarildi.\nU {role_name} edi."
    await message.answer(stat_text)

    # O'yinni yakunlash va mukofotlash
    for p_id in game["alive"]:
        p_data = get_player(p_id, "")
        p_data["coins"] += 150
        p_data["wins"] += 1

    active_games.pop(chat_id, None)
    await message.answer("🏆 O'yin yakunlandi! Shahar g'alaba qozondi!\n\n💰 Har bir ishtirokchiga +150 Coin taqdim etildi!")

# --- 5. IQTISODIY VA PROFIL TIZIMI ---
@dp.message(F.text == "/profile")
async def cmd_profile_view(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "Player"
    p = get_player(user_id, username)
    
    text = (
        f"👤 {message.from_user.full_name} Profil Ma'lumotlari:\n\n"
        f"🎮 O'yinlar: {p['games']}\n"
        f"🏆 G'alabalar: {p['wins']}\n"
        f"🪙 Coin: {p['coins']}\n"
        f"💎 Diamond: {p['diamonds']}\n\n"
        f"⭐ Rank: {p['rank']}\n"
        f"🏅 Achievementlar: {', '.join(p['achievements']) if p['achievements'] else 'Yoq'}"
    )
    await message.reply(text)

@dp.message(F.text == "/top")
async def cmd_top_view(message: Message):
    text = (
        f"🏆 Global Ultimate Reyting (Top 3 O'yinchilar):\n\n"
        f"1️⃣ @{OWNER_USERNAME} — ⭐ Master (132 G'alaba) [👑 OWNER]\n"
        f"2️⃣ @Mafia_Boss — ⭐ Diamond (94 G'alaba)\n"
        f"3️⃣ @Shadow_Uz — ⭐ Platinum (65 G'alaba)\n"
    )
    await message.reply(text)

# --- 6. SERVER WEBHOOK VA RUN ---
async def on_startup(bot: Bot) -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    # Agar webhook ishlamasa polling rejimiga o'tadi:
    # asyncio.create_task(dp.start_polling(bot))

def main():
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    
    app.on_startup.append(lambda _: on_startup(bot))
    
    port = int(os.getenv("PORT", 10000))
    web.run_app(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
