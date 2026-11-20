import os
os.environ["WHATSAPP_TOKEN"] = "mock_whatsapp_token"
os.environ["DATABASE_URL"] = "sqlite:///./test_test_enhancements.db"

import pytest
from datetime import date, datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, upgrade_db_schema
from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.utils.casing import to_title_case, capitalize_sentences, calculate_remaining_warranty
from app.services.report_generator import ReportGenerator
from app.services.gemini import gemini_service
from app.services.scheduler import check_inactive_tickets_job
from app.services.state_machine import StateMachineService

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_test_enhancements.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    upgrade_db_schema() # Run self-healing upgrade
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        if os.path.exists("./test_test_enhancements.db"):
            try:
                os.remove("./test_test_enhancements.db")
            except PermissionError:
                pass

def test_casing_utilities():
    assert to_title_case("syska 12 watt led bulb") == "Syska 12 Watt LED Bulb"
    assert to_title_case("rr 9 watt LED bulb") == "RR 9 Watt LED Bulb" # Preserves Fully capitalized words
    assert capitalize_sentences("hello world. this is a sentence! another sentence?") == "Hello world. This is a sentence! Another sentence?"
    assert capitalize_sentences("new line\nstarts with lower.") == "New line\nStarts with lower."

def test_warranty_calculator():
    sale_dt = date(2026, 1, 1)
    
    assert calculate_remaining_warranty(sale_dt, "No Warranty") == "No Warranty"
    
    future_sale = date.today()
    assert "Active" in calculate_remaining_warranty(future_sale, "1 Year")
    assert "Expired" in calculate_remaining_warranty(date(2020, 1, 1), "1 Year")

def test_csv_exports(db_session):
    # Setup dummy data
    c1 = Customer(phone_number="919999999999", name="Test Customer", is_subscribed=True)
    p1 = Product(name="Syska Led", category="Bulb", default_price=100.0, is_active=True)
    db_session.add(c1)
    db_session.add(p1)
    db_session.commit()
    
    generator = ReportGenerator(db_session)
    cust_csv = generator.generate_customer_csv()
    prod_csv = generator.generate_product_csv()
    
    assert os.path.exists(cust_csv)
    assert os.path.exists(prod_csv)
    
    # Read headers
    with open(cust_csv, "r") as f:
        header = f.readline()
        assert "Customer ID" in header
        assert "Lifetime Value" in header
        
    with open(prod_csv, "r") as f:
        header = f.readline()
        assert "Product Name" in header
        
    os.remove(cust_csv)
    os.remove(prod_csv)

def test_ticket_auto_close_job(db_session):
    # Setup customer with an active ticket but no activity for 2 hours
    past_activity = datetime.utcnow() - timedelta(hours=2)
    c1 = Customer(
        phone_number="919888888888", 
        name="John Support", 
        ticket_active=True, 
        notifications_enabled=True,
        ticket_number="TKT-TEST",
        last_ticket_activity=past_activity
    )
    db_session.add(c1)
    db_session.commit()
    
    # Run the background job manually by overriding SessionLocal in scheduler
    from app.services import scheduler
    orig_session_local = scheduler.SessionLocal
    scheduler.SessionLocal = TestingSessionLocal
    
    try:
        scheduler.check_inactive_tickets_job()
    finally:
        scheduler.SessionLocal = orig_session_local
    
    # Refresh customer and check status
    db_session.refresh(c1)
    assert c1.ticket_active == False
    assert c1.notifications_enabled == False

def test_admin_ticket_forwarding(db_session):
    # Setup customer with an active ticket
    from app.models.admin import Admin
    c1 = Customer(
        phone_number="919888888888", 
        name="John Support", 
        ticket_active=True, 
        notifications_enabled=True,
        ticket_number="TKT-TEST",
        last_ticket_activity=datetime.utcnow()
    )
    admin = Admin(phone_number="919876543210", name="Primary Admin")
    db_session.add(c1)
    db_session.add(admin)
    db_session.commit()
    
    service = StateMachineService(db_session)
    service.process_message(phone_number="919876543210", message_text="Hello customer, how can I help you?")
    
    db_session.refresh(c1)
    assert c1.ticket_active == True
    assert c1.notifications_enabled == True
    assert c1.last_ticket_activity is not None

