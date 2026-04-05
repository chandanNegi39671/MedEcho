"""
QR Generator Service
─────────────────────
Generates HMAC-signed QR codes for doctor clinic registration.

Each doctor gets one persistent QR code.
The QR encodes a signed URL so it cannot be forged.

Usage:
    png_bytes = generate_doctor_qr(doctor_id, "https://mediscribe.app")
    # Returns PNG bytes → store in DB or serve directly
"""

import hmac
import hashlib
import os
from io import BytesIO
from typing import Tuple

import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer

# Secret key for HMAC signing — load from env in production
QR_SECRET = os.getenv("QR_SECRET_KEY", "mediscribe-qr-secret-change-in-prod").encode()

FRONTEND_BASE = os.getenv("FRONTEND_URL", "http://localhost:3000")


def _make_token(doctor_id: str) -> str:
    """Generate a 16-char HMAC token for a doctor ID."""
    return hmac.new(QR_SECRET, doctor_id.encode(), hashlib.sha256).hexdigest()[:16]


def verify_qr_token(doctor_id: str, token: str) -> bool:
    """Verify that a QR token is valid for a doctor ID."""
    expected = _make_token(doctor_id)
    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(expected, token)


def generate_doctor_qr(doctor_id: str) -> Tuple[bytes, str]:
    """
    Generate a signed QR code PNG for a doctor.

    Returns:
        (png_bytes, scan_url) — PNG image bytes and the URL encoded in the QR

    The scan URL looks like:
        https://mediscribe.app/register?doc=<doctorId>&t=<hmac_token>

    When patient scans it, the frontend calls POST /qr/scan with doctorId + token.
    Backend verifies the token before processing.
    """
    token    = _make_token(doctor_id)
    scan_url = f"{FRONTEND_BASE}/register?doc={doctor_id}&t={token}"

    qr = qrcode.QRCode(
        version=2,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(scan_url)
    qr.make(fit=True)

    # Blue QR code on white background
    try:
        img = qr.make_image(
            image_factory=StyledPilImage,
            module_drawer=RoundedModuleDrawer(),
            fill_color="#1A73E8",
            back_color="white",
        )
    except Exception:
        # Fallback if styled image fails
        img = qr.make_image(fill_color="#1A73E8", back_color="white")

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), scan_url
