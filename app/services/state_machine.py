import logging
from datetime import datetime, date
import re
import os
import time

from sqlalchemy.orm import Session
from app.config import settings
from app.repositories.admin import AdminRepository
from app.repositories.customer import CustomerRepository
from app.repositories.product import ProductRepository
from app.repositories.sale import SaleRepository
from app.repositories.conversation_state import ConversationStateRepository
from app.models.broadcast import Broadcast
from app.models.customer import Customer
from app.services.whatsapp import whatsapp_service
from app.services.sheets import sheets_service
from app.services.pdf_generator import PDFGenerator
from app.utils.fuzzy import match_products
from app.utils.phone import clean_phone_number
from app.utils.casing import to_title_case, capitalize_sentences, calculate_remaining_warranty
from app.services.gemini import gemini_service

logger = logging.getLogger(__name__)

# Core Conversation States
STATE_IDLE = "STATE_IDLE"

# Sale Flow States
SALE_ASK_PRODUCT_NAME = "SALE_ASK_PRODUCT_NAME"
SALE_CONFIRM_PRODUCT_MATCH = "SALE_CONFIRM_PRODUCT_MATCH"
SALE_SELECT_PRODUCT_MATCH = "SALE_SELECT_PRODUCT_MATCH"
SALE_ASK_QUANTITY = "SALE_ASK_QUANTITY"
SALE_ASK_PRICE = "SALE_ASK_PRICE"
SALE_ASK_WARRANTY = "SALE_ASK_WARRANTY"
SALE_ASK_CUSTOM_WARRANTY = "SALE_ASK_CUSTOM_WARRANTY"
SALE_ASK_ADD_ANOTHER = "SALE_ASK_ADD_ANOTHER"
SALE_ASK_DATE = "SALE_ASK_DATE"
SALE_ASK_CUSTOM_DATE = "SALE_ASK_CUSTOM_DATE"
SALE_ASK_GENERATE_INVOICE = "SALE_ASK_GENERATE_INVOICE"
SALE_ASK_CUSTOMER_PHONE = "SALE_ASK_CUSTOMER_PHONE"
SALE_CONFIRM_CUSTOMER_NAME = "SALE_CONFIRM_CUSTOMER_NAME"
SALE_ASK_CUSTOMER_NAME = "SALE_ASK_CUSTOMER_NAME"
SALE_CONFIRM_PREVIEW = "SALE_CONFIRM_PREVIEW"
SALE_SHOW_PDF_PREVIEW = "SALE_SHOW_PDF_PREVIEW"

# Broadcast Flow States
BROADCAST_ASK_TYPE = "BROADCAST_ASK_TYPE"
BROADCAST_ASK_CONTENT = "BROADCAST_ASK_CONTENT"
BROADCAST_PREVIEW_REFORMAT = "BROADCAST_PREVIEW_REFORMAT"
BROADCAST_ASK_IMAGE = "BROADCAST_ASK_IMAGE"
BROADCAST_PREVIEW = "BROADCAST_PREVIEW"

# Search Customer Flow States
SEARCH_CUSTOMER_ASK_QUERY = "SEARCH_CUSTOMER_ASK_QUERY"
SEARCH_CUSTOMER_SHOW_RESULTS = "SEARCH_CUSTOMER_SHOW_RESULTS"

# Catalogue Flow States
CATALOGUE_MAIN = "CATALOGUE_MAIN"
CATALOGUE_ADD_NAME = "CATALOGUE_ADD_NAME"
CATALOGUE_ADD_CATEGORY = "CATALOGUE_ADD_CATEGORY"
CATALOGUE_ADD_PRICE = "CATALOGUE_ADD_PRICE"
CATALOGUE_REMOVE_SELECT = "CATALOGUE_REMOVE_SELECT"

# Admin Management Flow States
ADMIN_MAIN = "ADMIN_MAIN"
ADMIN_ADD_PHONE = "ADMIN_ADD_PHONE"
ADMIN_ADD_NAME = "ADMIN_ADD_NAME"
ADMIN_REMOVE_SELECT = "ADMIN_REMOVE_SELECT"

# Reports Flow States
REPORT_SELECT = "REPORT_SELECT"


