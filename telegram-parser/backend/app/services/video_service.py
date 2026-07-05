"""
Video Service
Конвертация обычных видео в видео-кружочки (Video Notes)
"""

import os
import uuid
import asyncio
import logging
import subprocess
from datetime import datetime
from typing import List, Dict

from app.models.account import Account
from app.services.telegram_service import telegram_service

logger = logging.getLogger(__name__)

TEMP_DIR = "/tmp/video_notes"
if not os.path.exists(TEMP_DIR):
    # Fallback for Windows/local
    TEMP_DIR = os.path.join(os.getcwd(), "temp_videos")
    os.makedirs(TEMP_DIR, exist_ok=True)

async def convert_to_video_note(input_path: str, output_path: str, max_duration: int = 60) -> bool:
    """
    Конвертация видео в формат кружочка Telegram (512x512, <1 min, H.264)
    Использует ffmpeg.
    """
    try:
        # crop='min(iw,ih)':'min(iw,ih)' - делает квадрат обрезая края
        # scale=512:512 - ресайз под размер кружка
        vf_filter = "crop='min(iw,ih)':'min(iw,ih)',scale=512:512"
        
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", vf_filter,
            "-t", str(max_duration),
            "-c:v", "libx264",
            "-c:a", "copy",
            output_path
        ]
        
        # Run ffmpeg synchronously via subprocess in an executor
        loop = asyncio.get_event_loop()
        process = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error: {e.stderr.decode('utf-8', errors='ignore')}")
        return False
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg conversion timed out")
        return False
    except Exception as e:
        logger.error(f"Conversion error: {e}")
        return False

async def send_video_note_to_chats(
    account: Account,
    input_video_path: str,
    target_chats: List[str]
) -> Dict:
    """
    Конвертирует видео и рассылает кружок по списку чатов.
    """
    result = {
        "account_id": account.id,
        "chats_processed": 0,
        "success_count": 0,
        "errors": []
    }
    
    unique_id = uuid.uuid4().hex
    output_video_path = os.path.join(TEMP_DIR, f"note_{unique_id}.mp4")
    
    try:
        # 1. Convert video
        success = await convert_to_video_note(input_video_path, output_video_path)
        if not success:
            result["errors"].append("Video conversion failed. Ensure ffmpeg is installed.")
            return result
            
        # 2. Get client
        client = await telegram_service.get_client(account)
        
        # 3. Send to each chat
        for chat in target_chats:
            try:
                # Clean up chat name
                target = chat.replace("@", "").strip()
                if "t.me/" in target:
                    target = target.split("t.me/")[-1]
                    if target.startswith("+") or target.startswith("joinchat/"):
                        target = chat # use full link for invite links
                
                await client.send_video_note(chat_id=target, video_note=output_video_path)
                result["success_count"] += 1
                
                # Small delay to prevent flood
                await asyncio.sleep(2)
                
            except Exception as e:
                result["errors"].append(f"{chat}: {str(e)}")
            
            result["chats_processed"] += 1
            
    finally:
        # Cleanup temp file
        if os.path.exists(output_video_path):
            try:
                os.remove(output_video_path)
            except OSError as e:
                logger.warning("Failed to delete temporary video %s: %s", output_video_path, e)
                
    return result
