from sqlalchemy import Column, Integer, String, Numeric, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base

class SaleItem(Base):
    __tablename__ = "sale_items"

    id = Column(Integer, primary_key=True, index=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False)
    product_name = Column(String, nullable=False) # Store name directly as snapshot
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True) # Nullable for custom admin products
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    warranty_info = Column(String, nullable=False) # e.g., "1 Year", "6 Months"

    sale = relationship("Sale", back_populates="items")
    product = relationship("Product")
