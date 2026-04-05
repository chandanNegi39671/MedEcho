"""
Analytics Router
─────────────────
Longitudinal patient intelligence — the feature that turns MediScribe
from a simple scribe into a clinical intelligence tool.

Endpoints:
  GET /analytics/patients/{id}/timeline     — Full visit history with trends
  GET /analytics/patients/{id}/symptoms     — Recurring symptom patterns
  GET /analytics/patients/{id}/risk-trend   — Disease risk trend over time
  GET /analytics/doctors/{id}/summary       — Doctor's clinic overview
  GET /analytics/benchmark                  — ROUGE benchmark vs Eka dataset
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List
from collections import Counter
import re

from database import get_session
from models import Patient, Visit, EMR, DiseaseRisk, Doctor

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _extract_keywords(text: str) -> List[str]:
    """Simple keyword extractor for symptoms from free text."""
    if not text:
        return []
    SYMPTOM_KEYWORDS = [
        "headache", "fever", "cough", "nausea", "vomiting", "pain", "fatigue",
        "dizziness", "breathlessness", "chest pain", "back pain", "weakness",
        "swelling", "rash", "itching", "cold", "sore throat", "diarrhea",
        "constipation", "burning", "anxiety", "insomnia", "loss of appetite",
        # Hindi transliterations
        "bukhaar", "sir dard", "khaasi", "dard", "thakaan", "chakkar",
    ]
    found = []
    text_lower = text.lower()
    for kw in SYMPTOM_KEYWORDS:
        if kw in text_lower:
            found.append(kw)
    return found


@router.get("/patients/{patient_id}/timeline")
def patient_timeline(patient_id: str, session: Session = Depends(get_session)):
    """
    Full longitudinal timeline for a patient.
    Returns every visit with its EMR and risk data — sorted newest first.
    """
    patient = session.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    visits = session.exec(
        select(Visit)
        .where(Visit.patientId == patient_id)
        .order_by(Visit.visitDate.desc())
    ).all()

    timeline = []
    for visit in visits:
        emr  = session.exec(select(EMR).where(EMR.visitId == visit.id)).first()
        risk = session.exec(select(DiseaseRisk).where(DiseaseRisk.visitId == visit.id)).first()
        timeline.append({
            "visitId":    visit.id,
            "visitDate":  visit.visitDate,
            "language":   visit.language,
            "status":     visit.status,
            "diagnosis":  emr.diagnosis if emr else None,
            "chiefComplaint": emr.chiefComplaint if emr else None,
            "medications": emr.medications if emr else [],
            "diseaseRisk": {
                "flu":          risk.fluProbability if risk else 0,
                "migraine":     risk.migraineProbability if risk else 0,
                "fatigue":      risk.fatigueProbability if risk else 0,
                "diabetes":     risk.diabetesProbability if risk else 0,
                "hypertension": risk.hypertensionProbability if risk else 0,
            } if risk else None,
        })

    return {
        "patient":       patient,
        "totalVisits":   len(visits),
        "timeline":      timeline,
    }


@router.get("/patients/{patient_id}/symptoms")
def recurring_symptoms(patient_id: str, session: Session = Depends(get_session)):
    """
    Detect recurring symptom patterns across all visits.
    Key insight for chronic condition detection.
    """
    patient = session.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    visits = session.exec(select(Visit).where(Visit.patientId == patient_id)).all()

    all_symptoms = []
    diagnoses    = []
    for visit in visits:
        emr = session.exec(select(EMR).where(EMR.visitId == visit.id)).first()
        if emr:
            all_symptoms.extend(_extract_keywords(emr.chiefComplaint or ""))
            all_symptoms.extend(_extract_keywords(emr.hpi or ""))
            if emr.diagnosis:
                diagnoses.append(emr.diagnosis)

    symptom_freq = Counter(all_symptoms).most_common(10)
    diagnosis_freq = Counter(diagnoses).most_common(5)

    # Flag recurring issues (appearing in >30% of visits)
    total = len(visits)
    recurring_flags = [
        {"symptom": sym, "count": cnt, "visitPercent": round(cnt / total * 100)}
        for sym, cnt in symptom_freq
        if total > 0 and cnt / total > 0.3
    ]

    return {
        "patientId":      patient_id,
        "totalVisits":    total,
        "topSymptoms":    [{"symptom": s, "count": c} for s, c in symptom_freq],
        "topDiagnoses":   [{"diagnosis": d, "count": c} for d, c in diagnosis_freq],
        "recurringFlags": recurring_flags,
        "insight": f"Recurring symptoms detected in {len(recurring_flags)} categories" if recurring_flags else "No strong recurring patterns found",
    }


@router.get("/patients/{patient_id}/risk-trend")
def risk_trend(patient_id: str, session: Session = Depends(get_session)):
    """
    Disease risk probability trend over time.
    Shows if a patient's risk is increasing or decreasing across visits.
    """
    visits = session.exec(
        select(Visit)
        .where(Visit.patientId == patient_id)
        .order_by(Visit.visitDate.asc())
    ).all()

    trend = []
    for visit in visits:
        risk = session.exec(
            select(DiseaseRisk).where(DiseaseRisk.visitId == visit.id)
        ).first()
        if risk:
            trend.append({
                "date":         visit.visitDate.strftime("%Y-%m-%d"),
                "flu":          risk.fluProbability,
                "migraine":     risk.migraineProbability,
                "fatigue":      risk.fatigueProbability,
                "diabetes":     risk.diabetesProbability,
                "hypertension": risk.hypertensionProbability,
            })

    # Simple trend direction: compare last 2 entries
    direction = {}
    if len(trend) >= 2:
        last, prev = trend[-1], trend[-2]
        for condition in ["flu", "migraine", "fatigue", "diabetes", "hypertension"]:
            diff = last[condition] - prev[condition]
            direction[condition] = "↑ increasing" if diff > 0.05 else "↓ decreasing" if diff < -0.05 else "→ stable"

    return {
        "patientId": patient_id,
        "trend":     trend,
        "direction": direction,
    }


@router.get("/doctors/{doctor_id}/summary")
def doctor_summary(doctor_id: str, session: Session = Depends(get_session)):
    """
    Clinic-level summary for a doctor — total patients, visits, language distribution.
    """
    doctor = session.exec(
        select(Doctor).where(Doctor.id == doctor_id)
    ).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    patients = session.exec(
        select(Patient).where(Patient.doctorId == doctor_id)
    ).all()
    patient_ids = [p.id for p in patients]

    all_visits = []
    for pid in patient_ids:
        visits = session.exec(select(Visit).where(Visit.patientId == pid)).all()
        all_visits.extend(visits)

    lang_counter = Counter(v.language or "en" for v in all_visits)
    total_visits = len(all_visits)

    return {
        "doctorName":       doctor.name,
        "clinicName":       doctor.clinicName,
        "totalPatients":    len(patients),
        "totalVisits":      total_visits,
        "languageBreakdown": dict(lang_counter),
        "avgVisitsPerPatient": round(total_visits / len(patients), 1) if patients else 0,
    }


@router.get("/benchmark")
def get_benchmark_info():
    """
    Returns benchmark context for the Eka dataset comparison.
    Run evaluation/benchmark.py to get actual scores.
    """
    return {
        "dataset":    "Eka Clinical Note Generation Dataset",
        "source":     "https://huggingface.co/datasets/ekacare/clinical_note_generation_dataset",
        "publishedBenchmark": 0.72,
        "metric":     "ROUGE-1 F1",
        "languages":  ["English", "Hindi", "Marathi"],
        "howToRun":   "python -m evaluation.benchmark --samples 20",
        "note":       "Run the benchmark script to get your actual score vs the 0.72 baseline",
    }
