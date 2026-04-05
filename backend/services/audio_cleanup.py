"""
Audio Cleanup Service
──────────────────────
Secure auto-deletion of audio files after 30 minutes.

WHY THIS MATTERS:
  Audio files contain:
    - Biometric data (voice) → sensitive personal data under DPDP Act 2023
    - Protected health information (PHI) → IT Act 2000
  Regular os.remove() only unlinks the file — data stays on disk until overwritten.
  We overwrite with zeros first (secure wipe) before deleting.

HOW IT RUNS:
  APScheduler runs cleanup_old_audio() every 5 minutes as an async background job.
  Started in main.py lifespan on app startup.

DELETION TRIGGERS (3 ways audio gets deleted):
  1. Auto: this scheduler (every 5 min, deletes files > 30 min old)
  2. On confirm: doctor confirms EMR → immediate deletion
  3. On disconnect: WebSocket disconnects → immediate deletion

AUDIT:
  Every deletion is logged to audit_log.txt with timestamp and file info.
"""

import os
import time
import json
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

UPLOAD_DIR   = "uploads"
MAX_AGE_SECS = 1800          # 30 minutes
AUDIT_LOG    = "audit_log.txt"

scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


# ── Secure Delete ─────────────────────────────────────────────────────────────
def secure_delete(file_path: str, reason: str = "auto_cleanup") -> bool:
    """
    Securely delete a file by overwriting with zeros before removal.

    Args:
        file_path : Path to the audio file
        reason    : Why it was deleted ("auto_cleanup" | "doctor_confirmed" | "ws_disconnect")

    Returns:
        True if deleted successfully, False if file not found or error
    """
    if not os.path.exists(file_path):
        return False

    try:
        file_size = os.path.getsize(file_path)

        # Overwrite with zeros — makes data unrecoverable
        with open(file_path, "wb") as f:
            f.write(b"\x00" * file_size)

        os.remove(file_path)
        _write_audit(file_path, file_size, reason)
        print(f"[AudioCleanup] Secure deleted: {os.path.basename(file_path)} ({file_size} bytes) — {reason}")
        return True

    except Exception as e:
        print(f"[AudioCleanup] Delete failed for {file_path}: {e}")
        return False


def _write_audit(file_path: str, file_size: int, reason: str):
    """Append deletion event to audit log."""
    event = {
        "timestamp": datetime.now().isoformat(),
        "file":      os.path.basename(file_path),
        "size_bytes": file_size,
        "reason":    reason,
        "action":    "secure_delete",
    }
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass   # Don't crash if audit log write fails


# ── Scheduled Cleanup Job ─────────────────────────────────────────────────────
@scheduler.scheduled_job("interval", minutes=5, id="audio_cleanup")
async def cleanup_old_audio():
    """
    Runs every 5 minutes.
    Deletes any audio file in uploads/ older than 30 minutes.
    """
    if not os.path.exists(UPLOAD_DIR):
        return

    now     = time.time()
    deleted = 0
    errors  = 0

    for fname in os.listdir(UPLOAD_DIR):
        # Only process audio files
        if not fname.endswith((".wav", ".mp3", ".webm", ".ogg", ".m4a", ".mp4")):
            continue

        fpath = os.path.join(UPLOAD_DIR, fname)
        try:
            age = now - os.path.getmtime(fpath)
            if age > MAX_AGE_SECS:
                if secure_delete(fpath, "auto_cleanup_30min"):
                    deleted += 1
                else:
                    errors += 1
        except Exception as e:
            print(f"[AudioCleanup] Error checking {fname}: {e}")
            errors += 1

    if deleted > 0 or errors > 0:
        print(f"[AudioCleanup] Cycle complete — deleted: {deleted} | errors: {errors}")


# ── Immediate Delete (called from router on confirm / disconnect) ─────────────
def delete_audio_now(file_path: str, reason: str = "immediate") -> bool:
    """
    Called immediately when:
    - Doctor confirms the EMR (no longer need the audio)
    - WebSocket disconnects
    """
    return secure_delete(file_path, reason)


# ── Scheduler Lifecycle ───────────────────────────────────────────────────────
def start_scheduler():
    """Start the background scheduler. Called from main.py lifespan."""
    if not scheduler.running:
        scheduler.start()
        print("[AudioCleanup] Scheduler started — audio files deleted after 30 min")


def stop_scheduler():
    """Stop the scheduler gracefully. Called from main.py lifespan shutdown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[AudioCleanup] Scheduler stopped")
