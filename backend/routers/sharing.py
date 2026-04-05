"""
Sharing Router
───────────────
Cross-doctor patient record sharing endpoints.

POST /sharing/request           → Request to share patient records to a new doctor
GET  /sharing/records/{token}   → Receiving doctor fetches the shared records
GET  /sharing/incoming/{doctor_id}  → Doctor sees all incoming shared records
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from pydantic import BaseModel
from typing import Optional

from database import get_session
from models import Patient, Doctor, ConsentLog, PatientShareConsent
from services.share_engine import build_patient_summary
from datetime import datetime

router = APIRouter(prefix="/sharing", tags=["sharing"])


# ── Request schemas ────────────────────────────────────────────────────────────
class ShareRequestBody(BaseModel):
    patientId:    str
    fromDoctorId: str
    toDoctorId:   str
    consentId:    str    # From POST /consent/sharing — proves patient agreed


# ── POST /sharing/request ──────────────────────────────────────────────────────
@router.post("/request")
def create_share_request(
    body: ShareRequestBody,
    session: Session = Depends(get_session),
):
    """
    Initiates a record share from one doctor to another.
    Requires a valid consentId proving the patient agreed.

    Called when:
    - Patient scans a new doctor's QR and has history (hasHistory=True from /qr/scan)
    - Patient explicitly requests sharing in the app
    """
    # Verify consent exists, is for this patient, and is not revoked
    consent = session.get(ConsentLog, body.consentId)
    if not consent:
        raise HTTPException(status_code=403, detail="No consent record found. Patient must consent first.")
    if consent.revokedAt:
        raise HTTPException(status_code=403, detail="Patient has revoked this consent.")
    if consent.patientId != body.patientId:
        raise HTTPException(status_code=403, detail="Consent does not match this patient.")
    if consent.consentType != "sharing":
        raise HTTPException(status_code=403, detail="Invalid consent type for sharing.")

    # Verify all parties exist
    patient   = session.get(Patient, body.patientId)
    to_doctor = session.get(Doctor,  body.toDoctorId)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    if not to_doctor:
        raise HTTPException(status_code=404, detail="Target doctor not found")

    # Check if a share record already exists
    existing = session.exec(
        select(PatientShareConsent)
        .where(PatientShareConsent.patientId    == body.patientId)
        .where(PatientShareConsent.toDoctorId   == body.toDoctorId)
        .where(PatientShareConsent.fromDoctorId == body.fromDoctorId)
    ).first()
    if existing and not existing.revoked:
        return {
            "status":       "already_shared",
            "shareToken":   existing.id,
            "toDoctorName": to_doctor.name,
            "message":      "Records already shared with this doctor.",
        }

    # Create share record
    share = PatientShareConsent(
        patientId=body.patientId,
        fromDoctorId=body.fromDoctorId,
        toDoctorId=body.toDoctorId,
        consentLogId=body.consentId,
    )
    session.add(share)
    session.commit()
    session.refresh(share)

    return {
        "status":       "share_created",
        "shareToken":   share.id,
        "toDoctorName": to_doctor.name,
        "patientName":  patient.name,
        "message":      f"Records will be shared with Dr. {to_doctor.name}. "
                        f"They can access them using token: {share.id}",
    }


# ── GET /sharing/records/{token} ── Receiving doctor fetches shared records ────
@router.get("/records/{share_token}")
def get_shared_records(
    share_token: str,
    session: Session = Depends(get_session),
):
    """
    Called by the RECEIVING doctor to access shared patient records.
    Returns a sanitised, read-only view of the patient's history.
    """
    share = session.get(PatientShareConsent, share_token)
    if not share:
        raise HTTPException(status_code=404, detail="Share record not found.")
    if share.revoked:
        raise HTTPException(status_code=403, detail="Patient has revoked this share.")

    # Build the sanitised summary
    summary = build_patient_summary(
        session=session,
        patient_id=share.patientId,
        consent_id=share.consentLogId,
    )
    if not summary:
        raise HTTPException(
            status_code=403,
            detail="Could not build record summary. Consent may be invalid or revoked."
        )

    return {
        "shareToken":  share_token,
        "fromDoctorId": share.fromDoctorId,
        "toDoctorId":   share.toDoctorId,
        "sharedSince":  share.createdAt,
        "records":      summary,
    }


# ── GET /sharing/incoming/{doctor_id} ── All records shared TO this doctor ─────
@router.get("/incoming/{doctor_id}")
def get_incoming_shares(
    doctor_id: str,
    session: Session = Depends(get_session),
):
    """
    Returns all patient record packages shared with this doctor.
    Shows in doctor's dashboard as "Patients with shared history".
    """
    shares = session.exec(
        select(PatientShareConsent)
        .where(PatientShareConsent.toDoctorId == doctor_id)
        .where(PatientShareConsent.revoked    == False)
    ).all()

    result = []
    for share in shares:
        patient = session.get(Patient, share.patientId)
        result.append({
            "shareToken":  share.id,
            "patientId":   share.patientId,
            "patientName": patient.name if patient else "Unknown",
            "patientAbha": patient.abhaId if patient else None,
            "sharedSince": share.createdAt,
            "fetchUrl":    f"/sharing/records/{share.id}",
        })

    return {
        "doctorId":     doctor_id,
        "totalShared":  len(result),
        "sharedPatients": result,
    }


# ── DELETE /sharing/{share_token} ── Revoke a share ───────────────────────────
@router.delete("/{share_token}")
def revoke_share(
    share_token: str,
    session: Session = Depends(get_session),
):
    """Patient or original doctor revokes the record share."""
    share = session.get(PatientShareConsent, share_token)
    if not share:
        raise HTTPException(status_code=404, detail="Share record not found.")

    share.revoked   = True
    share.revokedAt = datetime.now()
    session.commit()

    return {"status": "revoked", "shareToken": share_token, "message": "Record sharing has been revoked."}
