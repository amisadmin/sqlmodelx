from datetime import datetime
from typing import List, Optional

from sqlmodel import Field, Relationship

from sqlmodelx import SQLModel


class PkMixin(SQLModel):
    id: Optional[int] = Field(default=None, primary_key=True, nullable=False)


class UpdateTimeMixin(SQLModel):
    update_time: datetime = Field(default_factory=datetime.now, nullable=False)


class BaseUser(PkMixin):
    __tablename__ = "user"
    username: str = Field(default="", nullable=False, index=True)
    password: str = Field(default="", nullable=False)
    create_time: datetime = Field(default_factory=datetime.now, nullable=False)
    group_id: Optional[int] = Field(default=None, nullable=True, foreign_key="group.id")


class User(BaseUser, table=True):
    pass
    group: "Group" = Relationship(back_populates="users")


class Group(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True, nullable=False)
    name: str = Field(default="", nullable=False)
    create_time: datetime = Field(default_factory=datetime.now, nullable=False)
    users: List[User] = Relationship(back_populates="group", sa_relationship_kwargs={"enable_typechecks": False})


User.update_forward_refs()
