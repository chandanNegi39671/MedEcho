"""
Consent Router
───────────────
Handles patient consent for recording and data sharing.

POST /consent/recording      → Patient agrees to audio recording
POST /consent/sharing        → Patient agrees to share records with another doctor
DELETE /consent/{log_id}     → Patient revokes a consent
GET  /consent/patient/{id}   → Get all consent records for a patient (DPDP right to access)
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session
from pydantic import BaseModel
from typing import Optional

from database import get_session
from models import Patient, Doctor, ConsentLog
from services.consent_logger import log_consent, revoke_consent, get_patient_consents

router = APIRouter(prefix="/consent", tags=["consent"])


# ── Request schemas ────────────────────────────────────────────────────────────
class RecordingConsentRequest(BaseModel):
    patientId: str
    doctorId:  str
    # Patient explicitly ticks "I consent to this consultation being recorded
    # for transcription purposes only. The recording will be deleted within 30 minutes."
    consentGiven: bool


class SharingConsentRequest(BaseModel):
    patientId:      str
    fromDoctorId:   str
    toDoctorId:     str
    consentGiven:   bool


# ── POST /consent/recording ────────────────────────────────────────────────────
@router.post("/recording")
def record_recording_consent(
    request: RecordingConsentRequest,
    req: Request,
    session: Session = Depends(get_session),
):
    """
    Called BEFORE recording starts.
    Frontend must call this and receive 200 OK before enabling the mic.
    If patient does not consent → do not record.
    """
    if not request.consentGiven:
        raise HTTPException(
            status_code=400,
            detail="Recording cannot proceed without patient consent."
        )

    patient = session.get(Patient, request.patientId)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    doctor = session.get(Doctor, request.doctorId)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    ip = req.client.host if req.client else None

    log = log_consent(
        session=session,
        patient_id=request.patientId,
        doctor_id=request.doctorId,
        consent_type="recording",
        ip_address=ip,
        extra_data='{"purpose": "transcription_only", "retention_minutes": 30}',
    )

    return {
        "status":    "consent_recorded",
        "consentId": log.id,
        "message":   "Recording may proceed. Audio will be deleted within 30 minutes.",
    }


# ── POST /consent/sharing ──────────────────────────────────────────────────────
@router.post("/sharing")
def record_sharing_consent(
    request: SharingConsentRequest,
    req: Request,
    session: Session = Depends(get_session),
):
    """
    Called when patient agrees to share their records with a new doctor.
    Returns a consent token used to authorise the record transfer.
    """
    if not request.consentGiven:
        raise HTTPException(
            status_code=400,
            detail="Record sharing requires explicit patient consent."
        )

    patient = session.get(Patient, request.patientId)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    to_doctor = session.get(Doctor, request.toDoctorId)
    if not to_doctor:
        raise HTTPException(status_code=404, detail="Target doctor not found")

    ip = req.client.host if req.client else None

    import json
    log = log_consent(
        session=session,
        patient_id=request.patientId,
        doctor_id=request.fromDoctorId,
        consent_type="sharing",
        ip_address=ip,
        extra_data=json.dumps({
            "toDoctorId":   request.toDoctorId,
            "toDoctorName": to_doctor.name,
        }),
    )

    return {
        "status":       "sharing_consent_recorded",
        "consentId":    log.id,
        "consentToken": log.id,    # Used as auth token in /sharing/records/{token}
        "toDoctorName": to_doctor.name,
        "message":      f"Your records will be shared with Dr. {to_doctor.name}.",
    }


# ── DELETE /consent/{log_id} ── Patient revokes consent ────────────────────────
@router.delete("/{log_id}")
def revoke_patient_consent(
    log_id: str,
    session: Session = Depends(get_session),
):
    """
    Patient can revoke any consent at any time.
    Required by DPDP Act 2023 — right to withdraw consent.
    """
    log = revoke_consent(session, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Consent record not found")
    return {
        "status":    "revoked",
        "consentId": log_id,
        "revokedAt": log.revokedAt,
        "message":   "Consent has been revoked successfully.",
    }


# ── GET /consent/patient/{patient_id} ── All consents (DPDP data access right) ─
@router.get("/patient/{patient_id}")
def get_patient_consent_history(
    patient_id: str,
    session: Session = Depends(get_session),
):
    """
    Returns all consent records for a patient.
    Required by DPDP Act 2023 — right to access personal data.
    """
    patient = session.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    logs = get_patient_consents(session, patient_id)
    return {
        "patientId": patient_id,
        "total":     len(logs),
        "consents":  logs,
    }
