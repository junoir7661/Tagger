"""
Multi-Account /tagall System + Separate Control Bot
------------------------------------------------------
2 cheezein is file me hain:

1. Userbot accounts (string session se) - ye /tagall handle karte hain,
   aapki personal ID se message jaata hai.

2. Ek CONTROL BOT (BotFather token se) - isko aap seedha Telegram me
   dhoond kar DM karoge, normal bot ki tarah. Ye sirf AAPKI OWNER_ID
   se commands sunta hai:
       /listaccounts
       /stopaccount <number>
       /startaccount <number>
   Control bot khud kisi account ka OTP/session nahi jaanta - bas
   already-connected userbot accounts ko start/stop karta hai.

PEHLE: har account ke liye generate_session.py chala kar
STRING SESSION nikaal lo (alag-alag, apne hi terminal me, ek baar).

ENV VARIABLES:
    OWNER_ID             <- aapki apni Telegram numeric ID (@userinfobot se milegi)
    CONTROL_BOT_TOKEN    <- BotFather se "/newbot" karke mila token
    CONTROL_BOT_API_ID   <- my.telegram.org wala API ID (koi bhi account ka use kar sakte ho)
    CONTROL_BOT_API_HASH <- my.telegram.org wala API Hash (isी ke saath wala)

    ACCOUNT_1_API_ID
    ACCOUNT_1_API_HASH
    ACCOUNT_1_STRING_SESSION

    ACCOUNT_2_API_ID
    ACCOUNT_2_API_HASH
    ACCOUNT_2_STRING_SESSION

    ... ACCOUNT_3_*, ACCOUNT_4_*, ACCOUNT_5_* bhi isी tarah

Chalane ka tarika:
    pip install telethon --break-system-packages
    python multi_account_tagall.py

Control bot ko Telegram me uske @username se DM karo (jo BotFather
ne diya hoga) aur commands bhejo - sirf aapki OWNER_ID se chalenge.
"""

import os
import asyncio
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

MAX_ACCOUNTS = 5  # zarurat ho to badha sakte ho

OWNER_ID = os.environ.get("OWNER_ID")
if OWNER_ID:
    OWNER_ID = int(OWNER_ID)

CONTROL_BOT_TOKEN = os.environ.get("CONTROL_BOT_TOKEN")
CONTROL_BOT_API_ID = os.environ.get("CONTROL_BOT_API_ID")
CONTROL_BOT_API_HASH = os.environ.get("CONTROL_BOT_API_HASH")

# number -> {"config": {...}, "client": TelegramClient or None}
accounts_state = {}


def load_account_configs():
    """Env variables se jitne accounts mile utni config list bana deta hai."""
    configs = []
    for i in range(1, MAX_ACCOUNTS + 1):
        api_id = os.environ.get(f"ACCOUNT_{i}_API_ID")
        api_hash = os.environ.get(f"ACCOUNT_{i}_API_HASH")
        session_str = os.environ.get(f"ACCOUNT_{i}_STRING_SESSION")

        if api_id and api_hash and session_str:
            configs.append({
                "number": i,
                "label": f"Account {i}",
                "api_id": int(api_id),
                "api_hash": api_hash,
                "session": session_str,
            })
    return configs


def attach_tagall_handler(client, label):
    """Is account ke client par /tagall command attach karta hai."""

    @client.on(events.NewMessage(pattern=r"^/tagall(?:\s+(.*))?$"))
    async def tagall_handler(event):
        if not event.is_group:
            return

        match = event.pattern_match.group(1)
        extra_text = match.strip() if match else "Good Morning!"

        chat = await event.get_chat()

        try:
            participants = await client.get_participants(chat, aggressive=True)
        except Exception as e:
            await event.reply(f"[{label}] Members nikalne me error: {e}")
            return

        if not participants:
            await event.reply(f"[{label}] Koi members nahi mile.")
            return

        batch_size = 5
        mention_batches = []
        current_batch = []

        for user in participants:
            if user.bot:
                continue
            name = user.first_name or "User"
            mention = f"[{name}](tg://user?id={user.id})"
            current_batch.append(mention)
            if len(current_batch) == batch_size:
                mention_batches.append(current_batch)
                current_batch = []

        if current_batch:
            mention_batches.append(current_batch)

        for batch in mention_batches:
            text = f"{extra_text}\n" + " ".join(batch)
            try:
                await client.send_message(chat.id, text, parse_mode="md")
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds)
                await client.send_message(chat.id, text, parse_mode="md")
            await asyncio.sleep(1.5)


