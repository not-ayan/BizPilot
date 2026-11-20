import os
import logging
from collections import deque
import requests
from app.config import settings

logger = logging.getLogger(__name__)

class WhatsAppService:
    def __init__(self):
        self.token = settings.WHATSAPP_TOKEN
        self.phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        self.version = settings.WHATSAPP_API_VERSION
        
        self.base_url = f"https://graph.facebook.com/{self.version}/{self.phone_number_id}"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        # Track recent message IDs sent by the bot to filter out from webhooks
        self.recent_sent_message_ids = deque(maxlen=2000)
        
        # Verify if we are running in mock mode
        self.is_mock = self.token == "mock_whatsapp_token" or not self.phone_number_id
        if self.is_mock:
            logger.info("WhatsApp Service running in MOCK mode. Messages will be logged, not sent.")

    def _post(self, endpoint: str, payload: dict) -> dict:
        """Helper to send POST request to WhatsApp Graph API."""
        url = f"{self.base_url}/{endpoint}"
        if self.is_mock:
            import uuid
            mock_id = f"wamid.mock_{uuid.uuid4().hex}"
            logger.info(f"[Mock WhatsApp Request] URL: {url} | Payload: {payload} | Generated Message ID: {mock_id}")
            res = {"messaging_product": "whatsapp", "contacts": [{"input": payload.get("to"), "wa_id": payload.get("to")}], "messages": [{"id": mock_id}]}
            self.recent_sent_message_ids.append(mock_id)
            return res

        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=10)
            response.raise_for_status()
            res = response.json()
            if "messages" in res and len(res["messages"]) > 0:
                msg_id = res["messages"][0].get("id")
                if msg_id:
                    self.recent_sent_message_ids.append(msg_id)
            return res
        except requests.exceptions.RequestException as e:
            logger.error(f"WhatsApp API POST request failed: {e}")
            if response := getattr(e, 'response', None):
                logger.error(f"Response error content: {response.text}")
            raise e

    def send_text(self, to: str, text: str) -> dict:
        """Sends a standard text message."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": text
            }
        }
        return self._post("messages", payload)

    def send_buttons(self, to: str, text: str, buttons: list[dict]) -> dict:
        """
        Sends an interactive reply-buttons message.
        buttons list format: [{"id": "btn_id", "title": "Btn Title"}] (max 3 buttons)
        """
        # WhatsApp limits interactive button lists to 3 buttons and 20 chars per title.
        formatted_buttons = []
        for btn in buttons[:3]:
            formatted_buttons.append({
                "type": "reply",
                "reply": {
                    "id": btn["id"],
                    "title": str(btn["title"])[:20]
                }
            })
            
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": text
                },
                "action": {
                    "buttons": formatted_buttons
                }
            }
        }
        return self._post("messages", payload)

    def send_list(self, to: str, title: str, body: str, button_text: str, sections: list[dict]) -> dict:
        """
        Sends an interactive list menu.
        sections format:
        [{
            "title": "Sec Title",
            "rows": [{"id": "row_id", "title": "Row Title", "description": "optional"}]
        }]
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "header": {
                    "type": "text",
                    "text": title
                },
                "body": {
                    "text": body
                },
                "action": {
                    "button": button_text,
                    "sections": sections
                }
            }
        }
        return self._post("messages", payload)

    def upload_media(self, file_path: str, mime_type: str) -> str:
        """
        Uploads a local file to WhatsApp Cloud storage.
        Returns the Meta media_id string.
        """
        url = f"https://graph.facebook.com/{self.version}/{self.phone_number_id}/media"
        if self.is_mock:
            logger.info(f"[Mock WhatsApp Media Upload] File path: {file_path} | Mime: {mime_type}")
            return "mock_media_id_987654"

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found for upload: {file_path}")

        headers = {
            "Authorization": f"Bearer {self.token}"
        }
        
        try:
            with open(file_path, "rb") as f:
                files = {
                    "file": (os.path.basename(file_path), f, mime_type)
                }
                data = {
                    "messaging_product": "whatsapp",
                    "type": mime_type
                }
                response = requests.post(url, headers=headers, files=files, data=data, timeout=30)
                response.raise_for_status()
                result = response.json()
                return result["id"]
        except Exception as e:
            logger.error(f"WhatsApp Media Upload failed: {e}")
            if response := getattr(e, 'response', None):
                logger.error(f"Response error content: {response.text}")
            raise e

    def send_document(self, to: str, media_id: str, filename: str, caption: str = None) -> dict:
        """Sends a document (e.g. PDF invoice) using the media_id."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "document",
            "document": {
                "id": media_id,
                "filename": filename
            }
        }
        if caption:
            payload["document"]["caption"] = caption
        return self._post("messages", payload)

    def send_image(self, to: str, media_id: str, caption: str = None) -> dict:
        """Sends an image using the media_id."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "image",
            "image": {
                "id": media_id
            }
        }
        if caption:
            payload["image"]["caption"] = caption
        return self._post("messages", payload)

    def send_image_buttons(self, to: str, media_id: str, text: str, buttons: list[dict]) -> dict:
        """
        Sends an interactive reply-buttons message with an image header.
        """
        formatted_buttons = []
        for btn in buttons[:3]:
            formatted_buttons.append({
                "type": "reply",
                "reply": {
                    "id": btn["id"],
                    "title": str(btn["title"])[:20]
                }
            })
            
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "header": {
                    "type": "image",
                    "image": {
                        "id": media_id
                    }
                },
                "body": {
                    "text": text
                },
                "action": {
                    "buttons": formatted_buttons
                }
            }
        }
        return self._post("messages", payload)

whatsapp_service = WhatsAppService()
