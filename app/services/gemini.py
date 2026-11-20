import logging
import requests
from app.config import settings

logger = logging.getLogger(__name__)

class GeminiService:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.model = "gemini-2.5-flash"
        self.base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    def reformat_broadcast_message(self, raw_text: str) -> str:
        """
        Uses Gemini API to reformat the admin's broadcast message to be professional and engaging.
        Returns the reformatted text if successful, or the original text on failure/missing key.
        """
        if not self.api_key:
            logger.warning("GEMINI_API_KEY is not configured in settings. Returning original text.")
            return raw_text

        system_instruction = (
            "You are a professional shop assistant for 'BizPilot', a retail and electronics store. "
            "Format the customer broadcast message to be polite, clear, structured, and engaging. "
            "Use bullet points and friendly emojis where appropriate. "
            "Crucially, you MUST preserve all original details like pricing (Rs.), contact numbers, brand names, and product names exactly as provided. "
            "Do not invent new facts, promotions, or details. Return ONLY the reformatted message text, without any introductory or concluding remarks (do not write 'Here is your formatted message:' or similar)."
        )

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": raw_text}
                    ]
                }
            ],
            "systemInstruction": {
                "parts": [
                    {"text": system_instruction}
                ]
            },
            "generationConfig": {
                "temperature": 0.2,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 1024,
                "thinkingConfig": {
                    "thinkingBudget": 0
                }
            }
        }

        try:
            url = f"{self.base_url}?key={self.api_key}"
            headers = {"Content-Type": "application/json"}
            
            response = requests.post(url, json=payload, headers=headers, timeout=12)
            response.raise_for_status()
            
            data = response.json()
            candidates = data.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                for part in parts:
                    if not part.get("thought") and part.get("text"):
                        reformatted = part.get("text", "").strip()
                        if reformatted:
                            return reformatted
            
            logger.warning("Gemini API response did not contain expected text content structure.")
            return raw_text

        except Exception as e:
            logger.error(f"Error calling Gemini API for broadcast reformatting: {e}")
            return raw_text

gemini_service = GeminiService()