def test_excel_exports(db_session):
    c1 = Customer(phone_number="919999999999", name="Test Customer", is_subscribed=True)
    p1 = Product(name="Syska Led", category="Bulb", default_price=100.0, is_active=True)
    db_session.add(c1)
    db_session.add(p1)
    db_session.commit()
    
    generator = ReportGenerator(db_session)
    cust_xlsx = generator.generate_customer_excel()
    prod_xlsx = generator.generate_product_excel()
    
    assert os.path.exists(cust_xlsx)
    assert os.path.exists(prod_xlsx)
    
    # Read headers using openpyxl to verify correctness
    from openpyxl import load_workbook
    wb_c = load_workbook(cust_xlsx)
    ws_c = wb_c.active
    assert ws_c.cell(row=1, column=1).value == "Customer ID"
    assert ws_c.cell(row=1, column=10).value == "Lifetime Value (Rs.)"
    wb_c.close()
    
    wb_p = load_workbook(prod_xlsx)
    ws_p = wb_p.active
    assert ws_p.cell(row=1, column=1).value == "Product ID"
    assert ws_p.cell(row=1, column=2).value == "Product Name"
    wb_p.close()
    
    os.remove(cust_xlsx)
    os.remove(prod_xlsx)

def test_analytics_reports(db_session):
    # Setup dummy data with sales and items to trigger report generation
    c1 = Customer(phone_number="919999999999", name="Test Customer", created_at=datetime.utcnow() - timedelta(days=2))
    p1 = Product(name="Syska Led", category="Bulb", default_price=100.0, is_active=True)
    db_session.add(c1)
    db_session.add(p1)
    db_session.commit()
    
    sale = Sale(invoice_number="RM-20260619-0001", sale_date=date.today(), total_amount=100.0, customer_id=c1.id)
    db_session.add(sale)
    db_session.commit()
    
    sale_item = SaleItem(sale_id=sale.id, product_name="Syska Led", quantity=1, price=100.0, warranty_info="1 Year")
    db_session.add(sale_item)
    db_session.commit()
    
    generator = ReportGenerator(db_session)
    weekly = generator.generate_weekly_report_text()
    monthly = generator.generate_monthly_report_text()
    
    assert "BIZPILOT WEEKLY REPORT" in weekly
    assert "BIZPILOT MONTHLY REPORT" in monthly
    assert "Syska Led" in weekly
    assert "Test Customer" in monthly

def test_admin_manual_intervention_pauses_bot(db_session):
    from app.services.whatsapp import whatsapp_service
    from app.routers.webhook import handle_webhook
    from fastapi import Request
    
    # 1. Setup customer
    c1 = Customer(phone_number="919999888877", name="Customer Interrupted", is_subscribed=True)
    db_session.add(c1)
    db_session.commit()
    
    # 2. Simulate customer message to show menu/greeting
    state_machine = StateMachineService(db_session)
    state_machine.process_message(phone_number="919999888877", message_text="Hello")
    # Verify a message was sent (bot is active)
    assert len(whatsapp_service.recent_sent_message_ids) > 0
    bot_msg_id = list(whatsapp_service.recent_sent_message_ids)[-1]
    
    # 3. Simulate webhook receiving status update for a message that WAS sent by the bot.
    # It should NOT pause the bot.
    class MockRequest:
        def __init__(self, json_data):
            self.json_data = json_data
        async def json(self):
            return self.json_data
            
    payload_bot_status = {
        "entry": [{
            "changes": [{
                "value": {
                    "statuses": [{
                        "id": bot_msg_id,
                        "status": "sent",
                        "recipient_id": "919999888877"
                    }]
                }
            }]
        }]
    }
    
    import asyncio
    asyncio.run(handle_webhook(MockRequest(payload_bot_status), db_session))
    
    db_session.refresh(c1)
    assert c1.bot_paused_until is None
    
    # 4. Simulate webhook receiving status update for a message that WAS NOT sent by the bot (manual intervention).
    payload_admin_status = {
        "entry": [{
            "changes": [{
                "value": {
                    "statuses": [{
                        "id": "wamid.manual_admin_message_id_abc123",
                        "status": "sent",
                        "recipient_id": "919999888877"
                    }]
                }
            }]
        }]
    }
    
    asyncio.run(handle_webhook(MockRequest(payload_admin_status), db_session))
    
    db_session.refresh(c1)
    assert c1.bot_paused_until is not None
    assert (c1.bot_paused_until - datetime.utcnow()).total_seconds() > 0
    
    # Clear sent message ids list for clean test
    whatsapp_service.recent_sent_message_ids.clear()
    
    # 5. Customer messages again - bot should ignore (no messages sent)
    state_machine.process_message(phone_number="919999888877", message_text="Hello again")
    assert len(whatsapp_service.recent_sent_message_ids) == 0
    
    # 6. Change pause to past to simulate 1 hour passing, customer messages again - bot replies!
    c1.bot_paused_until = datetime.utcnow() - timedelta(minutes=1)
    db_session.add(c1)
    db_session.commit()
    
    state_machine.process_message(phone_number="919999888877", message_text="Hello again after pause")
    assert len(whatsapp_service.recent_sent_message_ids) > 0


