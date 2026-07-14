"""
Interactive Telethon authentication for signals-bridge.

Usage:
    docker compose run --rm signals-bridge python auth.py
"""
from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from telegram_adapter import telethon_session_lock

load_dotenv("/app/signals.env", override=False)
load_dotenv()

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
PHONE = os.environ["TELEGRAM_PHONE"]
SESSION_PATH = os.environ.get("SIGNALS_TELETHON_SESSION_PATH", "/app/sessions/signals_bridge")


async def main() -> None:
    with telethon_session_lock():
        client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                await client.send_code_request(PHONE)
                code = input("Enter the code you received: ").strip()
                try:
                    await client.sign_in(PHONE, code)
                except SessionPasswordNeededError:
                    password = input("Two-factor auth enabled. Enter your password: ").strip()
                    await client.sign_in(password=password)
            me = await client.get_me()
            print(f"Authorized as: {me.first_name} (@{me.username})")
        finally:
            await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
