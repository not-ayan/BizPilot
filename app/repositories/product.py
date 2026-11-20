from sqlalchemy.orm import Session
from app.models.product import Product

class ProductRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, product_id: int) -> Product:
        return self.db.query(Product).filter(Product.id == product_id).first()

    def get_by_name(self, name: str) -> Product:
        return self.db.query(Product).filter(Product.name.ilike(name)).first()

    def get_all_active(self) -> list[Product]:
        return self.db.query(Product).filter(Product.is_active == True).all()

    def get_all(self) -> list[Product]:
        return self.db.query(Product).all()

    def create_or_update(self, name: str, category: str, default_price: float, is_active: bool = True) -> Product:
        product = self.get_by_name(name)
        if product:
            product.category = category
            product.default_price = default_price
            product.is_active = is_active
        else:
            product = Product(name=name, category=category, default_price=default_price, is_active=is_active)
            self.db.add(product)
        self.db.commit()
        self.db.refresh(product)
        return product

    def set_active_status(self, name: str, is_active: bool) -> bool:
        product = self.get_by_name(name)
        if product:
            product.is_active = is_active
            self.db.commit()
            return True
        return False

    def delete(self, product: Product):
        self.db.delete(product)
        self.db.commit()