async def start_account(num):
    """Ek userbot account ko connect karke /tagall handler attach karta hai."""
    state = accounts_state[num]
    config = state["config"]

    if state["client"] and state["client"].is_connected():
        return "already_running"

    client = TelegramClient(
        StringSession(config["session"]),
        config["api_id"],
        config["api_hash"],
    )
    attach_tagall_handler(client, config["label"])

    await client.start()
    me = await client.get_me()
    state["client"] = client
    print(f"[{config['label']}] Connected: {me.first_name} ({me.id})")
    return "started"


async def stop_account(num):
    """Ek userbot account ko disconnect kar deta hai."""
    state = accounts_state[num]
    if state["client"] and state["client"].is_connected():
        await state["client"].disconnect()
        print(f"[{state['config']['label']}] Disconnected.")
        return "stopped"
    return "already_stopped"


def build_control_bot():
    """Control bot banata hai jo sirf OWNER_ID se commands sunega."""
    bot = TelegramClient(
        "control_bot_session",
        api_id=int(CONTROL_BOT_API_ID),
        api_hash=CONTROL_BOT_API_HASH,
    )

    @bot.on(events.NewMessage(pattern=r"^/listaccounts$"))
    async def list_cmd(event):
        if event.sender_id != OWNER_ID:
            return
        if not accounts_state:
            await event.reply("Koi account configured nahi hai.")
            return
        lines = []
        for num, state in sorted(accounts_state.items()):
            running = state["client"] and state["client"].is_connected()
            status = "connected" if running else "stopped"
            lines.append(f"Account {num}: {status}")
        await event.reply("\n".join(lines))

    @bot.on(events.NewMessage(pattern=r"^/stopaccount\s+(\d+)$"))
    async def stop_cmd(event):
        if event.sender_id != OWNER_ID:
            return
        num = int(event.pattern_match.group(1))
        if num not in accounts_state:
            await event.reply(f"Account {num} configured nahi hai.")
            return
        result = await stop_account(num)
        if result == "stopped":
            await event.reply(f"Account {num} disconnect kar diya.")
        else:
            await event.reply(f"Account {num} pehle se hi stopped hai.")

    @bot.on(events.NewMessage(pattern=r"^/startaccount\s+(\d+)$"))
    async def start_cmd(event):
        if event.sender_id != OWNER_ID:
            return
        num = int(event.pattern_match.group(1))
        if num not in accounts_state:
            await event.reply(f"Account {num} configured nahi hai.")
            return
        result = await start_account(num)
        if result == "started":
            await event.reply(f"Account {num} wapas connect ho gaya.")
        else:
            await event.reply(f"Account {num} pehle se hi connected hai.")

    return bot


async def main():
    if OWNER_ID is None:
        print("OWNER_ID env variable set nahi hai! @userinfobot se apni ID pata karo.")
        return

    if not CONTROL_BOT_TOKEN or not CONTROL_BOT_API_ID or not CONTROL_BOT_API_HASH:
        print("CONTROL_BOT_TOKEN / CONTROL_BOT_API_ID / CONTROL_BOT_API_HASH set nahi hain!")
        print("BotFather ko /newbot bhej kar token lo, aur my.telegram.org wala API ID/Hash daalo.")
        return

    configs = load_account_configs()
    if not configs:
        print("Koi userbot account env variables me nahi mila.")
        print("Pehle generate_session.py se STRING_SESSION bana kar env me daalo.")
        return

    for config in configs:
        accounts_state[config["number"]] = {"config": config, "client": None}

    print(f"{len(configs)} userbot account(s) mile. Sabko connect kar raha hoon...\n")
    for num in accounts_state:
        await start_account(num)

    print("\nControl bot start kar raha hoon...")
    control_bot = build_control_bot()
    await control_bot.start(bot_token=CONTROL_BOT_TOKEN)
    print("Control bot chalu hai. Usko Telegram me DM karke commands bhejo:")
    print("  /listaccounts")
    print("  /stopaccount <number>")
    print("  /startaccount <number>")
    print("(Sirf OWNER_ID wali ID se ye commands kaam karengi.)\n")

    await control_bot.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
