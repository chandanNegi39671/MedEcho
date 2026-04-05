from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlmodel import Session, select
from typing import List, Optional
from datetime import datetime
from database import get_session
from models import Patient, Doctor

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post("/", response_model=Patient)
def create_patient(patient: Patient, session: Session = Depends(get_session)):
    # Bug #10 fixed: patient is already validated by FastAPI — no double model_validate
    session.add(patient)
    session.commit()
    session.refresh(patient)
    return patient


@router.get("/", response_model=List[Patient])
def read_patients(
    doctor_id: str,
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = Query(None),
    session: Session = Depends(get_session)
):
    statement = select(Patient).where(Patient.doctorId == doctor_id)
    if search:
        statement = statement.where(
            Patient.name.ilike(f"%{search}%") |
            Patient.phone.ilike(f"%{search}%") |
            Patient.abhaId.ilike(f"%{search}%")
        )
    statement = statement.offset(skip).limit(limit)
    return session.exec(statement).all()


@router.get("/{patient_id}", response_model=Patient)
def read_patient(patient_id: str, session: Session = Depends(get_session)):
    patient = session.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@router.patch("/{patient_id}", response_model=Patient)
def update_patient(
    patient_id: str,
    updates: dict = Body(...),         # Bug #6 fixed: Body() so FastAPI parses JSON body
    session: Session = Depends(get_session)
):
    patient = session.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    for key, val in updates.items():
        if hasattr(patient, key):
            setattr(patient, key, val)
    patient.updatedAt = datetime.now()  # Bug #5 fixed: stamp the update time
    session.commit()
    session.refresh(patient)
    return patient
