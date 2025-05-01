import os
import time
import random
from dotenv import load_dotenv
from pymongo import MongoClient
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from pyrogram.enums import ChatAction

load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

app = Client("anon-bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo = MongoClient(MONGO_URI)
db = mongo["anonchat"]
users = db["users"]
waiting = db["waiting"]

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
    partner = get_user(uid).get("partner")
    print(f"[DEBUG] get_partner({uid}) -> {partner}")
    return partner

def disconnect(uid):
    partner = get_partner(uid)
    update_user(uid, {"partner": None})
    if partner:
        update_user(partner, {"partner": None})
    return partner

def find_match(mode, gender, uid):
    waiting.delete_many({"_id": uid})
    candidates = list(waiting.find({"mode": mode}))
    for c in candidates:
        other = get_user(c["_id"])
        if other and other.get("partner") is None and other.get("gender") != gender:
            waiting.delete_one({"_id": c["_id"]})
            return c["_id"]
    waiting.update_one({"_id": uid}, {"$set": {"mode": mode}}, upsert=True)
    return None

@app.on_message(filters.command("start"))
async def start(client, msg):
    uid = msg.from_user.id
    if not get_user(uid).get("nickname"):
        update_user(uid, {"nickname": generate_nickname(), "theme": "set2", "last_seen": time.time()})
    kb = [[
        InlineKeyboardButton("♂️ Male", callback_data="gender_male"),
        InlineKeyboardButton("♀️ Female", callback_data="gender_female")
    ]]
    await msg.reply("Select your gender:", reply_markup=InlineKeyboardMarkup(kb))

@app.on_callback_query(filters.regex("gender_"))
async def set_gender(client, cb):
    gender = cb.data.split("_")[1]
    update_user(cb.from_user.id, {"gender": gender, "partner": None})
    kb = [
        [InlineKeyboardButton("🔀 Chat with Stranger", callback_data="chat_random")],
        [InlineKeyboardButton("👨 Chat with Male", callback_data="chat_male")],
        [InlineKeyboardButton("👩 Chat with Female", callback_data="chat_female")]
    ]
    await cb.message.edit("Now choose how to chat:", reply_markup=InlineKeyboardMarkup(kb))

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

@app.on_callback_query(filters.regex("next"))
async def next_callback(client, cb):
    await stop_chat(client, cb)
    cb.data = "chat_random"
    await chat_mode(client, cb)

@app.on_message(filters.command("next"))
async def next_cmd(client, msg):
    class DummyCB:
        def __init__(self, user, message):
            self.from_user = user
            self.data = "chat_random"
            self.message = message
    await stop_chat(client, msg)
    await chat_mode(client, DummyCB(msg.from_user, msg))

@app.on_callback_query(filters.regex("stop"))
@app.on_message(filters.command("stop"))
async def stop_chat(client, event):
    uid = event.from_user.id if hasattr(event, "from_user") else event.message.from_user.id
    partner = disconnect(uid)
    if partner:
        await client.send_message(partner, "⚠️ Stranger has disconnected.")
        await client.send_message(partner, "How was your chat?\n👍 /good 👎 /bad")
    msg = "❌ Disconnected. Use /start to chat again."
    if isinstance(event, CallbackQuery):
        await event.answer(msg, show_alert=True)
    elif isinstance(event, Message):
        await event.reply(msg)

@app.on_message(filters.command("status"))
async def status(client, msg):
    uid = msg.from_user.id
    u = get_user(uid)
    text = f"👤 Nickname: {u.get('nickname')}\n⚙️ Gender: {u.get('gender')}\n"
    if u.get("partner"):
        dur = int(time.time() - u.get("chat_started", time.time()))
        m, s = divmod(dur, 60)
        text += f"🔗 Connected to: {get_user(u['partner']).get('nickname')} ({m}m {s}s)"
    else:
        q = waiting.find_one({"_id": uid})
        text += f"⌛ In queue: {q['mode']}" if q else "🪫 Not in chat or queue."
    await msg.reply(text)

@app.on_message(filters.command("good"))
@app.on_message(filters.command("bad"))
async def feedback(client, msg):
    uid = msg.from_user.id
    kind = msg.command[0]
    users.update_one({"_id": uid}, {"$inc": {f"feedback.{kind}": 1}})
    await msg.reply("✅ Feedback saved. Thank you!")

@app.on_message(filters.command("clearqueue") & filters.user(ADMIN_ID))
async def clear_queue(client, msg):
    waiting.delete_many({})
    await msg.reply("🧹 Queue cleared.")

@app.on_message(filters.command("online"))
async def online(client, msg):
    cutoff = time.time() - 600
    count = users.count_documents({"last_active": {"$gte": cutoff}})
    await msg.reply(f"👥 {count} users online in last 10 min.")

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_ID))
async def broadcast(client, msg):
    text = msg.text.split(" ", 1)[-1]
    for u in users.find():
        try:
            await client.send_message(u["_id"], f"📢 {text}")
        except:
            continue

@app.on_message(filters.private & filters.text & ~filters.command(["start", "stop", "next", "status", "good", "bad", "clearqueue", "online", "broadcast"]))
async def relay(client, msg):
    uid = msg.from_user.id
    partner = get_partner(uid)
    if partner:
        update_user(uid, {"last_active": time.time()})
        await client.send_chat_action(partner, ChatAction.TYPING)
        await client.send_message(partner, msg.text)
    else:
        await msg.reply("❗ You're not in a chat.")

app.run()
