"""
Transcription Router
─────────────────────
POST /transcribe/         — Upload audio file → transcript
POST /transcribe/detect   — Detect language from text snippet
WS   /transcribe/live     — WebSocket for live recording (chunked)

SECURITY: Audio is deleted immediately after transcription (upload endpoint)
          or after 30 minutes max (live endpoint via audio_cleanup scheduler).
          secure_delete() overwrites with zeros before removing.
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Form, WebSocket, WebSocketDisconnect
from typing import Optional
import shutil
import os
import uuid
from services.transcription import transcribe_audio, detect_language
from services.audio_cleanup import secure_delete

router = APIRouter(prefix="/transcribe", tags=["transcribe"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

SUPPORTED_LANGUAGES = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "mr": "Marathi",
    "bn": "Bengali",
    "gu": "Gujarati",
    "pa": "Punjabi",
    "ml": "Malayalam",
}


@router.get("/languages")
def get_supported_languages():
    return {"languages": SUPPORTED_LANGUAGES}


@router.post("/")
async def transcribe(
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    consentId: Optional[str] = Form(None),    # NEW: patient consent token
):
    """
    Upload audio file and get transcript.
    Audio is IMMEDIATELY deleted after transcription (secure wipe).

    consentId: token from POST /consent/recording — required in production.
    """
    # Validate file type
    allowed_types = {
        "audio/mpeg", "audio/wav", "audio/x-wav", "audio/webm",
        "audio/ogg", "audio/mp4", "audio/m4a", "video/webm"
    }
    if file.content_type and file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}"
        )

    ext         = os.path.splitext(file.filename or "audio.wav")[1] or ".wav"
    unique_name = f"{uuid.uuid4()}{ext}"
    file_path   = os.path.join(UPLOAD_DIR, unique_name)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        transcript_text = transcribe_audio(file_path, language)
        detected_lang   = language or detect_language(transcript_text)

        return {
            "text":           transcript_text,
            "language":       detected_lang,
            "languageName":   SUPPORTED_LANGUAGES.get(detected_lang, "Unknown"),
            "characterCount": len(transcript_text),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # SECURITY: Secure-delete immediately after transcription
        # Don't wait for the 30-min scheduler — delete now
        secure_delete(file_path, reason="immediate_post_transcription")


@router.post("/detect-language")
async def detect_text_language(text: str = Form(...)):
    lang = detect_language(text)
    return {
        "language":     lang,
        "languageName": SUPPORTED_LANGUAGES.get(lang, "Unknown"),
    }


@router.websocket("/live")
async def live_transcription(websocket: WebSocket):
    """
    WebSocket endpoint for live recording sessions.

    SECURITY FLOW:
      1. Client connects and sends { "language": "hi", "consentId": "xxx" }
         consentId must come from POST /consent/recording
      2. Client streams binary audio chunks
      3. Server accumulates chunks
      4. Client sends "STOP" → server transcribes + securely deletes audio
      5. On any disconnect → audio is securely deleted

    Audio file is deleted:
      - On STOP signal (immediate)
      - On WebSocket disconnect (immediate)
      - After 30 minutes (audio_cleanup scheduler, safety net)
    """
    await websocket.accept()
    audio_chunks: list = []
    language    = "en"
    tmp_path    = None

    try:
        # First message is config — must include consentId in production
        config   = await websocket.receive_json()
        language = config.get("language", "en")
        # consent_id = config.get("consentId")  # Validate in production

        await websocket.send_json({"status": "connected", "language": language})

        while True:
            data = await websocket.receive()

            if data.get("type") == "websocket.receive":
                if data.get("text") == "STOP":
                    break
                elif data.get("bytes"):
                    audio_chunks.append(data["bytes"])
                    await websocket.send_json({
                        "status": "recording",
                        "chunks": len(audio_chunks)
                    })

    except WebSocketDisconnect:
        pass   # Falls through to finally — audio will be deleted
    finally:
        # Process and SECURELY DELETE audio
        if audio_chunks:
            combined = b"".join(audio_chunks)
            tmp_path = os.path.join(UPLOAD_DIR, f"live_{uuid.uuid4()}.webm")
            try:
                with open(tmp_path, "wb") as f:
                    f.write(combined)

                transcript = transcribe_audio(tmp_path, language)
                detected   = detect_language(transcript)

                # Bug #7 fixed: wrap send in try/except — client may be gone
                try:
                    await websocket.send_json({
                        "status":       "done",
                        "transcript":   transcript,
                        "language":     detected,
                        "languageName": SUPPORTED_LANGUAGES.get(detected, "Unknown"),
                    })
                except Exception:
                    pass   # Client already disconnected

            except Exception as e:
                try:
                    await websocket.send_json({"status": "error", "detail": str(e)})
                except Exception:
                    pass
            finally:
                # SECURITY: Always securely delete — even if transcription failed
                if tmp_path:
                    secure_delete(tmp_path, reason="ws_session_ended")
        else:
            try:
                await websocket.send_json({"status": "done", "transcript": ""})
            except Exception:
                pass
