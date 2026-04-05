# MediScribe Backend (MedEcho)

AI-powered medical scribe application for Indian clinics. Built with FastAPI, SQLModel, and specialized for Indian languages.

## Project Structure

- `backend/`: FastAPI + SQLModel + PostgreSQL/SQLite
- `evaluation/`: Scripts for data augmentation and ROUGE evaluation.
- `routers/`: API endpoints for patients, doctors, EMR, and more.
- `services/`: Core logic including transcription (Whisper/Sarvam), EMR generation (Mistral), and ABHA integration.

## Prerequisites

- Python 3.10+
- PostgreSQL (or SQLite for development)
- API Keys: OpenAI, HuggingFace (optional), Sarvam AI (optional)

## Setup

### 1. Clone the repository
```bash
git clone https://github.com/chandanNegi39671/MedEcho.git
cd MedEcho/backend
```

### 2. Environment Setup
Create a `.env` file in the `backend/` directory by copying `.env.example`:
```bash
cp .env.example .env
```
Fill in the required variables (see [Environment Variables](#environment-variables) below).

### 3. Install Dependencies
```bash
python -m venv venv
# Windows
.\venv\Scripts\activate
# Mac/Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 4. Run the Application
```bash
fastapi dev main.py
```
The API will be available at `http://localhost:8000`.

## API Overview

- `GET /health`: Health check endpoint.
- `POST /transcribe`: Upload audio for transcription.
- `POST /emr/generate`: Generate structured EMR from transcript.
- `GET /patients`: List and manage patient records.
- `GET /doctors`: Doctor profile management.
- `POST /qr/generate`: Generate clinic registration QR codes.

## Environment Variables

The application requires the following environment variables:

- `DATABASE_URL`: Connection string for your database (e.g., `sqlite:///./medecho.db`).
- `OPENAI_API_KEY`: Required for transcription (Whisper) and fallback EMR.
- `HF_API_TOKEN`: Optional, used for fine-tuned Mistral model on HuggingFace.
- `SARVAM_API_KEY`: Optional, used for high-quality Indian language transcription.
- `ABDM_CLIENT_ID`: Optional, for ABHA ID integration.
- `QR_SECRET_KEY`: A strong secret key for HMAC-signed QR codes.

## License

MIT
