# BizPilot — State Machine Architecture & Analysis

This document provides the complete formal specification of all explicit and implicit state machines across the BizPilot WhatsApp Business Automation system. It defines their states, invariants, transition tables, analyzes reachable invalid states (including concurrency and retry edge cases), and tracks prioritized fixes.

---

## 1. Explicit State Machines

### 1.1 Admin Conversation State Machine (`ConversationState`)
* **State Persistence:** Stored in the `conversation_states` table (`phone_number`, `state`, `data`, `updated_at`).
* **Trigger:** Incoming WhatsApp webhook events from registered administrator phone numbers.

```
                                  ┌─────────────┐
                                  │ STATE_IDLE  │
                                  └──────┬──────┘
        ┌──────────────────┬─────────────┼──────────────┬──────────────┬─────────────┐
        ▼                  ▼             ▼              ▼              ▼             ▼
   [Sale Flow]        [Broadcast]    [Customer]    [Catalogue]      [Admin]      [Reports]
  SALE_ASK_PROD      BROADCAST_TYPE  SEARCH_QUERY  CATALOGUE_MAIN  ADMIN_MAIN  REPORT_SELECT
```

#### States Definition
| State Identifier | Purpose | Stored Context (`data`) |
| :--- | :--- | :--- |
| `STATE_IDLE` | Default quiescent state; listens for commands or forwards to active support tickets | `{}` |
| `SALE_ASK_PRODUCT_NAME` | Awaiting product name query from admin | `{"cart": [...]}` |
| `SALE_CONFIRM_PRODUCT_MATCH` | Single high-confidence fuzzy match found (>=85%); awaiting admin YES/NO | `{"cart": [...], "current_item": {...}}` |
| `SALE_SELECT_PRODUCT_MATCH` | Multiple fuzzy matches found; awaiting list selection or use raw text | `{"cart": [...], "temp_typed_name": str, "temp_matches": [...]}` |
| `SALE_ASK_QUANTITY` | Awaiting item quantity (integer > 0) | `{"cart": [...], "current_item": {...}}` |
| `SALE_ASK_PRICE` | Awaiting unit selling price (float > 0) | `{"cart": [...], "current_item": {...}}` |
| `SALE_ASK_WARRANTY` | Presenting warranty duration options (No, 6M, 1Y, 2Y, Custom) | `{"cart": [...], "current_item": {...}}` |
| `SALE_ASK_CUSTOM_WARRANTY` | Awaiting custom warranty duration string | `{"cart": [...], "current_item": {...}}` |
| `SALE_ASK_ADD_ANOTHER` | Asking whether to append another item to the cart (YES/NO) | `{"cart": [...]}` |
| `SALE_ASK_DATE` | Selecting sale date (TODAY or CUSTOM) | `{"cart": [...]}` |
| `SALE_ASK_CUSTOM_DATE` | Awaiting custom date string (`DD MMM`) | `{"cart": [...]}` |
| `SALE_ASK_GENERATE_INVOICE` | Asking whether to attach a customer profile & generate invoice | `{"cart": [...], "sale_date": "YYYY-MM-DD"}` |
| `SALE_ASK_CUSTOMER_PHONE` | Awaiting 10-digit customer mobile number | `{"cart": [...], "sale_date": "..."}` |
| `SALE_CONFIRM_CUSTOMER_NAME` | Existing customer found; prompt to keep saved name or change | `{"cart": [...], "customer_phone": "91..."}` |
| `SALE_ASK_CUSTOMER_NAME` | Awaiting customer name string | `{"cart": [...], "customer_phone": "91..."}` |
| `SALE_CONFIRM_PREVIEW` | Cart & customer summary shown; awaiting Generate PDF confirmation | `{"cart": [...], "customer_phone": "...", "customer_name": "..."}` |
| `SALE_SHOW_PDF_PREVIEW` | PDF generated & uploaded to Meta; awaiting admin Send Invoice confirmation | `{"cart": [...], "generated_pdf": "...", "generated_invoice_num": "..."}` |
| `BROADCAST_ASK_TYPE` | Selecting broadcast template type (Sale Offer, New Product, Custom) | `{}` |
| `BROADCAST_ASK_CONTENT` | Awaiting raw broadcast message content | `{"broadcast_type": "..."}` |
| `BROADCAST_PREVIEW_REFORMAT` | Showing Gemini AI reformatted version vs original; choose version | `{"broadcast_type": "...", "original_content": "...", "content": "..."}` |
| `BROADCAST_ASK_IMAGE` | Awaiting optional promotional image attachment or 'SKIP' | `{"broadcast_type": "...", "content": "..."}` |
| `BROADCAST_PREVIEW` | Final campaign preview; awaiting Send confirmation | `{"broadcast_type": "...", "content": "...", "image_media_id": ...}` |
| `SEARCH_CUSTOMER_ASK_QUERY` | Awaiting customer phone or name query | `{}` |
| `SEARCH_CUSTOMER_SHOW_RESULTS` | Customer profile or search results displayed; order history option | `{"search_results": [...]}` or `{"selected_customer_id": int}` |
| `CATALOGUE_MAIN` | Catalogue menu: Sync Sheet, Add Product, Remove Product | `{}` |
| `CATALOGUE_ADD_NAME` | Awaiting new product name | `{}` |
| `CATALOGUE_ADD_CATEGORY` | Awaiting product category | `{"new_product_name": "..."}` |
| `CATALOGUE_ADD_PRICE` | Awaiting default price | `{"new_product_name": "...", "new_product_category": "..."}` |
| `CATALOGUE_REMOVE_SELECT` | Presenting active product list to set inactive | `{}` |
| `ADMIN_MAIN` | Admin menu: List Admins, Add Admin, Remove Admin | `{}` |
| `ADMIN_ADD_PHONE` | Awaiting new admin phone number | `{}` |
| `ADMIN_ADD_NAME` | Awaiting new admin name | `{"new_admin_phone": "..."}` |
| `ADMIN_REMOVE_SELECT` | Presenting administrator list for deletion | `{}` |
| `REPORT_SELECT` | Reports menu: Weekly Report, Monthly Report, Excel Exports | `{}` |

