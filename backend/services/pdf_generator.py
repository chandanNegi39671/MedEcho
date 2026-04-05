from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.units import mm
from io import BytesIO

# ─── Colour Palette ───────────────────────────────────────────────────────────
BRAND_BLUE       = colors.HexColor("#1A73E8")
BRAND_BLUE_LIGHT = colors.HexColor("#E8F0FE")
SYMPTOM_BG       = colors.HexColor("#FFF8E1")   # warm yellow  – chief complaint / HPI
SYMPTOM_BORDER   = colors.HexColor("#F9A825")
DIAGNOSIS_BG     = colors.HexColor("#FCE4EC")   # soft red     – diagnosis
DIAGNOSIS_BORDER = colors.HexColor("#E53935")
RISK_LOW         = colors.HexColor("#E8F5E9")   # green
RISK_MED         = colors.HexColor("#FFF9C4")   # yellow
RISK_HIGH        = colors.HexColor("#FFEBEE")   # red
RISK_LOW_TEXT    = colors.HexColor("#2E7D32")
RISK_MED_TEXT    = colors.HexColor("#F57F17")
RISK_HIGH_TEXT   = colors.HexColor("#B71C1C")
SECTION_HEADER   = colors.HexColor("#37474F")
DIVIDER          = colors.HexColor("#CFD8DC")


def _risk_color(prob: float):
    """Return (bg_color, text_color, label) based on probability 0-1."""
    if prob >= 0.7:
        return RISK_HIGH, RISK_HIGH_TEXT, "HIGH"
    elif prob >= 0.4:
        return RISK_MED, RISK_MED_TEXT, "MODERATE"
    else:
        return RISK_LOW, RISK_LOW_TEXT, "LOW"


