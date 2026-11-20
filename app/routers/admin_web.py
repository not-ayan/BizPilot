import os
from fastapi import APIRouter, Depends, status, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.repositories.product import ProductRepository
from app.services.sheets import sheets_service
from app.utils.casing import to_title_case

router = APIRouter()

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")

@router.get("/admin/catalogue", response_class=HTMLResponse)
def get_catalogue_page():
    """Serves the catalogue manager HTML page."""
    html_path = os.path.join(TEMPLATES_DIR, "catalogue.html")
    if not os.path.exists(html_path):
        # Create templates directory if not exists
        os.makedirs(TEMPLATES_DIR, exist_ok=True)
        raise HTTPException(status_code=404, detail="Catalogue page template not found")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

@router.get("/api/web/products", tags=["Web Catalogue Admin"])
def get_products(db: Session = Depends(get_db)):
    """List all products in the database."""
    repo = ProductRepository(db)
    prods = repo.get_all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "category": p.category,
            "default_price": float(p.default_price),
            "is_active": p.is_active,
            "created_at": p.created_at.isoformat() if p.created_at else None
        } for p in prods
    ]

@router.post("/api/web/products", tags=["Web Catalogue Admin"])
def add_product(payload: dict, db: Session = Depends(get_db)):
    """Create a new product, casing the names and syncing to Google Sheets."""
    name = to_title_case(payload.get("name", "").strip())
    category = to_title_case(payload.get("category", "").strip())
    try:
        price = float(payload.get("default_price", 0.0))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid price value")

    if not name or not category:
        raise HTTPException(status_code=400, detail="Product name and category are required")

    repo = ProductRepository(db)
    
    # Check if duplicate
    existing = repo.get_by_name(name)
    if existing:
        raise HTTPException(status_code=400, detail=f"Product with name '{name}' already exists")

    product = repo.create_or_update(name, category, price, is_active=True)
    sheets_service.add_product(name, category, price, is_active=True)

    return {"status": "success", "product_id": product.id}

