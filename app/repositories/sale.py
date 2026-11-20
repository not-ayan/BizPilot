from datetime import date
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models.sale import Sale
from app.models.sale_item import SaleItem

class SaleRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, sale_id: int) -> Sale:
        return self.db.query(Sale).filter(Sale.id == sale_id).first()

    def get_by_invoice(self, invoice_number: str) -> Sale:
        return self.db.query(Sale).filter(Sale.invoice_number == invoice_number).first()

    def get_by_customer_id(self, customer_id: int) -> list[Sale]:
        return self.db.query(Sale).filter(Sale.customer_id == customer_id).order_by(Sale.sale_date.desc()).all()

    def get_next_invoice_number(self, sale_date: date) -> str:
        date_str = sale_date.strftime("%Y%m%d")
        prefix = f"RM-{date_str}-"
        
        # Find the highest sequence number for this date
        max_invoice = self.db.query(Sale.invoice_number).filter(
            Sale.invoice_number.like(f"{prefix}%")
        ).order_by(Sale.invoice_number.desc()).first()

        if max_invoice:
            try:
                # Extract sequence number from the end (last 4 digits)
                last_seq = int(max_invoice[0].split("-")[-1])
                next_seq = last_seq + 1
            except ValueError:
                next_seq = 1
        else:
            next_seq = 1

        return f"{prefix}{next_seq:04d}"

    def create(self, sale_date: date, total_amount: float, customer_id: int = None, pdf_path: str = None, items_data: list = None, invoice_number: str = None) -> Sale:
        if not invoice_number:
            invoice_number = self.get_next_invoice_number(sale_date)
        
        sale = Sale(
            invoice_number=invoice_number,
            sale_date=sale_date,
            customer_id=customer_id,
            total_amount=total_amount,
            pdf_path=pdf_path
        )
        self.db.add(sale)
        self.db.flush()  # Populate sale.id for sale_items reference

        if items_data:
            for item in items_data:
                sale_item = SaleItem(
                    sale_id=sale.id,
                    product_name=item["product_name"],
                    product_id=item.get("product_id"),
                    quantity=item["quantity"],
                    price=item["price"],
                    warranty_info=item["warranty_info"]
                )
                self.db.add(sale_item)

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            # Retry with newly computed sequence number in case of concurrent invoice collision
            invoice_number = self.get_next_invoice_number(sale_date)
            sale = Sale(
                invoice_number=invoice_number,
                sale_date=sale_date,
                customer_id=customer_id,
                total_amount=total_amount,
                pdf_path=pdf_path
            )
            self.db.add(sale)
            self.db.flush()
            if items_data:
                for item in items_data:
                    sale_item = SaleItem(
                        sale_id=sale.id,
                        product_name=item["product_name"],
                        product_id=item.get("product_id"),
                        quantity=item["quantity"],
                        price=item["price"],
                        warranty_info=item["warranty_info"]
                    )
                    self.db.add(sale_item)
            self.db.commit()
            
        self.db.refresh(sale)
        return sale

    def get_sales_in_range(self, start_date: date, end_date: date) -> list[Sale]:
        return self.db.query(Sale).filter(
            Sale.sale_date >= start_date,
            Sale.sale_date <= end_date
        ).all()

    def get_customer_stats(self, customer_id: int) -> dict:
        sales = self.db.query(Sale).filter(Sale.customer_id == customer_id).order_by(Sale.sale_date.desc()).all()
        if not sales:
            return {
                "purchase_count": 0,
                "last_purchase_date": None,
                "lifetime_value": 0.0
            }
        
        purchase_count = len(sales)
        last_purchase_date = sales[0].sale_date
        lifetime_value = float(sum(s.total_amount for s in sales))
        
        return {
            "purchase_count": purchase_count,
            "last_purchase_date": last_purchase_date,
            "lifetime_value": lifetime_value
        }
    
    def get_total_unique_customers(self) -> int:
        return self.db.query(func.count(func.distinct(Sale.customer_id))).filter(Sale.customer_id != None).scalar() or 0