#### State Transition Table (Admin Machine)
| Current State | Input / Event | Guard / Condition | Next State | Side Effects |
| :--- | :--- | :--- | :--- | :--- |
| `ANY` | `text == "cancel"` or `button_id == "global_cancel"` | None | `STATE_IDLE` | Deletes `conversation_states` row; displays Admin Main Menu |
| `STATE_IDLE` | Button `menu_record_sale` or text `1` / `record` | None | `SALE_ASK_PRODUCT_NAME` | Initializes empty cart in state data |
| `STATE_IDLE` | Button `menu_broadcast` or text `2` / `broadcast` | None | `BROADCAST_ASK_TYPE` | Prompts broadcast type buttons |
| `STATE_IDLE` | Button `menu_search_customer` or text `3` / `search` | None | `SEARCH_CUSTOMER_ASK_QUERY` | Prompts for query string |
| `STATE_IDLE` | Button `menu_manage_catalogue` or text `4` | None | `CATALOGUE_MAIN` | Prompts catalogue options |
| `STATE_IDLE` | Button `menu_view_reports` or text `5` | None | `REPORT_SELECT` | Sends reports list menu |
| `STATE_IDLE` | Button `menu_admin_management` or text `6` | None | `ADMIN_MAIN` | Sends admin options |
| `STATE_IDLE` | Non-command text message | Active support ticket exists | `STATE_IDLE` | Forwards message to active ticket customer |
| `SALE_ASK_PRODUCT_NAME` | Text (Product Query) | Match score >= 85% (single) | `SALE_CONFIRM_PRODUCT_MATCH` | Pre-fills `current_item` |
| `SALE_ASK_PRODUCT_NAME` | Text (Product Query) | Multiple matches (50-84%) | `SALE_SELECT_PRODUCT_MATCH` | Prepares match list |
| `SALE_ASK_PRODUCT_NAME` | Text (Product Query) | No fuzzy matches | `SALE_ASK_QUANTITY` | Uses raw text with price 0.0 |
| `SALE_CONFIRM_PRODUCT_MATCH`| Button `sale_match_yes` or text `yes` | None | `SALE_ASK_QUANTITY` | Keeps matched product name & price |
| `SALE_CONFIRM_PRODUCT_MATCH`| Button `sale_match_no` or text `no` | None | `SALE_ASK_QUANTITY` | Clears product ID, resets price |
| `SALE_SELECT_PRODUCT_MATCH` | Button `sale_select_<id>` | Valid product ID | `SALE_ASK_QUANTITY` | Selects item from list |
| `SALE_ASK_QUANTITY` | Text (Integer > 0) | `qty > 0` | `SALE_ASK_PRICE` | Stores quantity in `current_item` |
| `SALE_ASK_PRICE` | Text (Float > 0) | `price > 0` | `SALE_ASK_WARRANTY` | Stores price in `current_item` |
| `SALE_ASK_WARRANTY` | Button `warranty_<dur>` | Standard duration | `SALE_ASK_ADD_ANOTHER` | Appends item to cart |
| `SALE_ASK_WARRANTY` | Button `warranty_custom` | None | `SALE_ASK_CUSTOM_WARRANTY` | Prompts custom warranty string |
| `SALE_ASK_CUSTOM_WARRANTY` | Text (Non-empty) | Non-empty | `SALE_ASK_ADD_ANOTHER` | Appends item to cart |
| `SALE_ASK_ADD_ANOTHER` | Button `add_another_yes` | None | `SALE_ASK_PRODUCT_NAME` | Clears `current_item` for next item |
| `SALE_ASK_ADD_ANOTHER` | Button `add_another_no` | None | `SALE_ASK_DATE` | Retains full cart |
| `SALE_ASK_DATE` | Button `date_today` | None | `SALE_ASK_GENERATE_INVOICE` | Sets `sale_date` to today |
| `SALE_ASK_DATE` | Button `date_custom` | None | `SALE_ASK_CUSTOM_DATE` | Prompts `DD MMM` |
| `SALE_ASK_CUSTOM_DATE` | Text (`DD MMM`) | Valid date | `SALE_ASK_GENERATE_INVOICE` | Parses with current year |
| `SALE_ASK_GENERATE_INVOICE`| Button `gen_invoice_no` | None | `STATE_IDLE` | Saves anonymous sale; ends flow |
| `SALE_ASK_GENERATE_INVOICE`| Button `gen_invoice_yes`| None | `SALE_ASK_CUSTOMER_PHONE` | Prompts for 10-digit phone |
| `SALE_ASK_CUSTOMER_PHONE` | Text (Phone Number) | Customer in DB | `SALE_CONFIRM_CUSTOMER_NAME`| Displays customer summary |
| `SALE_ASK_CUSTOMER_PHONE` | Text (Phone Number) | New customer | `SALE_ASK_CUSTOMER_NAME` | Prompts for customer name |
| `SALE_CONFIRM_CUSTOMER_NAME`| Button `cust_name_use_saved` | None | `SALE_CONFIRM_PREVIEW` | Uses existing name |
| `SALE_CONFIRM_CUSTOMER_NAME`| Text (New Name) | Non-empty | `SALE_CONFIRM_PREVIEW` | Replaces customer name |
| `SALE_ASK_CUSTOMER_NAME` | Text (Name) | Non-empty | `SALE_CONFIRM_PREVIEW` | Sets new customer name |
| `SALE_CONFIRM_PREVIEW` | Button `preview_pdf_gen`| None | `SALE_SHOW_PDF_PREVIEW` | Generates PDF & uploads to Meta |
| `SALE_SHOW_PDF_PREVIEW` | Button `pdf_send_customer` | None | `STATE_IDLE` | Commits sale to DB; sends invoice |

