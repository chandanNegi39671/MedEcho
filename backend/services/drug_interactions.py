"""
Drug Interaction Checker
─────────────────────────
Checks for dangerous drug interactions using:
1. OpenFDA API (free, no key needed)
2. Local rule-based common Indian drug interactions

Usage:
    result = check_drug_interactions(["Metformin 500mg BD", "Alcohol"])
"""

import re
import httpx
from typing import List, Optional

# ── Common dangerous interactions (Indian clinic context) ─────
LOCAL_INTERACTIONS = [
    {
        "drugs":    ["warfarin", "aspirin"],
        "severity": "🔴 CRITICAL",
        "message":  "Warfarin + Aspirin — major bleeding risk. Avoid combination.",
    },
    {
        "drugs":    ["metformin", "alcohol"],
        "severity": "🔴 CRITICAL",
        "message":  "Metformin + Alcohol — lactic acidosis risk.",
    },
    {
        "drugs":    ["ace inhibitor", "potassium", "spironolactone"],
        "severity": "🟡 WARNING",
        "message":  "ACE inhibitor + Potassium-sparing diuretic — hyperkalemia risk.",
    },
    {
        "drugs":    ["ramipril", "spironolactone"],
        "severity": "🟡 WARNING",
        "message":  "Ramipril + Spironolactone — hyperkalemia risk. Monitor K+.",
    },
    {
        "drugs":    ["methotrexate", "nsaid"],
        "severity": "🔴 CRITICAL",
        "message":  "Methotrexate + NSAIDs — methotrexate toxicity risk.",
    },
    {
        "drugs":    ["methotrexate", "ibuprofen"],
        "severity": "🔴 CRITICAL",
        "message":  "Methotrexate + Ibuprofen — methotrexate toxicity risk.",
    },
    {
        "drugs":    ["sildenafil", "nitrate"],
        "severity": "🔴 CRITICAL",
        "message":  "Sildenafil + Nitrates — severe hypotension risk.",
    },
    {
        "drugs":    ["ssri", "tramadol"],
        "severity": "🔴 CRITICAL",
        "message":  "SSRI + Tramadol — serotonin syndrome risk.",
    },
    {
        "drugs":    ["sertraline", "tramadol"],
        "severity": "🔴 CRITICAL",
        "message":  "Sertraline + Tramadol — serotonin syndrome risk.",
    },
    {
        "drugs":    ["ciprofloxacin", "antacid"],
        "severity": "🟡 WARNING",
        "message":  "Ciprofloxacin + Antacids — reduced antibiotic absorption. Give 2hr apart.",
    },
    {
        "drugs":    ["atorvastatin", "clarithromycin"],
        "severity": "🟡 WARNING",
        "message":  "Atorvastatin + Clarithromycin — increased statin levels, myopathy risk.",
    },
    {
        "drugs":    ["digoxin", "amiodarone"],
        "severity": "🔴 CRITICAL",
        "message":  "Digoxin + Amiodarone — digoxin toxicity risk. Reduce digoxin dose.",
    },
    {
        "drugs":    ["lithium", "nsaid"],
        "severity": "🔴 CRITICAL",
        "message":  "Lithium + NSAIDs — lithium toxicity risk.",
    },
    {
        "drugs":    ["carbimazole", "warfarin"],
        "severity": "🟡 WARNING",
        "message":  "Carbimazole + Warfarin — altered anticoagulation effect. Monitor INR.",
    },
]

# Drug class mapping for local rules
DRUG_CLASS_MAP = {
    "nsaid":         ["ibuprofen", "diclofenac", "naproxen", "aspirin", "ketorolac"],
    "ssri":          ["sertraline", "fluoxetine", "escitalopram", "paroxetine"],
    "ace inhibitor": ["ramipril", "enalapril", "lisinopril", "perindopril"],
    "nitrate":       ["nitroglycerine", "isosorbide", "sorbitrate"],
    "antacid":       ["pantoprazole", "omeprazole", "ranitidine", "antacid", "gelusil"],
}


