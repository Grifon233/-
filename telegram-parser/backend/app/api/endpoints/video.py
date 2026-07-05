"""
Video API endpoints
Кружки из видео (Video Notes)
"""

import os
import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.session import get_db
from app.models.account import Account
from app.services.video_service import send_video_note_to_chats, TEMP_DIR
from app.api.deps import get_project_id

router = APIRouter()
logger = logging.getLogger(__name__)
MAX_VIDEO_UPLOAD_BYTES = 100 * 1024 * 1024

@router.post("/send-note")
async def upload_and_send_video_note(
    background_tasks: BackgroundTasks,
    account_id: int = Form(...),
    chats: str = Form(...), # Comma or newline separated
    video: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """
    Upload a video, convert to video note, and send to chats.
    """
    # Verify account
    result = await db.execute(select(Account).where(Account.id == account_id, Account.project_id == project_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
        
    if not video.filename or not video.filename.lower().endswith((".mp4", ".mov", ".avi")):
        raise HTTPException(status_code=400, detail="Invalid video format")
        
    # Process chats list
    target_chats = [c.strip() for c in chats.replace("\n", ",").split(",") if c.strip()]
    if not target_chats:
        raise HTTPException(status_code=400, detail="No valid chats provided")

    # Save uploaded file
    unique_id = uuid.uuid4().hex
    _, ext = os.path.splitext(video.filename)
    input_path = os.path.join(TEMP_DIR, f"upload_{unique_id}{ext}")
    
    uploaded_bytes = 0
    try:
        with open(input_path, "wb") as buffer:
            while chunk := await video.read(1024 * 1024):
                uploaded_bytes += len(chunk)
                if uploaded_bytes > MAX_VIDEO_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Video exceeds 100 MB limit")
                buffer.write(chunk)
    except Exception:
        if os.path.exists(input_path):
            os.remove(input_path)
        raise
        
    # We could send in background, but we need the result. 
    # For a simple implementation, let's just do it directly or via background and return status.
    # Since video processing can take a while, doing it in background is safer.
    
    async def process_and_cleanup():
        try:
            await send_video_note_to_chats(account, input_path, target_chats)
        finally:
            if os.path.exists(input_path):
                try:
                    os.remove(input_path)
                except Exception as e:
                    logger.error(f"Failed to delete temp video {input_path}: {e}")

    background_tasks.add_task(process_and_cleanup)

    return {
        "status": "processing",
        "message": f"Video uploaded and queued for sending to {len(target_chats)} chats",
        "chats": target_chats
    }