---

## 2. Implicit State Machines

### 2.1 Customer Support Ticket State Machine
* **Fields:** `Customer.ticket_active` (bool), `Customer.ticket_number` (string), `Customer.notifications_enabled` (bool), `Customer.last_ticket_activity` (datetime).
* **Quiescent State:** `TICKET_CLOSED` (`ticket_active = False`).
* **Active State:** `TICKET_ACTIVE` (`ticket_active = True`).

```
                    ┌────────────────────────┐
                    │     TICKET_CLOSED      │
                    │ (ticket_active = False)│
                    └───────────┬────────────┘
                                │ cust_menu_talk_owner
                                ▼
                    ┌────────────────────────┐
   cust messages    │     TICKET_ACTIVE      │  admin direct replies
 ──────────────────►│ (ticket_active = True) │◄─────────────────────
 (forwards to owner)│ (ticket_num = TKT-...) │  (forwards to cust)
                    └───────────┬────────────┘
                                │ close / 1hr timeout / admin button
                                ▼
                    ┌────────────────────────┐
                    │     TICKET_CLOSED      │
                    └────────────────────────┘
```

#### Invariants:
1. When `ticket_active == True`, `ticket_number` MUST be non-null.
2. When `ticket_active == True`, customer inbound messages MUST be forwarded to all administrators.
3. When `ticket_active == True`, customer inbound messages MUST NEVER be suppressed by `bot_paused_until`.
4. When `ticket_active == False`, customer messages invoke the standard interactive customer menu.