def test_sales_web_endpoints(db_session):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models.customer import Customer
    from app.models.sale import Sale

    from app.database import get_db
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    # 1. Setup pre-existing customer
    c1 = Customer(phone_number="919876543210", name="Sandro Test", is_subscribed=True)
    db_session.add(c1)
    db_session.commit()

    # 2. Test Customer search endpoint
    res = client.get("/api/web/customers/search?q=Sandro")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["name"] == "Sandro Test"
    assert data[0]["phone_number"] == "919876543210"

    # 3. Test record sale endpoint
    sale_payload = {
        "customer_phone": "919876543210",
        "customer_name": "Sandro Test",
        "sale_date": "2026-07-19",
        "generate_invoice": True,
        "send_whatsapp": False,
        "items": [
            {
                "product_name": "Syska 12W LED Bulb",
                "product_id": None,
                "quantity": 3,
                "price": 150.00,
                "warranty_info": "1 Year"
            }
        ]
    }
    
    res_sale = client.post("/api/web/sales", json=sale_payload)
    assert res_sale.status_code == 200
    res_data = res_sale.json()
    assert res_data["status"] == "success"
    assert "invoice_number" in res_data["sale"]
    assert res_data["sale"]["total_amount"] == 450.00

    # 4. Verify DB entries exist
    sale_db = db_session.query(Sale).filter(Sale.invoice_number == res_data["sale"]["invoice_number"]).first()
    assert sale_db is not None
    assert sale_db.total_amount == 450.00
    assert len(sale_db.items) == 1
    assert sale_db.items[0].product_name == "Syska 12W LED Bulb"
    assert sale_db.items[0].quantity == 3
    assert sale_db.items[0].price == 150.00
    assert sale_db.items[0].warranty_info == "1 Year"

    # Clean up generated invoice PDF
    if sale_db.pdf_path and os.path.exists(sale_db.pdf_path):
        os.remove(sale_db.pdf_path)

    # 5. Test Sales Preview endpoints
    preview_payload = {
        "customer_phone": "919876543210",
        "customer_name": "Sandro Test",
        "sale_date": "2026-07-19",
        "items": [
            {
                "product_name": "Syska 12W LED Bulb",
                "product_id": None,
                "quantity": 3,
                "price": 150.00,
                "warranty_info": "1 Year"
            }
        ]
    }
    
    res_prev = client.post("/api/web/sales/preview", json=preview_payload)
    assert res_prev.status_code == 200
    prev_data = res_prev.json()
    assert prev_data["status"] == "success"
    assert "preview_url" in prev_data
    assert "draft_filename" in prev_data

    # Test GET PDF endpoint
    res_pdf = client.get(prev_data["preview_url"])
    assert res_pdf.status_code == 200
    assert res_pdf.headers["content-type"] == "application/pdf"

    # Cleanup draft file
    from app.config import settings
    draft_path = os.path.join(settings.PDF_OUTPUT_DIR, prev_data["draft_filename"])
    if os.path.exists(draft_path):
        os.remove(draft_path)

    app.dependency_overrides.clear()


def test_whatsapp_button_title_truncation():
    from app.services.whatsapp import whatsapp_service
    res = whatsapp_service.send_buttons(
        to="919876543210",
        text="Choose:",
        buttons=[
            {"id": "btn_long", "title": "This is a very long button title exceeding twenty characters"}
        ]
    )
    assert res is not None