def generate_visit_pdf(visit, patient, doctor, emr, risk) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        rightMargin=50, leftMargin=50,
        topMargin=50, bottomMargin=30
    )

    styles = getSampleStyleSheet()

    # ── Custom Styles ──────────────────────────────────────────────────────────
    style_clinic = ParagraphStyle(
        "ClinicTitle", parent=styles["Title"],
        fontSize=18, textColor=BRAND_BLUE,
        alignment=TA_CENTER, spaceAfter=2
    )
    style_doctor = ParagraphStyle(
        "DoctorName", parent=styles["Normal"],
        fontSize=11, textColor=SECTION_HEADER,
        alignment=TA_CENTER, spaceAfter=2
    )
    style_section_header = ParagraphStyle(
        "SectionHeader", parent=styles["Heading3"],
        fontSize=10, textColor=colors.white,
        spaceBefore=0, spaceAfter=0, leftIndent=6
    )
    style_body = ParagraphStyle(
        "Body", parent=styles["Normal"],
        fontSize=10, leading=14, textColor=colors.HexColor("#212121")
    )
    style_highlight_label = ParagraphStyle(
        "HighlightLabel", parent=styles["Normal"],
        fontSize=9, textColor=colors.HexColor("#757575"),
        spaceBefore=0, spaceAfter=2
    )
    style_highlight_body = ParagraphStyle(
        "HighlightBody", parent=styles["Normal"],
        fontSize=11, leading=15, textColor=colors.HexColor("#212121"),
        fontName="Helvetica-Bold"
    )
    style_normal_label = ParagraphStyle(
        "NormalLabel", parent=styles["Normal"],
        fontSize=9, textColor=colors.HexColor("#757575")
    )
    style_normal_body = ParagraphStyle(
        "NormalBody", parent=styles["Normal"],
        fontSize=10, leading=14, textColor=colors.HexColor("#212121")
    )
    style_footer = ParagraphStyle(
        "Footer", parent=styles["Italic"],
        fontSize=8, textColor=colors.HexColor("#9E9E9E"),
        alignment=TA_CENTER
    )

    story = []
    W = 515  # usable page width

    # ── Helper: section header band ───────────────────────────────────────────
    def section_band(title: str, bg=BRAND_BLUE):
        t = Table(
            [[Paragraph(title.upper(), style_section_header)]],
            colWidths=[W]
        )
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ]))
        return t

    # ── Helper: plain two-col row ──────────────────────────────────────────────
    def plain_section(label: str, content: str):
        if not content:
            return None
        rows = [[
            Paragraph(label, style_normal_label),
            Paragraph(content, style_normal_body)
        ]]
        t = Table(rows, colWidths=[130, W - 130])
        t.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return t

    # ── Helper: HIGHLIGHTED box (for symptoms / diagnosis) ────────────────────
    def highlighted_box(label: str, content: str, bg, border_color):
        if not content:
            return None
        inner = Table(
            [[Paragraph(label, style_highlight_label)],
             [Paragraph(content, style_highlight_body)]],
            colWidths=[W - 24]
        )
        inner.setStyle(TableStyle([
            ("TOPPADDING",    (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ]))
        outer = Table([[inner]], colWidths=[W])
        outer.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), bg),
            ("BOX",           (0, 0), (-1, -1), 2, border_color),
            ("LEFTPADDING",   (0, 0), (-1, -1), 12),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        return outer

    # ══════════════════════════════════════════════════════════════════════════
    # HEADER
    # ══════════════════════════════════════════════════════════════════════════
    if doctor.clinicName:
        story.append(Paragraph(doctor.clinicName, style_clinic))
    story.append(Paragraph(f"Dr. {doctor.name}", style_doctor))
    if doctor.phone:
        story.append(Paragraph(f"📞 {doctor.phone}", style_doctor))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width=W, thickness=2, color=BRAND_BLUE))
    story.append(Spacer(1, 10))

    # ── Patient Info ──────────────────────────────────────────────────────────
    patient_rows = [
        [
            Paragraph("<b>Patient</b>", style_body),
            Paragraph(f"<b>{patient.name}</b>", style_body),
            Paragraph("<b>Date</b>", style_body),
            Paragraph(visit.visitDate.strftime("%d %b %Y"), style_body),
        ],
        [
            Paragraph("Age / Gender", style_normal_label),
            Paragraph(f"{patient.age or 'N/A'} yrs  /  {patient.gender or 'N/A'}", style_body),
            Paragraph("Visit ID", style_normal_label),
            Paragraph(visit.id[-10:], style_body),
        ],
    ]
    if patient.abhaId:
        patient_rows.append([
            Paragraph("ABHA ID", style_normal_label),
            Paragraph(patient.abhaId, style_body),
            Paragraph("", style_body), Paragraph("", style_body)
        ])

    pt = Table(patient_rows, colWidths=[90, 175, 70, 180])
    pt.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), BRAND_BLUE_LIGHT),
        ("BOX",           (0, 0), (-1, -1), 1, BRAND_BLUE),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(pt)
    story.append(Spacer(1, 14))

    # ══════════════════════════════════════════════════════════════════════════
    # ★ SYMPTOMS & COMPLAINTS — HIGHLIGHTED SECTION ★
    # ══════════════════════════════════════════════════════════════════════════
    story.append(section_band("🩺  Symptoms & Complaints", bg=SYMPTOM_BORDER))
    story.append(Spacer(1, 4))

    cc_box = highlighted_box(
        "Chief Complaint", emr.chiefComplaint,
        SYMPTOM_BG, SYMPTOM_BORDER
    )
    if cc_box:
        story.append(cc_box)
        story.append(Spacer(1, 6))

    hpi_box = highlighted_box(
        "History of Present Illness (Symptoms, Duration, Severity)",
        emr.hpi, SYMPTOM_BG, SYMPTOM_BORDER
    )
    if hpi_box:
        story.append(hpi_box)
        story.append(Spacer(1, 6))

    if emr.pastHistory:
        t = plain_section("Past History", emr.pastHistory)
        if t: story.append(t)

    story.append(Spacer(1, 10))

    # ══════════════════════════════════════════════════════════════════════════
    # CLINICAL FINDINGS
    # ══════════════════════════════════════════════════════════════════════════
    story.append(section_band("🔬  Clinical Findings"))
    story.append(Spacer(1, 4))

    for label, val in [
        ("Exam Findings", emr.examFindings),
        ("Allergies",     emr.allergies),
    ]:
        t = plain_section(label, val)
        if t:
            story.append(t)

    if emr.medications:
        med_text = "  •  ".join(emr.medications)
        t = plain_section("Medications", med_text)
        if t: story.append(t)

    story.append(Spacer(1, 10))

    # ══════════════════════════════════════════════════════════════════════════
    # ★ DIAGNOSIS & PLAN — HIGHLIGHTED SECTION ★
    # ══════════════════════════════════════════════════════════════════════════
    story.append(section_band("🏥  Diagnosis & Treatment Plan", bg=DIAGNOSIS_BORDER))
    story.append(Spacer(1, 4))

    diag_box = highlighted_box(
        "Diagnosis", emr.diagnosis,
        DIAGNOSIS_BG, DIAGNOSIS_BORDER
    )
    if diag_box:
        story.append(diag_box)
        story.append(Spacer(1, 6))

    plan_box = highlighted_box(
        "Plan / Treatment Instructions", emr.plan,
        DIAGNOSIS_BG, DIAGNOSIS_BORDER
    )
    if plan_box:
        story.append(plan_box)
        story.append(Spacer(1, 6))

    if emr.followUpDays:
        t = plain_section("Follow-Up", f"Please revisit in {emr.followUpDays} days.")
        if t: story.append(t)

    story.append(Spacer(1, 12))

    # ══════════════════════════════════════════════════════════════════════════
    # ★ AI DISEASE RISK ANALYSIS — HIGHLIGHTED SECTION ★
    # ══════════════════════════════════════════════════════════════════════════
    if risk:
        story.append(section_band("⚠️  AI Disease Risk Analysis", bg=colors.HexColor("#6A1B9A")))
        story.append(Spacer(1, 6))

        conditions = [
            ("Flu / Influenza",    risk.fluProbability),
            ("Migraine",           risk.migraineProbability),
            ("Fatigue / Burnout",  risk.fatigueProbability),
            ("Diabetes (T2DM)",    getattr(risk, "diabetesProbability",    0.0)),
            ("Hypertension",       getattr(risk, "hypertensionProbability", 0.0)),
        ]

        risk_rows = [[
            Paragraph("<b>Condition</b>", style_body),
            Paragraph("<b>Risk Level</b>", style_body),
            Paragraph("<b>Probability</b>", style_body),
        ]]

        for condition, prob in conditions:
            bg, tc, label = _risk_color(prob)
            bar_filled  = int(prob * 10)
            bar_empty   = 10 - bar_filled
            bar = "█" * bar_filled + "░" * bar_empty

            risk_rows.append([
                Paragraph(condition, style_body),
                Paragraph(
                    f'<font color="#{tc.hexval()[2:]}">'
                    f'<b>{label}</b></font>  {bar}',
                    style_body
                ),
                Paragraph(f"<b>{prob:.0%}</b>", style_body),
            ])

        rt = Table(risk_rows, colWidths=[170, 230, 115])
        row_colors = []
        for i, (_, prob) in enumerate(conditions, start=1):
            bg, _, _ = _risk_color(prob)
            row_colors.append(("BACKGROUND", (0, i), (-1, i), bg))

        rt.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#6A1B9A")),
            ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
            ("GRID",          (0, 0), (-1, -1), 0.5, DIVIDER),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            *row_colors
        ]))
        story.append(rt)

        if risk.notes:
            story.append(Spacer(1, 6))
            story.append(Paragraph(f"⚠️  <i>{risk.notes}</i>", style_body))

    # ── Hallucination warning ─────────────────────────────────────────────────
    if emr.hallucinationWarning:
        story.append(Spacer(1, 10))
        warn = Table(
            [[Paragraph(
                f"⚠️  <b>AI Confidence Warning:</b>  {emr.hallucinationDetails or 'Some fields may be inaccurate. Please verify.'}",
                ParagraphStyle("Warn", parent=style_body, textColor=RISK_HIGH_TEXT)
            )]],
            colWidths=[W]
        )
        warn.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), RISK_HIGH),
            ("BOX",           (0, 0), (-1, -1), 1.5, DIAGNOSIS_BORDER),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(warn)

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width=W, thickness=0.5, color=DIVIDER))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Generated by MediScribe  •  AI-assisted medical record", style_footer))

    doc.build(story)
    buffer.seek(0)
    return buffer


