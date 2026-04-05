from sqlmodel import create_engine, Session, SQLModel
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    DIRECT_URL: str = ""

    model_config = {"extra": "ignore", "env_file": ".env"}

settings = Settings()

def _normalise(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url

db_url = _normalise(settings.DATABASE_URL)
engine = create_engine(db_url, echo=True)

def get_session():
    with Session(engine) as session:
        yield session

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)