def test_warranty_calculator_boundary_cases():
    # Jan 31 sale with 2 months warranty -> exp Mar 1 (Feb has 28 days)
    # Remaining warranty must never contain negative numbers or fail
    res = calculate_remaining_warranty(date(2026, 1, 31), "2 Months")
    assert "left" in res or "Expired" in res or "Active" in res
    assert "-" not in res.replace("Expired", "")


def test_product_deletion_with_historical_sales(db_session):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    # 1. Add product
    prod = Product(name="Safe Delete Bulb", category="Bulb", default_price=120.0, is_active=True)
    db_session.add(prod)
    db_session.commit()

    # 2. Add historical sale referencing this product
    sale = Sale(invoice_number="RM-20260719-0999", sale_date=date.today(), total_amount=120.0)
    db_session.add(sale)
    db_session.flush()

    item = SaleItem(sale_id=sale.id, product_name="Safe Delete Bulb", product_id=prod.id, quantity=1, price=120.0, warranty_info="1 Year")
    db_session.add(item)
    db_session.commit()

    # 3. Attempt delete: should soft-deactivate instead of raising Foreign Key constraint crash
    del_res = client.delete(f"/api/web/products/{prod.id}")
    assert del_res.status_code == 200
    db_session.refresh(prod)
    assert prod.is_active == False

    app.dependency_overrides.clear()


def test_sale_repository_custom_invoice_number(db_session):
    from app.repositories.sale import SaleRepository
    repo = SaleRepository(db_session)
    sale = repo.create(
        sale_date=date.today(),
        total_amount=250.0,
        invoice_number="RM-CUSTOM-0001",
        items_data=[{"product_name": "Test Item", "quantity": 1, "price": 250.0, "warranty_info": "1 Year"}]
    )
    assert sale.invoice_number == "RM-CUSTOM-0001"


# =====================================================================
# STATE MACHINE ROBUSTNESS & REGRESSION TESTS
# =====================================================================

def test_active_ticket_bypasses_bot_paused(db_session):
    """
    Bug Group A: Active ticket messages must bypass bot_paused_until.
    Ensures customer responses during open support tickets are never dropped.
    """
    from app.models.admin import Admin
    from app.services.whatsapp import whatsapp_service
    
    admin = Admin(phone_number="919876543210", name="Shop Owner")
    c1 = Customer(
        phone_number="919999999991",
        name="Ticket Customer",
        ticket_active=True,
        notifications_enabled=True,
        ticket_number="TKT-9999",
        last_ticket_activity=datetime.utcnow() - timedelta(minutes=15),
        bot_paused_until=datetime.utcnow() + timedelta(hours=1)
    )
    db_session.add(admin)
    db_session.add(c1)
    db_session.commit()
    
    old_msg_count = len(whatsapp_service.recent_sent_message_ids)
    sm = StateMachineService(db_session)
    sm.process_message(phone_number="919999999991", message_text="I need help with my LED light warranty")
    
    db_session.refresh(c1)
    # Message was NOT ignored despite bot_paused_until
    assert len(whatsapp_service.recent_sent_message_ids) > old_msg_count
    # Activity timestamp was refreshed
    assert (datetime.utcnow() - c1.last_ticket_activity).total_seconds() < 10
    # Ticket remains active
    assert c1.ticket_active is True


def test_webhook_inbound_deduplication(db_session):
    """
    Bug Group B: Inbound webhook idempotency.
    Meta webhook delivery retries with duplicate wamid must be deduplicated.
    """
    import asyncio
    from unittest.mock import patch
    from app.routers.webhook import handle_webhook, processed_inbound_message_ids, processed_inbound_message_set
    
    processed_inbound_message_ids.clear()
    processed_inbound_message_set.clear()
    
    class MockRequest:
        def __init__(self, json_data):
            self.json_data = json_data
        async def json(self):
            return self.json_data
            
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": "wamid.RETRY_TEST_UNIQUE_ID_001",
                        "from": "919999999992",
                        "type": "text",
                        "text": {"body": "Test duplicate webhook"}
                    }]
                }
            }]
        }]
    }
    
    with patch.object(StateMachineService, "process_message") as mock_process:
        # First delivery
        asyncio.run(handle_webhook(MockRequest(payload), db_session))
        assert mock_process.call_count == 1
        
        # Second delivery (retry with identical message id)
        asyncio.run(handle_webhook(MockRequest(payload), db_session))
        # Must still be called only once
        assert mock_process.call_count == 1