def _extract_drug_names(medications) -> List[str]:
    """Extract clean drug names from medication strings."""
    if not medications:
        return []

    if isinstance(medications, str):
        medications = [medications]

    drug_names = []
    for med in medications:
        med_str = str(med).lower()
        # Remove dose/frequency — keep drug name only
        name = re.sub(r'\d+\s*(?:mg|ml|mcg|g|iu|units?)', '', med_str)
        name = re.sub(r'\b(?:tab|tablet|cap|capsule|syrup|inj|injection|drops?|oint)\b', '', name)
        name = re.sub(r'\b(?:od|bd|tds|qid|sos|stat|prn|daily|times?|days?|weeks?)\b', '', name)
        name = name.strip().split()[0] if name.strip() else ""
        if name and len(name) > 2:
            drug_names.append(name)

    return drug_names


def _expand_drug_classes(drug_names: List[str]) -> List[str]:
    """Add drug class labels for class-based interaction checks."""
    expanded = list(drug_names)
    for drug_class, members in DRUG_CLASS_MAP.items():
        for drug in drug_names:
            if any(member in drug for member in members):
                if drug_class not in expanded:
                    expanded.append(drug_class)
    return expanded


def _check_local_interactions(drug_names: List[str]) -> List[dict]:
    """Check against local rule database."""
    found = []
    expanded = _expand_drug_classes(drug_names)

    for rule in LOCAL_INTERACTIONS:
        rule_drugs = rule["drugs"]
        # Check if ALL drugs in the rule are present
        if all(any(rd in d for d in expanded) for rd in rule_drugs):
            found.append({
                "drugs":    rule["drugs"],
                "severity": rule["severity"],
                "message":  rule["message"],
                "source":   "local_rules",
            })

    return found


def _check_openfda(drug1: str, drug2: str) -> Optional[dict]:
    """Check OpenFDA drug interaction API."""
    try:
        url = (
            f"https://api.fda.gov/drug/label.json"
            f"?search=drug_interactions:{drug1}+AND+drug_interactions:{drug2}"
            f"&limit=1"
        )
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url)

        if resp.status_code == 200:
            data = resp.json()
            if data.get("results"):
                interaction_text = data["results"][0].get("drug_interactions", [""])[0]
                if interaction_text and drug2.lower() in interaction_text.lower():
                    return {
                        "drugs":    [drug1, drug2],
                        "severity": "🟡 WARNING",
                        "message":  interaction_text[:200] + "...",
                        "source":   "openFDA",
                    }
    except Exception:
        pass  # OpenFDA timeout — local rules already checked
    return None


def check_drug_interactions(medications) -> dict:
    """
    Main function — check all drug interactions.

    Args:
        medications: list of medication strings OR single string
                     e.g. ["Metformin 500mg BD", "Aspirin 75mg OD"]

    Returns:
        {
            "hasInteractions": bool,
            "hasCritical": bool,
            "interactions": [...],
            "drugsChecked": [...]
        }
    """
    drug_names = _extract_drug_names(medications)

    if len(drug_names) < 2:
        return {
            "hasInteractions": False,
            "hasCritical":     False,
            "interactions":    [],
            "drugsChecked":    drug_names,
            "message":         "Need at least 2 drugs to check interactions.",
        }

    # Local rules first (fast)
    interactions = _check_local_interactions(drug_names)

    # OpenFDA for pairs not caught locally (only first 3 pairs to avoid timeout)
    checked_pairs = set()
    for i, d1 in enumerate(drug_names[:4]):
        for d2 in drug_names[i+1:4]:
            pair = tuple(sorted([d1, d2]))
            if pair not in checked_pairs:
                checked_pairs.add(pair)
                fda_result = _check_openfda(d1, d2)
                if fda_result:
                    # Don't duplicate local results
                    already_found = any(
                        d1 in str(x["drugs"]) and d2 in str(x["drugs"])
                        for x in interactions
                    )
                    if not already_found:
                        interactions.append(fda_result)

    has_critical = any(i["severity"] == "🔴 CRITICAL" for i in interactions)

    return {
        "hasInteractions": len(interactions) > 0,
        "hasCritical":     has_critical,
        "interactions":    interactions,
        "drugsChecked":    drug_names,
        "interactionCount": len(interactions),
    }
