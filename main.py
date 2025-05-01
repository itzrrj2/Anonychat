import os
import time
import random
from datetime import datetime
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
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Initialize client and database
app = Client("anon-bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo = MongoClient(MONGO_URI)
db = mongo["anonchat"]
users = db["users"]
waiting = db["waiting"]
reports = db["reports"]
referrals = db["referrals"]

# Utilities
def generate_nickname():
    adjectives = ["Blue", "Fast", "Silent", "Bright", "Dark", "Happy", "Lazy"]
    animals = ["Tiger", "Wolf", "Lion", "Fox", "Bear", "Eagle", "Otter"]
    return random.choice(adjectives) + random.choice(animals)

def get_avatar_url(nick, theme="set2"):
    return f"https://robohash.org/{nick}?size=200x200&set={theme}"

def get_user(uid):
    return users.find_one({"_id": uid}) or {}

def update_user(uid, data):
    users.update_one({"_id": uid}, {"$set": data}, upsert=True)

def get_partner(uid):
    return get_user(uid).get("partner")

def disconnect(uid):
    user = get_user(uid)
    partner_id = user.get("partner")
    update_user(uid, {"partner": None})
    if partner_id:
        update_user(partner_id, {"partner": None})
    return partner_id

def find_match(mode, user_gender, uid):
    waiting.delete_many({"_id": uid})
    candidates = list(waiting.find({"mode": mode}))
    for c in candidates:
        other_id = c["_id"]
        other_user = get_user(other_id)
        if not other_user or other_user.get("partner"): continue
        other_gender = other_user.get("gender")
        if (
            mode == "random" or
            (mode == "male" and other_gender == "male") or
            (mode == "female" and other_gender == "female")
        ):
            waiting.delete_one({"_id": other_id})
            return other_id
    waiting.update_one({"_id": uid}, {"$set": {"mode": mode}}, upsert=True)
    return None

# Start
@app.on_message(filters.command("start"))
async def start(client, message):
    uid = message.from_user.id
    if not get_user(uid).get("nickname"):
        nickname = generate_nickname()
        update_user(uid, {"nickname": nickname, "theme": "set2", "last_seen": time.time()})
    kb = [[
        InlineKeyboardButton("♂️ Male", callback_data="gender_male"),
        InlineKeyboardButton("♀️ Female", callback_data="gender_female")
    ]]
    await message.reply("Welcome to Anonymous Chat Bot!
Select your gender:", reply_markup=InlineKeyboardMarkup(kb))

@app.on_callback_query(filters.regex("gender_"))
async def gender_select(client, cb):
    gender = cb.data.split("_")[1]
    uid = cb.from_user.id
    update_user(uid, {"gender": gender, "partner": None})
    kb = [
        [InlineKeyboardButton("🔀 Chat with Stranger", callback_data="chat_random")],
        [InlineKeyboardButton("👨 Chat with Male", callback_data="chat_male")],
        [InlineKeyboardButton("👩 Chat with Female", callback_data="chat_female")]
    ]
    await cb.message.edit(f"Gender set as {gender.capitalize()}.
Now choose how to chat:", reply_markup=InlineKeyboardMarkup(kb))

@app.on_callback_query(filters.regex("chat_"))
async def chat_mode(client, cb):
    uid = cb.from_user.id
    gender = get_user(uid).get("gender")
    mode = cb.data.split("_")[1]
    match = find_match(mode, gender, uid)
    if match:
        now = time.time()
        update_user(uid, {"partner": match, "last_active": now, "chat_started": now})
        update_user(match, {"partner": uid, "last_active": now, "chat_started": now})
        nick1 = get_user(uid).get("nickname")
        nick2 = get_user(match).get("nickname")
        theme1 = get_user(uid).get("theme", "set2")
        theme2 = get_user(match).get("theme", "set2")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Next", callback_data="next"), InlineKeyboardButton("⛔ Stop", callback_data="stop")]])
        await client.send_photo(uid, get_avatar_url(nick2, theme2), caption=f"✅ Connected to: {nick2}", reply_markup=kb)
        await client.send_photo(match, get_avatar_url(nick1, theme1), caption=f"✅ Connected to: {nick1}", reply_markup=kb)
    else:
        await cb.message.edit("⏳ Searching for a partner...")

@app.on_message(filters.command("status"))
async def status(client, message):
    uid = message.from_user.id
    u = get_user(uid)
    txt = f"👤 Nickname: {u.get('nickname')}
"
    txt += f"⚙️ Gender: {u.get('gender')}
"
    if u.get("partner"):
        duration = int(time.time() - u.get("chat_started", time.time()))
        mins, secs = divmod(duration, 60)
        txt += f"🔗 Connected to: {get_user(u['partner']).get('nickname')} ({mins}m {secs}s)"
    else:
        in_queue = waiting.find_one({"_id": uid})
        txt += f"⌛ In queue: {in_queue['mode']}" if in_queue else "🪫 Not in chat or queue."
    await message.reply(txt)

@app.on_message(filters.private & filters.text & ~filters.command(["start", "stop", "next", "status"]))
async def relay(client, message):
    uid = message.from_user.id
    partner = get_partner(uid)
    if partner:
        update_user(uid, {"last_active": time.time()})
        await client.send_chat_action(partner, "typing")
        await client.send_message(partner, message.text)
    else:
        await message.reply("❗ You're not in a chat.")

@app.on_callback_query(filters.regex("stop"))
@app.on_message(filters.command("stop"))
async def stop_chat(client, event):
    uid = event.from_user.id if hasattr(event, "from_user") else event.message.from_user.id
    partner = disconnect(uid)
    if partner:
        await client.send_message(partner, "⚠️ Stranger has disconnected.")
        await client.send_message(partner, "How was your chat?
👍 /good 👎 /bad")
    msg = "❌ Disconnected. Use /start to chat again."
    if hasattr(event, "message"):
        await event.message.reply(msg)
    else:
        await event.answer(msg, show_alert=True)

@app.on_message(filters.command("good"))
@app.on_message(filters.command("bad"))
async def feedback(client, message):
    uid = message.from_user.id
    fb = message.command[0]
    users.update_one({"_id": uid}, {"$inc": {f"feedback.{fb}": 1}})
    await message.reply("✅ Feedback saved. Thank you!")

@app.on_message(filters.command("next"))
async def next_chat(client, message):
    uid = message.from_user.id
    await stop_chat(client, message)
    await chat_mode(client, type("obj", (object,), {"from_user": message.from_user, "data": "chat_random", "message": message})())

@app.on_message(filters.command("clearqueue") & filters.user(ADMIN_ID))
async def clear_queue(client, message):
    waiting.delete_many({})
    await message.reply("🧹 Queue cleared.")

@app.on_message(filters.command("online"))
async def online_count(client, message):
    cutoff = time.time() - 600  # last 10 min
    count = users.count_documents({"last_active": {"$gte": cutoff}})
    await message.reply(f"👥 {count} users online in the last 10 minutes.")

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_ID))
async def broadcast(client, message):
    msg = message.text.split(" ", 1)[-1]
    for u in users.find():
        try:
            await client.send_message(u["_id"], f"📢 {msg}")
        except:
            continue

app.run()
