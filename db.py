from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SessionType
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URL
from models import Base, Chat

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
Session = sessionmaker(bind=engine)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_or_create_chat(session: SessionType, chat_id: int, chat_type: str) -> Chat:
    chat = session.get(Chat, chat_id)
    if chat is None:
        chat = Chat(id=chat_id, type=chat_type)
        session.add(chat)
        session.commit()
    elif chat.type != chat_type:
        chat.type = chat_type
        session.commit()
    return chat
