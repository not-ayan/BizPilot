import logging
import requests
from decimal import Decimal
from sqlalchemy.orm import Session
from app.config import settings
from app.repositories.product import ProductRepository

logger = logging.getLogger(__name__)

class GoogleSheetsService:
    def __init__(self):
        # Enabled if we have a valid-looking Apps Script macros URL and secret token is configured
        self.enabled = (
            bool(settings.GOOGLE_SHEET_URL) and 
            "script.google.com/macros/s" in settings.GOOGLE_SHEET_URL and 
            bool(settings.GOOGLE_SHEETS_API_SECRET) and 
            settings.GOOGLE_SHEETS_API_SECRET != "your_shared_secret_passcode_here"
        )
        
        if self.enabled:
            logger.info("Google Sheets Service initialized successfully using Google Apps Script Web App.")
        else:
            logger.info("Google Sheets Service running in mock/offline mode (Google Apps Script URL or secret missing/default).")

    def sync_from_sheet(self, db: Session) -> dict:
        """
        Reads all items from the Google Sheet via Google Apps Script Web App 
        and updates the local SQLite/PostgreSQL database.
        """
        repo = ProductRepository(db)
        if not self.enabled:
            logger.info("Sheets sync: Google Sheets disabled. Running database catalog list check.")
            # Mock sync: return summary of current database products
            db_products = repo.get_all()
            return {"added": 0, "updated": len(db_products), "errors": 0, "mode": "mock_offline"}

        try:
            # Send GET request with token to Apps Script endpoint
            response = requests.get(
                settings.GOOGLE_SHEET_URL, 
                params={"token": settings.GOOGLE_SHEETS_API_SECRET},
                timeout=15
            )
            response.raise_for_status()
            records = response.json()
            
            if isinstance(records, dict) and records.get("status") == "unauthorized":
                raise Exception("Unauthorized: Invalid sheets secret token.")

            added_count = 0
            updated_count = 0
            
            for row in records:
                name = str(row.get("Product Name", "")).strip()
                category = str(row.get("Category", "Electronics")).strip()
                price_val = row.get("Default Price") if row.get("Default Price") is not None else row.get("Default price", 0)
                active_val = row.get("Active Status") if row.get("Active Status") is not None else row.get("Active status", "TRUE")
                
                if not name:
                    continue
                
                try:
                    price = float(price_val)
                except ValueError:
                    price = 0.0
                    
                # Active status could be string ("TRUE"/"FALSE") or boolean
                if isinstance(active_val, bool):
                    is_active = active_val
                else:
                    is_active = str(active_val).strip().upper() in ["TRUE", "YES", "1", "ACTIVE"]
                
                # Check DB status
                db_prod = repo.get_by_name(name)
                if not db_prod:
                    if is_active:
                        repo.create_or_update(name, category, price, is_active)
                        added_count += 1
                else:
                    if (db_prod.category != category or 
                        float(db_prod.default_price) != price or 
                        db_prod.is_active != is_active):
                        repo.create_or_update(name, category, price, is_active)
                        updated_count += 1
            
            return {"added": added_count, "updated": updated_count, "errors": 0, "mode": "live"}
        except Exception as e:
            logger.error(f"Error syncing from Google Sheets: {e}")
            return {"added": 0, "updated": 0, "errors": 1, "error_msg": str(e), "mode": "live"}

    def add_product(self, name: str, category: str, default_price: float, is_active: bool = True) -> bool:
        """
        Appends a new product row to the Google Sheet via Apps Script Web App POST request.
        """
        if not self.enabled:
            logger.info(f"Mock Sheet Add Product: {name}, {category}, {default_price}")
            return True
            
        try:
            payload = {
                "action": "add",
                "name": name,
                "category": category,
                "price": default_price,
                "is_active": is_active,
                "token": settings.GOOGLE_SHEETS_API_SECRET
            }
            response = requests.post(settings.GOOGLE_SHEET_URL, json=payload, timeout=15)
            response.raise_for_status()
            res_data = response.json()
            return res_data.get("status") == "success"
        except Exception as e:
            logger.error(f"Error adding product to Google Sheet Web App: {e}")
            return False

    def update_product(self, name: str, category: str, default_price: float, is_active: bool) -> bool:
        """
        Finds a row by product name and updates the category, price, and active status.
        """
        if not self.enabled:
            logger.info(f"Mock Sheet Update Product: {name}")
            return True
            
        try:
            payload = {
                "action": "update",
                "name": name,
                "category": category,
                "price": default_price,
                "is_active": is_active,
                "token": settings.GOOGLE_SHEETS_API_SECRET
            }
            response = requests.post(settings.GOOGLE_SHEET_URL, json=payload, timeout=15)
            response.raise_for_status()
            res_data = response.json()
            return res_data.get("status") == "success"
        except Exception as e:
            logger.error(f"Error updating product in Google Sheet Web App: {e}")
            return False

    def remove_product(self, name: str) -> bool:
        """
        Sets a product row's Active Status to FALSE in the Google Sheet.
        """
        if not self.enabled:
            logger.info(f"Mock Sheet Remove/Inactivate Product: {name}")
            return True
            
        try:
            payload = {
                "action": "remove",
                "name": name,
                "token": settings.GOOGLE_SHEETS_API_SECRET
            }
            response = requests.post(settings.GOOGLE_SHEET_URL, json=payload, timeout=15)
            response.raise_for_status()
            res_data = response.json()
            return res_data.get("status") == "success"
        except Exception as e:
            logger.error(f"Error removing product from Google Sheet Web App: {e}")
            return False

sheets_service = GoogleSheetsService()
