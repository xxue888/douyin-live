import os
import sys
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PORT: int = 8000
    HOST: str = "127.0.0.1"
    
    # Path settings
    BASE_DIR: Path = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent.parent
    DATA_DIR: Path = Path(sys.executable).parent / "data" if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent.parent / "data"
    CONFIG_PATH: Path = Path(sys.executable).parent / "data" / "config.json" if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent.parent / "data" / "config.json"
    COOKIES_PATH: Path = Path(sys.executable).parent / "data" / "cookies.json" if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent.parent / "data" / "cookies.json"
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

# Ensure data dir exists
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)