---

### 2.2 Customer Bot Silence (Intervention Pause) State Machine
* **Field:** `Customer.bot_paused_until` (timestamp, nullable).
* **States:**
  - `BOT_ACTIVE`: `bot_paused_until IS NULL` OR `utcnow() >= bot_paused_until`.
  - `BOT_SILENCED`: `utcnow() < bot_paused_until`.

#### Invariants:
1. `BOT_SILENCED` is entered when Meta sends a `status == "sent"` webhook for a message ID not produced by the bot.
2. In `BOT_SILENCED`, automated generic menu fallbacks must be suppressed to avoid interrupting the owner's manual conversation.
3. **Crucial Invariant:** An active support ticket (`ticket_active == True`) takes precedence over `BOT_SILENCED`. Ticket messages MUST continue being delivered to the owner.
4. Explicit customer opt-out (`STOP`) or explicit menu navigation (`MENU`) must clear or bypass `BOT_SILENCED`.

---

### 2.3 Product Catalogue Lifecycle
* **Field:** `Product.is_active` (bool).
* **States:** `ACTIVE` (`is_active = True`), `INACTIVE` (`is_active = False`).
* **Invariant:** Products referenced by historical sales items (`SaleItem.product_id == Product.id`) MUST NOT be deleted from the database. Deleting them must transition them to `INACTIVE` (soft delete) to maintain relational integrity.

---

### 2.4 Inbound Webhook Idempotency Machine
* **Key:** `msg["id"]` (`wamid.HBg...`).
* **States:** `UNPROCESSED`, `PROCESSED`.
* **Invariant:** Every incoming message ID from Meta must be processed at most once. Webhook retries from Meta must not cause duplicate state transitions, duplicate billing, or duplicate WhatsApp messages.

---

## 3. Discovered Invalid States, Transitions & Race Conditions

### Bug Group A: Bot Silence Traps Active Support Tickets (Impact: CRITICAL)
* **Evidence:** In `state_machine.py`, lines 151-153 evaluated `customer.bot_paused_until` before line 156 (`if customer.ticket_active:`).
* **Reachable Invalid State:**
  1. Customer opens ticket (`ticket_active = True`).
  2. Owner manually types "Hello" to the customer on WhatsApp.
  3. Webhook receives `status == "sent"`, setting `customer.bot_paused_until = now + 1 hour`.
  4. Customer replies: "Do you have the 12W bulb in stock?".
  5. State machine dropped the message at line 152 because `bot_paused_until` was in the future.
  6. **Result:** Customer was silenced inside an active ticket; messages never forwarded to the owner; customer could not exit via "close".

