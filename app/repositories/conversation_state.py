from sqlalchemy.orm import Session
from app.models.conversation_state import ConversationState

class ConversationStateRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, phone_number: str) -> ConversationState:
        return self.db.query(ConversationState).filter(ConversationState.phone_number == phone_number).first()

    def save(self, phone_number: str, state: str, data: dict) -> ConversationState:
        import copy
        db_state = self.get(phone_number)
        if db_state:
            db_state.state = state
            db_state.data = copy.deepcopy(data)
        else:
            db_state = ConversationState(phone_number=phone_number, state=state, data=copy.deepcopy(data))
            self.db.add(db_state)
        self.db.commit()
        self.db.refresh(db_state)
        return db_state

    def delete(self, phone_number: str):
        db_state = self.get(phone_number)
        if db_state:
            self.db.delete(db_state)
            self.db.commit()
