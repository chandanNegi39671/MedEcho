from typing import Optional, List
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import Column, String, JSON
from sqlalchemy.dialects.postgresql import ARRAY
import uuid


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Doctor(SQLModel, table=True):
    __tablename__ = "doctors"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    clerkId: str = Field(unique=True, index=True)
    name: str
    phone: Optional[str] = None
    clinicName: Optional[str] = None
    city: Optional[str] = None
    preferredLanguage: Optional[str] = Field(default="en")
    createdAt: datetime = Field(default_factory=datetime.now)
    updatedAt: datetime = Field(default_factory=datetime.now)

    patients: List["Patient"] = Relationship(back_populates="doctor")
    qr_code: Optional["QRCode"] = Relationship(back_populates="doctor")


class Patient(SQLModel, table=True):
    __tablename__ = "patients"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    doctorId: str = Field(foreign_key="doctors.id", index=True)
    name: str
    phone: Optional[str] = Field(default=None, index=True)
    age: Optional[int] = None
    gender: Optional[str] = None
    abhaId: Optional[str] = Field(default=None, index=True)   # indexed for fast QR-scan lookup
    bloodGroup: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.now)
    updatedAt: datetime = Field(default_factory=datetime.now)

    doctor: Doctor = Relationship(back_populates="patients")
    visits: List["Visit"] = Relationship(back_populates="patient")
    consent_logs: List["ConsentLog"] = Relationship(back_populates="patient")
    share_consents_given: List["PatientShareConsent"] = Relationship(
        back_populates="patient",
        sa_relationship_kwargs={"foreign_keys": "[PatientShareConsent.patientId]"}
    )


class Visit(SQLModel, table=True):
    __tablename__ = "visits"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    patientId: str = Field(foreign_key="patients.id", index=True)
    visitDate: datetime = Field(default_factory=datetime.now)
    status: str = Field(default="DRAFT")   # DRAFT, CONFIRMED, EXPORTED

    audioUrl: Optional[str] = None
    audioDuration: Optional[int] = None
    transcript: Optional[str] = None
    language: Optional[str] = Field(default="en")

    createdAt: datetime = Field(default_factory=datetime.now)
    updatedAt: datetime = Field(default_factory=datetime.now)

    patient: Patient = Relationship(back_populates="visits")
    emr: Optional["EMR"] = Relationship(back_populates="visit")
    disease_risks: Optional["DiseaseRisk"] = Relationship(back_populates="visit")


class EMR(SQLModel, table=True):
    __tablename__ = "emrs"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    visitId: str = Field(foreign_key="visits.id", unique=True)

    chiefComplaint: Optional[str] = None
    hpi: Optional[str] = None
    pastHistory: Optional[str] = None
    medications: List[str] = Field(default=[], sa_column=Column(ARRAY(String)))
    allergies: Optional[str] = None
    examFindings: Optional[str] = None
    diagnosis: Optional[str] = None
    plan: Optional[str] = None
    followUpDays: Optional[int] = None

    generatedByAI: bool = Field(default=True)
    editedByDoctor: bool = Field(default=False)
    doctorEdits: Optional[str] = None
    hallucinationWarning: Optional[bool] = Field(default=False)
    hallucinationDetails: Optional[str] = None
    rougeScore: Optional[float] = None

    createdAt: datetime = Field(default_factory=datetime.now)
    updatedAt: datetime = Field(default_factory=datetime.now)

    visit: Visit = Relationship(back_populates="emr")


class DiseaseRisk(SQLModel, table=True):
    __tablename__ = "disease_risks"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    visitId: str = Field(foreign_key="visits.id", unique=True)

    fluProbability: float = Field(default=0.0)
    migraineProbability: float = Field(default=0.0)
    fatigueProbability: float = Field(default=0.0)
    diabetesProbability: float = Field(default=0.0)
    hypertensionProbability: float = Field(default=0.0)
    notes: Optional[str] = None

    createdAt: datetime = Field(default_factory=datetime.now)

    visit: Visit = Relationship(back_populates="disease_risks")


# ═══════════════════════════════════════════════════════════════════════════════
# NEW MODELS — QR System, Sharing, Consent
# ═══════════════════════════════════════════════════════════════════════════════

class QRCode(SQLModel, table=True):
    """One QR code per doctor — links their clinic to patient registration."""
    __tablename__ = "qr_codes"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    doctorId: str = Field(foreign_key="doctors.id", unique=True, index=True)
    scanUrl: str                          # The signed URL encoded in the QR
    scanCount: int = Field(default=0)     # How many patients have scanned it
    createdAt: datetime = Field(default_factory=datetime.now)

    doctor: Optional[Doctor] = Relationship(back_populates="qr_code")


class ConsentLog(SQLModel, table=True):
    """
    Audit log of every patient consent event.
    Required by DPDP Act 2023 and IT Act 2000 for legal compliance.
    """
    __tablename__ = "consent_logs"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    patientId: str = Field(foreign_key="patients.id", index=True)
    doctorId: str = Field(foreign_key="doctors.id", index=True)

    # "recording" | "sharing" | "qr_register"
    consentType: str

    ipAddress: Optional[str] = None       # Patient's IP at time of consent
    extraData: Optional[str] = None       # JSON string for context

    consentAt: datetime = Field(default_factory=datetime.now)
    revokedAt: Optional[datetime] = None  # Set when patient withdraws consent

    patient: Optional[Patient] = Relationship(back_populates="consent_logs")


class PatientShareConsent(SQLModel, table=True):
    """
    Records that a patient has consented to share their records
    from one doctor to another.
    """
    __tablename__ = "patient_share_consents"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    patientId:    str = Field(foreign_key="patients.id", index=True)
    fromDoctorId: str = Field(foreign_key="doctors.id", index=True)
    toDoctorId:   str = Field(foreign_key="doctors.id", index=True)
    consentLogId: str = Field(foreign_key="consent_logs.id")

    revoked:   bool = Field(default=False)
    revokedAt: Optional[datetime] = None
    createdAt: datetime = Field(default_factory=datetime.now)

    patient: Optional[Patient] = Relationship(
        back_populates="share_consents_given",
        sa_relationship_kwargs={"foreign_keys": "[PatientShareConsent.patientId]"}
    )
