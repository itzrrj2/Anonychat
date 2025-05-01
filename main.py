import os
from dotenv import load_dotenv
from pymongo import MongoClient
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Load environment variables
load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

# Initialize Pyrogram bot
app = Client("anonbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# MongoDB connection
mongo = MongoClient(MONGO_URI)
db = mongo["anonchat"]
users = db["users"]
waiting = db["waiting"]

# Utility Functions
def get_user(uid):
    return users.find_one({"_id": uid})

def update_user(uid, data):
    users.update_one({"_id": uid}, {"$set": data}, upsert=True)

def get_partner(uid):
    user = get_user(uid)
    return user.get("partner")

def disconnect(uid):
    user = get_user(uid)
    pid = user.get("partner")
    update_user(uid, {"partner": None})
    if pid:
        update_user(pid, {"partner": None})
    return pid

def find_match(mode, gender, uid):
    candidates = list(waiting.find({"mode": mode}))
    for c in candidates:
        if c["_id"] != uid and get_user(c["_id"]).get("gender") != gender:
            waiting.delete_one({"_id": c["_id"]})
            return c["_id"]
    waiting.insert_one({"_id": uid, "mode": mode})
    return None

# Start
@app.on_message(filters.command("start"))
async def start(client, message):
    keyboard = [
        [InlineKeyboardButton("♂️ Male", callback_data="gender_male"),
         InlineKeyboardButton("♀️ Female", callback_data="gender_female")]
    ]
    await message.reply("Welcome to Anonymous Chat!\nChoose your gender:", reply_markup=InlineKeyboardMarkup(keyboard))

# Gender Selection
@app.on_callback_query(filters.regex("gender_"))
async def set_gender(client, cb):
    gender = cb.data.split("_")[1]
    update_user(cb.from_user.id, {"gender": gender, "partner": None})
    keyboard = [
        [InlineKeyboardButton("🔀 Chat with Stranger", callback_data="chat_random")],
        [InlineKeyboardButton("👨 Chat with Male", callback_data="chat_male")],
        [InlineKeyboardButton("👩 Chat with Female", callback_data="chat_female")]
    ]
    await cb.message.edit_text(f"Gender set to {gender.capitalize()}.\nChoose your chat option:", reply_markup=InlineKeyboardMarkup(keyboard))

# Chat Mode Selection
@app.on_callback_query(filters.regex("chat_"))
async def chat_request(client, cb):
    mode = cb.data.split("_")[1]
    uid = cb.from_user.id
    gender = get_user(uid).get("gender")
    match = find_match(mode, gender, uid)

    if match:
        update_user(uid, {"partner": match})
        update_user(match, {"partner": uid})

        buttons = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Next", callback_data="next"), InlineKeyboardButton("⛔ Stop", callback_data="stop")]])
        await client.send_message(uid, "✅ You are now connected to a stranger!", reply_markup=buttons)
        await client.send_message(match, "✅ You are now connected to a stranger!", reply_markup=buttons)
    else:
        await cb.message.edit_text("⏳ Waiting for a match...")

# Messaging
@app.on_message(filters.private & filters.text & ~filters.command(["start", "next", "stop"]))
async def message_forward(client, message):
    uid = message.from_user.id
    partner = get_partner(uid)
    if partner:
        await client.send_message(partner, message.text)
    else:
        await message.reply("❗ You're not connected to anyone.\nUse /start to begin.")

# /stop or Stop button
@app.on_message(filters.command("stop"))
@app.on_callback_query(filters.regex("stop"))
async def stop_chat(client, event):
    uid = event.from_user.id if hasattr(event, "from_user") else event.message.from_user.id
    partner = disconnect(uid)
    if partner:
        await client.send_message(partner, "⚠️ Stranger disconnected the chat.")
    if hasattr(event, "message"):
        await event.message.reply("❌ You have left the chat. Use /start to find another.")
    else:
        await event.answer("❌ Disconnected.", show_alert=True)

# /next or Next button
@app.on_message(filters.command("next"))
@app.on_callback_query(filters.regex("next"))
async def next_chat(client, event):
    uid = event.from_user.id if hasattr(event, "from_user") else event.message.from_user.id
    partner = disconnect(uid)
    if partner:
        await client.send_message(partner, "⚠️ Stranger left the chat.")
    gender = get_user(uid).get("gender")
    mode = "random"
    match = find_match(mode, gender, uid)
    if match:
        update_user(uid, {"partner": match})
        update_user(match, {"partner": uid})

        buttons = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Next", callback_data="next"), InlineKeyboardButton("⛔ Stop", callback_data="stop")]])
        await client.send_message(uid, "✅ Connected to a new stranger.", reply_markup=buttons)
        await client.send_message(match, "✅ Connected to a new stranger.", reply_markup=buttons)
    else:
        if hasattr(event, "message"):
            await event.message.reply("⏳ Searching for a new partner...")
        else:
            await event.answer("⏳ Searching...", show_alert=False)

# Run the bot
app.run()
