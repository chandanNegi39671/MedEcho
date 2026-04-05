"""
Share Engine
─────────────
Builds a sanitised patient record summary package for cross-doctor sharing.

What IS shared:
  - Patient demographics (name, age, gender, ABHA ID)
  - Last 5 visit summaries (date, diagnosis, medications, disease risk trend)
  - Recurring symptoms / patterns from analytics

What is NOT shared:
  - Raw audio files (deleted after 30 min anyway)
  - Raw transcripts (private conversation)
  - Hallucination warnings (internal quality metric, not clinical)
  - Doctor's personal notes / edits

The sharing is READ-ONLY — the receiving doctor cannot modify the previous
doctor's records.
"""

from typing import Optional
from datetime import datetime
from sqlmodel import Session, select

from models import Patient, Visit, EMR, DiseaseRisk, ConsentLog


MAX_VISITS_TO_SHARE = 5   # Last N visits shared


def build_patient_summary(
    session:    Session,
    patient_id: str,
    consent_id: str,
) -> Optional[dict]:
    """
    Build a shareable patient record package.

    Args:
        session:    DB session
        patient_id: Patient whose records to share
        consent_id: ConsentLog ID proving patient consented

    Returns:
        Sanitised summary dict, or None if consent is invalid/revoked
    """
    # Verify consent exists and is not revoked
    consent = session.get(ConsentLog, consent_id)
    if not consent:
        return None
    if consent.revokedAt is not None:
        return None
    if consent.consentType != "sharing":
        return None
    if consent.patientId != patient_id:
        return None

    # Get patient
    patient = session.get(Patient, patient_id)
    if not patient:
        return None

    # Get last N visits (most recent first)
    visits = session.exec(
        select(Visit)
        .where(Visit.patientId == patient_id)
        .order_by(Visit.visitDate.desc())
        .limit(MAX_VISITS_TO_SHARE)
    ).all()

    visit_summaries = []
    all_diagnoses   = []
    risk_trend      = []

    for visit in visits:
        emr  = session.exec(select(EMR).where(EMR.visitId == visit.id)).first()
        risk = session.exec(select(DiseaseRisk).where(DiseaseRisk.visitId == visit.id)).first()

        summary = {
            "visitDate":      visit.visitDate.strftime("%d %b %Y"),
            "language":       visit.language,
            "diagnosis":      emr.diagnosis      if emr else None,
            "chiefComplaint": emr.chiefComplaint if emr else None,
            "medications":    emr.medications    if emr else [],
            "plan":           emr.plan           if emr else None,
            "followUpDays":   emr.followUpDays   if emr else None,
            "examFindings":   emr.examFindings   if emr else None,
            "pastHistory":    emr.pastHistory    if emr else None,
            "allergies":      emr.allergies      if emr else None,
            # Intentionally excluded: transcript, raw audio, hallucinationWarning,
            # doctorEdits, rougeScore (internal metrics)
        }

        if emr and emr.diagnosis:
            all_diagnoses.append(emr.diagnosis)

        if risk:
            risk_trend.append({
                "date":         visit.visitDate.strftime("%Y-%m-%d"),
                "diabetes":     risk.diabetesProbability,
                "hypertension": risk.hypertensionProbability,
                "flu":          risk.fluProbability,
                "migraine":     risk.migraineProbability,
                "fatigue":      risk.fatigueProbability,
            })

        visit_summaries.append(summary)

    # Build recurring conditions summary
    from collections import Counter
    diagnosis_freq = Counter(all_diagnoses).most_common(3)

    return {
        "sharedAt":     datetime.now().isoformat(),
        "consentId":    consent_id,
        "totalVisitsShared": len(visits),
        "note":         "READ ONLY — These records are from the patient's previous doctor. "
                        "You cannot edit them.",

        # Patient demographics
        "patient": {
            "name":      patient.name,
            "age":       patient.age,
            "gender":    patient.gender,
            "abhaId":    patient.abhaId,
            "bloodGroup": patient.bloodGroup,
            "address":   patient.address,
            # Excluded: phone (privacy), internal notes
        },

        # Clinical history
        "visitHistory":      visit_summaries,
        "topDiagnoses":      [{"diagnosis": d, "count": c} for d, c in diagnosis_freq],
        "diseaseRiskTrend":  risk_trend,

        # Warnings for receiving doctor
        "importantFlags": _build_flags(visit_summaries),
    }


def _build_flags(visits: list) -> list:
    """
    Build clinical alert flags for the receiving doctor.
    E.g. known allergies, chronic conditions, high-risk scores.
    """
    flags = []

    # Check allergies across visits
    allergies = set()
    for v in visits:
        a = v.get("allergies")
        if a and a.upper() != "NKDA" and a.lower() != "none":
            allergies.add(a)
    if allergies:
        flags.append({
            "type":    "ALLERGY",
            "message": f"Known allergies: {', '.join(allergies)}",
            "level":   "HIGH",
        })

    # Check for chronic conditions in past history
    chronic_keywords = ["diabetes", "hypertension", "asthma", "epilepsy", "thyroid", "copd"]
    chronic_found = set()
    for v in visits:
        ph = (v.get("pastHistory") or "").lower()
        for kw in chronic_keywords:
            if kw in ph:
                chronic_found.add(kw.capitalize())
    if chronic_found:
        flags.append({
            "type":    "CHRONIC_CONDITION",
            "message": f"Chronic conditions on record: {', '.join(chronic_found)}",
            "level":   "MEDIUM",
        })

    return flags
