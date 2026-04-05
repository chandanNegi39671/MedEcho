from fastapi import APIRouter, Depends, HTTPException, Body
from sqlmodel import Session, select
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from database import get_session
from models import Visit, EMR, DiseaseRisk, Patient

router = APIRouter(prefix="/visits", tags=["visits"])


class DiseaseRiskData(BaseModel):
    fluProbability: float
    migraineProbability: float
    fatigueProbability: float
    diabetesProbability: float = 0.0
    hypertensionProbability: float = 0.0
    notes: Optional[str] = None


class CreateVisitRequest(BaseModel):
    patientId: str
    transcript: str
    audioUrl: Optional[str] = None
    language: Optional[str] = "en"
    emrData: dict
    diseaseRisk: DiseaseRiskData
    hallucinationWarning: bool = False
    hallucinationDetails: Optional[str] = None
    rougeScore: Optional[float] = None


@router.get("/", response_model=List[Visit])
def read_visits(patient_id: str, session: Session = Depends(get_session)):
    statement = (
        select(Visit)
        .where(Visit.patientId == patient_id)
        .order_by(Visit.visitDate.desc())
    )
    return session.exec(statement).all()


@router.post("/", response_model=Visit)
def create_visit(request: CreateVisitRequest, session: Session = Depends(get_session)):
    try:
        visit = Visit(
            patientId=request.patientId,
            transcript=request.transcript,
            audioUrl=request.audioUrl,
            language=request.language,
            status="CONFIRMED"
        )
        session.add(visit)
        session.commit()
        session.refresh(visit)

        emr_data = request.emrData
        emr = EMR(
            visitId=visit.id,
            chiefComplaint=emr_data.get("chiefComplaint"),
            hpi=emr_data.get("hpi"),
            pastHistory=emr_data.get("pastHistory"),
            medications=emr_data.get("medications", []),
            allergies=emr_data.get("allergies"),
            examFindings=emr_data.get("examFindings"),
            diagnosis=emr_data.get("diagnosis"),
            plan=emr_data.get("plan"),
            followUpDays=emr_data.get("followUpDays"),
            generatedByAI=True,
            editedByDoctor=False,
            hallucinationWarning=request.hallucinationWarning,
            hallucinationDetails=request.hallucinationDetails,
            rougeScore=request.rougeScore,
        )
        session.add(emr)

        risk_data = request.diseaseRisk
        risk = DiseaseRisk(
            visitId=visit.id,
            fluProbability=risk_data.fluProbability,
            migraineProbability=risk_data.migraineProbability,
            fatigueProbability=risk_data.fatigueProbability,
            diabetesProbability=risk_data.diabetesProbability,
            hypertensionProbability=risk_data.hypertensionProbability,
            notes=risk_data.notes,
        )
        session.add(risk)

        session.commit()
        session.refresh(visit)
        return visit

    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{visit_id}")
def read_visit(visit_id: str, session: Session = Depends(get_session)):
    visit = session.get(Visit, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    emr  = session.exec(select(EMR).where(EMR.visitId == visit_id)).first()
    risk = session.exec(select(DiseaseRisk).where(DiseaseRisk.visitId == visit_id)).first()

    return {"visit": visit, "emr": emr, "diseaseRisk": risk}


@router.patch("/{visit_id}/emr")
def update_emr(
    visit_id: str,
    updates: dict = Body(...),         # Bug #6 fixed: Body() for correct JSON body parsing
    session: Session = Depends(get_session)
):
    """Doctor edits the AI-generated EMR. Tracks that it was edited."""
    emr = session.exec(select(EMR).where(EMR.visitId == visit_id)).first()
    if not emr:
        raise HTTPException(status_code=404, detail="EMR not found")

    for key, val in updates.items():
        if hasattr(emr, key):
            setattr(emr, key, val)

    emr.editedByDoctor = True
    emr.updatedAt = datetime.now()     # Bug #5 fixed: stamp the update time
    session.commit()
    session.refresh(emr)
    return emr
