# PROJECT_CONTEXT.md

## 1. Project overview
MediScribe is a FastAPI backend for AI-assisted outpatient documentation in Indian clinic workflows. The implementation is API-first and service-oriented: it handles doctor/patient records, visit storage, transcription, EMR generation, consent logging, record sharing, QR-based patient registration, PDF export, and analytics. The intended runtime environment is a Python web server (FastAPI + Uvicorn) with a SQL database configured through `DATABASE_URL` and external AI/health APIs via environment keys. The primary users are clinic-facing applications (frontend not included in this repository snapshot) and operational staff who need structured visit records and patient continuity.

Maturity level appears mid-stage: the code has production-oriented concerns (consent audit trails, secure audio deletion, scheduler lifecycle, modular routers/services) but also evolving behavior and inconsistencies (README drift, dependency drift, benchmark script mismatch).

README-vs-code mismatch: README states `frontend/` exists and backend is “FastAPI + SQLModel + PostgreSQL,” but this repository snapshot contains only `backend/`, `README.md`, and `PROJECT_CONTEXT.md`; no `frontend/` tree is present. README env examples are also incomplete relative to code-required keys.

## 2. System purpose
The system captures and processes clinical workflow artifacts through HTTP/WebSocket endpoints:
- Captures audio (`/transcribe/` and `/transcribe/live`) and consent events (`/consent/*`).
- Generates structured EMR JSON (`/generate-emr/`) with alerts and interaction checks.
- Stores core entities (doctor, patient, visit, EMR, disease risk, consent, sharing, QR metadata) in SQL tables.
- Exposes retrieval and reporting endpoints (`/patients`, `/visits`, `/analytics`, `/sharing/records/*`).
- Exposes export outputs (clinical PDF and prescription PDF) for downstream care and pharmacy workflows.

Primary user outcomes:
- Faster consultation documentation and structured record persistence.
- Cross-doctor continuity through consent-driven sharing.
- Patient onboarding through QR scan flow.
- Safety/quality augmentation through abnormal value and drug interaction checks.

Most important runtime responsibilities:
- Non-lossy persistence of clinical records and auditable consent.
- Fast API responsiveness while delegating cleanup to scheduler and external API calls to service modules.
- Privacy/security controls around audio retention and consent revocation.

## 3. Architecture summary
Major implementation layers and interactions:
- **API entry layer (`backend/main.py`)**: creates FastAPI app, configures CORS, registers routers, runs startup/shutdown lifecycle.
- **Router layer (`backend/routers/*.py`)**: endpoint contracts, request validation, HTTP/WebSocket semantics, DB session dependency wiring.
- **Service layer (`backend/services/*.py`)**: external integrations (OpenAI/Sarvam/HuggingFace/ABDM/OpenFDA), EMR logic, consent/sharing engines, PDF generation, audio cleanup scheduler.
- **Persistence layer (`backend/database.py`, `backend/models.py`)**: SQLModel/SQLAlchemy engine, session management, table schema.
- **Background lifecycle layer (`services/audio_cleanup.py`)**: APScheduler job deletes stale audio files and writes audit logs.
- **Evaluation/fine-tuning tooling (`backend/evaluation/*.py`)**: offline benchmarking, augmentation, and fine-tune preparation/launch; not part of request-serving runtime.

No plugin/hook framework, worker queue, or dedicated search engine module is present in this repository.

## 4. Directory structure
- `backend/main.py` (source, runtime entry)
  - Owns FastAPI app construction, lifespan startup/shutdown, CORS, router inclusion.
  - Calls `create_db_and_tables()` and scheduler start/stop.
- `backend/database.py` (source, runtime infrastructure)
  - Owns DB engine creation (`DATABASE_URL`), session generator, table creation.
  - Called by routers via `Depends(get_session)` and startup lifecycle.
- `backend/models.py` (source, schema/model ownership)
  - Owns SQLModel table definitions: `Doctor`, `Patient`, `Visit`, `EMR`, `DiseaseRisk`, `QRCode`, `ConsentLog`, `PatientShareConsent`.
  - Uses PostgreSQL-specific ARRAY type for `EMR.medications`.
