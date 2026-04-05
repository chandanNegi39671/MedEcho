from fastapi import APIRouter, Depends, HTTPException, Body
from sqlmodel import Session, select
from datetime import datetime
from database import get_session
from models import Doctor

router = APIRouter(prefix="/doctors", tags=["doctors"])


@router.get("/by-clerk-id/{clerk_id}", response_model=Doctor)
def get_doctor_by_clerk_id(clerk_id: str, session: Session = Depends(get_session)):
    statement = select(Doctor).where(Doctor.clerkId == clerk_id)
    doctor = session.exec(statement).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return doctor


@router.post("/", response_model=Doctor)
def create_doctor(doctor: Doctor, session: Session = Depends(get_session)):
    session.add(doctor)
    session.commit()
    session.refresh(doctor)
    return doctor


@router.patch("/{doctor_id}", response_model=Doctor)
def update_doctor(
    doctor_id: str,
    updates: dict = Body(...),         # Bug #6 fixed: Body() for correct JSON body parsing
    session: Session = Depends(get_session)
):
    doctor = session.get(Doctor, doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    for key, val in updates.items():
        if hasattr(doctor, key):
            setattr(doctor, key, val)
    doctor.updatedAt = datetime.now()  # Bug #5 fixed: stamp the update time
    session.commit()
    session.refresh(doctor)
    return doctor
