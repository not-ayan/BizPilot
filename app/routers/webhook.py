from fastapi import APIRouter, Request, Response, Depends, Query, status
from sqlalchemy.orm import Session
from collections import deque
import logging

from app.config import settings
from app.database import get_db
from app.services.state_machine import StateMachineService

logger = logging.getLogger(__name__)
router = APIRouter()

# Deduplication cache for incoming message IDs from Meta (at-least-once delivery protection)
processed_inbound_message_ids = deque(maxlen=5000)
processed_inbound_message_set = set()

@router.get("/webhook")
def verify_webhook(
    mode: str = Query(None, alias="hub.mode"),
    verify_token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge")
):
    """
    Validation endpoint for WhatsApp Business webhook verification.
    """
    if mode == "subscribe" and verify_token == settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified successfully.")
        return Response(content=challenge, media_type="text/plain")
    
    logger.warning("WhatsApp webhook verification token mismatch or invalid mode.")
    return Response(content="Forbidden", status_code=status.HTTP_403_FORBIDDEN)

@router.post("/webhook")
async def handle_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Callback endpoint for WhatsApp event notifications.
    """
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse webhook JSON payload: {e}")
        return Response(content="Invalid JSON", status_code=status.HTTP_400_BAD_REQUEST)

    logger.debug(f"Incoming Webhook Payload: {payload}")

    entries = payload.get("entry", [])

    # Process statuses list to detect manual admin replies
    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            statuses = value.get("statuses", [])
            for status_item in statuses:
                msg_id = status_item.get("id")
                recipient_id = status_item.get("recipient_id")
                status_val = status_item.get("status")
                
                # If status is 'sent' and it's NOT in our list of bot-sent messages, it's a manual admin message
                if status_val == "sent" and msg_id and recipient_id:
                    from app.services.whatsapp import whatsapp_service
                    if msg_id not in whatsapp_service.recent_sent_message_ids:
                        from datetime import datetime, timedelta
                        from app.repositories.customer import CustomerRepository
                        customer_repo = CustomerRepository(db)
                        customer = customer_repo.get_by_phone(recipient_id)
                        if customer:
                            customer.bot_paused_until = datetime.utcnow() + timedelta(hours=1)
                            db.commit()
                            logger.info(f"Admin manually replied to customer {recipient_id}. Pausing bot for 1 hour until {customer.bot_paused_until}.")

    # Process messages list
    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            for msg in messages:
                msg_id = msg.get("id")
                if msg_id:
                    if msg_id in processed_inbound_message_set:
                        logger.info(f"Duplicate incoming WhatsApp message ID {msg_id} detected. Skipping.")
                        continue
                    if len(processed_inbound_message_ids) >= 5000:
                        oldest = processed_inbound_message_ids.popleft()
                        processed_inbound_message_set.discard(oldest)
                    processed_inbound_message_ids.append(msg_id)
                    processed_inbound_message_set.add(msg_id)

                phone_number = msg.get("from")
                msg_type = msg.get("type")

                message_text = None
                button_id = None
                media_id = None

                if msg_type == "text":
                    message_text = msg.get("text", {}).get("body")
                elif msg_type == "interactive":
                    interactive = msg.get("interactive", {})
                    i_type = interactive.get("type")
                    if i_type == "button_reply":
                        button_reply = interactive.get("button_reply", {})
                        button_id = button_reply.get("id")
                        message_text = button_reply.get("title")
                    elif i_type == "list_reply":
                        list_reply = interactive.get("list_reply", {})
                        button_id = list_reply.get("id")
                        message_text = list_reply.get("title")
                elif msg_type == "image":
                    image = msg.get("image", {})
                    media_id = image.get("id")
                    message_text = image.get("caption") or "SKIP"
                elif msg_type == "button":
                    button = msg.get("button", {})
                    button_id = button.get("payload")
                    message_text = button.get("text")

                if phone_number:
                    # Run inside database transaction block
                    service = StateMachineService(db)
                    try:
                        service.process_message(
                            phone_number=phone_number,
                            message_text=message_text,
                            button_id=button_id,
                            media_id=media_id
                        )
                    except Exception as err:
                        logger.error(
                            f"State transition crash on sender {phone_number}: {err}", 
                            exc_info=True
                        )
                        # We commit whatever did not fail, but we don't break webhook loops.

    # Always return a 200 OK so WhatsApp doesn't continuously resend the webhook event.
    return Response(content="EVENT_RECEIVED", status_code=status.HTTP_200_OK)
