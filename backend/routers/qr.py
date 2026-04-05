"""
QR Router
──────────
Endpoints for QR code generation and patient scan registration.

GET  /qr/doctors/{doctor_id}         → Get/generate QR PNG for a doctor
GET  /qr/doctors/{doctor_id}/url     → Get just the scan URL (for frontend display)
POST /qr/scan                        → Patient scans QR → register/link patient
GET  /qr/doctors/{doctor_id}/scans   → How many times this QR has been scanned
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlmodel import Session, select
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from database import get_session
from models import Doctor, Patient, QRCode
from services.qr_generator import generate_doctor_qr, verify_qr_token
from services.abha_client import fetch_patient_by_abha_id, parse_gender

router = APIRouter(prefix="/qr", tags=["qr"])


# ── Request / Response schemas ─────────────────────────────────────────────────
class ScanRequest(BaseModel):
    doctorId:  str
    token:     str                       # HMAC token from QR URL
    abhaId:    Optional[str] = None      # Patient provides ABHA ID
    name:      Optional[str] = None      # Fallback if no ABHA
    phone:     Optional[str] = None
    age:       Optional[int] = None
    gender:    Optional[str] = None


class ScanResponse(BaseModel):
    status:       str                    # "new_patient" | "existing_patient"
    patientId:    str
    patientName:  str
    doctorName:   str
    message:      str
    hasHistory:   bool                   # True if patient has records from other doctors


# ── GET /qr/doctors/{doctor_id} ── Serve QR PNG ────────────────────────────────
@router.get("/doctors/{doctor_id}")
def get_doctor_qr(doctor_id: str, session: Session = Depends(get_session)):
    """
    Returns QR code as PNG image for the doctor to print / display.
    Creates a QRCode record in DB if one doesn't exist yet.
    """
    doctor = session.get(Doctor, doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    # Check if QR record exists
    qr_record = session.exec(
        select(QRCode).where(QRCode.doctorId == doctor_id)
    ).first()

    # Generate QR
    png_bytes, scan_url = generate_doctor_qr(doctor_id)

    # Create or update record
    if not qr_record:
        qr_record = QRCode(doctorId=doctor_id, scanUrl=scan_url)
        session.add(qr_record)
        session.commit()

    return Response(content=png_bytes, media_type="image/png")


# ── GET /qr/doctors/{doctor_id}/url ── Return scan URL ─────────────────────────
@router.get("/doctors/{doctor_id}/url")
def get_doctor_qr_url(doctor_id: str, session: Session = Depends(get_session)):
    """Returns the URL encoded in the doctor's QR code (for frontend display)."""
    doctor = session.get(Doctor, doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    _, scan_url = generate_doctor_qr(doctor_id)
    return {
        "doctorId":  doctor_id,
        "doctorName": doctor.name,
        "clinicName": doctor.clinicName,
        "scanUrl":   scan_url,
    }


# ── POST /qr/scan ── Patient scans QR → register ───────────────────────────────
@router.post("/scan", response_model=ScanResponse)
async def scan_qr(request: ScanRequest, session: Session = Depends(get_session)):
    """
    Called when a patient scans a doctor's QR code.

    Flow:
      1. Verify HMAC token (prevent forged QR scans)
      2. Look up ABHA ID via ABDM API if provided
      3. Find or create patient record
      4. Link patient to doctor
      5. Check for existing records from other doctors (for sharing feature)
    """
    # Step 1 — Verify token
    if not verify_qr_token(request.doctorId, request.token):
        raise HTTPException(status_code=403, detail="Invalid QR code. Please scan the doctor's official QR.")

    # Step 2 — Verify doctor exists
    doctor = session.get(Doctor, request.doctorId)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    # Step 3 — Fetch from ABHA if provided
    patient_data = {}
    if request.abhaId:
        abha_data = await fetch_patient_by_abha_id(request.abhaId)
        if abha_data:
            patient_data = abha_data

    # Step 4 — Check if patient already exists (by ABHA ID or phone)
    existing_patient = None
    if request.abhaId:
        existing_patient = session.exec(
            select(Patient).where(Patient.abhaId == request.abhaId)
        ).first()
    elif request.phone:
        existing_patient = session.exec(
            select(Patient)
            .where(Patient.phone == request.phone)
            .where(Patient.doctorId == request.doctorId)
        ).first()

    # Step 5 — Check if patient has history with other doctors
    has_history = False
    if existing_patient and existing_patient.doctorId != request.doctorId:
        has_history = True

    # Step 6 — Create new patient or return existing
    if existing_patient and existing_patient.doctorId == request.doctorId:
        # Already registered with this doctor
        return ScanResponse(
            status="existing_patient",
            patientId=existing_patient.id,
            patientName=existing_patient.name,
            doctorName=doctor.name,
            message=f"Welcome back! Dr. {doctor.name} can now see your records.",
            hasHistory=False,
        )

    # Create new patient record for this doctor
    name   = patient_data.get("name") or request.name or "Unknown Patient"
    gender = parse_gender(patient_data.get("gender")) or request.gender
    phone  = patient_data.get("mobile") or request.phone

    # Parse age from DOB if available
    age = request.age
    if patient_data.get("dob"):
        try:
            parts = patient_data["dob"].split("/")
            birth_year = int(parts[2]) if len(parts) == 3 else None
            if birth_year:
                age = datetime.now().year - birth_year
        except Exception:
            pass

    new_patient = Patient(
        doctorId=request.doctorId,
        name=name,
        phone=phone,
        age=age,
        gender=gender,
        abhaId=request.abhaId,
        address=patient_data.get("address"),
    )
    session.add(new_patient)

    # Increment QR scan count
    qr_record = session.exec(
        select(QRCode).where(QRCode.doctorId == request.doctorId)
    ).first()
    if qr_record:
        qr_record.scanCount += 1
        session.add(qr_record)

    session.commit()
    session.refresh(new_patient)

    return ScanResponse(
        status="new_patient",
        patientId=new_patient.id,
        patientName=new_patient.name,
        doctorName=doctor.name,
        message=f"Registered successfully with Dr. {doctor.name}.",
        hasHistory=has_history,
    )


# ── GET /qr/doctors/{doctor_id}/scans ── Scan stats ───────────────────────────
@router.get("/doctors/{doctor_id}/scans")
def get_scan_stats(doctor_id: str, session: Session = Depends(get_session)):
    """Returns how many patients have scanned this doctor's QR code."""
    qr_record = session.exec(
        select(QRCode).where(QRCode.doctorId == doctor_id)
    ).first()
    if not qr_record:
        return {"doctorId": doctor_id, "scanCount": 0, "qrCreatedAt": None}
    return {
        "doctorId":    doctor_id,
        "scanCount":   qr_record.scanCount,
        "qrCreatedAt": qr_record.createdAt,
    }