- `backend/routers/` (source, HTTP/WebSocket handlers)
  - `patients.py`, `doctors.py`: CRUD-style read/create/update.
  - `visits.py`: visit creation, visit detail retrieval, EMR edits.
  - `transcribe.py`: file upload transcription + live WebSocket transcription.
  - `emr.py`: EMR generation/evaluation/model status.
  - `export.py`: clinical PDF and prescription PDF streaming.
  - `analytics.py`: timeline, symptom recurrence, risk trends, doctor summary, benchmark info.
  - `qr.py`: QR generation, scan registration, scan stats.
  - `sharing.py`: consent-backed record sharing lifecycle.
  - `consent.py`: recording/sharing consent log, revoke, patient consent history.
- `backend/services/` (source, business logic + integrations)
  - Transcription routing (`transcription.py`), EMR routing (`emr_router.py`), safety checks, translation, PDF generators, QR signing, ABDM client, sharing/consent logic, scheduled audio cleanup.
  - `emr_engine.py` is a compatibility wrapper delegating to `emr_router.py`.
- `backend/evaluation/` (source, offline tooling)
  - `benchmark.py`, `augment.py`, `finetune_prep.py`, `finetune_runner.py`.
  - Used for model quality workflows, not imported by `main.py`.
- `backend/requirements.txt` (runtime dependency config)
  - Declares core packages, but code imports additional libraries not listed (see sections 9/11).
- `backend/.env` (runtime config artifact)
  - Loaded by Pydantic settings classes in multiple services.
- `backend/__init__.py` (package marker)

## 5. Runtime workflow
1. Process start (`main.py`): FastAPI app is instantiated; on lifespan startup, DB tables are created and audio cleanup scheduler starts.
2. API consumption begins:
   - Patient/doctor identity records are created/read via `/patients` and `/doctors`.
   - Consent events are recorded via `/consent/recording` and `/consent/sharing`.
3. Audio ingestion:
   - Upload mode: `/transcribe/` writes temporary file under `uploads/`, transcribes, returns text/language, then secure-deletes file in `finally`.
   - Live mode: `/transcribe/live` accumulates chunks, writes temp `.webm`, transcribes on `STOP`, returns transcript, then secure-deletes.
4. EMR generation:
   - Client calls `/generate-emr/`; service chooses HuggingFace Mistral if configured, else regex fallback.
   - Post-processing adds abnormal-value alerts and drug-interaction results; optional Hindi/bilingual transformation.
5. Visit persistence:
   - Client submits `/visits/` with transcript + `emrData` + disease risk; backend writes `Visit`, then `EMR`, then `DiseaseRisk`.
6. Retrieval/continuity:
   - `/visits/{id}`, `/analytics/*`, `/sharing/*` expose longitudinal and shared summaries.
   - `/export/*` renders downloadable PDFs.
7. Background retention enforcement:
   - Every 5 minutes scheduler deletes audio files older than 30 minutes; writes JSON-lines audit entries.
8. Shutdown:
   - Lifespan shutdown stops scheduler.

Explicit vs inferred:
- Explicit in code: steps 1, 3, 4 endpoint behavior, 5 persistence sequence, 7 scheduler job.
- Inferred from endpoint contracts: frontend orchestration order between consent → transcription → EMR → visit creation.

## 6. Backend deep dive
Backend entry points:
- `backend/main.py` is the sole API process entry.
- Router modules are mounted directly in `main.py`; there is no intermediate controller layer.

Service boundaries:
- **Transcription boundary**: `services/transcription.py` routes language-specific STT between OpenAI Whisper and Sarvam.
- **EMR boundary**: `services/emr_router.py` handles model routing, HF calls, hallucination filtering, fallback extraction, model status metadata.
- **Clinical safety boundary**: `abnormal_alerts.py` and `drug_interactions.py` run deterministic checks on generated EMR.
- **Consent/sharing boundary**: `consent_logger.py` and `share_engine.py` enforce consent-backed data access patterns.
- **Document generation boundary**: `pdf_generator.py` and `prescription_generator.py` produce ReportLab outputs.
- **Cleanup boundary**: `audio_cleanup.py` enforces retention and secure deletion.

