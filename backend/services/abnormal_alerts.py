"""
Abnormal Value Alert Service
─────────────────────────────
Detects dangerous/abnormal clinical values from EMR examFindings.
Pure rule-based — no model needed.

Examples:
  BP 180/110  → 🔴 Hypertensive Crisis
  SpO2 88%    → 🔴 Critical hypoxia
  Glucose 400 → 🔴 Hyperglycaemic emergency
"""

import re
from typing import Optional

# ── Alert levels ──────────────────────────────────────────────
CRITICAL = "🔴 CRITICAL"
WARNING  = "🟡 WARNING"
NORMAL   = "🟢 NORMAL"


# ── Vital sign extractors ─────────────────────────────────────
def _extract_bp(text: str):
    """Extract systolic/diastolic from text like 'BP 150/90'"""
    m = re.search(r'bp\s*[:\-]?\s*(\d{2,3})\s*/\s*(\d{2,3})', text, re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _extract_spo2(text: str):
    """Extract SpO2 percentage"""
    m = re.search(r'spo2?\s*[:\-]?\s*(\d{2,3})\s*%?', text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _extract_temp(text: str):
    """Extract temperature in F"""
    m = re.search(r'temp(?:erature)?\s*[:\-]?\s*(\d{2,3}(?:\.\d)?)\s*[fF]?', text, re.IGNORECASE)
    return float(m.group(1)) if m else None


def _extract_pulse(text: str):
    """Extract pulse/heart rate"""
    m = re.search(r'(?:pulse|hr|heart rate)\s*[:\-]?\s*(\d{2,3})', text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _extract_glucose(text: str):
    """Extract blood glucose"""
    m = re.search(r'(?:glucose|sugar|fasting|rbs|ppbs)\s*[:\-]?\s*(\d{2,3})', text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _extract_hba1c(text: str):
    """Extract HbA1c"""
    m = re.search(r'hba1c\s*[:\-]?\s*(\d{1,2}(?:\.\d)?)', text, re.IGNORECASE)
    return float(m.group(1)) if m else None


# ── Alert rules ───────────────────────────────────────────────
def check_bp(systolic, diastolic) -> Optional[dict]:
    if systolic is None:
        return None
    if systolic >= 180 or diastolic >= 120:
        return {"field": "BP", "value": f"{systolic}/{diastolic}", "level": CRITICAL,
                "message": "Hypertensive Crisis — immediate intervention needed"}
    if systolic >= 160 or diastolic >= 100:
        return {"field": "BP", "value": f"{systolic}/{diastolic}", "level": WARNING,
                "message": "Grade 2 Hypertension — urgent review needed"}
    if systolic <= 90 or diastolic <= 60:
        return {"field": "BP", "value": f"{systolic}/{diastolic}", "level": CRITICAL,
                "message": "Hypotension — monitor closely"}
    return None


def check_spo2(spo2) -> Optional[dict]:
    if spo2 is None:
        return None
    if spo2 < 90:
        return {"field": "SpO2", "value": f"{spo2}%", "level": CRITICAL,
                "message": "Critical hypoxia — oxygen therapy needed immediately"}
    if spo2 < 94:
        return {"field": "SpO2", "value": f"{spo2}%", "level": WARNING,
                "message": "Low oxygen saturation — monitor and consider oxygen"}
    return None


def check_temp(temp) -> Optional[dict]:
    if temp is None:
        return None
    if temp >= 104:
        return {"field": "Temperature", "value": f"{temp}F", "level": CRITICAL,
                "message": "Hyperpyrexia — emergency cooling needed"}
    if temp >= 101:
        return {"field": "Temperature", "value": f"{temp}F", "level": WARNING,
                "message": "High fever — antipyretics and investigation needed"}
    if temp <= 96:
        return {"field": "Temperature", "value": f"{temp}F", "level": WARNING,
                "message": "Hypothermia — monitor closely"}
    return None


def check_pulse(pulse) -> Optional[dict]:
    if pulse is None:
        return None
    if pulse >= 150:
        return {"field": "Pulse", "value": f"{pulse}/min", "level": CRITICAL,
                "message": "Severe tachycardia — ECG needed urgently"}
    if pulse >= 100:
        return {"field": "Pulse", "value": f"{pulse}/min", "level": WARNING,
                "message": "Tachycardia — investigate cause"}
    if pulse <= 50:
        return {"field": "Pulse", "value": f"{pulse}/min", "level": WARNING,
                "message": "Bradycardia — ECG recommended"}
    return None


def check_glucose(glucose) -> Optional[dict]:
    if glucose is None:
        return None
    if glucose >= 400:
        return {"field": "Glucose", "value": f"{glucose} mg/dL", "level": CRITICAL,
                "message": "Severe hyperglycaemia — rule out DKA"}
    if glucose >= 200:
        return {"field": "Glucose", "value": f"{glucose} mg/dL", "level": WARNING,
                "message": "High blood sugar — medication review needed"}
    if glucose <= 60:
        return {"field": "Glucose", "value": f"{glucose} mg/dL", "level": CRITICAL,
                "message": "Hypoglycaemia — immediate glucose needed"}
    return None


def check_hba1c(hba1c) -> Optional[dict]:
    if hba1c is None:
        return None
    if hba1c >= 10:
        return {"field": "HbA1c", "value": f"{hba1c}%", "level": CRITICAL,
                "message": "Very poor glycaemic control — regimen change needed"}
    if hba1c >= 8:
        return {"field": "HbA1c", "value": f"{hba1c}%", "level": WARNING,
                "message": "Poor glycaemic control — medication adjustment needed"}
    return None


# ── Main function ─────────────────────────────────────────────
def check_abnormal_values(emr: dict) -> dict:
    """
    Scan EMR examFindings + hpi for abnormal values.
    Returns list of alerts with severity levels.

    Usage:
        alerts = check_abnormal_values(emr_dict)
    """
    # Combine all relevant text
    text = " ".join([
        str(emr.get("examFindings") or ""),
        str(emr.get("hpi") or ""),
        str(emr.get("chiefComplaint") or ""),
        str(emr.get("plan") or ""),
    ])

    alerts = []

    # Run all checks
    sys_bp, dia_bp = _extract_bp(text)
    checks = [
        check_bp(sys_bp, dia_bp),
        check_spo2(_extract_spo2(text)),
        check_temp(_extract_temp(text)),
        check_pulse(_extract_pulse(text)),
        check_glucose(_extract_glucose(text)),
        check_hba1c(_extract_hba1c(text)),
    ]

    alerts = [c for c in checks if c is not None]

    # Overall severity
    has_critical = any(a["level"] == CRITICAL for a in alerts)
    has_warning  = any(a["level"] == WARNING  for a in alerts)

    return {
        "hasAlerts":       len(alerts) > 0,
        "hasCritical":     has_critical,
        "overallSeverity": CRITICAL if has_critical else WARNING if has_warning else NORMAL,
        "alerts":          alerts,
        "alertCount":      len(alerts),
    }
