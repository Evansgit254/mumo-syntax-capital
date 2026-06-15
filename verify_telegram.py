import os
import asyncio
from telegram import Bot
from dotenv import load_dotenv

async def verify():
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not token:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN not found in .env")
        return

    print(f"🤖 Initializing bot with token: {token[:10]}...{token[-5:]}")
    try:
        bot = Bot(token=token)
        me = await bot.get_me()
        print(f"✅ Bot connected! Name: @{me.username}")
    except Exception as e:
        print(f"❌ CONNECTION ERROR: {e}")
        return

    print("\n---------------------------------------------------------")
    print("👉 ACTION REQUIRED: Send a message to your bot on Telegram.")
    print("I am waiting for your message to catch your Chat ID...")
    print("---------------------------------------------------------")

    last_update_id = -1
    while True:
        try:
            updates = await bot.get_updates(offset=last_update_id + 1, timeout=10)
            for update in updates:
                if update.message:
                    print("\n🎉 GOT IT!")
                    print(f"👤 User: {update.message.from_user.first_name} (@{update.message.from_user.username})")
                    print(f"🆔 YOUR PERSONAL CHAT ID: {update.message.chat.id}")
                    print("\n---------------------------------------------------------")
                    print("1. Copy this number.")
                    print("2. Put it in your .env for TELEGRAM_CHAT_ID.")
                    print("3. Restart your services.")
                    print("---------------------------------------------------------")
                    return
                last_update_id = update.update_id
            await asyncio.sleep(1)
        except Exception as e:
            if "Conflict" in str(e):
                print("⚠️ CONFLICT: Your bot is already running on the VM.")
                print("Please run: 'sudo systemctl stop mumo-signal-service' first, then try again.")
                return
            print(f"⚠️ Polling... ({e})")
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(verify())
