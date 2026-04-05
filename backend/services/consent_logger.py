"""
Consent Logger
───────────────
Logs patient consent events for DPDP Act 2023 and IT Act 2000 compliance.

Every time a patient consents to being recorded, that event is written to the
ConsentLog table with full metadata. This is your legal proof of compliance.

Consent types:
  - "recording"   : patient agrees to audio recording for transcription
  - "sharing"     : patient agrees to share records with another doctor
  - "qr_register" : patient registers via QR scan (implicit consent to treatment)
"""

from datetime import datetime
from typing import Optional
from sqlmodel import Session
from models import ConsentLog


def log_consent(
    session: Session,
    patient_id:   str,
    doctor_id:    str,
    consent_type: str,                   # "recording" | "sharing" | "qr_register"
    ip_address:   Optional[str] = None,
    extra_data:   Optional[str] = None,  # JSON string for any extra context
) -> ConsentLog:
    """
    Write a consent event to the database.

    Args:
        session:      DB session
        patient_id:   ID of the patient giving consent
        doctor_id:    ID of the doctor in the session
        consent_type: Type of consent being recorded
        ip_address:   Patient's IP address (for legal audit trail)
        extra_data:   Any additional context as JSON string

    Returns:
        The created ConsentLog record
    """
    log = ConsentLog(
        patientId=patient_id,
        doctorId=doctor_id,
        consentType=consent_type,
        ipAddress=ip_address,
        extraData=extra_data,
        consentAt=datetime.now(),
    )
    session.add(log)
    session.commit()
    session.refresh(log)
    print(f"[Consent] Logged: {consent_type} | patient={patient_id} | doctor={doctor_id}")
    return log


def revoke_consent(
    session: Session,
    log_id: str,
) -> Optional[ConsentLog]:
    """
    Mark a consent as revoked (patient withdrew consent).
    Required by DPDP Act — patient can revoke at any time.
    """
    log = session.get(ConsentLog, log_id)
    if not log:
        return None
    log.revokedAt = datetime.now()
    session.commit()
    session.refresh(log)
    print(f"[Consent] Revoked: {log_id}")
    return log


def get_patient_consents(session: Session, patient_id: str) -> list:
    """Get all consent records for a patient (for patient data request)."""
    from sqlmodel import select
    return session.exec(
        select(ConsentLog).where(ConsentLog.patientId == patient_id)
    ).all()
