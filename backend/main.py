from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
from database import create_db_and_tables
from routers import patients, doctors, visits, transcribe, emr, export, analytics
# New routers
from routers import qr, sharing, consent
# Audio cleanup scheduler
from services.audio_cleanup import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_db_and_tables()
    start_scheduler()       # Begin 30-min audio auto-delete background job
    yield
    # Shutdown
    stop_scheduler()


app = FastAPI(
    title="MediScribe API",
    description="AI-powered medical scribe backend for Indian clinics",
    version="3.0.0",
    lifespan=lifespan
)

# CORS — Bug #8 fixed: load production URL from env
_frontend_url = os.getenv("FRONTEND_URL", "")
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
if _frontend_url and _frontend_url not in origins:
    origins.append(_frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "MediScribe Backend v3.0 is running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


# ── Original routers ───────────────────────────────────────────────────────────
app.include_router(patients.router)
app.include_router(doctors.router)
app.include_router(visits.router)
app.include_router(transcribe.router)
app.include_router(emr.router)
app.include_router(export.router)
app.include_router(analytics.router)

# ── New routers ────────────────────────────────────────────────────────────────
app.include_router(qr.router)        # /qr/*       — QR code generation + patient scan
app.include_router(sharing.router)   # /sharing/*  — Cross-doctor record sharing
app.include_router(consent.router)   # /consent/*  — Patient consent logging (DPDP)