class StateMachineService:
    def __init__(self, db: Session):
        self.db = db
        self.admin_repo = AdminRepository(db)
        self.customer_repo = CustomerRepository(db)
        self.product_repo = ProductRepository(db)
        self.sale_repo = SaleRepository(db)
        self.state_repo = ConversationStateRepository(db)

    def process_message(self, phone_number: str, message_text: str = None, button_id: str = None, media_id: str = None) -> None:
        phone_number = clean_phone_number(phone_number)
        admin = self.admin_repo.get_by_phone(phone_number)
        
        # Bootstrap primary admin
        primary_admin_clean = clean_phone_number(settings.PRIMARY_ADMIN_PHONE)
        if phone_number == primary_admin_clean and not admin:
            admin = self.admin_repo.create(phone_number, "Primary Admin")
            logger.info(f"Bootstrapped primary admin: {phone_number}")

        if admin:
            self._handle_admin_flow(admin, message_text, button_id, media_id)
        else:
            self._handle_customer_flow(phone_number, message_text, button_id)

    def _notify_admins_of_optin(self, customer_phone: str, customer_name: str) -> None:
        try:
            admins = self.admin_repo.get_all()
            for adm in admins:
                whatsapp_service.send_text(
                    to=adm.phone_number,
                    text=f"📢 Info: Customer {to_title_case(customer_name)} ({customer_phone}) has opted-in/subscribed to promotional messages."
                )
        except Exception as e:
            logger.error(f"Error sending admin opt-in notification: {e}")

    # ==========================================
    # CUSTOMER FLOW
    # ==========================================
    def _send_customer_main_menu(self, phone_number: str) -> None:
        title = "BizPilot Store Menu"
        body = (
            "🌟 *Welcome to BizPilot!*\n"
            "Your trusted store for electronics, appliances, and retail goods.\n\n"
            "How can we serve you today? Please tap the button below to browse options:"
        )
        button_text = "Select Option"
        
        sections = [
            {
                "title": "Shop & Catalog",
                "rows": [
                    {"id": "cust_menu_catalogue", "title": "View Catalogue", "description": "Download our latest product catalogue PDF"},
                    {"id": "cust_menu_info", "title": "My Profile Info", "description": "View details & order history"},
                    {"id": "cust_menu_talk_owner", "title": "Talk to Owner", "description": "Open a support ticket to chat with us"}
                ]
            },
            {
                "title": "Subscriptions",
                "rows": [
                    {"id": "cust_menu_subscribe", "title": "Subscribe Updates", "description": "Get notifications of sales & offers"},
                    {"id": "cust_menu_unsubscribe", "title": "Unsubscribe", "description": "Stop promotional updates"}
                ]
            }
        ]
        whatsapp_service.send_list(phone_number, title, capitalize_sentences(body), button_text, sections)

    def _handle_customer_flow(self, phone_number: str, message_text: str = None, button_id: str = None) -> None:
        raw_text = (message_text or "").strip()
        text = raw_text.upper()
        
        # Check if customer exists in DB, if not create with notifications OFF by default
        customer = self.customer_repo.get_by_phone(phone_number)
        if not customer:
            customer = self.customer_repo.create(phone_number, "Subscriber", is_subscribed=False)

        # 1. Ticketing system chat session (active ticket conversation always handled)
        if customer.ticket_active:
            if button_id == "customer_close_ticket" or text == "CLOSE":
                self.customer_repo.update_ticket_status(phone_number, ticket_active=False, notifications_enabled=False)
                whatsapp_service.send_text(phone_number, capitalize_sentences("Your support ticket has been closed. Thank you! Returning to main menu."))
                
                # Notify admins
                admins = self.admin_repo.get_all()
                for admin in admins:
                    whatsapp_service.send_text(
                        admin.phone_number, 
                        f"🎟️ Ticket #{customer.ticket_number} for customer {customer.name} ({customer.phone_number}) was closed by the customer."
                    )
                self._send_customer_main_menu(phone_number)
                return
            elif button_id or text in ["MENU", "STOP", "START"] or button_id in ["cust_menu_catalogue", "cust_menu_info", "cust_menu_talk_owner", "cust_menu_subscribe", "cust_menu_unsubscribe", "cust_menu_past_purchases", "customer_optout", "customer_menu"]:
                # Close the ticket if they use list navigation/opt-out button replies
                self.customer_repo.update_ticket_status(phone_number, ticket_active=False, notifications_enabled=False)
                admins = self.admin_repo.get_all()
                for admin in admins:
                    whatsapp_service.send_text(
                        admin.phone_number, 
                        f"🎟️ Ticket #{customer.ticket_number} closed automatically because the customer selected a menu option."
                    )
                # Fall through to let the standard menu handler process the selection!
            else:
                # Inside active ticket: forward message to owners (admins)
                admins = self.admin_repo.get_all()
                for admin in admins:
                    whatsapp_service.send_text(
                        admin.phone_number, 
                        f"💬 Ticket #{customer.ticket_number} - {customer.name} ({customer.phone_number}):\n{raw_text}"
                    )
                # Update activity time
                self.customer_repo.update_ticket_status(phone_number, ticket_active=True, notifications_enabled=True)
                whatsapp_service.send_text(phone_number, "Message forwarded to owner. 📨 (Type 'close' to end this ticket)")
                return

        # Explicit commands or interactive button clicks clear/bypass the temporary silence
        if button_id or text in ["MENU", "START", "STOP", "HELLO", "HI"]:
            if customer.bot_paused_until:
                customer.bot_paused_until = None
                self.db.commit()
        elif customer.bot_paused_until and datetime.utcnow() < customer.bot_paused_until:
            logger.info(f"Bot is temporarily paused/silenced for customer {phone_number} until {customer.bot_paused_until}. Message ignored.")
            return

        # 2. Main Menu Actions & Interactions
        if button_id == "customer_menu" or text == "MENU" or button_id == "customer_optin" or text in ["HELLO", "HI"]:
            self._send_customer_main_menu(phone_number)
            return

        elif button_id == "cust_menu_catalogue":
            whatsapp_service.send_text(phone_number, "Generating product catalogue PDF, please wait...")
            active_prods = self.product_repo.get_all_active()
            path = PDFGenerator.generate_catalogue(active_prods)
            try:
                media_id = whatsapp_service.upload_media(path, "application/pdf")
                whatsapp_service.send_document(
                    to=phone_number,
                    media_id=media_id,
                    filename=os.path.basename(path),
                    caption="Here is our latest product catalogue."
                )
            except Exception as e:
                logger.error(f"Error sending catalog PDF: {e}", exc_info=True)
                whatsapp_service.send_text(phone_number, "⚠️ Sorry, there was an error generating the catalogue file. Please contact store support.")
            return

        elif button_id == "cust_menu_info":
            stats = self.sale_repo.get_customer_stats(customer.id)
            phone_num = customer.phone_number
            if phone_num.startswith("91") and len(phone_num) == 12:
                formatted_phone = f"+91 {phone_num[2:7]} {phone_num[7:]}"
            else:
                formatted_phone = phone_num
            profile_msg = (
                f"👤 *YOUR PROFILE*\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📝 *Name:* {to_title_case(customer.name)}\n"
                f"📞 *Phone:* {formatted_phone}\n"
                f"📢 *Promotions:* {'Subscribed' if customer.is_subscribed else 'Unsubscribed'}\n"
                f"📅 *Registered:* {customer.created_at.strftime('%d-%b-%Y') if customer.created_at else 'N/A'}\n\n"
                f"📊 *PURCHASE STATS*\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🛍️ *Total Orders:* {stats['purchase_count']}\n"
                f"💰 *Lifetime Spent:* Rs. {stats['lifetime_value']:.2f}"
            )
            buttons = [
                {"id": "cust_menu_past_purchases", "title": "Past Purchases"},
                {"id": "customer_menu", "title": "Main Menu"}
            ]
            whatsapp_service.send_buttons(phone_number, profile_msg, buttons)
            return

        elif button_id == "cust_menu_past_purchases" or button_id == "customer_past_purchases" or text == "PAST PURCHASES":
            sales = self.sale_repo.get_by_customer_id(customer.id)
            if not sales:
                whatsapp_service.send_text(phone_number, "You do not have any past purchases recorded yet.")
                self._send_customer_main_menu(phone_number)
                return
                
            history_msg = "📜 *PURCHASE HISTORY & WARRANTIES*\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            for idx, sale in enumerate(sales, 1):
                items_str = ", ".join([f"{to_title_case(item.product_name)} (x{item.quantity})" for item in sale.items])
                history_msg += (
                    f"📄 *Invoice:* {sale.invoice_number}\n"
                    f"📅 *Date:* {sale.sale_date.strftime('%d-%b-%Y')}\n"
                    f"🛍️ *Products:* {items_str}\n"
                    f"💰 *Amount:* Rs. {sale.total_amount:.2f}\n"
                    f"🛡️ *Warranty Status*:\n"
                )
                for item in sale.items:
                    rem_warranty = calculate_remaining_warranty(sale.sale_date, item.warranty_info)
                    history_msg += (
                        f" • {to_title_case(item.product_name)}: {item.warranty_info}\n"
                        f"   └─ _{rem_warranty}_\n"
                    )
                history_msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
            buttons = [
                {"id": "customer_menu", "title": "Main Menu"}
            ]
            whatsapp_service.send_buttons(phone_number, history_msg, buttons)
            return

        elif button_id == "cust_menu_subscribe" or text == "START" or button_id == "optin_yes":
            self.customer_repo.update_subscription(phone_number, subscribe=True)
            whatsapp_service.send_text(
                phone_number, 
                capitalize_sentences("Thank you! You have been subscribed to promotional updates. You can reply 'STOP' at any time to unsubscribe.")
            )
            self._notify_admins_of_optin(phone_number, customer.name)
            return

        elif button_id == "cust_menu_unsubscribe" or text == "STOP" or button_id == "optin_no" or button_id == "customer_optout":
            self.customer_repo.update_subscription(phone_number, subscribe=False)
            whatsapp_service.send_text(
                phone_number, 
                capitalize_sentences("You have been unsubscribed from promotional updates. You will not receive further broadcasts from us.")
            )
            return

        elif button_id == "cust_menu_talk_owner":
            ticket_num = f"TKT-{phone_number[-4:]}-{int(time.time()) % 10000:04d}"
            
            # Enable ticket & notifications!
            self.customer_repo.update_ticket_status(phone_number, ticket_active=True, notifications_enabled=True, ticket_number=ticket_num)
            
            whatsapp_service.send_text(
                phone_number, 
                f"🎟️ *Ticket #{ticket_num} Started*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Please type your query or support message below. The owner will review and reply directly to you here.\n\n"
                f"💡 _Tip: Reply 'close' at any time to end this support session._"
            )
            
            # Send message to all admins with close ticket button
            admins = self.admin_repo.get_all()
            for admin in admins:
                whatsapp_service.send_buttons(
                    to=admin.phone_number,
                    text=(
                        f"🎟️ Support Ticket Open: #{ticket_num}\n"
                        f"Customer: {customer.name} ({customer.phone_number})\n\n"
                        f"Chat notifications are now ON for this customer. To chat with them, just reply here. Click below to close the ticket when resolved:"
                    ),
                    buttons=[
                        {"id": f"close_ticket_{phone_number}", "title": "Close Ticket"}
                    ]
                )
            return

        # Default fallback: Greeting and main menu entry button
        greeting = (
            f"👋 *Hello {to_title_case(customer.name or 'there')}!*\n\n"
            f"Welcome to *BizPilot*. We offer high-quality electronics, appliances, and retail goods. 🌟\n\n"
            f"Please tap the button below to open our main menu and browse our services."
        )
        buttons = [
            {"id": "customer_menu", "title": "Open Menu"}
        ]
        whatsapp_service.send_buttons(phone_number, capitalize_sentences(greeting), buttons)


    # ==========================================
    # ADMIN FLOW
    # ==========================================
    def _handle_admin_flow(self, admin, message_text: str = None, button_id: str = None, media_id: str = None) -> None:
        phone_number = admin.phone_number
        db_state = self.state_repo.get(phone_number)
        
        # Close Ticket action triggered by admin button
        if button_id and button_id.startswith("close_ticket_"):
            cust_phone = button_id.replace("close_ticket_", "")
            customer = self.customer_repo.get_by_phone(cust_phone)
            if customer:
                self.customer_repo.update_ticket_status(cust_phone, ticket_active=False, notifications_enabled=False)
                whatsapp_service.send_text(phone_number, f"✅ Support Ticket #{customer.ticket_number} for customer {customer.name} ({cust_phone}) has been closed.")
                
                # Notify customer
                whatsapp_service.send_buttons(
                    to=cust_phone,
                    text="The shop owner has closed this support ticket chat. If you need further assistance, please open the menu.",
                    buttons=[
                        {"id": "customer_menu", "title": "Open Menu"}
                    ]
                )
            else:
                whatsapp_service.send_text(phone_number, "Error: Customer profile not found.")
            return

        import copy
        current_state = db_state.state if db_state else STATE_IDLE
        state_data = copy.deepcopy(db_state.data) if (db_state and db_state.data) else {}

        text = (message_text or "").strip().lower()
        if text == "cancel" or button_id == "global_cancel":
            self.state_repo.delete(phone_number)
            whatsapp_service.send_text(phone_number, "Operation cancelled. Back to main menu.")
            self._send_admin_main_menu(phone_number)
            return

        if current_state == STATE_IDLE:
            self._process_admin_idle(phone_number, text, button_id, raw_text=message_text)
            return

        if current_state.startswith("SALE_"):
            self._process_sale_flow(phone_number, current_state, state_data, text, button_id)
        elif current_state.startswith("BROADCAST_"):
            self._process_broadcast_flow(phone_number, current_state, state_data, text, button_id, media_id, admin.id)
        elif current_state.startswith("SEARCH_CUSTOMER_"):
            self._process_search_customer_flow(phone_number, current_state, state_data, text, button_id)
        elif current_state.startswith("CATALOGUE_"):
            self._process_catalogue_flow(phone_number, current_state, state_data, text, button_id)
        elif current_state.startswith("ADMIN_"):
            self._process_admin_management_flow(phone_number, current_state, state_data, text, button_id)
        elif current_state.startswith("REPORT_"):
            self._process_report_flow(phone_number, current_state, state_data, text, button_id)
        else:
            logger.warning(f"Unknown state: {current_state}. Resetting to idle.")
            self.state_repo.delete(phone_number)
            self._send_admin_main_menu(phone_number)

    # ==========================================
    # MENU ROUTING
    # ==========================================
    def _send_admin_main_menu(self, to: str) -> None:
        title = "BizPilot Automation"
        body = "Welcome to the Admin Main Menu. Please choose an operation:"
        button_text = "Select Option"
        
        sections = [
            {
                "title": "Shop Operations",
                "rows": [
                    {"id": "menu_record_sale", "title": "Record Sale", "description": "Log sales & send customer invoices"},
                    {"id": "menu_broadcast", "title": "Broadcast", "description": "Send promotional messages to list"},
                    {"id": "menu_search_customer", "title": "Search Customer", "description": "Lookup history and stats"},
                    {"id": "menu_manage_catalogue", "title": "Manage Catalogue", "description": "Sync or modify catalog items"},
                    {"id": "menu_view_reports", "title": "Reports & Exports", "description": "View reports and export data"},
                    {"id": "menu_admin_management", "title": "Admin Management", "description": "Add or remove system admins"}
                ]
            }
        ]
        
        self.state_repo.save(to, STATE_IDLE, {})
        whatsapp_service.send_list(to, title, body, button_text, sections)

    def _process_admin_idle(self, phone_number: str, text: str, button_id: str, raw_text: str = None) -> None:
        if button_id == "menu_record_sale" or text == "1" or "record" in text:
            self.state_repo.save(phone_number, SALE_ASK_PRODUCT_NAME, {"cart": []})
            whatsapp_service.send_text(phone_number, "=== Record Sale ===\n\nEnter product name (or type 'cancel' to exit):")
            
        elif button_id == "menu_broadcast" or text == "2" or "broadcast" in text:
            self.state_repo.save(phone_number, BROADCAST_ASK_TYPE, {})
            buttons = [
                {"id": "bc_type_sale", "title": "Sale Offer"},
                {"id": "bc_type_product", "title": "New Product"},
                {"id": "bc_type_custom", "title": "Custom Message"}
            ]
            whatsapp_service.send_buttons(phone_number, "Select broadcast type:", buttons)
            
        elif button_id == "menu_search_customer" or text == "3" or "search" in text:
            self.state_repo.save(phone_number, SEARCH_CUSTOMER_ASK_QUERY, {})
            whatsapp_service.send_text(phone_number, "=== Customer Search ===\n\nEnter phone number or customer name (or type 'cancel' to exit):")
            
        elif button_id == "menu_manage_catalogue" or text == "4" or "catalogue" in text:
            self.state_repo.save(phone_number, CATALOGUE_MAIN, {})
            buttons = [
                {"id": "cat_sync", "title": "Sync from Sheet"},
                {"id": "cat_add", "title": "Add Product"},
                {"id": "cat_remove", "title": "Remove Product"}
            ]
            whatsapp_service.send_buttons(phone_number, "=== Catalogue Management ===\n\nChoose an action:", buttons)
            
        elif button_id == "menu_view_reports" or text == "5" or "report" in text:
            self.state_repo.save(phone_number, REPORT_SELECT, {})
            sections = [
                {
                    "title": "Analytical Reports",
                    "rows": [
                        {"id": "rpt_weekly", "title": "Weekly Report", "description": "Last 7 days store analytics"},
                        {"id": "rpt_monthly", "title": "Monthly Report", "description": "Last 30 days store analytics"}
                    ]
                },
                {
                    "title": "Data Exports",
                    "rows": [
                        {"id": "rpt_export_cust", "title": "Customer List (Excel)", "description": "Export all customer data to Excel"},
                        {"id": "rpt_export_prod", "title": "Product List (Excel)", "description": "Export product catalogue to Excel"}
                    ]
                },
                {
                    "title": "Actions",
                    "rows": [
                        {"id": "global_cancel", "title": "Main Menu", "description": "Return to main menu"}
                    ]
                }
            ]
            whatsapp_service.send_list(phone_number, "Reports & Exports", "Choose a report or export action:", "Select Option", sections)
            
        elif button_id == "menu_admin_management" or text == "6" or "admin" in text:
            self.state_repo.save(phone_number, ADMIN_MAIN, {})
            buttons = [
                {"id": "adm_list", "title": "List Admins"},
                {"id": "adm_add", "title": "Add Admin"},
                {"id": "adm_remove", "title": "Remove Admin"}
            ]
            whatsapp_service.send_buttons(phone_number, "=== Admin Management ===\n\nChoose an action:", buttons)
            
        elif button_id in ["admin_menu", "global_cancel"] or text in ["menu", "main menu"]:
            self._send_admin_main_menu(phone_number)
            return

        else:
            # Check if there's an active ticket we can forward this message to
            active_customers = self.db.query(Customer).filter(Customer.ticket_active == True).order_by(Customer.last_ticket_activity.desc()).all()
            if active_customers and raw_text:
                active_customer = active_customers[0]
                # Forward to customer
                whatsapp_service.send_text(
                    to=active_customer.phone_number,
                    text=f"✉️ Message from Owner:\n{raw_text}"
                )
                # Also notify the admin that it was forwarded
                note = f" (Note: {len(active_customers)} active tickets open)" if len(active_customers) > 1 else ""
                whatsapp_service.send_text(
                    to=phone_number,
                    text=f"✅ Message forwarded to {active_customer.name} ({active_customer.phone_number}).{note}"
                )
                # Update activity time
                self.customer_repo.update_ticket_status(
                    active_customer.phone_number,
                    ticket_active=True,
                    notifications_enabled=True
                )
            else:
                self._send_admin_main_menu(phone_number)

    # ==========================================
    # SALE FLOW PROCESSING
    # ==========================================
    def _process_sale_flow(self, phone_number: str, state: str, data: dict, text: str, button_id: str) -> None:
        if state == SALE_ASK_PRODUCT_NAME:
            typed_name = text
            if not typed_name:
                whatsapp_service.send_text(phone_number, "Please enter a valid product name (or type 'cancel' to exit):")
                return

            active_products = self.product_repo.get_all_active()
            matches = match_products(typed_name, active_products, limit=3, score_cutoff=50.0)

            if len(matches) == 1 and matches[0][1] >= 85.0:
                matched_prod, score = matches[0]
                data["current_item"] = {
                    "product_name": matched_prod.name,
                    "product_id": matched_prod.id,
                    "default_price": float(matched_prod.default_price)
                }
                self.state_repo.save(phone_number, SALE_CONFIRM_PRODUCT_MATCH, data)
                buttons = [
                    {"id": "sale_match_yes", "title": "YES"},
                    {"id": "sale_match_no", "title": "NO"},
                    {"id": "global_cancel", "title": "CANCEL"}
                ]
                whatsapp_service.send_buttons(phone_number, f"Did you mean:\n{matched_prod.name}", buttons)
                
            elif len(matches) > 1:
                data["temp_typed_name"] = typed_name
                data["temp_matches"] = [
                    {"id": str(p.id), "name": p.name, "default_price": float(p.default_price)} for p, score in matches
                ]
                self.state_repo.save(phone_number, SALE_SELECT_PRODUCT_MATCH, data)
                
                rows = []
                for p, score in matches:
                    rows.append({
                        "id": f"sale_select_{p.id}",
                        "title": p.name[:24],
                        "description": f"Price: Rs. {float(p.default_price):.2f}"
                    })
                rows.append({
                    "id": "sale_select_typed",
                    "title": "Use entered text",
                    "description": f"Use '{typed_name}'"
                })
                rows.append({
                    "id": "global_cancel",
                    "title": "Cancel Sale",
                    "description": "Exit sale recording"
                })
                sections = [{"title": "Matches found", "rows": rows}]
                whatsapp_service.send_list(phone_number, "Select Product", "Multiple matches found. Choose one:", "Options", sections)
            else:
                data["current_item"] = {
                    "product_name": typed_name,
                    "product_id": None,
                    "default_price": 0.0
                }
                self.state_repo.save(phone_number, SALE_ASK_QUANTITY, data)
                whatsapp_service.send_text(phone_number, f"Product: {to_title_case(typed_name)}\n\nEnter quantity (or type 'cancel' to exit):")

        elif state == SALE_CONFIRM_PRODUCT_MATCH:
            if button_id == "sale_match_yes" or text in ["yes", "y", "1"]:
                self.state_repo.save(phone_number, SALE_ASK_QUANTITY, data)
                whatsapp_service.send_text(phone_number, f"Selected: {to_title_case(data['current_item']['product_name'])}\n\nEnter quantity (or type 'cancel' to exit):")
            else:
                data["current_item"]["product_name"] = data["current_item"]["product_name"]
                data["current_item"]["product_id"] = None
                data["current_item"]["default_price"] = 0.0
                self.state_repo.save(phone_number, SALE_ASK_QUANTITY, data)
                whatsapp_service.send_text(phone_number, f"Using: {to_title_case(data['current_item']['product_name'])}\n\nEnter quantity (or type 'cancel' to exit):")

        elif state == SALE_SELECT_PRODUCT_MATCH:
            matched_id = None
            if button_id and button_id.startswith("sale_select_"):
                val = button_id.replace("sale_select_", "")
                if val != "typed":
                    matched_id = int(val)
            
            if matched_id:
                matched_prod = self.product_repo.get_by_id(matched_id)
                data["current_item"] = {
                    "product_name": matched_prod.name,
                    "product_id": matched_prod.id,
                    "default_price": float(matched_prod.default_price)
                }
            else:
                data["current_item"] = {
                    "product_name": data.get("temp_typed_name", "Unknown"),
                    "product_id": None,
                    "default_price": 0.0
                }
            
            data.pop("temp_typed_name", None)
            data.pop("temp_matches", None)
            
            self.state_repo.save(phone_number, SALE_ASK_QUANTITY, data)
            whatsapp_service.send_text(phone_number, f"Product: {to_title_case(data['current_item']['product_name'])}\n\nEnter quantity (or type 'cancel' to exit):")

        elif state == SALE_ASK_QUANTITY:
            try:
                qty = int(text)
                if qty <= 0:
                    raise ValueError()
            except ValueError:
                whatsapp_service.send_text(phone_number, "Invalid quantity. Please enter a positive whole number (or type 'cancel' to exit):")
                return
            
            data["current_item"]["quantity"] = qty
            self.state_repo.save(phone_number, SALE_ASK_PRICE, data)
            
            default_price = data["current_item"].get("default_price", 0.0)
            if default_price > 0:
                whatsapp_service.send_text(phone_number, f"Enter selling price per unit (Default: Rs. {default_price:.2f}) (or type 'cancel' to exit):")
            else:
                whatsapp_service.send_text(phone_number, "Enter selling price per unit (or type 'cancel' to exit):")

        elif state == SALE_ASK_PRICE:
            try:
                price = float(text)
                if price <= 0:
                    raise ValueError()
            except ValueError:
                whatsapp_service.send_text(phone_number, "Invalid price. Please enter a valid positive decimal number (or type 'cancel' to exit):")
                return
            
            data["current_item"]["price"] = price
            self.state_repo.save(phone_number, SALE_ASK_WARRANTY, data)
            
            sections = [
                {
                    "title": "Standard Options",
                    "rows": [
                        {"id": "warranty_no", "title": "No Warranty", "description": "No manufacturer warranty coverage"},
                        {"id": "warranty_6m", "title": "6 Month Warranty", "description": "6 Months standard warranty"},
                        {"id": "warranty_1y", "title": "1 Year Warranty", "description": "1 Year standard warranty"},
                        {"id": "warranty_2y", "title": "2 Year Warranty", "description": "2 Years standard warranty"}
                    ]
                },
                {
                    "title": "Other Options",
                    "rows": [
                        {"id": "warranty_custom", "title": "Custom Warranty", "description": "Type a custom warranty duration"},
                        {"id": "global_cancel", "title": "Cancel Sale", "description": "Discard current sale logs"}
                    ]
                }
            ]
            whatsapp_service.send_list(phone_number, "Select Warranty", "Select a warranty duration for this product:", "Warranty Options", sections)

        elif state == SALE_ASK_WARRANTY:
            warranty = "No Warranty"
            if button_id == "warranty_no" or text == "no warranty":
                warranty = "No Warranty"
            elif button_id == "warranty_6m" or text == "6 month warranty":
                warranty = "6 Month"
            elif button_id == "warranty_1y" or text == "1 year warranty":
                warranty = "1 Year"
            elif button_id == "warranty_2y" or text == "2 year warranty":
                warranty = "2 Year"
            elif button_id == "warranty_custom" or text == "custom warranty":
                self.state_repo.save(phone_number, SALE_ASK_CUSTOM_WARRANTY, data)
                whatsapp_service.send_text(phone_number, "Enter custom warranty duration (e.g. 18 Months, 3 Years, Lifetime) (or type 'cancel' to exit):")
                return
            elif text:
                warranty = text
                
            data["current_item"]["warranty_info"] = to_title_case(warranty)
            
            cart = data.get("cart", [])
            cart.append(data["current_item"])
            data["cart"] = cart
            data.pop("current_item", None)
            
            self.state_repo.save(phone_number, SALE_ASK_ADD_ANOTHER, data)
            
            buttons = [
                {"id": "add_another_yes", "title": "YES"},
                {"id": "add_another_no", "title": "NO"},
                {"id": "global_cancel", "title": "CANCEL"}
            ]
            whatsapp_service.send_buttons(phone_number, "Add another product to this sale?", buttons)

        elif state == SALE_ASK_CUSTOM_WARRANTY:
            if not text:
                whatsapp_service.send_text(phone_number, "Warranty text cannot be empty. Please enter custom warranty duration (or type 'cancel' to exit):")
                return
                
            data["current_item"]["warranty_info"] = to_title_case(text)
            
            cart = data.get("cart", [])
            cart.append(data["current_item"])
            data["cart"] = cart
            data.pop("current_item", None)
            
            self.state_repo.save(phone_number, SALE_ASK_ADD_ANOTHER, data)
            buttons = [
                {"id": "add_another_yes", "title": "YES"},
                {"id": "add_another_no", "title": "NO"},
                {"id": "global_cancel", "title": "CANCEL"}
            ]
            whatsapp_service.send_buttons(phone_number, "Add another product to this sale?", buttons)

        elif state == SALE_ASK_ADD_ANOTHER:
            if button_id == "add_another_yes" or text in ["yes", "y", "1"]:
                self.state_repo.save(phone_number, SALE_ASK_PRODUCT_NAME, data)
                whatsapp_service.send_text(phone_number, "Enter product name (or type 'cancel' to exit):")
            else:
                self.state_repo.save(phone_number, SALE_ASK_DATE, data)
                buttons = [
                    {"id": "date_today", "title": "TODAY"},
                    {"id": "date_custom", "title": "CUSTOM DATE"},
                    {"id": "global_cancel", "title": "CANCEL"}
                ]
                whatsapp_service.send_buttons(phone_number, "Select sale date option:", buttons)

        elif state == SALE_ASK_DATE:
            if button_id == "date_today" or text == "today" or text == "1":
                data["sale_date"] = date.today().isoformat()
                self.state_repo.save(phone_number, SALE_ASK_GENERATE_INVOICE, data)
                buttons = [
                    {"id": "gen_invoice_yes", "title": "YES"},
                    {"id": "gen_invoice_no", "title": "NO"},
                    {"id": "global_cancel", "title": "CANCEL"}
                ]
                whatsapp_service.send_buttons(phone_number, "Generate invoice for customer?", buttons)
            else:
                self.state_repo.save(phone_number, SALE_ASK_CUSTOM_DATE, data)
                whatsapp_service.send_text(phone_number, "Enter sale date in 'DD MMM' format (e.g. 15 May or 02 Jun) (or type 'cancel' to exit):")

        elif state == SALE_ASK_CUSTOM_DATE:
            date_match = re.search(r"(\d{1,2})\s*([a-zA-Z]{3,9})", text)
            if not date_match:
                whatsapp_service.send_text(phone_number, "Format not recognized. Please use 'DD MMM' (e.g., 15 May) (or type 'cancel' to exit):")
                return
            
            day, month_str = date_match.group(1), date_match.group(2)
            current_year = date.today().year
            try:
                parsed_dt = datetime.strptime(f"{day} {month_str[:3]} {current_year}", "%d %b %Y")
                data["sale_date"] = parsed_dt.date().isoformat()
            except ValueError:
                whatsapp_service.send_text(phone_number, "Invalid date format or values. Try again (e.g., 15 May) (or type 'cancel' to exit):")
                return
                
            self.state_repo.save(phone_number, SALE_ASK_GENERATE_INVOICE, data)
            buttons = [
                {"id": "gen_invoice_yes", "title": "YES"},
                {"id": "gen_invoice_no", "title": "NO"},
                {"id": "global_cancel", "title": "CANCEL"}
            ]
            whatsapp_service.send_buttons(phone_number, "Generate invoice for customer?", buttons)

        elif state == SALE_ASK_GENERATE_INVOICE:
            if button_id == "gen_invoice_no" or text in ["no", "n", "2"]:
                cart = data["cart"]
                total = sum(item["quantity"] * item["price"] for item in cart)
                sale_date = date.fromisoformat(data["sale_date"])
                
                # Title-case product names in cart for DB saving
                for item in cart:
                    item["product_name"] = to_title_case(item["product_name"])
                
                sale = self.sale_repo.create(
                    sale_date=sale_date,
                    total_amount=total,
                    customer_id=None,
                    pdf_path=None,
                    items_data=cart
                )
                
                whatsapp_service.send_text(phone_number, f"✅ Sale saved successfully without customer profile.\nInvoice Number: {sale.invoice_number}")
                self.state_repo.delete(phone_number)
                self._send_admin_main_menu(phone_number)
            else:
                # Ask phone number first!
                self.state_repo.save(phone_number, SALE_ASK_CUSTOMER_PHONE, data)
                whatsapp_service.send_text(phone_number, "=== Customer Phone ===\n\nEnter customer phone number (10 digits) (or type 'cancel' to exit):")

        elif state == SALE_ASK_CUSTOMER_PHONE:
            clean_phone = clean_phone_number(text)
            if len(clean_phone) != 12 or not clean_phone.startswith("91"):
                whatsapp_service.send_text(phone_number, "Invalid phone number. Please enter a 10-digit mobile number (or type 'cancel' to exit):")
                return
                
            data["customer_phone"] = clean_phone
            customer = self.customer_repo.get_by_phone(clean_phone)
            
            if customer:
                # Customer exists! Show saved details and prompt admin to choose saved name or enter new one
                stats = self.sale_repo.get_customer_stats(customer.id)
                last_purchase_date_str = stats['last_purchase_date'].strftime('%d-%b-%Y') if stats['last_purchase_date'] else 'N/A'
                
                summary_msg = (
                    f"👤 Existing Customer Found!\n"
                    f"Name: {customer.name}\n"
                    f"Purchase Count: {stats['purchase_count']}\n"
                    f"Last Purchase: {last_purchase_date_str}\n"
                    f"Promotions Status: {'Subscribed' if customer.is_subscribed else 'Unsubscribed'}\n\n"
                    f"Choose an option or type a new name directly to rename this customer:"
                )
                self.state_repo.save(phone_number, SALE_CONFIRM_CUSTOMER_NAME, data)
                use_saved_title = f"Use '{customer.name}'"
                if len(use_saved_title) > 20:
                    use_saved_title = f"Use {customer.name}"[:20]
                buttons = [
                    {"id": "cust_name_use_saved", "title": use_saved_title},
                    {"id": "cust_name_type_new", "title": "Change Name"},
                    {"id": "global_cancel", "title": "Cancel Sale"}
                ]
                whatsapp_service.send_buttons(phone_number, summary_msg, buttons)
            else:
                # New customer, ask for name
                self.state_repo.save(phone_number, SALE_ASK_CUSTOMER_NAME, data)
                whatsapp_service.send_text(phone_number, "👤 New Customer. Enter customer name (or type 'cancel' to exit):")

        elif state == SALE_CONFIRM_CUSTOMER_NAME:
            customer = self.customer_repo.get_by_phone(data["customer_phone"])
            if not customer:
                whatsapp_service.send_text(phone_number, "Error: Customer not found. Resetting flow.")
                self.state_repo.delete(phone_number)
                self._send_admin_main_menu(phone_number)
                return
                
            if button_id == "cust_name_use_saved" or text in ["use", "use saved"] or text.startswith("use ") or text == f"use '{customer.name.lower()}'":
                data["customer_name"] = customer.name
                self._transition_to_sale_preview(phone_number, data)
            elif button_id == "cust_name_type_new" or text == "change name":
                self.state_repo.save(phone_number, SALE_ASK_CUSTOMER_NAME, data)
                whatsapp_service.send_text(phone_number, "Enter customer name (or type 'cancel' to exit):")
            elif text:
                # Admin typed the name directly
                data["customer_name"] = to_title_case(text)
                self._transition_to_sale_preview(phone_number, data)
            else:
                whatsapp_service.send_text(phone_number, "Please select an option:")

        elif state == SALE_ASK_CUSTOMER_NAME:
            if not text:
                whatsapp_service.send_text(phone_number, "Please enter customer name (or type 'cancel' to exit):")
                return
            data["customer_name"] = to_title_case(text)
            self._transition_to_sale_preview(phone_number, data)

        elif state == SALE_CONFIRM_PREVIEW:
            if button_id == "preview_pdf_gen" or text == "generate pdf" or text == "1":
                cust_phone = data["customer_phone"]
                cust_name = data["customer_name"]
                
                sale_date = date.fromisoformat(data["sale_date"])
                temp_invoice = self.sale_repo.get_next_invoice_number(sale_date)
                
                cart = data["cart"]
                total = sum(item["quantity"] * item["price"] for item in cart)
                
                # Title-case product names in cart for PDF
                for item in cart:
                    item["product_name"] = to_title_case(item["product_name"])
                
                filepath = PDFGenerator.generate_invoice(
                    invoice_number=temp_invoice,
                    sale_date=sale_date,
                    customer_name=cust_name,
                    customer_phone=cust_phone,
                    items=cart,
                    total_amount=total,
                    output_dir=settings.PDF_OUTPUT_DIR
                )
                
                data["generated_pdf"] = filepath
                data["generated_invoice_num"] = temp_invoice
                self.state_repo.save(phone_number, SALE_SHOW_PDF_PREVIEW, data)
                
                try:
                    pdf_media_id = whatsapp_service.upload_media(filepath, "application/pdf")
                    data["pdf_media_id"] = pdf_media_id
                    self.state_repo.save(phone_number, SALE_SHOW_PDF_PREVIEW, data)
                    
                    whatsapp_service.send_document(
                        to=phone_number, 
                        media_id=pdf_media_id, 
                        filename=os.path.basename(filepath),
                        caption=f"Preview Invoice: {temp_invoice}"
                    )
                except Exception as e:
                    logger.error(f"Error uploading PDF invoice: {e}", exc_info=True)
                    whatsapp_service.send_text(phone_number, f"⚠️ Error uploading PDF: {e}. Attempting offline generation message flow.")
                
                buttons = [
                    {"id": "pdf_send_customer", "title": "SEND INVOICE"},
                    {"id": "global_cancel", "title": "CANCEL"}
                ]
                whatsapp_service.send_buttons(phone_number, "Check invoice preview above. Click below to confirm:", buttons)
            else:
                self.state_repo.delete(phone_number)
                whatsapp_service.send_text(phone_number, "Sale recording cancelled.")
                self._send_admin_main_menu(phone_number)

        elif state == SALE_SHOW_PDF_PREVIEW:
            if button_id == "pdf_send_customer" or text == "send invoice" or text == "1":
                cust_phone = data["customer_phone"]
                cust_name = data["customer_name"]
                
                customer = self.customer_repo.get_by_phone(cust_phone)
                if not customer:
                    customer = self.customer_repo.create(cust_phone, cust_name)
                else:
                    if customer.name != cust_name:
                        customer.name = cust_name
                        self.db.commit()
                        self.db.refresh(customer)
                
                # Check purchase count BEFORE saving this sale to determine if it is the first purchase!
                sales_before = self.sale_repo.get_by_customer_id(customer.id)
                is_first_purchase = len(sales_before) == 0
                
                cart = data["cart"]
                total = sum(item["quantity"] * item["price"] for item in cart)
                sale_date = date.fromisoformat(data["sale_date"])
                
                sale = self.sale_repo.create(
                    sale_date=sale_date,
                    total_amount=total,
                    customer_id=customer.id,
                    pdf_path=data["generated_pdf"],
                    items_data=cart,
                    invoice_number=data.get("generated_invoice_num")
                )
                
                pdf_media_id = data.get("pdf_media_id")
                if pdf_media_id:
                    # Dynamic warmer greeting message for the first purchase
                    if is_first_purchase:
                        greeting = (
                            f"Dear {cust_name}, thank you for your first purchase at BizPilot! 🌟\n\n"
                            f"We have generated your invoice {sale.invoice_number} and it is attached below.\n"
                            f"We are committed to providing you with the best products and service.\n\n"
                            f"If you have any questions about your purchase or warranty, feel free to use the menu options below."
                        )
                    else:
                        greeting = (
                            f"Dear {cust_name}, thank you for shopping at BizPilot!\n\n"
                            f"We have generated your invoice {sale.invoice_number} and it is attached below."
                        )
                    
                    # Capitalize outgoing sentences dynamically
                    whatsapp_service.send_text(cust_phone, capitalize_sentences(greeting))
                    
                    whatsapp_service.send_document(
                        to=cust_phone,
                        media_id=pdf_media_id,
                        filename=os.path.basename(data["generated_pdf"]),
                        caption="Here is your purchase invoice."
                    )
                    
                    # Opt-in to promotions prompt
                    optin_text = "Would you like to receive updates about New Products, Sales, and Offers from BizPilot?"
                    optin_buttons = [
                        {"id": "optin_yes", "title": "YES"},
                        {"id": "optin_no", "title": "NO"}
                    ]
                    whatsapp_service.send_buttons(cust_phone, optin_text, optin_buttons)
                else:
                    if is_first_purchase:
                        whatsapp_service.send_text(
                            cust_phone, 
                            capitalize_sentences(f"Dear {cust_name}, thank you for your first purchase at BizPilot! 🌟 Your invoice number is {sale.invoice_number}.")
                        )
                    else:
                        whatsapp_service.send_text(
                            cust_phone, 
                            capitalize_sentences(f"Dear {cust_name}, thank you for shopping at BizPilot. Your invoice number is {sale.invoice_number}.")
                        )
                
                whatsapp_service.send_text(phone_number, f"✅ Invoice {sale.invoice_number} sent successfully to customer!")
                self.state_repo.delete(phone_number)
                self._send_admin_main_menu(phone_number)
            else:
                self.state_repo.delete(phone_number)
                whatsapp_service.send_text(phone_number, "Checkout transaction cancelled.")
                self._send_admin_main_menu(phone_number)

    def _transition_to_sale_preview(self, phone_number: str, data: dict) -> None:
        self.state_repo.save(phone_number, SALE_CONFIRM_PREVIEW, data)
        cust_phone = data["customer_phone"]
        cust_name = data["customer_name"]
        
        customer = self.customer_repo.get_by_phone(cust_phone)
        summary_msg = ""
        if customer:
            stats = self.sale_repo.get_customer_stats(customer.id)
            last_purchase_date_str = stats['last_purchase_date'].strftime('%d-%b-%Y') if stats['last_purchase_date'] else 'N/A'
            summary_msg = (
                f"👤 Existing Customer:\n"
                f"Name: {cust_name}\n"
                f"Purchase Count: {stats['purchase_count']}\n"
                f"Last Purchase: {last_purchase_date_str}\n"
                f"Promotions Status: {'Subscribed' if customer.is_subscribed else 'Unsubscribed'}\n"
            )
        else:
            summary_msg = f"👤 New customer registration:\nName: {cust_name}\nPhone: {cust_phone}\n"
            
        cart = data["cart"]
        total = sum(item["quantity"] * item["price"] for item in cart)
        
        preview_body = (
            f"{summary_msg}\n"
            f"🛒 CART DETAILS:\n"
        )
        for item in cart:
            preview_body += f"- {to_title_case(item['product_name'])} x {item['quantity']} (Rs. {item['price']:.2f})\n"
            
        preview_body += f"\n💰 TOTAL: Rs. {total:.2f}\nDate: {data['sale_date']}"
        
        buttons = [
            {"id": "preview_pdf_gen", "title": "Generate PDF"},
            {"id": "global_cancel", "title": "CANCEL"}
        ]
        whatsapp_service.send_buttons(phone_number, preview_body, buttons)


    # ==========================================
    # BROADCAST FLOW PROCESSING
    # ==========================================
    def _process_broadcast_flow(self, phone_number: str, state: str, data: dict, text: str, button_id: str, media_id: str, admin_id: int) -> None:
        if state == BROADCAST_ASK_TYPE:
            bc_type = "Custom"
            if button_id == "bc_type_sale":
                bc_type = "Sale Offer"
            elif button_id == "bc_type_product":
                bc_type = "New Product"
            elif button_id == "bc_type_custom":
                bc_type = "Custom"
            elif text:
                bc_type = text
                
            data["broadcast_type"] = bc_type
            self.state_repo.save(phone_number, BROADCAST_ASK_CONTENT, data)
            whatsapp_service.send_text(phone_number, "Enter the message content for the broadcast (or type 'cancel' to exit):")

        elif state == BROADCAST_ASK_CONTENT:
            if not text:
                whatsapp_service.send_text(phone_number, "Message content cannot be blank. Enter broadcast message (or type 'cancel' to exit):")
                return
            
            # Trigger Gemini API reformatting!
            whatsapp_service.send_text(phone_number, "Formatting message with Gemini API...")
            reformatted_content = gemini_service.reformat_broadcast_message(text)
            
            data["original_content"] = text
            data["content"] = reformatted_content
            
            self.state_repo.save(phone_number, BROADCAST_PREVIEW_REFORMAT, data)
            
            preview_text = (
                f"=== Gemini Reformatted Version ===\n\n"
                f"{reformatted_content}\n\n"
                f"Choose which version of the message you want to use:"
            )
            buttons = [
                {"id": "bc_use_reformatted", "title": "Use Reformatted"},
                {"id": "bc_use_original", "title": "Use Original"},
                {"id": "global_cancel", "title": "Cancel Broadcast"}
            ]
            whatsapp_service.send_buttons(phone_number, preview_text, buttons)

        elif state == BROADCAST_PREVIEW_REFORMAT:
            if button_id == "bc_use_reformatted" or text == "use reformatted":
                # Content is already reformatted in data["content"]
                pass
            elif button_id == "bc_use_original" or text == "use original":
                data["content"] = data["original_content"]
            else:
                whatsapp_service.send_text(phone_number, "Please select an option:")
                return
                
            data.pop("original_content", None)
            self.state_repo.save(phone_number, BROADCAST_ASK_IMAGE, data)
            whatsapp_service.send_text(phone_number, "Upload an image for the broadcast (send as image file attachment) or reply with 'SKIP' to proceed without an image (or type 'cancel' to exit):")

        elif state == BROADCAST_ASK_IMAGE:
            if media_id:
                data["image_media_id"] = media_id
            elif text == "skip":
                data["image_media_id"] = None
            else:
                whatsapp_service.send_text(phone_number, "Please upload an image, or type 'SKIP' to continue (or type 'cancel' to exit):")
                return

            self.state_repo.save(phone_number, BROADCAST_PREVIEW, data)
            
            preview_prefix = f"=== BROADCAST PREVIEW ===\nType: {data['broadcast_type']}\n\nContent:\n{data['content']}"
            if data["image_media_id"]:
                whatsapp_service.send_image(phone_number, data["image_media_id"], caption=preview_prefix)
            else:
                whatsapp_service.send_text(phone_number, preview_prefix)
                
            buttons = [
                {"id": "bc_confirm_send", "title": "SEND"},
                {"id": "global_cancel", "title": "CANCEL"}
            ]
            whatsapp_service.send_buttons(phone_number, "Confirm sending this broadcast to all subscribed customers?", buttons)

        elif state == BROADCAST_PREVIEW:
            if button_id == "bc_confirm_send" or text == "send" or text == "1":
                subscribers = self.customer_repo.get_all_subscribed()
                
                # Append the opt-out notice automatically to the broadcast message
                raw_bc_text = data["content"]
                opt_out_suffix = "\n\n---\nIf you wish to stop receiving updates, reply 'STOP' or use the buttons below."
                bc_text_with_optout = capitalize_sentences(raw_bc_text + opt_out_suffix)
                
                # Set up buttons for the customer: Stop updates, View Catalogue
                cust_buttons = [
                    {"id": "customer_optout", "title": "Stop Updates"},
                    {"id": "cust_menu_catalogue", "title": "View Catalogue"}
                ]
                
                count = 0
                for sub in subscribers:
                    try:
                        if data["image_media_id"]:
                            whatsapp_service.send_image_buttons(
                                to=sub.phone_number, 
                                media_id=data["image_media_id"], 
                                text=bc_text_with_optout, 
                                buttons=cust_buttons
                            )
                        else:
                            whatsapp_service.send_buttons(
                                to=sub.phone_number, 
                                text=bc_text_with_optout, 
                                buttons=cust_buttons
                            )
                        count += 1
                    except Exception as e:
                        logger.error(f"Failed to send broadcast to {sub.phone_number}: {e}")
                
                bc = Broadcast(
                    broadcast_type=data["broadcast_type"],
                    message_content=data["content"],
                    image_url=data.get("image_media_id"),
                    sent_by_admin_id=admin_id,
                    recipients_count=count
                )
                self.db.add(bc)
                self.db.commit()
                
                whatsapp_service.send_text(phone_number, f"✅ Broadcast sent successfully to {count} subscribers!")
                self.state_repo.delete(phone_number)
                self._send_admin_main_menu(phone_number)
            else:
                self.state_repo.delete(phone_number)
                whatsapp_service.send_text(phone_number, "Broadcast message discarded.")
                self._send_admin_main_menu(phone_number)


    # ==========================================
    # SEARCH CUSTOMER FLOW PROCESSING
    # ==========================================
    def _process_search_customer_flow(self, phone_number: str, state: str, data: dict, text: str, button_id: str) -> None:
        if state == SEARCH_CUSTOMER_ASK_QUERY:
            query = text
            if not query:
                whatsapp_service.send_text(phone_number, "Please enter a valid search text:")
                return

            customers = self.customer_repo.search_by_name_or_phone(query)
            if not customers:
                whatsapp_service.send_text(phone_number, "No customers found matching that query. Enter a new search query or type 'cancel' to exit:")
                return

            if len(customers) == 1:
                self._show_customer_details(phone_number, customers[0].id)
            else:
                data["search_results"] = [c.id for c in customers]
                self.state_repo.save(phone_number, SEARCH_CUSTOMER_SHOW_RESULTS, data)
                
                rows = []
                for c in customers[:9]:
                    rows.append({
                        "id": f"cust_view_{c.id}",
                        "title": c.name[:24],
                        "description": f"Phone: {c.phone_number}"
                    })
                sections = [{"title": "Search Results", "rows": rows}]
                whatsapp_service.send_list(phone_number, "Customer Results", "Multiple customers found:", "Select customer", sections)

        elif state == SEARCH_CUSTOMER_SHOW_RESULTS:
            cust_id = None
            if button_id and button_id.startswith("cust_view_"):
                cust_id = int(button_id.replace("cust_view_", ""))
            elif button_id and button_id.startswith("cust_hist_"):
                cust_id = int(button_id.replace("cust_hist_", ""))
                self._show_customer_order_history(phone_number, cust_id)
                return
            elif button_id == "cust_search_again":
                self.state_repo.save(phone_number, SEARCH_CUSTOMER_ASK_QUERY, {})
                whatsapp_service.send_text(phone_number, "Enter phone number or customer name:")
                return

            if cust_id:
                self._show_customer_details(phone_number, cust_id)
            else:
                self.state_repo.delete(phone_number)
                self._send_admin_main_menu(phone_number)

    def _show_customer_details(self, admin_phone: str, customer_id: int) -> None:
        customer = self.db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            whatsapp_service.send_text(admin_phone, "Error: Customer not found.")
            return

        stats = self.sale_repo.get_customer_stats(customer.id)
        msg = (
            f"👤 CUSTOMER PROFILE\n"
            f"Name: {to_title_case(customer.name)}\n"
            f"Phone: {customer.phone_number}\n"
            f"Subscribed: {'YES' if customer.is_subscribed else 'NO'}\n"
            f"Customer Since: {customer.created_at.strftime('%d-%b-%Y') if customer.created_at else 'N/A'}\n\n"
            f"📊 STATISTICS:\n"
            f"Total Purchases: {stats['purchase_count']}\n"
            f"Lifetime Value: Rs. {stats['lifetime_value']:.2f}\n"
            f"Last Purchase: {stats['last_purchase_date'].strftime('%d-%b-%Y') if stats['last_purchase_date'] else 'N/A'}"
        )
        
        self.state_repo.save(admin_phone, SEARCH_CUSTOMER_SHOW_RESULTS, {"selected_customer_id": customer_id})
        
        buttons = [
            {"id": f"cust_hist_{customer_id}", "title": "Order History"},
            {"id": "cust_search_again", "title": "Search Again"},
            {"id": "global_cancel", "title": "Main Menu"}
        ]
        whatsapp_service.send_buttons(admin_phone, msg, buttons)

    def _show_customer_order_history(self, admin_phone: str, customer_id: int) -> None:
        sales = self.sale_repo.get_by_customer_id(customer_id)
        if not sales:
            whatsapp_service.send_text(admin_phone, "No purchase history found for this customer.")
            self._show_customer_details(admin_phone, customer_id)
            return

        history_msg = "📜 PURCHASE HISTORY:\n\n"
        for idx, sale in enumerate(sales[:5], 1):
            items_str = ", ".join([f"{to_title_case(item.product_name)} (x{item.quantity})" for item in sale.items])
            history_msg += (
                f"{idx}. Invoice: {sale.invoice_number}\n"
                f"   Date: {sale.sale_date.strftime('%d-%b-%Y')}\n"
                f"   Products: {items_str}\n"
                f"   Amount: Rs. {sale.total_amount:.2f}\n"
                f"   Warranties: " + ", ".join([f"{to_title_case(item.product_name)}: {item.warranty_info}" for item in sale.items]) + "\n\n"
            )

        if len(sales) > 5:
            history_msg += f"Showing last 5 of {len(sales)} transactions."

        buttons = [
            {"id": f"cust_view_{customer_id}", "title": "Back to Profile"},
            {"id": "global_cancel", "title": "Main Menu"}
        ]
        whatsapp_service.send_buttons(admin_phone, history_msg, buttons)


    # ==========================================
    # CATALOGUE FLOW PROCESSING
    # ==========================================
    def _process_catalogue_flow(self, phone_number: str, state: str, data: dict, text: str, button_id: str) -> None:
        if state == CATALOGUE_MAIN:
            if button_id == "cat_sync" or text == "1":
                whatsapp_service.send_text(phone_number, "Syncing catalog with Google Sheet, please wait...")
                res = sheets_service.sync_from_sheet(self.db)
                if res.get("errors", 0) > 0:
                    whatsapp_service.send_text(phone_number, f"❌ Sync Failed:\n{res.get('error_msg')}")
                else:
                    whatsapp_service.send_text(
                        phone_number, 
                        f"✅ Sync Completed!\n"
                        f"Added: {res['added']} items\n"
                        f"Updated: {res['updated']} items\n"
                        f"Mode: {res['mode']}"
                    )
                self.state_repo.delete(phone_number)
                self._send_admin_main_menu(phone_number)
                
            elif button_id == "cat_add" or text == "2":
                self.state_repo.save(phone_number, CATALOGUE_ADD_NAME, {})
                whatsapp_service.send_text(phone_number, "Enter new product name:")
                
            elif button_id == "cat_remove" or text == "3":
                active_products = self.product_repo.get_all_active()
                if not active_products:
                    whatsapp_service.send_text(phone_number, "No active products found in catalogue.")
                    self.state_repo.delete(phone_number)
                    self._send_admin_main_menu(phone_number)
                    return
                
                rows = []
                for p in active_products[:9]:
                    rows.append({
                        "id": f"cat_rem_{p.id}",
                        "title": p.name[:24],
                        "description": f"Price: Rs. {p.default_price:.2f}"
                    })
                sections = [{"title": "Active Products", "rows": rows}]
                self.state_repo.save(phone_number, CATALOGUE_REMOVE_SELECT, {})
                whatsapp_service.send_list(phone_number, "Select Product", "Choose a product to set inactive:", "Products", sections)
            else:
                self.state_repo.delete(phone_number)
                self._send_admin_main_menu(phone_number)

        elif state == CATALOGUE_ADD_NAME:
            if not text:
                whatsapp_service.send_text(phone_number, "Product name cannot be blank. Enter product name:")
                return
            data["new_product_name"] = to_title_case(text)
            self.state_repo.save(phone_number, CATALOGUE_ADD_CATEGORY, data)
            whatsapp_service.send_text(phone_number, "Enter product category (e.g., Bulb, Inverter, Mobile):")

        elif state == CATALOGUE_ADD_CATEGORY:
            if not text:
                whatsapp_service.send_text(phone_number, "Category cannot be blank. Enter category:")
                return
            data["new_product_category"] = to_title_case(text)
            self.state_repo.save(phone_number, CATALOGUE_ADD_PRICE, data)
            whatsapp_service.send_text(phone_number, "Enter product default price (numbers only):")

        elif state == CATALOGUE_ADD_PRICE:
            try:
                price = float(text)
                if price <= 0:
                    raise ValueError()
            except ValueError:
                whatsapp_service.send_text(phone_number, "Invalid price. Please enter a valid decimal number:")
                return
            
            name = data["new_product_name"]
            cat = data["new_product_category"]
            
            existing = self.product_repo.get_by_name(name)
            is_new = existing is None
            self.product_repo.create_or_update(name, cat, price, is_active=True)
            sheet_success = sheets_service.add_product(name, cat, price, is_active=True)
            
            action_verb = "added" if is_new else "updated"
            sheet_status = "and Google Sheets" if sheet_success else "(Google Sheets update failed)"
            whatsapp_service.send_text(phone_number, f"✅ Product '{name}' {action_verb} successfully in database {sheet_status}!")
            
            self.state_repo.delete(phone_number)
            self._send_admin_main_menu(phone_number)

        elif state == CATALOGUE_REMOVE_SELECT:
            prod_id = None
            if button_id and button_id.startswith("cat_rem_"):
                prod_id = int(button_id.replace("cat_rem_", ""))
                
            if prod_id:
                product = self.product_repo.get_by_id(prod_id)
                if product:
                    self.product_repo.set_active_status(product.name, is_active=False)
                    sheet_success = sheets_service.remove_product(product.name)
                    
                    sheet_status = "and Google Sheets" if sheet_success else "(Google Sheet update failed)"
                    whatsapp_service.send_text(phone_number, f"✅ Product '{product.name}' has been set inactive in DB {sheet_status}.")
                else:
                    whatsapp_service.send_text(phone_number, "Product not found.")
            else:
                whatsapp_service.send_text(phone_number, "Action cancelled.")
                
            self.state_repo.delete(phone_number)
            self._send_admin_main_menu(phone_number)


    # ==========================================
    # ADMIN ROLES FLOW PROCESSING
    # ==========================================
    def _process_admin_management_flow(self, phone_number: str, state: str, data: dict, text: str, button_id: str) -> None:
        if state == ADMIN_MAIN:
            if button_id == "adm_list" or text == "1":
                admins = self.admin_repo.get_all()
                msg = "👤 SYSTEM ADMINISTRATORS:\n\n"
                for idx, adm in enumerate(admins, 1):
                    msg += f"{idx}. {adm.name} ({adm.phone_number})\n"
                whatsapp_service.send_text(phone_number, msg)
                self.state_repo.delete(phone_number)
                self._send_admin_main_menu(phone_number)
                
            elif button_id == "adm_add" or text == "2":
                self.state_repo.save(phone_number, ADMIN_ADD_PHONE, {})
                whatsapp_service.send_text(phone_number, "Enter the phone number of the new admin (10 digits):")
                
            elif button_id == "adm_remove" or text == "3":
                admins = self.admin_repo.get_all()
                primary_phone = clean_phone_number(settings.PRIMARY_ADMIN_PHONE)
                rows = []
                for adm in admins:
                    if adm.phone_number == phone_number or adm.phone_number == primary_phone:
                        continue
                    if len(rows) >= 9:
                        break
                    rows.append({
                        "id": f"adm_rem_{adm.phone_number}",
                        "title": adm.name[:24],
                        "description": f"Phone: {adm.phone_number}"
                    })
                
                if not rows:
                    whatsapp_service.send_text(phone_number, "No other administrators available to remove.")
                    self.state_repo.delete(phone_number)
                    self._send_admin_main_menu(phone_number)
                    return

                sections = [{"title": "Admins", "rows": rows}]
                self.state_repo.save(phone_number, ADMIN_REMOVE_SELECT, {})
                whatsapp_service.send_list(phone_number, "Remove Admin", "Select an administrator to remove:", "Admins", sections)
            else:
                self.state_repo.delete(phone_number)
                self._send_admin_main_menu(phone_number)

        elif state == ADMIN_ADD_PHONE:
            clean_phone = clean_phone_number(text)
            if len(clean_phone) != 12 or not clean_phone.startswith("91"):
                whatsapp_service.send_text(phone_number, "Invalid phone number. Enter a valid 10-digit mobile number:")
                return

            existing = self.admin_repo.get_by_phone(clean_phone)
            if existing:
                whatsapp_service.send_text(phone_number, f"User {clean_phone} is already an admin. Process cancelled.")
                self.state_repo.delete(phone_number)
                self._send_admin_main_menu(phone_number)
                return

            data["new_admin_phone"] = clean_phone
            self.state_repo.save(phone_number, ADMIN_ADD_NAME, data)
            whatsapp_service.send_text(phone_number, "Enter the name of the new admin:")

        elif state == ADMIN_ADD_NAME:
            if not text:
                whatsapp_service.send_text(phone_number, "Name cannot be blank. Enter admin name:")
                return
            
            new_phone = data["new_admin_phone"]
            self.admin_repo.create(new_phone, to_title_case(text))
            
            whatsapp_service.send_text(phone_number, f"✅ Admin '{to_title_case(text)}' ({new_phone}) added successfully!")
            self.state_repo.delete(phone_number)
            self._send_admin_main_menu(phone_number)

        elif state == ADMIN_REMOVE_SELECT:
            target_phone = None
            if button_id and button_id.startswith("adm_rem_"):
                target_phone = button_id.replace("adm_rem_", "")

            primary_phone = clean_phone_number(settings.PRIMARY_ADMIN_PHONE)
            if target_phone and target_phone == primary_phone:
                whatsapp_service.send_text(phone_number, "⚠️ Primary Administrator cannot be removed.")
            elif target_phone:
                admin_obj = self.admin_repo.get_by_phone(target_phone)
                if admin_obj:
                    self.admin_repo.delete(target_phone)
                    whatsapp_service.send_text(phone_number, f"✅ Admin '{admin_obj.name}' ({target_phone}) removed successfully.")
                else:
                    whatsapp_service.send_text(phone_number, "Admin not found.")
            else:
                whatsapp_service.send_text(phone_number, "Action cancelled.")
                
            self.state_repo.delete(phone_number)
            self._send_admin_main_menu(phone_number)


    # ==========================================
    # REPORTING FLOW PROCESSING
    # ==========================================
    def _process_report_flow(self, phone_number: str, state: str, data: dict, text: str, button_id: str) -> None:
        from app.services.report_generator import ReportGenerator
        
        generator = ReportGenerator(self.db)
        
        if button_id == "rpt_weekly" or text == "weekly":
            whatsapp_service.send_text(phone_number, "Generating Weekly Report, please wait...")
            report_text = generator.generate_weekly_report_text()
            whatsapp_service.send_text(phone_number, report_text)
            
        elif button_id == "rpt_monthly" or text == "monthly":
            whatsapp_service.send_text(phone_number, "Generating Monthly Report, please wait...")
            report_text = generator.generate_monthly_report_text()
            whatsapp_service.send_text(phone_number, report_text)
            
        elif button_id == "rpt_export_cust" or "customer" in text:
            whatsapp_service.send_text(phone_number, "Generating Customer Excel list, please wait...")
            try:
                filepath = generator.generate_customer_excel()
                media_id = whatsapp_service.upload_media(filepath, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                whatsapp_service.send_document(
                    to=phone_number,
                    media_id=media_id,
                    filename=os.path.basename(filepath),
                    caption="BizPilot Customer List Data Export"
                )
            except Exception as e:
                logger.error(f"Error generating customer Excel: {e}", exc_info=True)
                whatsapp_service.send_text(phone_number, f"⚠️ Error generating customer Excel: {e}")
                
        elif button_id == "rpt_export_prod" or "product" in text:
            whatsapp_service.send_text(phone_number, "Generating Product Excel list, please wait...")
            try:
                filepath = generator.generate_product_excel()
                media_id = whatsapp_service.upload_media(filepath, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                whatsapp_service.send_document(
                    to=phone_number,
                    media_id=media_id,
                    filename=os.path.basename(filepath),
                    caption="BizPilot Product List Data Export"
                )
            except Exception as e:
                logger.error(f"Error generating product Excel: {e}", exc_info=True)
                whatsapp_service.send_text(phone_number, f"⚠️ Error generating product Excel: {e}")
            
        else:
            whatsapp_service.send_text(phone_number, "Action cancelled.")

        self.state_repo.delete(phone_number)
        self._send_admin_main_menu(phone_number)