Request/handler flow pattern:
- Router validates payload (Pydantic/FastAPI), opens SQLModel session dependency, calls service logic or DB operations, commits/refreshes entities, returns JSON/stream response.
- Error handling is generally local `try/except` with `HTTPException` or fallback behavior in services.

Worker/background jobs:
- No distributed worker or queue.
- Single in-process APScheduler job (`cleanup_old_audio`) is the only recurring background mechanism.

Persistence layer:
- Engine from env URL; sessions are short-lived per request.
- Schema creation occurs on startup via `SQLModel.metadata.create_all(engine)`.

Search layer:
- No dedicated search service/index.
- Query patterns are SQL filters + `ilike` in patient list, plus analytics keyword extraction using in-memory rules.

Important utilities/config:
- Environment-driven settings classes in `database.py`, `transcription.py`, `abha_client.py`.
- HMAC token signing in `qr_generator.py`.
- Multiple graceful fallbacks (HF→regex, Sarvam→Whisper, ABDM unavailable→manual path, OpenFDA failures ignored).

Significant design patterns:
- Thin router / service-heavy organization.
- Defensive fallback integration strategy.
- Compliance-oriented audit and revocation model for consent.

## 7. Data and storage model
Persisted entities/tables (explicit in `models.py`):
- `doctors`: clinician identity and profile (`clerkId` unique/indexed).
- `patients`: doctor-linked patient profile (`doctorId` FK, `phone`/`abhaId` indexed).
- `visits`: encounter-level metadata, transcript pointer fields, status lifecycle.
- `emrs`: one-to-one with visit (`visitId` unique), structured clinical fields, hallucination/ROUGE metadata.
- `disease_risks`: one-to-one with visit (`visitId` unique), probability scores.
- `qr_codes`: one-per-doctor QR metadata and scan counts.
- `consent_logs`: audit trail of consent events with revoke timestamp.
- `patient_share_consents`: active/revoked consent-backed sharing relationship.

Write timing:
- Startup: table creation only.
- Request-time writes: doctor/patient CRUD, consent log insertion/revoke, visit+EMR+risk creation, QR record creation/scan count increment, sharing record creation/revoke.
- File-side writes: audit log entries for secure deletes.

Query patterns:
- Point lookups by primary key (`session.get`) and filtered SQLModel `select(...where...)`.
- Time ordering in visits and analytics (`order_by(visitDate)`).
- String search in patient list via `ilike` on name/phone/abhaId.

Indexes/search strategies:
- Field-level indices declared for core lookup fields (e.g., `clerkId`, `doctorId`, `abhaId`, `patientId` relationships).
- No FTS/vector index implementation.

## 8. Search, memory, and retrieval
Actual retrieval behavior in this repository:
- Full-text style retrieval is limited to SQL `ilike` filters in `patients` listing.
- Analytics retrieval is structured, not search-index based:
  - Timeline by patient visit ordering.
  - Symptom recurrence from keyword extraction over EMR fields.
  - Risk trend from sequential disease risk rows.
- Sharing retrieval uses consent token lookup and sanitized package assembly via `share_engine.build_patient_summary`.

Not present in code:
- No vector/semantic search.
- No ranking model beyond direct SQL/order-by and frequency counts.
- No progressive disclosure pipeline.
- No context-injection subsystem.

Evidence labels:
- “No vector/semantic search” is explicit in codebase scope (no vector DB client or embedding pipeline in runtime modules).
- “Progressive disclosure/context injection absent” is explicit by absence of related modules/endpoints in current tree.

## 9. Operational behavior
Startup requirements (explicit in code):
- Python runtime with FastAPI stack.
- Valid `DATABASE_URL` in backend `.env`.
- Optional keys for integrations: OpenAI, Anthropic, Sarvam, HuggingFace token/model, ABDM credentials, frontend URL, QR secret.

