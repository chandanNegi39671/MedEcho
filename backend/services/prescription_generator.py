"""
Prescription Slip Generator
─────────────────────────────
Generates a clean A5 prescription slip (Rx) — what the patient takes to the pharmacy.

This is SEPARATE from the full clinical PDF (pdf_generator.py):
  - Clinical PDF  → Doctor's records, full EMR, risk scores
  - Prescription  → Patient-facing, medicines + dosage + follow-up only

Layout (A5 148mm × 210mm):
  ┌────────────────────────────┐
  │  🏥 Clinic Name            │
  │  Dr. Name  |  Reg No.      │
  │  Phone  |  Date            │
  ├────────────────────────────┤
  │  Rx  Patient: Name, Age    │
  │       ABHA: xxxx           │
  ├────────────────────────────┤
  │  MEDICINES                 │
  │  ┌──────┬────┬──────┬────┐ │
  │  │Drug  │Dose│Freq  │Days│ │
  │  └──────┴────┴──────┴────┘ │
  ├────────────────────────────┤
  │  ADVICE                    │
  │  - Rest, fluids, etc.      │
  ├────────────────────────────┤
  │  Follow-up: 3 days         │
  │  [Doctor Signature]        │
  └────────────────────────────┘
"""

from io import BytesIO
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A5
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)

# ── Colour palette ─────────────────────────────────────────────────────────────
BRAND_BLUE    = colors.HexColor("#1A73E8")
BRAND_LIGHT   = colors.HexColor("#E8F0FE")
DARK_TEXT     = colors.HexColor("#212121")
GRAY_TEXT     = colors.HexColor("#757575")
RX_GREEN      = colors.HexColor("#1A7A3A")
DIVIDER_COLOR = colors.HexColor("#CFD8DC")
MED_HEADER_BG = colors.HexColor("#37474F")
WARNING_BG    = colors.HexColor("#FFF8E1")
WARNING_BORDER= colors.HexColor("#F9A825")


def _parse_medication(med_str: str) -> dict:
    """
    Parse a medication string like 'Tab Paracetamol 500mg TDS x3 days'
    into structured fields for the table.
    """
    parts = med_str.strip().split()
    drug  = " ".join(parts[:3]) if len(parts) >= 3 else med_str

    # Extract frequency
    freq_map = {
        "OD": "Once daily", "BD": "Twice daily", "TDS": "3 times/day",
        "QID": "4 times/day", "SOS": "As needed", "STAT": "Immediately",
        "HS": "At bedtime", "AC": "Before meals", "PC": "After meals",
    }
    freq = "As directed"
    for key, val in freq_map.items():
        if key in med_str.upper():
            freq = val
            break

    # Extract duration
    duration = ""
    for part in parts:
        if part.lower().startswith("x") and any(c.isdigit() for c in part):
            duration = part.replace("x", "").replace("X", "") + " days"
            break

    # Instructions
    instructions = ""
    med_lower = med_str.lower()
    if "with food" in med_lower or "after meal" in med_lower or "pc" in med_lower:
        instructions = "After meals"
    elif "empty stomach" in med_lower or "before meal" in med_lower or "ac" in med_lower:
        instructions = "Before meals"
    elif "at night" in med_lower or "hs" in med_lower or "bedtime" in med_lower:
        instructions = "At bedtime"

    return {
        "drug":         drug,
        "frequency":    freq,
        "duration":     duration,
        "instructions": instructions,
    }


