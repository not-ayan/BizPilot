from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from app.database import Base

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    is_subscribed = Column(Boolean, default=False) # Subscription status for broadcasts
    notifications_enabled = Column(Boolean, default=False) # Ticket chat notifications enabled
    ticket_active = Column(Boolean, default=False) # Is currently in a talk-to-owner ticket
    ticket_number = Column(String, nullable=True) # Active ticket identifier
    last_ticket_activity = Column(DateTime, nullable=True) # Timestamp of last message in ticket
    bot_paused_until = Column(DateTime, nullable=True) # Time until which bot is paused for this customer
    created_at = Column(DateTime, default=datetime.utcnow)
