from sqlalchemy.orm import Session
from app.models.customer import Customer
from app.utils.phone import clean_phone_number

class CustomerRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_phone(self, phone_number: str) -> Customer:
        return self.db.query(Customer).filter(Customer.phone_number == clean_phone_number(phone_number)).first()

    def get_all_subscribed(self) -> list[Customer]:
        return self.db.query(Customer).filter(Customer.is_subscribed == True).all()

    def search_by_name_or_phone(self, query: str) -> list[Customer]:
        # Clean query if it looks like a phone number to match clean format
        cleaned_query = clean_phone_number(query) if any(c.isdigit() for c in query) else query
        return self.db.query(Customer).filter(
            (Customer.name.ilike(f"%{query}%")) | 
            (Customer.phone_number.like(f"%{cleaned_query}%"))
        ).all()

    def create(self, phone_number: str, name: str, is_subscribed: bool = False) -> Customer:
        from app.utils.casing import to_title_case
        customer = Customer(
            phone_number=clean_phone_number(phone_number), 
            name=to_title_case(name), 
            is_subscribed=is_subscribed,
            notifications_enabled=False,
            ticket_active=False
        )
        self.db.add(customer)
        self.db.commit()
        self.db.refresh(customer)
        return customer

    def update_subscription(self, phone_number: str, subscribe: bool) -> Customer:
        customer = self.get_by_phone(clean_phone_number(phone_number))
        if customer:
            customer.is_subscribed = subscribe
            self.db.commit()
            self.db.refresh(customer)
        return customer

    def update_ticket_status(self, phone_number: str, ticket_active: bool, notifications_enabled: bool, ticket_number: str = None) -> Customer:
        customer = self.get_by_phone(clean_phone_number(phone_number))
        if customer:
            customer.ticket_active = ticket_active
            customer.notifications_enabled = notifications_enabled
            if ticket_number is not None:
                customer.ticket_number = ticket_number
            from datetime import datetime
            customer.last_ticket_activity = datetime.utcnow()
            self.db.commit()
            self.db.refresh(customer)
        return customer