# ─── Quick test (runs only when executed directly) ────────────────────────────
if __name__ == "__main__":
    from datetime import datetime
    from types import SimpleNamespace

    doctor  = SimpleNamespace(name="Arjun Mehta", clinicName="Mehta Clinic", phone="+91 98765 43210")
    patient = SimpleNamespace(name="Priya Sharma", age=34, gender="Female", abhaId="ABHA-123456")
    visit   = SimpleNamespace(id="visit_abc123xyz", visitDate=datetime.now())
    emr     = SimpleNamespace(
        chiefComplaint="Severe headache and nausea since 2 days",
        hpi="Patient reports throbbing headache on right side, photophobia, no fever. Pain rated 8/10. Started 2 days ago after a stressful event.",
        pastHistory="Hypertension (controlled). No surgical history.",
        medications=["Sumatriptan 50mg", "Paracetamol 500mg", "Metoprolol 25mg"],
        allergies="Penicillin",
        examFindings="BP 138/88 mmHg, Temp 98.4°F, Fundus normal, No neck rigidity.",
        diagnosis="Migraine without aura (G43.009)",
        plan="Rest in dark quiet room. Start Sumatriptan at onset. Avoid triggers (stress, bright light). Hydration.",
        followUpDays=7,
        hallucinationWarning=False,
        hallucinationDetails=None,
    )
    risk = SimpleNamespace(
        fluProbability=0.15,
        migraineProbability=0.88,
        fatigueProbability=0.52,
        notes="Migraine probability is HIGH — symptoms strongly align with migraine without aura."
    )

    pdf = generate_visit_pdf(visit, patient, doctor, emr, risk)
    with open("/mnt/user-data/outputs/sample_visit_report.pdf", "wb") as f:
        f.write(pdf.read())
    print("PDF written.")