def generate_prescription_pdf(visit, patient, doctor, emr) -> BytesIO:
    """
    Generate an A5 prescription slip PDF.

    Args:
        visit:   Visit model instance
        patient: Patient model instance
        doctor:  Doctor model instance
        emr:     EMR model instance

    Returns:
        BytesIO buffer containing the PDF
    """
    buffer = BytesIO()
    W, H   = A5          # 148mm × 210mm

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A5,
        rightMargin=12*mm, leftMargin=12*mm,
        topMargin=10*mm,   bottomMargin=10*mm,
    )

    styles = getSampleStyleSheet()
    usable_w = W - 24*mm   # 148 - 24 = 124mm → in points ≈ 351

    # ── Custom styles ──────────────────────────────────────────────────────────
    s_clinic = ParagraphStyle("Clinic", parent=styles["Normal"],
        fontSize=13, textColor=BRAND_BLUE, fontName="Helvetica-Bold",
        alignment=TA_CENTER, spaceAfter=2)
    s_doctor = ParagraphStyle("Doctor", parent=styles["Normal"],
        fontSize=9, textColor=DARK_TEXT, alignment=TA_CENTER, spaceAfter=1)
    s_small  = ParagraphStyle("Small", parent=styles["Normal"],
        fontSize=8, textColor=GRAY_TEXT, alignment=TA_CENTER)
    s_rx     = ParagraphStyle("Rx", parent=styles["Normal"],
        fontSize=22, textColor=RX_GREEN, fontName="Helvetica-Bold",
        spaceAfter=2)
    s_label  = ParagraphStyle("Label", parent=styles["Normal"],
        fontSize=8, textColor=GRAY_TEXT)
    s_value  = ParagraphStyle("Value", parent=styles["Normal"],
        fontSize=10, textColor=DARK_TEXT, fontName="Helvetica-Bold")
    s_advice = ParagraphStyle("Advice", parent=styles["Normal"],
        fontSize=9, textColor=DARK_TEXT, leading=13)
    s_followup = ParagraphStyle("Followup", parent=styles["Normal"],
        fontSize=11, textColor=BRAND_BLUE, fontName="Helvetica-Bold",
        alignment=TA_CENTER)
    s_footer = ParagraphStyle("Footer", parent=styles["Normal"],
        fontSize=7, textColor=GRAY_TEXT, alignment=TA_CENTER)

    story = []
    PW = 351   # usable width in points (approx)

    # ── HEADER ─────────────────────────────────────────────────────────────────
    if doctor.clinicName:
        story.append(Paragraph(doctor.clinicName, s_clinic))
    story.append(Paragraph(f"Dr. {doctor.name}", s_doctor))
    if doctor.phone:
        story.append(Paragraph(f"📞 {doctor.phone}  |  Date: {visit.visitDate.strftime('%d %b %Y')}", s_small))
    story.append(Spacer(1, 3*mm))
    story.append(HRFlowable(width=PW, thickness=1.5, color=BRAND_BLUE))
    story.append(Spacer(1, 3*mm))

    # ── PATIENT INFO ───────────────────────────────────────────────────────────
    pt_rows = [
        [Paragraph("Patient", s_label),
         Paragraph(f"<b>{patient.name}</b>  |  {patient.age or '?'} yrs  |  {patient.gender or '?'}", s_value)],
    ]
    if patient.abhaId:
        pt_rows.append([
            Paragraph("ABHA ID", s_label),
            Paragraph(patient.abhaId, s_value),
        ])
    if emr.diagnosis:
        pt_rows.append([
            Paragraph("Diagnosis", s_label),
            Paragraph(f"<b>{emr.diagnosis}</b>", s_value),
        ])

    pt_table = Table(pt_rows, colWidths=[55, PW - 55])
    pt_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), BRAND_LIGHT),
        ("BOX",           (0, 0), (-1, -1), 1, BRAND_BLUE),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(pt_table)
    story.append(Spacer(1, 4*mm))

    # ── Rx SYMBOL ──────────────────────────────────────────────────────────────
    story.append(Paragraph("℞", s_rx))

    # ── MEDICINES TABLE ────────────────────────────────────────────────────────
    if emr.medications:
        med_header = [
            Paragraph("<b>Medicine</b>",    ParagraphStyle("mh", fontSize=8, textColor=colors.white, fontName="Helvetica-Bold")),
            Paragraph("<b>Frequency</b>",   ParagraphStyle("mh", fontSize=8, textColor=colors.white, fontName="Helvetica-Bold")),
            Paragraph("<b>Duration</b>",    ParagraphStyle("mh", fontSize=8, textColor=colors.white, fontName="Helvetica-Bold")),
            Paragraph("<b>Instructions</b>",ParagraphStyle("mh", fontSize=8, textColor=colors.white, fontName="Helvetica-Bold")),
        ]
        med_rows = [med_header]

        for i, med_str in enumerate(emr.medications):
            parsed = _parse_medication(med_str)
            bg = colors.white if i % 2 == 0 else colors.HexColor("#F5F5F5")
            row_style = ParagraphStyle("mr", fontSize=8, textColor=DARK_TEXT)
            med_rows.append([
                Paragraph(parsed["drug"],         row_style),
                Paragraph(parsed["frequency"],    row_style),
                Paragraph(parsed["duration"],     row_style),
                Paragraph(parsed["instructions"], row_style),
            ])

        col_widths = [PW * 0.38, PW * 0.25, PW * 0.17, PW * 0.20]
        med_table = Table(med_rows, colWidths=col_widths)

        row_colors = [("BACKGROUND", (0, 0), (-1, 0), MED_HEADER_BG)]
        for i in range(1, len(med_rows)):
            bg = colors.white if i % 2 == 1 else colors.HexColor("#F5F5F5")
            row_colors.append(("BACKGROUND", (0, i), (-1, i), bg))

        med_table.setStyle(TableStyle([
            ("GRID",          (0, 0), (-1, -1), 0.5, DIVIDER_COLOR),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            *row_colors,
        ]))
        story.append(med_table)
        story.append(Spacer(1, 4*mm))

    # ── ADVICE ─────────────────────────────────────────────────────────────────
    if emr.plan:
        story.append(HRFlowable(width=PW, thickness=0.5, color=DIVIDER_COLOR))
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph("<b>Advice</b>", ParagraphStyle("advh", fontSize=9,
            textColor=DARK_TEXT, fontName="Helvetica-Bold", spaceAfter=3)))
        # Split plan by semicolons into bullet points
        advice_items = [a.strip() for a in emr.plan.split(";") if a.strip()]
        for item in advice_items[:4]:   # max 4 advice items on prescription
            story.append(Paragraph(f"•  {item}", s_advice))
        story.append(Spacer(1, 3*mm))

    # ── ALLERGIES WARNING ──────────────────────────────────────────────────────
    if emr.allergies and emr.allergies.upper() != "NKDA":
        warn_table = Table(
            [[Paragraph(f"⚠️  Allergy: {emr.allergies}",
                ParagraphStyle("aw", fontSize=9, textColor=colors.HexColor("#E65100"),
                    fontName="Helvetica-Bold"))]],
            colWidths=[PW]
        )
        warn_table.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), WARNING_BG),
            ("BOX",           (0, 0), (-1, -1), 1.5, WARNING_BORDER),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(warn_table)
        story.append(Spacer(1, 3*mm))

    # ── FOLLOW-UP ──────────────────────────────────────────────────────────────
    story.append(HRFlowable(width=PW, thickness=1, color=BRAND_BLUE))
    story.append(Spacer(1, 2*mm))

    if emr.followUpDays:
        followup_date = (visit.visitDate + timedelta(days=emr.followUpDays)).strftime("%d %b %Y")
        story.append(Paragraph(
            f"📅  Next Visit: <b>{followup_date}</b>  (in {emr.followUpDays} days)",
            s_followup
        ))
    else:
        story.append(Paragraph("Return if symptoms worsen or don't improve in 3 days.", s_followup))

    story.append(Spacer(1, 6*mm))

    # ── DOCTOR SIGNATURE BLOCK ─────────────────────────────────────────────────
    sig_rows = [[
        Paragraph("", s_label),
        Paragraph(f"<b>Dr. {doctor.name}</b>", ParagraphStyle("sig",
            fontSize=10, textColor=DARK_TEXT, fontName="Helvetica-Bold", alignment=TA_RIGHT))
    ]]
    sig_table = Table(sig_rows, colWidths=[PW * 0.5, PW * 0.5])
    sig_table.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(sig_table)

    # ── FOOTER ─────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 3*mm))
    story.append(HRFlowable(width=PW, thickness=0.5, color=DIVIDER_COLOR))
    story.append(Spacer(1, 1*mm))
    story.append(Paragraph(
        "Generated by MediScribe AI  •  This prescription is valid for 30 days",
        s_footer
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer
