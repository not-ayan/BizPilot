from datetime import datetime
from sqlalchemy import Column, String, JSON, DateTime
from app.database import Base

class ConversationState(Base):
    __tablename__ = "conversation_states"

    phone_number = Column(String, primary_key=True, index=True)
    state = Column(String, nullable=False) # e.g. "STATE_IDLE", "SALE_ASK_PRODUCT_NAME"
    data = Column(JSON, nullable=False, default=dict) # Stores wizard/session variables
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