Dependencies/runtimes:
- FastAPI + SQLModel + SQLAlchemy engine.
- APScheduler for periodic cleanup.
- External HTTP APIs: OpenAI, Sarvam, HuggingFace Inference, ABDM, OpenFDA.
- ReportLab for PDF generation.

Ports/services:
- API port is not hardcoded in code; expected from Uvicorn/FastAPI launch command.
- CORS allows localhost:3000 and optional `FRONTEND_URL`.

Local storage paths:
- Temporary audio under `backend/uploads/`.
- Deletion audit entries in `backend/audit_log.txt`.

Graceful degradation behavior:
- Transcription falls back from Sarvam to Whisper on Sarvam errors.
- EMR falls back from HuggingFace model to regex extraction.
- ABDM integration returns `None`/manual path when unconfigured or failing.
- OpenFDA interaction lookup failures do not fail request.
- Audit log write failure is swallowed to avoid crashing deletion flow.

Performance-sensitive choices:
- Audio cleanup runs asynchronously every 5 minutes.
- Uploaded audio is deleted immediately post-transcription and on WebSocket end.
- Per-request DB sessions and direct SQL queries; no explicit caching.

Failure handling visible in code:
- Router-level `HTTPException` for missing entities/invalid consent.
- Local try/except with rollback in visit creation.
- Best-effort WebSocket sends guarded by try/except to tolerate disconnect races.

## 10. Conventions and packaging
Source vs built artifacts:
- Repository is source-only for backend runtime; no build output directories, container manifests, or packaged distributions in this snapshot.
- `evaluation/` acts as development/ML tooling, not deployed request path.

Packaging/build approach:
- No custom build pipeline in repo root for backend.
- Runtime expected via virtualenv + `pip install -r requirements.txt` + FastAPI/Uvicorn execution.

Tests/docs layout:
- No dedicated `tests/` or `docs/` directory present in this repository snapshot.
- Operational and architectural context is mostly in code docstrings and top-level README.

Contributor conventions to preserve:
- Keep thin router / service module separation.
- Maintain explicit consent checks before sharing flows.
- Preserve secure audio deletion semantics (`finally` blocks + scheduler).
- Keep fallback paths for external AI/API dependencies to avoid hard runtime failure.

## 11. Gaps and uncertainties
- Frontend orchestration sequence between endpoints (consent/transcription/emr/visit) is **inferred only**; backend exposes endpoints but does not enforce full workflow chain server-side.
- Production deployment topology (gunicorn/uvicorn workers, reverse proxy, hosting) is **unclear from code**.
- Authentication/authorization enforcement is **unclear from code** (no auth middleware or token validation in backend routes).
- README claim of local `frontend/` folder is **documented only** (not present in current tree).
- README dependency/env coverage is **documented only** and incomplete versus code imports/settings.
- Benchmark target values and script output fields have internal drift (`benchmark.py` expects `aggregate["benchmark"]`, evaluator returns `ekaScribeBenchmark`) and are **explicit in code** mismatch.
- Requirements completeness is **explicit in code** mismatch: runtime imports include packages not declared in `backend/requirements.txt` (e.g., `openai`, `anthropic`, `pydantic-settings`).

## 12. Next engineering steps
- Align README with implementation: update project tree description, required env vars, and real dependency surface.
- Reconcile dependency manifests: add missing runtime packages to `backend/requirements.txt` and remove unused entries where appropriate.
- Add auth and authorization controls around patient record access, sharing retrieval, and consent mutation endpoints.
- Add integration tests for the critical workflow chain (consent → transcribe → generate EMR → persist visit → export/share).
- Harden evaluation tooling consistency (benchmark field naming, documented benchmark target values).
- Consider centralizing error/observability patterns (structured logs instead of prints, explicit external API failure metrics).
- Define and document production configuration (DB engine assumptions, scaling model, scheduler behavior under multi-worker deployment).