def test_ticket_auto_close_with_null_activity(db_session):
    """
    Bug Group C: Auto-close job handles tickets with last_ticket_activity IS NULL.
    """
    from app.models.admin import Admin
    from app.services import scheduler
    
    admin = Admin(phone_number="919876543210", name="Shop Owner")
    c1 = Customer(
        phone_number="919888888887",
        name="Null Activity Customer",
        ticket_active=True,
        notifications_enabled=True,
        ticket_number="TKT-NULL-1",
        last_ticket_activity=None
    )
    db_session.add(admin)
    db_session.add(c1)
    db_session.commit()
    
    orig_session_local = scheduler.SessionLocal
    scheduler.SessionLocal = TestingSessionLocal
    try:
        check_inactive_tickets_job()
    finally:
        scheduler.SessionLocal = orig_session_local
        
    db_session.refresh(c1)
    assert c1.ticket_active is False
    assert c1.notifications_enabled is False


def test_sale_preview_does_not_mutate_customer_before_confirmation(db_session):
    """
    Bug Group D: Premature customer mutation in sale preview.
    Entering SALE_CONFIRM_PREVIEW for a new customer must not create a record
    in the database until SALE_SHOW_PDF_PREVIEW is explicitly confirmed.
    """
    from unittest.mock import patch
    from app.models.admin import Admin
    from app.services.state_machine import (
        SALE_ASK_CUSTOMER_PHONE,
        SALE_ASK_CUSTOMER_NAME,
        SALE_CONFIRM_PREVIEW,
        SALE_SHOW_PDF_PREVIEW,
        STATE_IDLE
    )
    from app.services.pdf_generator import PDFGenerator
    
    admin = Admin(phone_number="919876543210", name="Shop Owner")
    prod = Product(name="Syska 12W LED", category="Bulb", default_price=150.0, is_active=True)
    db_session.add(admin)
    db_session.add(prod)
    db_session.commit()
    
    new_phone = "919123456789"
    assert db_session.query(Customer).filter_by(phone_number=new_phone).first() is None
    
    sm = StateMachineService(db_session)
    cart_item = {"product_name": prod.name, "product_id": prod.id, "quantity": 1, "price": 150.0, "warranty_info": "1 Year"}
    data = {"cart": [cart_item], "sale_date": date.today().isoformat()}
    
    # 1. Enter customer phone
    sm.state_repo.save(admin.phone_number, SALE_ASK_CUSTOMER_PHONE, data)
    sm.process_message(phone_number=admin.phone_number, message_text="9123456789")
    
    state_obj = sm.state_repo.get(admin.phone_number)
    assert state_obj.state == SALE_ASK_CUSTOMER_NAME
    assert db_session.query(Customer).filter_by(phone_number=new_phone).first() is None
    
    # 2. Enter customer name -> transitions to SALE_CONFIRM_PREVIEW
    sm.process_message(phone_number=admin.phone_number, message_text="Alice In Wonderland")
    state_obj = sm.state_repo.get(admin.phone_number)
    assert state_obj.state == SALE_CONFIRM_PREVIEW
    # Customer MUST NOT exist in DB yet
    assert db_session.query(Customer).filter_by(phone_number=new_phone).first() is None
    
    # 3. Simulate cancelling preview -> resets to IDLE, customer still not created
    sm.process_message(phone_number=admin.phone_number, message_text="cancel")
    state_obj = sm.state_repo.get(admin.phone_number)
    assert state_obj is None or state_obj.state == STATE_IDLE
    assert db_session.query(Customer).filter_by(phone_number=new_phone).first() is None
    
    # 4. Now test the confirmation path
    data["customer_phone"] = new_phone
    data["customer_name"] = "Alice In Wonderland"
    sm.state_repo.save(admin.phone_number, SALE_CONFIRM_PREVIEW, data)
    
    with patch.object(PDFGenerator, "generate_invoice", return_value="dummy_path.pdf"), \
         patch("app.services.whatsapp.whatsapp_service.upload_media", return_value="mock_media_123"):
        # Admin selects 1 (Generate PDF preview)
        sm.process_message(phone_number=admin.phone_number, message_text="1")
        
        state_obj = sm.state_repo.get(admin.phone_number)
        assert state_obj.state == SALE_SHOW_PDF_PREVIEW
        # Customer still not created prior to invoice confirmation
        assert db_session.query(Customer).filter_by(phone_number=new_phone).first() is None
        
        # Admin confirms send invoice
        sm.process_message(phone_number=admin.phone_number, button_id="pdf_send_customer")
        
        # Now customer MUST be created in DB!
        created_cust = db_session.query(Customer).filter_by(phone_number=new_phone).first()
        assert created_cust is not None
        assert created_cust.name == "Alice In Wonderland"
        
        # Verify sale is recorded
        sales = sm.sale_repo.get_by_customer_id(created_cust.id)
        assert len(sales) == 1
        assert sales[0].total_amount == 150.0


