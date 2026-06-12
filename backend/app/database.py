import json
import os
from .config import settings
from .schemas.models import AppConfig

def load_config() -> AppConfig:
    if not settings.CONFIG_PATH.exists():
        # Create a default configuration
        default_config = AppConfig()
        save_config(default_config)
        return default_config
        
    try:
        with open(settings.CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return AppConfig(**data)
    except Exception as e:
        print(f"Error loading config.json, using defaults. Error: {e}")
        return AppConfig()

def save_config(config: AppConfig):
    # Ensure directory exists
    settings.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(settings.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config.model_dump(), f, ensure_ascii=False, indent=2)

def update_config(updates: dict) -> AppConfig:
    current = load_config()
    current_dict = current.model_dump()
    for key, value in updates.items():
        if key in current_dict:
            current_dict[key] = value
    updated = AppConfig(**current_dict)
    save_config(updated)
    return updated
