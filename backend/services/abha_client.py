"""
ABHA / Aadhaar Client
──────────────────────
Interfaces with India's Ayushman Bharat Digital Mission (ABDM) Sandbox API
to verify ABHA IDs and fetch patient demographic data.

Sandbox docs: https://sandbox.abdm.gov.in/docs
Production:   https://healthidsbx.abdm.gov.in

Flow:
  1. POST /v1/search/searchByHealthId   → check if ABHA ID exists
  2. POST /v1/search/searchByMobile     → fallback search by phone
  3. GET  /v1/account/getByHealthId     → fetch full profile (name, dob, gender, address)

Set ABDM_CLIENT_ID and ABDM_CLIENT_SECRET in .env for sandbox credentials.
Register at: https://sandbox.abdm.gov.in/register

If ABDM keys are not configured, the client returns a "manual entry" fallback
so the app works without NHA integration during development.
"""

import os
import httpx
from typing import Optional
from pydantic_settings import BaseSettings


class ABDMSettings(BaseSettings):
    ABDM_CLIENT_ID:     str = ""
    ABDM_CLIENT_SECRET: str = ""
    ABDM_BASE_URL:      str = "https://healthidsbx.abdm.gov.in/api"

    class Config:
        env_file = ".env"


abdm_settings = ABDMSettings()

ABDM_CONFIGURED = bool(
    abdm_settings.ABDM_CLIENT_ID and abdm_settings.ABDM_CLIENT_SECRET
)


async def _get_abdm_token() -> Optional[str]:
    """Get bearer token from ABDM gateway."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{abdm_settings.ABDM_BASE_URL}/v1/sessions",
                json={
                    "clientId":     abdm_settings.ABDM_CLIENT_ID,
                    "clientSecret": abdm_settings.ABDM_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            return resp.json().get("accessToken")
    except Exception as e:
        print(f"[ABHA] Token fetch failed: {e}")
        return None


async def fetch_patient_by_abha_id(abha_id: str) -> Optional[dict]:
    """
    Fetch patient demographics from ABDM using ABHA ID.

    Args:
        abha_id: Patient's ABHA ID (e.g. "12-3456-7890-1234" or "user@abdm")

    Returns:
        dict with keys: name, dob, gender, mobile, address, abhaId
        or None if not found / ABDM not configured
    """
    if not ABDM_CONFIGURED:
        print("[ABHA] ABDM not configured — returning None (manual entry required)")
        return None

    token = await _get_abdm_token()
    if not token:
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{abdm_settings.ABDM_BASE_URL}/v1/account/getByHealthId",
                params={"healthId": abha_id},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Token":       f"Bearer {token}",
                    "Accept":        "application/json",
                },
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()

        return {
            "abhaId":  abha_id,
            "name":    f"{data.get('firstName', '')} {data.get('lastName', '')}".strip(),
            "dob":     data.get("dayOfBirth", "") + "/" + data.get("monthOfBirth", "") + "/" + data.get("yearOfBirth", ""),
            "gender":  data.get("gender"),           # M / F / O
            "mobile":  data.get("mobile"),
            "address": data.get("address"),
            "state":   data.get("stateName"),
            "district":data.get("districtName"),
        }
    except httpx.HTTPStatusError as e:
        print(f"[ABHA] HTTP error {e.response.status_code}: {e.response.text[:200]}")
        return None
    except Exception as e:
        print(f"[ABHA] Error: {e}")
        return None


async def verify_abha_id_exists(abha_id: str) -> bool:
    """Quick check — does this ABHA ID exist in the ABDM system?"""
    result = await fetch_patient_by_abha_id(abha_id)
    return result is not None


def parse_gender(abdm_gender: Optional[str]) -> Optional[str]:
    """Convert ABDM gender code to readable string."""
    mapping = {"M": "Male", "F": "Female", "O": "Other"}
    return mapping.get(abdm_gender or "", abdm_gender)
