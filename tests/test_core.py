import os
os.environ["WHATSAPP_TOKEN"] = "mock_whatsapp_token"
os.environ["DATABASE_URL"] = "sqlite:///./test_test.db"

import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.product import Product
from app.models.admin import Admin
from app.models.customer import Customer
from app.services.pdf_generator import PDFGenerator, number_to_words
from app.utils.fuzzy import match_products
from app.services.state_machine import StateMachineService, SALE_ASK_QUANTITY, SALE_ASK_PRICE, SALE_ASK_WARRANTY

# Setup test SQLite database
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        if os.path.exists("./test_test.db"):
            try:
                os.remove("./test_test.db")
            except PermissionError:
                pass

def test_number_to_words():
    # Test cases for Indian Rupee word formatting
    assert number_to_words(0) == "Rupees Zero Only"
    assert number_to_words(105) == "Rupees One Hundred and Five Only"
    assert number_to_words(2500) == "Rupees Two Thousand Five Hundred Only"
    assert number_to_words(150000) == "Rupees One Lakh Fifty Thousand Only"
    assert number_to_words(1234.56) == "Rupees One Thousand Two Hundred and Thirty Four and Fifty Six Paise Only"

def test_fuzzy_matching():
    # Setup dummy products
    p1 = Product(name="RR 9 Watt LED Bulb", category="Bulbs", default_price=120.0, is_active=True)
    p2 = Product(name="Syska 12 Watt LED Bulb", category="Bulbs", default_price=180.0, is_active=True)
    p3 = Product(name="Microtek Inverter 1050VA", category="Inverter", default_price=6500.0, is_active=True)
    
    products = [p1, p2, p3]
    
    # Check exact matches
    res1 = match_products("rr 9 watt", products)
    assert len(res1) > 0
    assert res1[0][0].name == "RR 9 Watt LED Bulb"
    assert res1[0][1] >= 80.0
    
    # Check typo tolerance
    res2 = match_products("syska bulvb", products)
    assert len(res2) > 0
    assert res2[0][0].name == "Syska 12 Watt LED Bulb"
    
    # Check category search match
    res3 = match_products("micro inverter", products)
    assert len(res3) > 0
    assert res3[0][0].name == "Microtek Inverter 1050VA"

def test_pdf_generation():
    invoice_num = "RM-20260618-0001"
    sale_date = date(2026, 6, 18)
    cust_name = "Assam Customer"
    cust_phone = "919876543210"
    
    items = [
        {"product_name": "RR 9 Watt LED Bulb", "quantity": 5, "price": 100.0, "warranty_info": "1 Year"},
        {"product_name": "Microtek Inverter", "quantity": 1, "price": 6000.0, "warranty_info": "2 Years"}
    ]
    total = 6500.0
    
    filepath = PDFGenerator.generate_invoice(
        invoice_number=invoice_num,
        sale_date=sale_date,
        customer_name=cust_name,
        customer_phone=cust_phone,
        items=items,
        total_amount=total,
        output_dir="./test_invoices"
    )
    
    assert os.path.exists(filepath)
    assert filepath.endswith(".pdf")
    
    # Clean up generated PDF file
    if os.path.exists(filepath):
        os.remove(filepath)
    if os.path.exists("./test_invoices"):
        os.rmdir("./test_invoices")

def test_state_machine_transitions(db_session):
    # Setup test admin (using the primary admin phone)
    admin_phone = "919876543210"
    admin = Admin(phone_number=admin_phone, name="Primary Admin")
    db_session.add(admin)
    
    # Setup dummy catalogue product
    p1 = Product(name="RR 9 Watt LED Bulb", category="Bulb", default_price=150.0, is_active=True)
    db_session.add(p1)
    db_session.commit()
    
    # Debug print
    active_products = db_session.query(Product).filter(Product.is_active == True).all()
    print("\n[DEBUG] Active products in DB:", [p.name for p in active_products])
    print("[DEBUG] Fuzzy matches:", match_products("rr 9 watt", active_products))
    
    service = StateMachineService(db_session)
    
    # 1. Trigger "Record Sale"
    service.process_message(phone_number=admin_phone, button_id="menu_record_sale")
    state_obj = service.state_repo.get(admin_phone)
    assert state_obj.state == "SALE_ASK_PRODUCT_NAME"
    
    # 2. Enter product name matching RR bulb with high-confidence
    service.process_message(phone_number=admin_phone, message_text="rr 9 watt")
    state_obj = service.state_repo.get(admin_phone)
    assert state_obj.state == "SALE_CONFIRM_PRODUCT_MATCH"
    assert state_obj.data["current_item"]["product_name"] == "RR 9 Watt LED Bulb"
    
    # 3. Confirm match
    service.process_message(phone_number=admin_phone, button_id="sale_match_yes")
    state_obj = service.state_repo.get(admin_phone)
    assert state_obj.state == SALE_ASK_QUANTITY
    
    # 4. Enter quantity
    service.process_message(phone_number=admin_phone, message_text="4")
    state_obj = service.state_repo.get(admin_phone)
    assert state_obj.state == SALE_ASK_PRICE
    assert state_obj.data["current_item"]["quantity"] == 4
    
    # 5. Enter price
    service.process_message(phone_number=admin_phone, message_text="140")
    state_obj = service.state_repo.get(admin_phone)
    assert state_obj.state == SALE_ASK_WARRANTY
    assert state_obj.data["current_item"]["price"] == 140.0
    
    # 6. Select warranty
    service.process_message(phone_number=admin_phone, button_id="warranty_1y")
    state_obj = service.state_repo.get(admin_phone)
    assert state_obj.state == "SALE_ASK_ADD_ANOTHER"
    assert len(state_obj.data["cart"]) == 1
    assert state_obj.data["cart"][0]["product_name"] == "RR 9 Watt LED Bulb"
    assert state_obj.data["cart"][0]["warranty_info"] == "1 Year"
