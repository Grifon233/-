import sys
import os
import asyncio
from pathlib import Path

# Add backend to sys.path
backend_path = r"C:\Users\ЗС\OneDrive\Рабочий стол\Телеграмм парсер\src\backend"
sys.path.append(backend_path)

# Mock tgcrypto before any imports
import app.services._compat.tgcrypto_stub
import sys
import app.services._compat.tgcrypto_stub as stub
sys.modules["tgcrypto"] = stub

from app.services.tdata_converter import convert_tdata_folder, TDataImportError
from pyrogram import Client

async def try_verify(tdata_path, api_id, api_hash, passcode, proxy_info):
    print(f"\n--- Attempting conversion for {tdata_path} with passcode: {passcode} ---")
    result = None
    try:
        result = convert_tdata_folder(tdata_path, api_id, api_hash, passcode=passcode)
        print(f"Conversion successful!")
    except Exception as e:
        print(f"Failed: {e}")
        return False

    if result:
        print(f"Phone: {result.phone_number}")
        print(f"User ID: {result.user_id}")
        
        print("Verifying session with proxy...")
        client = Client(
            name="test_account",
            api_id=api_id,
            api_hash=api_hash,
            session_string=result.session_string,
            proxy=proxy_info,
            in_memory=True
        )
        
        try:
            async with client:
                me = await client.get_me()
                print(f"Successfully logged in as: {me.first_name} (@{me.username})")
                print(f"Account ID: {me.id}")
                print(f"Status: OK")
                return True
        except Exception as e:
            print(f"Verification Error: {e}")
    return False

async def main():
    paths = [
        Path(r"C:\Users\ЗС\OneDrive\Рабочий стол\extracted_tdata_4"),
        Path(r"C:\Users\ЗС\OneDrive\Рабочий стол\extracted_tdata_3\tdata"),
        Path(r"C:\Users\ЗС\OneDrive\Рабочий стол\extracted_tdata_2\tdata"),
        Path(r"C:\Users\ЗС\OneDrive\Рабочий стол\extracted_tdata\tdata"),
    ]
    passcodes = [None, "10013"] # Try without passcode first for autoregs usually
    
    proxy_info = {
        "scheme": "socks5",
        "hostname": "196.16.110.162",
        "port": 8000,
        "username": "vm9XXY",
        "password": "kwrCYR"
    }
    
    api_id = 2040
    api_hash = "b18441a1ff607e106cf21230e9c032d8"

    for p in paths:
        if not p.exists(): continue
        for pc in passcodes:
            if await try_verify(p, api_id, api_hash, pc, proxy_info):
                print("\nALL DONE! Success found.")
                return

if __name__ == "__main__":
    asyncio.run(main())
