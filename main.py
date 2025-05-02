import os
import asyncio
import random
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient

# Load environment variables
load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
FORCE_JOIN_CHANNEL = os.getenv("FORCE_JOIN_CHANNEL")

# Init
bot = Client("simpdatingbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo = MongoClient(MONGO_URI)
db = mongo["anonchat"]
users = db["users"]
queue = db["queue"]

# Utils
def get_gender(uid):
    u = users.find_one({"user_id": uid})
    return u.get("gender") if u else None

def get_partner(uid):
    u = users.find_one({"user_id": uid})
    return u.get("partner") if u else None

def in_chat(uid):
    return get_partner(uid) is not None

def leave_chat(uid):
    users.update_one({"user_id": uid}, {"$unset": {"partner": ""}})
    users.update_one({"partner": uid}, {"$unset": {"partner": ""}})

# /start
@bot.on_message(filters.command("start"))
async def start(client, message: Message):
    user_id = message.from_user.id
    if not users.find_one({"user_id": user_id}):
        users.insert_one({"user_id": user_id})
    await message.reply(
        "Welcome to SIMP DATING ANONYMOUS CHAT!\n\n"
        "Choose your gender to begin.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("♂ Male", callback_data="gender_male"),
             InlineKeyboardButton("♀ Female", callback_data="gender_female")]
        ])
    )

# Set Gender
@bot.on_callback_query(filters.regex("gender_"))
async def set_gender(client, cb: CallbackQuery):
    gender = cb.data.split("_")[1]
    users.update_one({"user_id": cb.from_user.id}, {"$set": {"gender": gender}})
    await client.send_message(cb.from_user.id,
        "Gender set! Now choose how to chat.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Random Stranger", callback_data="match_random")],
            [InlineKeyboardButton("Chat with Male", callback_data="match_male"),
             InlineKeyboardButton("Chat with Female", callback_data="match_female")]
        ])
    )

# Match Request
@bot.on_callback_query(filters.regex("match_"))
async def match_user(client, cb: CallbackQuery):
    user_id = cb.from_user.id
    if in_chat(user_id):
        await cb.answer("You're already in a chat!", show_alert=True)
        return
    pref = cb.data.split("_")[1]
    existing = queue.find_one({"pref": pref, "user_id": {"$ne": user_id}})
    if existing:
        partner_id = existing["user_id"]
        queue.delete_one({"user_id": partner_id})
        users.update_one({"user_id": user_id}, {"$set": {"partner": partner_id}})
        users.update_one({"user_id": partner_id}, {"$set": {"partner": user_id}})
        await client.send_message(user_id, "You're now chatting anonymously.")
        await client.send_message(partner_id, "You're now chatting anonymously.")
    else:
        queue.insert_one({"user_id": user_id, "pref": pref})
        await client.send_message(user_id, "Looking for a match...")

# Leave Chat
@bot.on_message(filters.command("leave"))
async def leave(client, message: Message):
    uid = message.from_user.id
    if in_chat(uid):
        pid = get_partner(uid)
        leave_chat(uid)
        await client.send_message(pid, "Your partner has left the chat.")
        await message.reply("You left the chat.")
    else:
        queue.delete_many({"user_id": uid})
        await message.reply("You are not in a chat.")

# Chat Relay
@bot.on_message(filters.private & ~filters.command(["start", "leave", "clearqueue", "broadcast"]))
async def relay(client, message: Message):
    uid = message.from_user.id
    if not in_chat(uid): return
    pid = get_partner(uid)
    try:
        await client.send_chat_action(pid, "typing")
        await message.copy(pid)
    except Exception:
        await message.reply("Failed to send message.")

# Admin: Clear Queue
@bot.on_message(filters.command("clearqueue") & filters.user(ADMIN_ID))
async def clear_queue(client, message: Message):
    queue.delete_many({})
    await message.reply("Matching queue cleared.")

# Admin: Broadcast
@bot.on_message(filters.command("broadcast") & filters.user(ADMIN_ID))
async def broadcast(client, message: Message):
    if len(message.text.split(None, 1)) < 2:
        await message.reply("Usage: /broadcast your_message")
        return
    text = message.text.split(None, 1)[1]
    count = 0
    for user in users.find():
        try:
            await client.send_message(user["user_id"], text)
            count += 1
        except:
            continue
    await message.reply(f"Message sent to {count} users.")

bot.run()
