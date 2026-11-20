# BizPilot — Retail & Commerce Automation

[![Python Version](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-2563EB.svg?style=flat-square)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-059669.svg?style=flat-square)](https://fastapi.tiangolo.com)
[![WhatsApp Cloud API](https://img.shields.io/badge/Meta%20Cloud%20API-v19.0-16A34A.svg?style=flat-square)](https://developers.facebook.com/docs/whatsapp/cloud-api)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-0284C7.svg?style=flat-square)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-475569.svg?style=flat-square)](https://www.docker.com/)
[![Tests Passing](https://img.shields.io/badge/Tests-23%2F23%20Passing-0D9488.svg?style=flat-square)]()

BizPilot is an omnichannel commerce, billing, catalogue management, and customer operations platform engineered for modern retail and electronics stores.

The system unifies conversational WhatsApp commerce, an in-store web Point-of-Sale (POS) terminal, automated ReportLab PDF invoice generation, bi-directional Google Sheets inventory synchronization, Gemini 2.5 Flash copywriting, and an intelligent customer support bridge with owner-intervention detection.

---

## Table of Contents
- [Architecture](#architecture)
- [Key Features](#key-features)
- [Technology Stack](#technology-stack)
- [Directory Layout](#directory-layout)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Local Setup](#local-setup)
  - [Docker Compose Deployment](#docker-compose-deployment)
- [Environment Configuration](#environment-configuration)
- [Meta WhatsApp Cloud API Configuration](#meta-whatsapp-cloud-api-configuration)
- [Web Admin & POS Dashboards](#web-admin--pos-dashboards)
- [State Machine Architecture](#state-machine-architecture)
- [Automated Testing](#automated-testing)
- [API Reference](#api-reference)
- [License](#license)

---

## Architecture

```mermaid
flowchart TD
    Meta["Meta WhatsApp Cloud API"] <-->|Inbound / Outbound Webhooks| WebhookRouter["Webhook Router (/webhook)"]
    WebhookRouter --> Deduplication["In-Memory Message Deduplicator (wamid LRU)"]
    Deduplication --> StateMachine["StateMachineService (Core Engine)"]
    
    subgraph Core Engine
        StateMachine --> AdminFlow["Admin State Machine (23 States)"]
        StateMachine --> CustFlow["Customer State Machine & Support Desk"]
        StateMachine --> PauseEngine["Intervention Detection & Silence Engine"]
    end
    
    subgraph Data & Persistence
        AdminFlow <--> DB[(PostgreSQL / SQLite)]
        CustFlow <--> DB
        DB <--> WebAdmin["FastAPI Web Admin & POS Dashboard"]
    end
    
    subgraph Integrations
        AdminFlow --> Gemini["Google Gemini 2.5 Flash (AI Copywriting)"]
        AdminFlow --> Sheets["Google Sheets Sync (Apps Script Webhook)"]
        AdminFlow --> PDF["ReportLab Engine (Invoices & Catalogues)"]
        AdminFlow --> Excel["OpenPyXL Engine (Analytics & LTV Exports)"]
    end

    subgraph Background Daemons
        Scheduler["APScheduler"] --> InactivityCheck["Support Ticket Inactivity Auto-Close"]
        Scheduler --> SheetsPeriodic["Periodic Inventory Sync"]
    end
```

---

## Key Features

### Conversational Commerce & Invoicing
- **Fuzzy Product Resolution**: Powered by `RapidFuzz` for typo-tolerant product lookups directly within conversational chat.
- **Dynamic PDF Invoice Rendering**: Generates retail invoices formatted with a structured monochrome aesthetic, GST calculations, itemized breakdown, and currency words conversion.
- **Collision-Resistant Invoice Sequencing**: Auto-incrementing invoice numbering (`RM-YYYYMMDD-XXXX`) backed by database rollback and sequence recalculation against concurrent transactions.
- **Direct WhatsApp Dispatch**: Uploads generated PDFs to Meta's media CDN and delivers them as interactive document messages.

### Warranty Tracking & Lifecycle Engine
- **Calendar-Accurate Calculations**: Computes exact warranty expiration across months of varying lengths (e.g., `11 Months and 28 Days left`).
- **Customer Self-Service**: Customers can inspect past orders, active warranties, and product details on demand via the WhatsApp self-service menu.

### Support Ticketing & Owner Intervention Bridge
- **Two-Way Support Routing**: Customers can initiate a support ticket (`#TKT-XXXX`) that routes incoming inquiries to store administrators in real time.
- **Owner Manual Intervention Detection**: When store owners reply manually to a customer via a linked WhatsApp mobile device, the platform intercepts the webhook `sent` status and pauses automated bot responses for 1 hour to prevent interference.
- **Inactivity Timeout**: Background workers automatically resolve stale tickets after 1 hour of silence, alerting both customer and admin.

### AI-Assisted Broadcast Marketing
- **Gemini 2.5 Flash Copywriting**: Automatically formats promotional announcements into clear, structured marketing copy with calls to action while filtering out internal reasoning thoughts.
- **Opt-Out Compliance**: Built-in subscription status management (`STOP` / `START`) to maintain regulatory compliance.

### Google Sheets Catalogue Synchronization
- **Google Apps Script Bridge**: Synchronizes stock, categories, and prices with Google Sheets via secure shared-secret token authentication, eliminating service account credential bottlenecks.

### Web Management Interfaces
- **Catalogue Manager (`/admin/catalogue`)**: Fast web UI for managing products, categories, active stock flags, and triggering manual sync operations.
- **Web Point of Sale (`/admin/sales`)**: Desktop-friendly POS terminal for counter sales, customer lookups, multi-item cart management, and real-time invoice previewing.

---

## Technology Stack

- **Application Backend**: FastAPI (Asynchronous Python)
- **ASGI Server**: Uvicorn
- **ORM & Data Layer**: SQLAlchemy 2.0 with Alembic database migrations
- **Databases**: PostgreSQL 15+ (Production) / SQLite (Testing & Local Development)
- **Document & Spreadsheet Generation**: ReportLab (PDF) and OpenPyXL (Excel)
- **Fuzzy Matching**: RapidFuzz
- **Background Scheduling**: APScheduler
- **AI Processing**: Google Gemini API (`gemini-2.5-flash`)
- **Containerization**: Docker & Docker Compose

---

## Directory Layout

```
├── alembic/                 # Database schema migrations
├── app/
│   ├── config.py            # Pydantic settings & environment configuration
│   ├── database.py          # Database session factory & schema self-healing
│   ├── main.py              # Application lifecycle & FastAPI root
│   ├── models/              # SQLAlchemy domain models
│   ├── repositories/        # Database query & persistence layer
│   ├── routers/             # Webhook handlers & web admin routes
│   ├── services/            # Core business logic (State Machine, PDF, Sheets, Gemini)
│   ├── templates/           # HTML templates for Web POS and Catalogue
│   └── utils/               # Phone formatting, currency casing, and math helpers
├── invoices/                # Working directory for rendered invoice files
├── tests/                   # Pytest test suite (Core, Enhancements, State Machines)
├── .env.example             # Template for required environment variables
├── docker-compose.yml       # PostgreSQL and application service definition
├── Dockerfile               # Production container definition
├── pytest.ini               # Pytest configuration
├── enhancements_info.md     # Engineering change history
├── requirements.txt         # Production dependencies
└── STATE_MACHINES.md        # State machine specifications & invariant analysis
```

---

## Getting Started

### Prerequisites
- Python 3.11, 3.12, or 3.13
- PostgreSQL 15+ (or SQLite for local evaluation)
- Meta WhatsApp Business Cloud API developer account
- Google Gemini API key (optional for broadcast assistance)

---

### Local Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/not-ayan/BizPilot.git
   cd BizPilot
   ```

2. **Create and activate a virtual environment**:
   ```bash
   # Windows
   python -m venv .venv
   .venv\Scripts\activate

   # Linux / macOS
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Set up environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

5. **Run the development server**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

   Interactive OpenAPI documentation is available at `http://localhost:8000/docs`.

---

### Docker Compose Deployment

To run the application alongside an isolated PostgreSQL container:

```bash
docker-compose up --build -d
```

Verify service status:
```bash
curl http://localhost:8000/
```

---

## Environment Configuration

| Variable | Description | Example / Default |
| :--- | :--- | :--- |
| `DATABASE_URL` | PostgreSQL or SQLite connection URI | `postgresql://postgres:postgres@localhost:5432/bizpilot` |
| `WHATSAPP_TOKEN` | Meta WhatsApp Cloud API Permanent Access Token | `EAAN...` |
| `WHATSAPP_PHONE_NUMBER_ID`| Meta Phone Number Identifier | `1147488658455129` |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | Meta Business Account Identifier (WABA) | `1264480849097479` |
| `WHATSAPP_WEBHOOK_VERIFY_TOKEN` | Verification token configured in Meta App Dashboard | `your_webhook_verify_token` |
| `WHATSAPP_API_VERSION` | Meta Graph API Version | `v19.0` |
| `PRIMARY_ADMIN_PHONE` | Primary administrator mobile number (10 digits) | `9876543210` |
| `SECRET_KEY` | Application secret key for session signatures | `your_secret_key_here` |
| `PORT` | Application listening port | `8000` |
| `PDF_OUTPUT_DIR` | Directory path for generated PDF invoices | `invoices` |
| `GEMINI_API_KEY` | Google Gemini API key for marketing assistant | `AIzaSy...` |
| `GOOGLE_SHEET_URL` | Google Apps Script Web App sync endpoint | `https://script.google.com/macros/s/.../exec` |
| `GOOGLE_SHEETS_API_SECRET` | Passphrase for Apps Script endpoint authentication | `your_sync_passphrase` |

---

## Meta WhatsApp Cloud API Configuration

1. In the **Meta App Dashboard**, navigate to **WhatsApp > Configuration**.
2. Under **Webhook**:
   - **Callback URL**: `https://your-domain.com/webhook`
   - **Verify Token**: Must match `WHATSAPP_WEBHOOK_VERIFY_TOKEN` in `.env`.
3. Under **Webhook Fields**, subscribe to:
   - `messages`: Processes customer and admin conversation input.
   - `message_status`: Enables owner intervention detection and bot auto-pause.
4. Ensure the phone number has an active WhatsApp Business payment profile configured.

---

## Web Admin & POS Dashboards

The application provides two browser-based interfaces:

- **Catalogue Management (`/admin/catalogue`)**: Real-time product editing, category administration, and Google Sheets synchronization.
- **Sales POS Terminal (`/admin/sales`)**: Counter checkout interface with customer search, dynamic multi-item cart, live invoice PDF preview, and WhatsApp auto-dispatch.

---

## State Machine Architecture

The conversation flow is strictly governed by explicit and implicit state machines documented with transition tables in [STATE_MACHINES.md](STATE_MACHINES.md):

- **Explicit Admin Conversation States**: A 23-state machine managing multi-item sales, preview confirmations, broadcast composition, customer search, inventory edits, and admin roles.
- **Implicit Domain Machines**:
  - Customer Support Desk Machine (`TICKET_CLOSED` <-> `TICKET_ACTIVE`)
  - Owner Intervention Machine (`BOT_ACTIVE` <-> `BOT_SILENCED`)
  - Product Lifecycle Machine (`ACTIVE` <-> `INACTIVE` soft deletion)
  - Inbound Webhook Idempotency Machine (`UNPROCESSED` -> `PROCESSED`)

---

## Automated Testing

Execute the test suite with pytest:

```bash
pytest -v
```

### Coverage Highlights:
- **Core Engine**: Number-to-words currency formatting, fuzzy product matching, and ReportLab PDF layout generation.
- **Idempotency & Retries**: Webhook duplicate delivery deduplication tests.
- **State Machine Invariants**: Support tickets bypass bot silence, cancellation preserves database customer state, and primary admin credentials cannot be deleted.
- **Reporting & Exports**: Native Excel `.xlsx` workbook generation, customer lifetime value calculations, and scheduler inactivity timeouts.

---

## API Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Service health check |
| `GET` | `/webhook` | Meta Webhook challenge verification |
| `POST`| `/webhook` | Inbound WhatsApp message and status callback |
| `GET` | `/admin/catalogue` | Catalogue Management Web Interface |
| `GET` | `/admin/sales` | Web Point of Sale (POS) Terminal |
| `GET` | `/api/web/products` | List all inventory products |
| `POST`| `/api/web/products` | Create an inventory product |
| `POST`| `/api/web/sync` | Trigger Google Sheets catalogue sync |
| `POST`| `/api/web/sales` | Record a new sale transaction & issue invoice |
| `POST`| `/api/web/sales/preview`| Generate draft PDF invoice preview |
| `POST`| `/api/reports/weekly` | Generate on-demand store analytics report |

---

## License

Designed and maintained for BizPilot Commerce & Retail.  
All rights reserved.