### Bug Group B: Webhook Duplicate Delivery / Retry Re-Execution (Impact: HIGH)
* **Evidence:** `webhook.py` parsed `entry -> changes -> messages` and immediately invoked `process_message()` without deduplicating `msg.get("id")`.
* **Reachable Invalid State:**
  1. Meta delivered a webhook for an admin clicking "Send Invoice" (`pdf_send_customer`).
  2. If the response timed out (>3000ms), Meta retried the webhook.
  3. The handler executed `pdf_send_customer` a second time, generating two separate `Sale` records, two invoices, and sending duplicate messages to the customer.

### Bug Group C: Support Ticket Inactive Inactivity Checker Misses Null Activity (Impact: MEDIUM)
* **Evidence:** In `scheduler.py`, `check_inactive_tickets_job` filtered `Customer.last_ticket_activity < one_hour_ago`.
* **Reachable Invalid State:** If a customer record was created or migrated with `last_ticket_activity IS NULL` and `ticket_active = True`, SQL comparison `< one_hour_ago` evaluated to NULL (falsy), causing the ticket to stay active permanently.

### Bug Group D: Premature Mutation of Customer Profile on Preview (Impact: MEDIUM)
* **Evidence:** In `SALE_CONFIRM_PREVIEW`, `customer_repo.create` or `customer.name = cust_name` committed to the database before the admin approved sending the invoice in `SALE_SHOW_PDF_PREVIEW`.
* **Reachable Invalid State:** If the admin cancelled the preview, the database retained the newly registered customer or modified name despite the sale being cancelled.

### Bug Group E: Blind Routing & Admin Main Menu Lockout in `STATE_IDLE` (Impact: MEDIUM)
* **Evidence:** In `state_machine.py`, `_process_admin_idle` forwarded any unrecognized text to `Customer.ticket_active == True` ordered by latest activity.
* **Reachable Invalid State:** If an admin in `STATE_IDLE` typed "menu", it forwarded "menu" to the customer instead of showing the admin menu, locking the admin out of the main menu while tickets were open.

---

## 4. Fixes & Regression Test Coverage

| Issue ID | Priority | Component | Fix Implemented | Regression Test | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **ISSUE-1** | Critical | `app/services/state_machine.py` | Prioritized active ticket checks before `bot_paused_until`. Allowed `MENU`, `START`, `STOP`, `HELLO`, `HI` to bypass pause. | `test_active_ticket_bypasses_bot_paused` | **Verified (Passed)** |
| **ISSUE-2** | High | `app/routers/webhook.py` | Added in-memory deduplication cache (`processed_inbound_message_ids`, maxlen 5000). Repeated `msg["id"]` drops duplicate execution from Meta webhook retries. | `test_webhook_inbound_deduplication` | **Verified (Passed)** |
| **ISSUE-3** | Medium | `app/services/scheduler.py` | Updated `check_inactive_tickets_job` to include `or_(Customer.last_ticket_activity < one_hour_ago, Customer.last_ticket_activity == None)`. | `test_ticket_auto_close_with_null_activity` | **Verified (Passed)** |
| **ISSUE-4** | Medium | `app/services/state_machine.py` | Removed premature DB customer mutation during `SALE_CONFIRM_PREVIEW`. Deferred creation and updates to explicit confirmation in `SALE_SHOW_PDF_PREVIEW`. | `test_sale_preview_does_not_mutate_customer_before_confirmation` | **Verified (Passed)** |
| **ISSUE-5** | Medium | `app/services/state_machine.py` | Added explicit `menu` / `main menu` check in `STATE_IDLE` before ticket forwarding. Added active ticket count notice. | `test_admin_idle_menu_with_active_ticket` | **Verified (Passed)** |
| **ISSUE-6** | Medium | `app/services/state_machine.py` | Protected `PRIMARY_ADMIN_PHONE` from deletion and excluded it from the removal list in `ADMIN_REMOVE_SELECT`. | `test_primary_admin_protected_from_deletion` | **Verified (Passed)** |
| **ISSUE-7** | Medium | `app/repositories/sale.py` | Added retry loop with rollback on concurrent invoice number collision in `SaleRepository.create()`. | `test_sale_repository_custom_invoice_number` | **Verified (Passed)** |

