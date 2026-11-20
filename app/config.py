import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@db:5432/bizpilot"
    
    WHATSAPP_TOKEN: str = "mock_whatsapp_token"
    WHATSAPP_PHONE_NUMBER_ID: str = "mock_phone_number_id"
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = "mock_waba_id"
    WHATSAPP_WEBHOOK_VERIFY_TOKEN: str = "mock_verify_token"
    WHATSAPP_API_VERSION: str = "v19.0"
    
    GOOGLE_SHEETS_CREDENTIALS_FILE: str = "credentials.json"
    GOOGLE_SHEET_URL: str = "https://docs.google.com/spreadsheets/d/mock_id/edit"
    GOOGLE_SHEETS_API_SECRET: str = "your_api_secret_here"
    
    PRIMARY_ADMIN_PHONE: str = "9876543210"
    SECRET_KEY: str = "dev_secret_key_123"
    PORT: int = 8000
    
    # PDF storage settings
    PDF_OUTPUT_DIR: str = "invoices"
    
    # Gemini API settings
    GEMINI_API_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

# Ensure invoice directory exists
os.makedirs(settings.PDF_OUTPUT_DIR, exist_ok=True)
