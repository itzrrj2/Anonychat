import os
import time
import random
from dotenv import load_dotenv
from pymongo import MongoClient
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from pyrogram.enums import ChatAction, ChatMemberStatus

# Load environment variables
load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Initialize bot and DB
app = Client("anon-bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo = MongoClient(MONGO_URI)
db = mongo["anonchat"]
users = db["users"]
waiting = db["waiting"]
config = db["config"]

# Channel cache
CHANNEL_CACHE = {"premium": [], "basic": []}

def get_channels(premium=False):
    key = "premium" if premium else "basic"
    if not CHANNEL_CACHE[key]:
        data = config.find_one({"_id": key}) or {}
        CHANNEL_CACHE[key] = data.get("channels", [])
    return CHANNEL_CACHE[key]

def set_channels(channel_list, premium=False):
    key = "premium" if premium else "basic"
    config.update_one({"_id": key}, {"$set": {"channels": channel_list}}, upsert=True)
    CHANNEL_CACHE[key] = channel_list

def generate_nickname():
    adjectives = ["Blue", "Fast", "Silent", "Bright", "Dark", "Happy", "Lazy"]
    animals = ["Tiger", "Wolf", "Lion", "Fox", "Bear", "Eagle", "Otter"]
    return random.choice(adjectives) + random.choice(animals)

def get_user(uid, _cache={}):
    if uid in _cache:
        return _cache[uid]
    user = users.find_one({"_id": uid}) or {}
    _cache[uid] = user
    return user

def update_user(uid, data):
    users.update_one({"_id": uid}, {"$set": data}, upsert=True)

def get_partner(uid):
    return get_user(uid).get("partner")

def disconnect(uid):
    partner = get_partner(uid)
    update_user(uid, {"partner": None})
    if partner:
        update_user(partner, {"partner": None})
    return partner

async def check_force_join(bot, user):
    db_user = get_user(user.id)
    premium = db_user.get("is_premium", False)
    channels = get_channels(premium)
    not_joined = []
    for ch in channels:
        try:
            clean_ch = ch.lstrip('@')
            member = await bot.get_chat_member(clean_ch, user.id)
            if member.status not in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
                not_joined.append(ch)
        except Exception as e:
            print(f"Membership check error for {ch}: {str(e)}")
            not_joined.append(ch)
    return not_joined

@app.on_message(filters.command("start"))
async def start(client, msg):
    uid = msg.from_user.id
    user = await client.get_users(uid)
    update_user(uid, {"is_premium": getattr(user, "is_premium", False)})

    not_joined = await check_force_join(client, user)
    if not_joined:
        btns = [[InlineKeyboardButton(f"Channel #{i+1}", url=f"https://t.me/{ch.lstrip('@')}")] for i, ch in enumerate(not_joined)]
        btns.append([InlineKeyboardButton("✅ I Joined", callback_data="check_join")])
        await msg.reply("Please join all channels to continue:", reply_markup=InlineKeyboardMarkup(btns))
        return

    if not get_user(uid).get("nickname"):
        update_user(uid, {
            "nickname": generate_nickname(),
            "theme": "set2",
            "last_seen": time.time()
        })

    kb = [[
        InlineKeyboardButton("♂️ Male", callback_data="gender_male"),
        InlineKeyboardButton("♀️ Female", callback_data="gender_female")
    ]]
    await msg.reply("👋 Welcome to Anonymous Chat Bot!\nPlease select your gender:", reply_markup=InlineKeyboardMarkup(kb))

@app.on_callback_query(filters.regex("check_join"))
async def recheck_join(client, cb):
    user = await client.get_users(cb.from_user.id)
    not_joined = await check_force_join(client, user)

    if not_joined:
        btns = [[InlineKeyboardButton(f"Channel #{i+1}", url=f"https://t.me/{ch.lstrip('@')}")] for i, ch in enumerate(not_joined)]
        btns.append([InlineKeyboardButton("✅ I Joined", callback_data="check_join")])
        await cb.message.reply("Please join all channels to continue:", reply_markup=InlineKeyboardMarkup(btns))
        try: await cb.message.delete()
        except: pass
    else:
        await cb.message.reply("✅ You're verified and ready to start!")
        try: await cb.message.delete()
        except: pass
        await start(client, cb.message)

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
    await cb.message.reply(f"Gender set as {gender.capitalize()}.\nNow choose how to chat:", reply_markup=InlineKeyboardMarkup(kb))
    try: await cb.message.delete()
    except: pass

def find_match(mode, user_gender, uid):
    waiting.delete_many({"_id": uid})
    query = {"mode": mode}
    if mode == "male":
        query["gender"] = "male"
    elif mode == "female":
        query["gender"] = "female"
    candidate = waiting.find_one(query)
    if candidate:
        waiting.delete_one({"_id": candidate["_id"]})
        return candidate["_id"]
    waiting.update_one({"_id": uid}, {"$set": {"mode": mode, "gender": user_gender}}, upsert=True)
    return None

@app.on_callback_query(filters.regex("chat_"))
async def chat_mode(client, cb):
    uid = cb.from_user.id
    user_data = get_user(uid)
    gender = user_data.get("gender")
    mode = cb.data.split("_")[1]
    match = find_match(mode, gender, uid)
    if match:
        now = time.time()
        partner_data = get_user(match)
        update_user(uid, {"partner": match, "last_active": now, "chat_started": now})
        update_user(match, {"partner": uid, "last_active": now, "chat_started": now})
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ Next", callback_data="next"), InlineKeyboardButton("⛔ Stop", callback_data="stop")]
        ])
        await client.send_message(uid, f"✅ Connected to: {partner_data.get('nickname')}", reply_markup=kb)
        await client.send_message(match, f"✅ Connected to: {user_data.get('nickname')}", reply_markup=kb)
    else:
        await cb.message.reply("⏳ Searching for a partner...")
        try: await cb.message.delete()
        except: pass

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
        await client.send_message(partner, "⚠️ Stranger has disconnected.\nHow was your chat?\n👍 /good 👎 /bad")
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

