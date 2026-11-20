from datetime import date, timedelta
from sqlalchemy import func, and_
from sqlalchemy.orm import Session
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.customer import Customer
from app.models.product import Product

class ReportGenerator:
    def __init__(self, db: Session):
        self.db = db

    def generate_weekly_report_text(self) -> str:
        """
        Generates analytics for the past 7 days (e.g., last Thursday to Wednesday).
        """
        end_dt = date.today()
        start_dt = end_dt - timedelta(days=7)
        
        # 1. Total Revenue
        revenue = self.db.query(func.sum(Sale.total_amount)).filter(
            Sale.sale_date >= start_dt,
            Sale.sale_date <= end_dt
        ).scalar() or 0.0
        
        # 2. Total Transactions
        transactions = self.db.query(func.count(Sale.id)).filter(
            Sale.sale_date >= start_dt,
            Sale.sale_date <= end_dt
        ).scalar() or 0
        
        # 3. New Customers Registered
        from datetime import datetime, time
        start_datetime = datetime.combine(start_dt, time.min)
        new_cust = self.db.query(func.count(Customer.id)).filter(
            Customer.created_at >= start_datetime
        ).scalar() or 0
        
        # 4. Returning Customers
        # Customers who purchased in this period AND had a purchase prior
        purchasing_cust_ids = self.db.query(Sale.customer_id).filter(
            Sale.sale_date >= start_dt,
            Sale.sale_date <= end_dt,
            Sale.customer_id != None
        ).distinct().all()
        
        returning_cust = 0
        for (cust_id,) in purchasing_cust_ids:
            prior_purchase = self.db.query(func.count(Sale.id)).filter(
                Sale.customer_id == cust_id,
                Sale.sale_date < start_dt
            ).scalar() or 0
            if prior_purchase > 0:
                returning_cust += 1
                
        # 5. Top Selling Products
        top_products = self.db.query(
            SaleItem.product_name,
            func.sum(SaleItem.quantity).label("total_qty")
        ).join(Sale).filter(
            Sale.sale_date >= start_dt,
            Sale.sale_date <= end_dt
        ).group_by(SaleItem.product_name).order_by(
            func.sum(SaleItem.quantity).desc()
        ).limit(5).all()

        products_text = ""
        if top_products:
            for idx, (name, qty) in enumerate(top_products, 1):
                products_text += f"   {idx}. {name}: {qty} units\n"
        else:
            products_text = "   No items sold.\n"

        report_body = (
            f"📊 *BIZPILOT WEEKLY REPORT*\n"
            f"Period: {start_dt.strftime('%d-%b-%Y')} to {end_dt.strftime('%d-%b-%Y')}\n"
            f"----------------------------------\n"
            f"💰 *Total Revenue:* Rs. {float(revenue):,.2f}\n"
            f"🛒 *Transactions:* {transactions}\n"
            f"👥 *New Customers:* {new_cust}\n"
            f"🔄 *Returning Customers:* {returning_cust}\n\n"
            f"📦 *Top Selling Products:*\n"
            f"{products_text}"
            f"----------------------------------"
        )
        return report_body

    def generate_monthly_report_text(self) -> str:
        """
        Generates analytics for the past 30 days.
        """
        end_dt = date.today()
        start_dt = end_dt - timedelta(days=30)
        
        # 1. Total Revenue
        revenue = self.db.query(func.sum(Sale.total_amount)).filter(
            Sale.sale_date >= start_dt,
            Sale.sale_date <= end_dt
        ).scalar() or 0.0
        
        # 2. Top Products
        top_products = self.db.query(
            SaleItem.product_name,
            func.sum(SaleItem.quantity).label("total_qty")
        ).join(Sale).filter(
            Sale.sale_date >= start_dt,
            Sale.sale_date <= end_dt
        ).group_by(SaleItem.product_name).order_by(
            func.sum(SaleItem.quantity).desc()
        ).limit(5).all()
        
        products_text = ""
        if top_products:
            for idx, (name, qty) in enumerate(top_products, 1):
                products_text += f"   {idx}. {name}: {qty} units\n"
        else:
            products_text = "   No items sold.\n"
            
        # 3. Top Customers
        top_customers = self.db.query(
            Customer.name,
            Customer.phone_number,
            func.sum(Sale.total_amount).label("spent")
        ).join(Sale, Sale.customer_id == Customer.id).filter(
            Sale.sale_date >= start_dt,
            Sale.sale_date <= end_dt
        ).group_by(Customer.name, Customer.phone_number).order_by(
            func.sum(Sale.total_amount).desc()
        ).limit(5).all()

        customers_text = ""
        if top_customers:
            for idx, (name, phone, spent) in enumerate(top_customers, 1):
                customers_text += f"   {idx}. {name} ({phone[-10:]}): Rs. {float(spent):,.2f}\n"
        else:
            customers_text = "   No customers recorded.\n"

        # 4. New Customers Registered
        from datetime import datetime, time
        start_datetime = datetime.combine(start_dt, time.min)
        new_cust = self.db.query(func.count(Customer.id)).filter(
            Customer.created_at >= start_datetime
        ).scalar() or 0
        
        # 5. Returning Customers
        purchasing_cust_ids = self.db.query(Sale.customer_id).filter(
            Sale.sale_date >= start_dt,
            Sale.sale_date <= end_dt,
            Sale.customer_id != None
        ).distinct().all()
        
        returning_cust = 0
        for (cust_id,) in purchasing_cust_ids:
            prior_purchase = self.db.query(func.count(Sale.id)).filter(
                Sale.customer_id == cust_id,
                Sale.sale_date < start_dt
            ).scalar() or 0
            if prior_purchase > 0:
                returning_cust += 1
                
        # 6. Broadcast Subscriber counts
        subscribers = self.db.query(func.count(Customer.id)).filter(Customer.is_subscribed == True).scalar() or 0
        unsubscribed = self.db.query(func.count(Customer.id)).filter(Customer.is_subscribed == False).scalar() or 0

        report_body = (
            f"📢 *BIZPILOT MONTHLY REPORT*\n"
            f"Period: {start_dt.strftime('%d-%b-%Y')} to {end_dt.strftime('%d-%b-%Y')}\n"
            f"----------------------------------\n"
            f"💰 *Total Revenue:* Rs. {float(revenue):,.2f}\n"
            f"👥 *New Customers:* {new_cust}\n"
            f"🔄 *Returning Customers:* {returning_cust}\n"
            f"✉️ *Broadcast Subscribers:* {subscribers}\n"
            f"🚫 *Broadcast Opt-Outs:* {unsubscribed}\n\n"
            f"📦 *Top Products:*\n"
            f"{products_text}\n"
            f"👤 *Top Customers:*\n"
            f"{customers_text}"
            f"----------------------------------"
        )
        return report_body

    def generate_customer_csv(self) -> str:
        """
        Generates a CSV of all customer data and returns the absolute path.
        """
        import os
        import csv
        from app.config import settings
        
        filepath = os.path.join(settings.PDF_OUTPUT_DIR, "customer_list.csv")
        customers = self.db.query(Customer).order_by(Customer.id).all()
        
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Customer ID", "Name", "Phone Number", "Is Subscribed", 
                "Notifications Enabled", "Ticket Active", "Ticket Number", 
                "Created At", "Total Purchase Count", "Lifetime Value (Rs.)"
            ])
            
            from app.repositories.sale import SaleRepository
            sale_repo = SaleRepository(self.db)
            
            for c in customers:
                stats = sale_repo.get_customer_stats(c.id)
                writer.writerow([
                    c.id, c.name, c.phone_number, c.is_subscribed,
                    getattr(c, 'notifications_enabled', False), 
                    getattr(c, 'ticket_active', False), 
                    getattr(c, 'ticket_number', ""),
                    c.created_at.strftime("%Y-%m-%d %H:%M:%S") if c.created_at else "",
                    stats["purchase_count"],
                    f"{stats['lifetime_value']:.2f}"
                ])
                
        return os.path.abspath(filepath)

    def generate_product_csv(self) -> str:
        """
        Generates a CSV of all product data and returns the absolute path.
        """
        import os
        import csv
        from app.config import settings
        
        filepath = os.path.join(settings.PDF_OUTPUT_DIR, "product_list.csv")
        products = self.db.query(Product).order_by(Product.id).all()
        
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Product ID", "Product Name", "Category", "Default Price (Rs.)", "Is Active", "Created At"
            ])
            
            for p in products:
                writer.writerow([
                    p.id, p.name, p.category, f"{float(p.default_price):.2f}", p.is_active,
                    p.created_at.strftime("%Y-%m-%d %H:%M:%S") if p.created_at else ""
                ])
                
        return os.path.abspath(filepath)

    def generate_customer_excel(self) -> str:
        """
        Generates an Excel spreadsheet of all customer data and returns the absolute path.
        """
        import os
        from openpyxl import Workbook
        from app.config import settings
        
        filepath = os.path.join(settings.PDF_OUTPUT_DIR, "customer_list.xlsx")
        customers = self.db.query(Customer).order_by(Customer.id).all()
        
        wb = Workbook()
        ws = wb.active
        ws.title = "Customers"
        
        headers = [
            "Customer ID", "Name", "Phone Number", "Is Subscribed", 
            "Notifications Enabled", "Ticket Active", "Ticket Number", 
            "Created At", "Total Purchase Count", "Lifetime Value (Rs.)"
        ]
        ws.append(headers)
        
        from app.repositories.sale import SaleRepository
        sale_repo = SaleRepository(self.db)
        
        for c in customers:
            stats = sale_repo.get_customer_stats(c.id)
            ws.append([
                c.id, c.name, c.phone_number, 
                "Yes" if c.is_subscribed else "No",
                "Yes" if getattr(c, 'notifications_enabled', False) else "No",
                "Yes" if getattr(c, 'ticket_active', False) else "No",
                getattr(c, 'ticket_number', ""),
                c.created_at.strftime("%Y-%m-%d %H:%M:%S") if c.created_at else "",
                stats["purchase_count"],
                stats["lifetime_value"]
            ])
            
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = col[0].column_letter
            ws.column_dimensions[col_letter].width = max(max_len + 3, 10)
            
        wb.save(filepath)
        return os.path.abspath(filepath)

    def generate_product_excel(self) -> str:
        """
        Generates an Excel spreadsheet of all product data and returns the absolute path.
        """
        import os
        from openpyxl import Workbook
        from app.config import settings
        
        filepath = os.path.join(settings.PDF_OUTPUT_DIR, "product_list.xlsx")
        products = self.db.query(Product).order_by(Product.id).all()
        
        wb = Workbook()
        ws = wb.active
        ws.title = "Products"
        
        headers = [
            "Product ID", "Product Name", "Category", "Default Price (Rs.)", "Is Active", "Created At"
        ]
        ws.append(headers)
        
        for p in products:
            ws.append([
                p.id, p.name, p.category, float(p.default_price),
                "Yes" if p.is_active else "No",
                p.created_at.strftime("%Y-%m-%d %H:%M:%S") if p.created_at else ""
            ])
            
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = col[0].column_letter
            ws.column_dimensions[col_letter].width = max(max_len + 3, 10)
            
        wb.save(filepath)
        return os.path.abspath(filepath)


