from sqlalchemy.orm import Session
from app.models.admin import Admin
from app.utils.phone import clean_phone_number

class AdminRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_phone(self, phone_number: str) -> Admin:
        return self.db.query(Admin).filter(Admin.phone_number == clean_phone_number(phone_number)).first()

    def get_all(self) -> list[Admin]:
        return self.db.query(Admin).all()

    def create(self, phone_number: str, name: str) -> Admin:
        admin = Admin(phone_number=clean_phone_number(phone_number), name=name)
        self.db.add(admin)
        self.db.commit()
        self.db.refresh(admin)
        return admin

    def delete(self, phone_number: str) -> bool:
        admin = self.get_by_phone(phone_number)
        if admin:
            self.db.delete(admin)
            self.db.commit()
            return True
        return False

