import sys
import os
import asyncio
import binascii
import struct
import base64
from pathlib import Path

# Add backend to sys.path
backend_path = r"C:\Users\ЗС\OneDrive\Рабочий стол\Телеграмм парсер\src\backend"
sys.path.append(backend_path)

# Mock tgcrypto before any imports
import sys
import app.services._compat.tgcrypto_stub as stub
sys.modules["tgcrypto"] = stub

from pyrogram import Client
from telethon.sessions import StringSession

def hex_to_session_string(auth_key_hex, dc_id):
    """
    Telethon StringSession format:
    1 byte for DC ID
    IP address and port (optional, empty here)
    256 bytes for auth key
    """
    auth_key = binascii.unhexlify(auth_key_hex)
    if len(auth_key) != 256:
        raise ValueError(f"Auth key must be 256 bytes, got {len(auth_key)}")
    
    # Telethon format: DC_ID (1 byte) + IP (4 bytes, 0) + Port (2 bytes, 0) + AuthKey (256 bytes)
    data = struct.pack('>B4sH', dc_id, b'\0\0\0\0', 0) + auth_key
    return base64.urlsafe_b64encode(data).decode('ascii')

async def verify_and_add():
    phone = "13235248634"
    auth_key_hex = "6bcda4d72e2a4c1862e300e8222ce93132e0e560d5b7965427d11f6ebf965cf4beec131e5f8bc878f7e2c9183424040974c8334469f6e1f062d96c9c81156641b9d4791f421f1519782845c20202979669666c0780447385c7f8272844c8030045e0d473210d48f615f212d46e92156a6c9c811d619a8d46e200e566d5b096c944d4791542f6d566d5b0121d61448b1d4204d5b0964175c044c9b99092497645021f15d909d944d2d46e966e6c078b17b204621b124876d7d4c06c9a8d6e921d7207c041751d720045d61244d4d4791f4217154942d4b9176c9c8141b9d585053550f8e8"
    dc_id = 1
    
    proxy_info = {
        "scheme": "socks5",
        "hostname": "196.16.110.162",
        "port": 8000,
        "username": "vm9XXY",
        "password": "kwrCYR"
    }
    
    api_id = 2040
    api_hash = "b18441a1ff607e106cf21230e9c032d8"

    print(f"--- Converting HEX to Session String for {phone} ---")
    try:
        # Telethon and Pyrogram session strings are different, but we can use Telethon to verify or
        # try to construct a Pyrogram one. Pyrogram is preferred since the project uses it.
        # Constructing Pyrogram session string:
        # Format: DC_ID (1 byte) + Test Mode (1 byte) + AuthKey (256 bytes) + UserID (8 bytes) + IsBot (1 byte)
        # Note: Pyrogram session string formats vary by version.
        
        # Easier way: Use Telethon to login with the Auth Key and then we could export if needed, 
        # but let's try direct Pyrogram verification if we can get the format right.
        
        # Pyrogram 2.0 format (base64):
        # >BI?256sQ?
        # B: DC ID (1 byte)
        # I: API ID (4 bytes)
        # ?: Test Mode (1 byte)
        # 256s: Auth Key (256 bytes)
        # Q: User ID (8 bytes)
        # ?: Is Bot (1 byte)
        
        auth_key = binascii.unhexlify(auth_key_hex)
        user_id = 8928500039 # Provided by user
        
        # Pyrogram 2.0 Session String construction
        packed = struct.pack(">BI?256sQ?", dc_id, api_id, False, auth_key, user_id, False)
        pyrogram_session = base64.urlsafe_b64encode(packed).decode().rstrip("=")
        
        print("\n--- Verifying with Pyrogram ---")
        client = Client(
            name="pyrogram_verify",
            api_id=api_id,
            api_hash=api_hash,
            session_string=pyrogram_session,
            proxy=proxy_info,
            in_memory=True
        )
        
        async with client:
            me = await client.get_me()
            print(f"SUCCESS! Logged in as: {me.first_name} (@{me.username})")
            print(f"Account ID: {me.id}")
            print(f"Pyrogram Session String (save this!): {pyrogram_session}")

    except Exception as e:
        print(f"Verification Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(verify_and_add())
