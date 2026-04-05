from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from services.emr_router import generate_emr, get_model_status
from services.rouge_evaluator import evaluate_emr_against_ground_truth
from services.abnormal_alerts import check_abnormal_values
from services.drug_interactions import check_drug_interactions
from services.hindi_emr import emr_to_hindi, emr_bilingual

router = APIRouter(prefix="/generate-emr", tags=["emr"])


class GenerateEMRRequest(BaseModel):
    transcript: str
    language:   Optional[str] = "en"
    model:      Optional[str] = "auto"
    outputLang: Optional[str] = "en"   # "en" | "hi" | "bilingual"


class EvaluateEMRRequest(BaseModel):
    transcript:  str
    groundTruth: dict
    language:    Optional[str] = "en"
    model:       Optional[str] = "auto"


@router.post("/")
async def generate_emr_endpoint(request: GenerateEMRRequest):
    """
    Generate structured EMR from a consultation transcript.
    Automatically checks abnormal values + drug interactions.
    Supports Hindi output via outputLang=hi
    """
    if not request.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript cannot be empty")
    try:
        # ── Generate EMR ──────────────────────────────────────
        emr = generate_emr(
            transcript=request.transcript,
            language=request.language or "en",
            model=request.model or "auto"
        )

        # ── Disease risk defaults ─────────────────────────────
        risk = emr.setdefault("diseaseRisk", {})
        for f in ["fluProbability", "migraineProbability", "fatigueProbability",
                  "diabetesProbability", "hypertensionProbability"]:
            risk.setdefault(f, 0.0)

        # ── Abnormal value alerts ─────────────────────────────
        emr["abnormalAlerts"] = check_abnormal_values(emr)

        # ── Drug interaction check ────────────────────────────
        emr["drugInteractions"] = check_drug_interactions(
            emr.get("medications", [])
        )

        # ── Hindi output if requested ─────────────────────────
        output_lang = request.outputLang or "en"
        if output_lang == "hi":
            emr = emr_to_hindi(emr)
        elif output_lang == "bilingual":
            emr = emr_bilingual(emr)

        return emr

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/evaluate")
async def evaluate_emr_endpoint(request: EvaluateEMRRequest):
    """Generate EMR and evaluate against ground truth using ROUGE."""
    if not request.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript cannot be empty")
    try:
        generated = generate_emr(
            transcript=request.transcript,
            language=request.language or "en",
            model=request.model or "auto"
        )
        rouge = evaluate_emr_against_ground_truth(generated, request.groundTruth)
        return {"generatedEMR": generated, "rougeEvaluation": rouge}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models")
def model_status():
    """Returns which models are available and their benchmark scores."""
    return get_model_status()
