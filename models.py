from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Chat(Base):
    __tablename__ = "chat"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    type: Mapped[str] = mapped_column(String(32))
    chat_title: Mapped[str | None] = mapped_column(String, default=None)
    last_applied_title: Mapped[str | None] = mapped_column(String, default=None)

    variables: Mapped[list["Variable"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan"
    )


class Variable(Base):
    __tablename__ = "variable"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chat.id"))
    name: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String(16))
    value: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    chat: Mapped["Chat"] = relationship(back_populates="variables")