@app.on_message(filters.command(["good", "bad"]))
async def feedback(client, msg):
    uid = msg.from_user.id
    kind = msg.command[0]
    users.update_one({"_id": uid}, {"$inc": {f"feedback.{kind}": 1}})
    await msg.reply("✅ Feedback saved. Thank you!")

@app.on_message(filters.command("setchannels") & filters.user(ADMIN_ID))
async def set_channels_cmd(client, msg):
    parts = msg.text.split()
    if len(parts) < 3:
        await msg.reply("Usage:\n/setchannels premium @ch1 @ch2\n/setchannels basic @chX")
        return
    mode = parts[1].lower()
    channels = parts[2:]
    if mode not in ["premium", "basic"]:
        await msg.reply("❌ Mode must be 'premium' or 'basic'")
        return
    set_channels(channels, premium=(mode == "premium"))
    await msg.reply(f"✅ {mode.capitalize()} channels updated:\n" + "\n".join(channels))

@app.on_message(filters.command("getchannels") & filters.user(ADMIN_ID))
async def get_channels_cmd(client, msg):
    premium = get_channels(True)
    basic = get_channels(False)
    await msg.reply(
        f"**Premium Users Channels:**\n" + "\n".join(premium or ["None"]) +
        f"\n\n**Non-Premium Users Channels:**\n" + "\n".join(basic or ["None"])
    )

@app.on_message(filters.command("debugcheck") & filters.user(ADMIN_ID))
async def debug_check(client, msg):
    log = []
    for mode in ["premium", "basic"]:
        channels = get_channels(premium=(mode == "premium"))
        log.append(f"\n🔍 Checking {mode.capitalize()} Channels:")
        for ch in channels:
            try:
                clean_ch = ch.lstrip('@')
                member = await client.get_chat_member(clean_ch, msg.from_user.id)
                log.append(f"✅ Bot has access to {ch} - Status: {member.status}")
            except Exception as e:
                log.append(f"❌ Cannot access {ch} — {e.__class__.__name__}: {str(e)}")
    await msg.reply("\n".join(log))

@app.on_message(
    filters.private &
    ~filters.command(["start", "stop", "next", "status", "good", "bad", "setchannels", "getchannels", "debugcheck"])
)
async def relay(client, msg):
    uid = msg.from_user.id
    user = get_user(uid)
    partner = user.get("partner")
    if not partner:
        await msg.reply("❗ You're not in a chat.")
        return
    update_user(uid, {"last_active": time.time()})
    try:
        await client.send_chat_action(partner, ChatAction.TYPING)
        await client.copy_message(partner, uid, msg.id)
    except Exception as e:
        await msg.reply(f"⚠️ Failed to forward: {str(e)}")

app.run()
