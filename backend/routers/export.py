from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select
from database import get_session
from models import Visit, EMR, DiseaseRisk, Patient, Doctor
from services.pdf_generator import generate_visit_pdf
from services.prescription_generator import generate_prescription_pdf

router = APIRouter(prefix="/export", tags=["export"])


# ── Existing: Full clinical PDF ────────────────────────────────────────────────
@router.get("/visits/{visit_id}/pdf")
def export_visit_pdf(visit_id: str, session: Session = Depends(get_session)):
    """Full clinical PDF — for doctor's records. Includes all EMR fields + risk scores."""
    visit = session.get(Visit, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    patient = session.get(Patient, visit.patientId)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    doctor = session.get(Doctor, patient.doctorId)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    emr  = session.exec(select(EMR).where(EMR.visitId == visit_id)).first()
    risk = session.exec(select(DiseaseRisk).where(DiseaseRisk.visitId == visit_id)).first()

    if not emr:
        raise HTTPException(status_code=404, detail="EMR not found for this visit")

    pdf_buffer = generate_visit_pdf(visit, patient, doctor, emr, risk)
    filename   = f"Visit_{patient.name.replace(' ', '_')}_{visit.visitDate.strftime('%Y%m%d')}.pdf"

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ── NEW: Prescription slip (A5, patient-facing) ────────────────────────────────
@router.get("/visits/{visit_id}/prescription")
def export_prescription(visit_id: str, session: Session = Depends(get_session)):
    """
    Generates an A5 prescription slip for the patient to take to the pharmacy.
    Contains: medicines + dosage + instructions + follow-up date only.
    Separate from the full clinical PDF.
    """
    visit = session.get(Visit, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    patient = session.get(Patient, visit.patientId)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    doctor = session.get(Doctor, patient.doctorId)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    emr = session.exec(select(EMR).where(EMR.visitId == visit_id)).first()
    if not emr:
        raise HTTPException(status_code=404, detail="EMR not found for this visit")

    if not emr.medications:
        raise HTTPException(
            status_code=400,
            detail="No medications in this EMR — prescription slip requires at least one medicine."
        )

    pdf_buffer = generate_prescription_pdf(visit, patient, doctor, emr)
    filename   = f"Prescription_{patient.name.replace(' ', '_')}_{visit.visitDate.strftime('%Y%m%d')}.pdf"

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
