from apscheduler.schedulers.background import BackgroundScheduler
from app.database import SessionLocal
from app.repositories.admin import AdminRepository
from app.services.report_generator import ReportGenerator
from app.services.whatsapp import whatsapp_service
import logging

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

def send_weekly_report_job():
    logger.info("Executing automated weekly report job...")
    db = SessionLocal()
    try:
        admin_repo = AdminRepository(db)
        admins = admin_repo.get_all()
        if not admins:
            logger.warning("No registered admins found to receive weekly report.")
            return
            
        generator = ReportGenerator(db)
        report_text = generator.generate_weekly_report_text()
        
        for admin in admins:
            try:
                whatsapp_service.send_text(admin.phone_number, report_text)
                logger.info(f"Weekly report sent to admin: {admin.phone_number}")
            except Exception as e:
                logger.error(f"Failed to send weekly report to admin {admin.phone_number}: {e}")
    finally:
        db.close()

def send_monthly_report_job():
    logger.info("Executing automated monthly report job...")
    db = SessionLocal()
    try:
        admin_repo = AdminRepository(db)
        admins = admin_repo.get_all()
        if not admins:
            logger.warning("No registered admins found to receive monthly report.")
            return
            
        generator = ReportGenerator(db)
        report_text = generator.generate_monthly_report_text()
        
        for admin in admins:
            try:
                whatsapp_service.send_text(admin.phone_number, report_text)
                logger.info(f"Monthly report sent to admin: {admin.phone_number}")
            except Exception as e:
                logger.error(f"Failed to send monthly report to admin {admin.phone_number}: {e}")
    finally:
        db.close()

def check_inactive_tickets_job():
    logger.info("Executing automated ticket inactivity check job...")
    db = SessionLocal()
    try:
        from app.models.customer import Customer
        from datetime import datetime, timedelta
        
        # Tickets active for more than 1 hour or without recorded activity
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        inactive_customers = db.query(Customer).filter(
            Customer.ticket_active == True,
            (Customer.last_ticket_activity < one_hour_ago) | (Customer.last_ticket_activity == None)
        ).all()
        
        if not inactive_customers:
            logger.info("No inactive tickets found.")
            return
            
        for cust in inactive_customers:
            try:
                ticket_num = cust.ticket_number
                cust.ticket_active = False
                cust.notifications_enabled = False
                db.commit()
                db.refresh(cust)
                
                # Send customer auto-close notification
                whatsapp_service.send_text(
                    cust.phone_number,
                    "Your support ticket has been closed automatically due to 1 hour of inactivity. If you need further assistance, please open the menu."
                )
                
                # Send admin notification
                from app.repositories.admin import AdminRepository
                admin_repo = AdminRepository(db)
                admins = admin_repo.get_all()
                for admin in admins:
                    whatsapp_service.send_text(
                        admin.phone_number,
                        f"🎟️ Ticket #{ticket_num} for customer {cust.name} ({cust.phone_number}) was automatically closed due to 1 hour of inactivity."
                    )
                logger.info(f"Automatically closed inactive ticket #{ticket_num} for customer {cust.phone_number}")
            except Exception as e:
                logger.error(f"Failed to automatically close ticket for customer {cust.phone_number}: {e}")
    finally:
        db.close()

def start_scheduler():
    # Run every Wednesday night at 9:00 PM (21:00)
    scheduler.add_job(
        send_weekly_report_job, 
        'cron', 
        day_of_week='wed', 
        hour=21, 
        minute=0,
        id='weekly_report_job',
        replace_existing=True
    )
    
    # Run on the 1st of every month at 9:00 PM (21:00)
    scheduler.add_job(
        send_monthly_report_job, 
        'cron', 
        day='1', 
        hour=21, 
        minute=0,
        id='monthly_report_job',
        replace_existing=True
    )
    
    # Run ticket inactivity checker every 5 minutes
    scheduler.add_job(
        check_inactive_tickets_job,
        'interval',
        minutes=5,
        id='ticket_inactivity_check_job',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("Background report scheduler started.")

def stop_scheduler():
    scheduler.shutdown()
    logger.info("Background report scheduler stopped.")
