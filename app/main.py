import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, status, Response, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, get_db
from app.routers.webhook import router as webhook_router
from app.routers.admin_web import router as admin_web_router
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.sheets import sheets_service
from app.repositories.admin import AdminRepository
from app.services.report_generator import ReportGenerator

# Configure logging format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("app.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Ensure database tables are created
    logger.info("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    from app.database import upgrade_db_schema
    upgrade_db_schema()
    
    # Seed Primary Admin and default Categories if not present
    try:
        from sqlalchemy.orm import sessionmaker
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        
        # Seed Admin
        admin_repo = AdminRepository(session)
        primary_admin = admin_repo.get_by_phone(settings.PRIMARY_ADMIN_PHONE)
        if not primary_admin:
            admin_repo.create(settings.PRIMARY_ADMIN_PHONE, "Primary Admin")
            logger.info(f"Seeded primary admin phone: {settings.PRIMARY_ADMIN_PHONE}")
            
        # Seed Categories
        from app.models.category import Category
        from app.models.product import Product
        from app.utils.casing import to_title_case
        
        # Collect distinct categories from products and default list
        existing_prod_cats = [r[0] for r in session.query(Product.category).distinct().all() if r[0]]
        default_cats = {"Bulbs", "Inverters", "Appliances"}
        for cat in existing_prod_cats:
            default_cats.add(cat.strip())
            
        for cat_name in default_cats:
            formatted_name = to_title_case(cat_name)
            exists = session.query(Category).filter(Category.name == formatted_name).first()
            if not exists:
                new_cat = Category(name=formatted_name)
                session.add(new_cat)
        
        session.commit()
        session.close()
    except Exception as e:
        logger.error(f"Error seeding startup data: {e}")
    
    # Start background scheduler
    logger.info("Starting scheduler tasks...")
    start_scheduler()
    
    yield
    
    # Shutdown: Clean up background tasks
    logger.info("Stopping scheduler tasks...")
    stop_scheduler()

app = FastAPI(
    title="BizPilot WhatsApp Automation API",
    description="Production-grade business automation backend for BizPilot.",
    version="1.0.0",
    lifespan=lifespan
)

# Mount Routers
app.include_router(webhook_router, tags=["Webhook"])
app.include_router(admin_web_router, tags=["Admin Web Catalogue"])

@app.get("/", status_code=status.HTTP_200_OK)
def read_root():
    """System health check endpoint."""
    return {
        "status": "healthy",
        "app": "BizPilot WhatsApp Business Automation",
        "primary_admin": settings.PRIMARY_ADMIN_PHONE,
        "sheets_sync_enabled": sheets_service.enabled
    }

# Admin Manual Trigger REST Endpoints
@app.post("/api/catalogue/sync", tags=["System Management"])
def force_sync(db: Session = Depends(get_db)):
    """Manually triggers a catalog sync from Google Sheets to local DB."""
    res = sheets_service.sync_from_sheet(db)
    if res.get("errors", 0) > 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {res.get('error_msg')}"
        )
    return {"status": "success", "results": res}

@app.post("/api/reports/weekly", tags=["System Management"])
def manual_weekly_report(db: Session = Depends(get_db)):
    """Generates the weekly report text on demand."""
    generator = ReportGenerator(db)
    return {"report": generator.generate_weekly_report_text()}

@app.post("/api/reports/monthly", tags=["System Management"])
def manual_monthly_report(db: Session = Depends(get_db)):
    """Generates the monthly report text on demand."""
    generator = ReportGenerator(db)
    return {"report": generator.generate_monthly_report_text()}