@router.put("/api/web/products/{product_id}", tags=["Web Catalogue Admin"])
def update_product(product_id: int, payload: dict, db: Session = Depends(get_db)):
    """Update product price, category, status, and sync to Google Sheets."""
    repo = ProductRepository(db)
    product = repo.get_by_id(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    name = to_title_case(payload.get("name", "").strip()) or product.name
    category = to_title_case(payload.get("category", "").strip()) or product.category
    
    try:
        price = float(payload.get("default_price", float(product.default_price)))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid price value")

    is_active = payload.get("is_active", product.is_active)
    old_name = product.name

    # Check if the new name is already taken by another product
    if name.lower() != old_name.lower():
        existing_with_new_name = repo.get_by_name(name)
        if existing_with_new_name:
            raise HTTPException(status_code=400, detail=f"Product with name '{name}' already exists")

    # Update local DB product fields directly
    product.name = name
    product.category = category
    product.default_price = price
    product.is_active = is_active
    db.commit()

    # Sync to Google Sheets
    if name != old_name:
        # If name changed, inactivate/remove the old product name and add the new one
        sheets_service.remove_product(old_name)
        sheets_service.add_product(name, category, price, is_active)
    else:
        sheets_service.update_product(name, category, price, is_active)

    return {"status": "success"}

@router.delete("/api/web/products/{product_id}", tags=["Web Catalogue Admin"])
def delete_product(product_id: int, db: Session = Depends(get_db)):
    """Delete a product from DB and trigger removal on Sheets."""
    repo = ProductRepository(db)
    product = repo.get_by_id(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    name = product.name
    
    # Check if product is referenced in historical sales
    from app.models.sale_item import SaleItem
    has_sales = db.query(SaleItem).filter(SaleItem.product_id == product.id).first() is not None
    if has_sales:
        product.is_active = False
        db.commit()
        sheets_service.remove_product(name)
        return {"status": "success", "message": "Product deactivated to preserve historical sales records"}

    repo.delete(product)
    sheets_service.remove_product(name)

    return {"status": "success"}

@router.post("/api/web/sync", tags=["Web Catalogue Admin"])
def force_sync(db: Session = Depends(get_db)):
    """Triggers sheets sync."""
    res = sheets_service.sync_from_sheet(db)
    if res.get("errors", 0) > 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {res.get('error_msg')}"
        )
    return {"status": "success", "results": res}

# Category Management Routes
from app.models.category import Category

@router.get("/api/web/categories", tags=["Web Catalogue Admin"])
def get_categories(db: Session = Depends(get_db)):
    """List all categories."""
    cats = db.query(Category).order_by(Category.name.asc()).all()
    return [{"id": c.id, "name": c.name} for c in cats]

@router.post("/api/web/categories", tags=["Web Catalogue Admin"])
def add_category(payload: dict, db: Session = Depends(get_db)):
    """Add a new category."""
    name = to_title_case(payload.get("name", "").strip())
    if not name:
        raise HTTPException(status_code=400, detail="Category name is required")
    
    # Check if duplicate
    existing = db.query(Category).filter(Category.name == name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Category '{name}' already exists")
    
    cat = Category(name=name)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return {"status": "success", "category": {"id": cat.id, "name": cat.name}}

@router.delete("/api/web/categories/{category_id}", tags=["Web Catalogue Admin"])
def delete_category(category_id: int, db: Session = Depends(get_db)):
    """Delete a category."""
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    
    # Check if category is currently used by any products
    from app.models.product import Product
    used_count = db.query(Product).filter(Product.category == cat.name).count()
    if used_count > 0:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot delete category '{cat.name}' as it is currently assigned to {used_count} product(s)"
        )
        
    db.delete(cat)
    db.commit()
    return {"status": "success"}

@router.get("/admin/sales", response_class=HTMLResponse)
def get_sales_page():
    """Serves the sales recording HTML page."""
    html_path = os.path.join(TEMPLATES_DIR, "sales.html")
    if not os.path.exists(html_path):
        raise HTTPException(status_code=404, detail="Sales page template not found")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

@router.get("/api/web/customers/search", tags=["Web Sales Admin"])
def search_customers(q: str, db: Session = Depends(get_db)):
    """Search customers by name or phone number."""
    from app.repositories.customer import CustomerRepository
    repo = CustomerRepository(db)
    customers = repo.search_by_name_or_phone(q)
    return [
        {
            "id": c.id,
            "name": c.name,
            "phone_number": c.phone_number,
        } for c in customers
    ]

@router.post("/api/web/sales", tags=["Web Sales Admin"])
def record_sale(payload: dict, db: Session = Depends(get_db)):
    """Record a sale, generate invoice PDF, and optionally send via WhatsApp."""
    from datetime import date
    from app.repositories.customer import CustomerRepository
    from app.repositories.sale import SaleRepository
    from app.services.pdf_generator import PDFGenerator
    from app.services.whatsapp import whatsapp_service
    from app.utils.phone import clean_phone_number
    from app.config import settings

    customer_phone = payload.get("customer_phone", "").strip()
    customer_name = to_title_case(payload.get("customer_name", "").strip())
    sale_date_str = payload.get("sale_date", date.today().isoformat())
    items = payload.get("items", [])
    generate_invoice = payload.get("generate_invoice", True)
    send_whatsapp = payload.get("send_whatsapp", False)

    try:
        sale_date = date.fromisoformat(sale_date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    if not items:
        raise HTTPException(status_code=400, detail="At least one item is required")

    # Clean phone if provided
    cleaned_phone = None
    customer = None
    if customer_phone:
        cleaned_phone = clean_phone_number(customer_phone)
        if len(cleaned_phone) != 12 or not cleaned_phone.startswith("91"):
            raise HTTPException(status_code=400, detail="Invalid phone number format. Must be a 10-digit mobile number.")
        
        customer_repo = CustomerRepository(db)
        customer = customer_repo.get_by_phone(cleaned_phone)
        if not customer:
            if not customer_name:
                raise HTTPException(status_code=400, detail="Customer name is required for new customer profiles")
            customer = customer_repo.create(cleaned_phone, customer_name)
        else:
            if customer_name and customer.name != customer_name:
                customer.name = customer_name
                db.commit()
                db.refresh(customer)

    # Title-case and format items
    formatted_items = []
    for it in items:
        formatted_items.append({
            "product_name": to_title_case(it["product_name"]),
            "product_id": it.get("product_id"),
            "quantity": int(it["quantity"]),
            "price": float(it["price"]),
            "warranty_info": it.get("warranty_info", "No Warranty")
        })

    total_amount = sum(float(item["quantity"]) * float(item["price"]) for item in formatted_items)
    
    # Generate temporary invoice number
    sale_repo = SaleRepository(db)
    invoice_number = sale_repo.get_next_invoice_number(sale_date)

    pdf_path = None
    pdf_media_id = None

    if generate_invoice and customer:
        pdf_path = PDFGenerator.generate_invoice(
            invoice_number=invoice_number,
            sale_date=sale_date,
            customer_name=customer.name,
            customer_phone=customer.phone_number,
            items=formatted_items,
            total_amount=total_amount,
            output_dir=settings.PDF_OUTPUT_DIR
        )

        if send_whatsapp:
            try:
                pdf_media_id = whatsapp_service.upload_media(pdf_path, "application/pdf")
                # Send text and document
                sales_before = sale_repo.get_by_customer_id(customer.id)
                is_first_purchase = len(sales_before) == 0
                
                if is_first_purchase:
                    greeting = (
                        f"Dear {customer.name}, thank you for your first purchase at BizPilot! 🌟\n\n"
                        f"We have generated your invoice {invoice_number} and it is attached below.\n"
                        f"We are committed to providing you with the best products and service.\n\n"
                        f"If you have any questions about your purchase or warranty, feel free to contact us."
                    )
                else:
                    greeting = (
                        f"Dear {customer.name}, thank you for shopping at BizPilot!\n\n"
                        f"We have generated your invoice {invoice_number} and it is attached below."
                    )
                
                whatsapp_service.send_text(customer.phone_number, greeting)
                whatsapp_service.send_document(
                    to=customer.phone_number,
                    media_id=pdf_media_id,
                    filename=os.path.basename(pdf_path),
                    caption="Here is your purchase invoice."
                )
            except Exception as e:
                # Log warning but do not fail the request completely
                import logging
                logging.getLogger(__name__).error(f"Error sending invoice on WhatsApp: {e}", exc_info=True)

    # Save the sale
    sale = sale_repo.create(
        sale_date=sale_date,
        total_amount=total_amount,
        customer_id=customer.id if customer else None,
        pdf_path=pdf_path,
        items_data=formatted_items,
        invoice_number=invoice_number
    )

    return {
        "status": "success",
        "sale": {
            "id": sale.id,
            "invoice_number": sale.invoice_number,
            "total_amount": float(sale.total_amount),
            "pdf_path": sale.pdf_path
        }
    }

@router.get("/api/web/invoices/{filename}", tags=["Web Sales Admin"])
def get_invoice_pdf(filename: str):
    """Serves a generated invoice PDF file."""
    from fastapi.responses import FileResponse
    from app.config import settings
    filepath = os.path.join(settings.PDF_OUTPUT_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Invoice PDF not found")
    return FileResponse(filepath, media_type="application/pdf")

@router.post("/api/web/sales/preview", tags=["Web Sales Admin"])
def preview_invoice(payload: dict, db: Session = Depends(get_db)):
    """Generate a draft invoice PDF without saving the sale to the database."""
    from datetime import date
    from app.repositories.customer import CustomerRepository
    from app.repositories.sale import SaleRepository
    from app.services.pdf_generator import PDFGenerator
    from app.config import settings
    from app.utils.phone import clean_phone_number

    customer_phone = payload.get("customer_phone", "").strip()
    customer_name = to_title_case(payload.get("customer_name", "").strip())
    sale_date_str = payload.get("sale_date", date.today().isoformat())
    items = payload.get("items", [])

    try:
        sale_date = date.fromisoformat(sale_date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    if not items:
        raise HTTPException(status_code=400, detail="At least one item is required")

    # Basic customer validation (phone/name) for invoice preview header
    phone_to_display = customer_phone
    name_to_display = customer_name
    if customer_phone:
        try:
            cleaned_phone = clean_phone_number(customer_phone)
            phone_to_display = cleaned_phone
            customer_repo = CustomerRepository(db)
            customer = customer_repo.get_by_phone(cleaned_phone)
            if customer and not name_to_display:
                name_to_display = customer.name
        except Exception:
            pass

    if not name_to_display:
        name_to_display = "Retail Customer"
    if not phone_to_display:
        phone_to_display = "N/A"

    total_amount = sum(float(item["quantity"]) * float(item["price"]) for item in items)
    
    # Next sequence number for preview
    sale_repo = SaleRepository(db)
    invoice_number = f"DRAFT-{sale_repo.get_next_invoice_number(sale_date)}"

    formatted_items = []
    for it in items:
        formatted_items.append({
            "product_name": to_title_case(it["product_name"]),
            "quantity": int(it["quantity"]),
            "price": float(it["price"]),
            "warranty_info": it.get("warranty_info", "No Warranty")
        })

    # Save with a temporary filename prefix so we know it's a draft
    draft_filename = f"draft_{invoice_number}.pdf"
    filepath = os.path.join(settings.PDF_OUTPUT_DIR, draft_filename)

    PDFGenerator.generate_invoice(
        invoice_number=invoice_number,
        sale_date=sale_date,
        customer_name=name_to_display,
        customer_phone=phone_to_display,
        items=formatted_items,
        total_amount=total_amount,
        output_dir=settings.PDF_OUTPUT_DIR
    )
    
    # Rename to the draft filename if PDFGenerator default is different
    default_filename = f"{invoice_number.replace('/', '_')}.pdf"
    default_filepath = os.path.join(settings.PDF_OUTPUT_DIR, default_filename)
    if os.path.exists(default_filepath) and default_filepath != filepath:
        if os.path.exists(filepath):
            os.remove(filepath)
        os.rename(default_filepath, filepath)

    return {
        "status": "success",
        "preview_url": f"/api/web/invoices/{draft_filename}",
        "draft_filename": draft_filename
    }

