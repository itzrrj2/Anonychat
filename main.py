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

# Pyrogram client
app = Client("anon-bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# MongoDB connection
mongo = MongoClient(MONGO_URI)
db = mongo["anonchat"]
users = db["users"]
waiting = db["waiting"]

# Helper Functions
def get_user(uid):
    return users.find_one({"_id": uid})

def update_user(uid, data):
    users.update_one({"_id": uid}, {"$set": data}, upsert=True)

def get_partner(uid):
    user = get_user(uid)
    return user.get("partner")

def disconnect(uid):
    user = get_user(uid)
    partner_id = user.get("partner")
    update_user(uid, {"partner": None})
    if partner_id:
        update_user(partner_id, {"partner": None})
    return partner_id

def find_match(mode, gender, uid):
    candidates = list(waiting.find({"mode": mode}))
    for c in candidates:
        if c["_id"] != uid and get_user(c["_id"]).get("gender") != gender:
            waiting.delete_one({"_id": c["_id"]})
            return c["_id"]

    waiting.update_one({"_id": uid}, {"$set": {"mode": mode}}, upsert=True)
    return None

# Start Handler
@app.on_message(filters.command("start"))
async def start(client, message):
    kb = [
        [InlineKeyboardButton("♂️ Male", callback_data="gender_male"),
         InlineKeyboardButton("♀️ Female", callback_data="gender_female")]
    ]
    await message.reply("Welcome to Anonymous Chat Bot!\nPlease select your gender:", reply_markup=InlineKeyboardMarkup(kb))

# Gender Selection
@app.on_callback_query(filters.regex("gender_"))
async def set_gender(client, cb):
    gender = cb.data.split("_")[1]
    update_user(cb.from_user.id, {"gender": gender, "partner": None})
    kb = [
        [InlineKeyboardButton("🔀 Chat with Stranger", callback_data="chat_random")],
        [InlineKeyboardButton("👨 Chat with Male", callback_data="chat_male")],
        [InlineKeyboardButton("👩 Chat with Female", callback_data="chat_female")]
    ]
    await cb.message.edit(f"Gender set to {gender.capitalize()}.\nNow, choose a chat mode:", reply_markup=InlineKeyboardMarkup(kb))

# Chat Matching
@app.on_callback_query(filters.regex("chat_"))
async def chat_request(client, cb):
    mode = cb.data.split("_")[1]
    uid = cb.from_user.id
    gender = get_user(uid).get("gender")
    match = find_match(mode, gender, uid)

    if match:
        update_user(uid, {"partner": match})
        update_user(match, {"partner": uid})

        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Next", callback_data="next"), InlineKeyboardButton("⛔ Stop", callback_data="stop")]])
        await client.send_message(uid, "✅ You're connected to a stranger!", reply_markup=kb)
        await client.send_message(match, "✅ You're connected to a stranger!", reply_markup=kb)
    else:
        await cb.message.edit("⏳ Searching for a partner... Please wait.")

# Relay Messages
@app.on_message(filters.private & filters.text & ~filters.command(["start", "next", "stop"]))
async def message_forward(client, message):
    uid = message.from_user.id
    partner = get_partner(uid)
    if partner:
        await client.send_message(partner, message.text)
    else:
        await message.reply("❗ You're not connected. Use /start to begin.")

# Stop Chat
@app.on_message(filters.command("stop"))
@app.on_callback_query(filters.regex("stop"))
async def stop_chat(client, event):
    uid = event.from_user.id if hasattr(event, "from_user") else event.message.from_user.id
    partner = disconnect(uid)
    if partner:
        await client.send_message(partner, "⚠️ Stranger has disconnected.")
    msg = "❌ Disconnected from chat. Use /start to begin again."
    if hasattr(event, "message"):
        await event.message.reply(msg)
    else:
        await event.answer(msg, show_alert=True)

# Next Chat
@app.on_message(filters.command("next"))
@app.on_callback_query(filters.regex("next"))
async def next_chat(client, event):
    uid = event.from_user.id if hasattr(event, "from_user") else event.message.from_user.id
    old_partner = disconnect(uid)
    if old_partner:
        await client.send_message(old_partner, "⚠️ Stranger left the chat.")

    gender = get_user(uid).get("gender")
    match = find_match("random", gender, uid)

    if match:
        update_user(uid, {"partner": match})
        update_user(match, {"partner": uid})
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Next", callback_data="next"), InlineKeyboardButton("⛔ Stop", callback_data="stop")]])
        await client.send_message(uid, "✅ Connected to a new stranger!", reply_markup=kb)
        await client.send_message(match, "✅ Connected to a new stranger!", reply_markup=kb)
    else:
        msg = "⏳ Searching for a new partner..."
        if hasattr(event, "message"):
            await event.message.reply(msg)
        else:
            await event.answer(msg, show_alert=False)

# Run Bot
app.run()
