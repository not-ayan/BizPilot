from datetime import datetime
from sqlalchemy import Column, Integer, String, Date, JSON, DateTime
from app.database import Base

class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    report_type = Column(String, nullable=False) # "Weekly", "Monthly"
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    data = Column(JSON, nullable=False) # Stores metrics like revenue, transaction counts, etc.
    created_at = Column(DateTime, default=datetime.utcnow)
