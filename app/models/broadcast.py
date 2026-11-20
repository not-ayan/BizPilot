from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base

class Broadcast(Base):
    __tablename__ = "broadcasts"

    id = Column(Integer, primary_key=True, index=True)
    broadcast_type = Column(String, nullable=False) # e.g. "Sale", "New Product", "Custom"
    message_content = Column(Text, nullable=False)
    image_url = Column(String, nullable=True) # Remote URL or local filename
    sent_by_admin_id = Column(Integer, ForeignKey("admins.id"), nullable=False)
    recipients_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    admin = relationship("Admin")