def test_admin_idle_menu_with_active_ticket(db_session):
    """
    Bug Group E: Admin typing 'menu' in STATE_IDLE opens main menu
    even when an active customer ticket exists.
    """
    from unittest.mock import patch
    from app.models.admin import Admin
    from app.services.whatsapp import whatsapp_service
    
    admin = Admin(phone_number="919876543210", name="Shop Owner")
    c1 = Customer(
        phone_number="919888888886",
        name="Active Ticket Customer",
        ticket_active=True,
        notifications_enabled=True,
        ticket_number="TKT-ACTIVE-1",
        last_ticket_activity=datetime.utcnow()
    )
    db_session.add(admin)
    db_session.add(c1)
    db_session.commit()
    
    sm = StateMachineService(db_session)
    with patch.object(whatsapp_service, "send_list") as mock_list, \
         patch.object(whatsapp_service, "send_text") as mock_text:
        sm.process_message(phone_number=admin.phone_number, message_text="menu")
        
        # Admin main menu must be sent
        mock_list.assert_called_once()
        args = mock_list.call_args[0]
        assert args[0] == admin.phone_number
        assert "BizPilot Automation" in args[1]
        
        # "menu" must NOT be forwarded to customer
        for call in mock_text.call_args_list:
            if call[1].get("to") == c1.phone_number or (call[0] and call[0][0] == c1.phone_number):
                text_sent = call[1].get("text") or call[0][1]
                assert "menu" not in text_sent.lower()


def test_primary_admin_protected_from_deletion(db_session):
    """
    Bug Group E: Primary admin cannot be deleted or listed in removal UI.
    """
    from unittest.mock import patch
    from app.config import settings
    from app.models.admin import Admin
    from app.services.whatsapp import whatsapp_service
    from app.utils.phone import clean_phone_number
    from app.services.state_machine import ADMIN_MAIN, ADMIN_REMOVE_SELECT
    
    primary_clean = clean_phone_number(settings.PRIMARY_ADMIN_PHONE)
    primary_admin = Admin(phone_number=primary_clean, name="Primary Admin")
    secondary_admin = Admin(phone_number="919888888881", name="Secondary Admin")
    third_admin = Admin(phone_number="919888888882", name="Third Admin")
    db_session.add(primary_admin)
    db_session.add(secondary_admin)
    db_session.add(third_admin)
    db_session.commit()
    
    sm = StateMachineService(db_session)
    
    # 1. Admin 3 views removal list
    sm.state_repo.save(third_admin.phone_number, ADMIN_MAIN, {})
    with patch.object(whatsapp_service, "send_list") as mock_list:
        sm.process_message(phone_number=third_admin.phone_number, button_id="adm_remove")
        mock_list.assert_called_once()
        call_sections = mock_list.call_args[0][4]
        listed_ids = [row["id"] for row in call_sections[0]["rows"]]
        assert f"adm_rem_{primary_clean}" not in listed_ids
        assert "adm_rem_919888888881" in listed_ids
        
    # 2. Forged payload targeting primary admin
    sm.state_repo.save(third_admin.phone_number, ADMIN_REMOVE_SELECT, {})
    with patch.object(whatsapp_service, "send_text") as mock_text:
        sm.process_message(phone_number=third_admin.phone_number, button_id=f"adm_rem_{primary_clean}")
        assert db_session.query(Admin).filter_by(phone_number=primary_clean).first() is not None
        sent_msg = mock_text.call_args_list[0][0][1]
        assert "Primary Administrator cannot be removed" in sent_msg






