from datetime import datetime
from typing import List

from sqlalchemy import Column, ForeignKey, Integer, String, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import (
    InstrumentedAttribute,
    column_property,
    declared_attr,
    deferred,
    relationship,
)
from sqlmodel import Field, Relationship, Session, select

from sqlmodelx import SQLModel
from sqlmodelx.main import SQLModelMetaclass


class PkMixin(SQLModel):
    id: int = Field(default=None, primary_key=True, nullable=False)


class BaseUser(PkMixin):
    username: str = Field(default="", nullable=False)
    password: str = Field(default="", nullable=False)
    create_time: datetime = Field(default_factory=datetime.now, nullable=False)
    group_id: int = Field(default=None, nullable=True, foreign_key="group.id")


class User(BaseUser, table=True):
    __tablename__ = "user"
    group: "Group" = Relationship(back_populates="users")


class Group(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True, nullable=False)
    name: str = Field(default="", nullable=False)
    create_time: datetime = Field(default_factory=datetime.now, nullable=False)
    users: List[User] = Relationship(back_populates="group", sa_relationship_kwargs={"enable_typechecks": False})


def test_class_and_metaclass(engine):
    """Test class and metaclass"""
    from sqlmodel import SQLModel as _SQLModel
    from sqlmodel.main import SQLModelMetaclass as _SQLModelMetaclass

    assert isinstance(User, SQLModelMetaclass)
    assert isinstance(User, _SQLModelMetaclass)
    assert issubclass(User, SQLModel)
    assert issubclass(User, _SQLModel)


def test_base_is_table_and_subclass_is_table(engine):
    """Test base class and subclass are both ORM database tables"""

    # Extend the user ORM model to add a field
    class NickNameUser(User, table=True):
        nickname: str = Field(default="")

    # Extend the user ORM model to add a field
    class AvatarUser(NickNameUser, table=True):
        avatar: str = Field(default="")

    # Create the database tables
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    avatar_user = AvatarUser(
        username="Deadpond",
        password="Dive Wilson",
        nickname="nickname",
        avatar="avatar",
        group=Group(name="admin"),
    )

    with Session(engine) as session:
        session.add(avatar_user)
        session.commit()
        session.refresh(avatar_user)
        assert avatar_user.id is not None
        # The relationship property of the base class will also be inherited
        assert avatar_user.group.id is not None

        nickname_user = session.query(NickNameUser).first()
        assert nickname_user.nickname == avatar_user.nickname
        # The relationship property of the base class will also be inherited
        assert nickname_user.group.id == avatar_user.group.id

        user = session.exec(select(User)).first()
        assert user.username == avatar_user.username
        assert user.group.id == avatar_user.group.id


def test_base_is_table_and_subclass_is_not_table(engine):
    """Test base class is an ORM database table, the subclass is not"""

    # Create a pydantic model quickly through inheritance
    class NickNameUserSchema(User, table=False):
        nickname: str = Field(default="")
        group_: Group = Field(default=None, alias="group")

    user = User(username="Deadpond", password="Dive Wilson", group=Group(name="admin"))

    with Session(engine) as session:
        session.add(user)
        session.commit()
        session.refresh(user)
        assert user.id is not None
        assert user.group.id is not None

        user_ex = NickNameUserSchema.from_orm(user, update={"nickname": "nickname"})
        assert user_ex.id == user.id
        assert user_ex.nickname == "nickname"
        assert user_ex.group_.id == user.group.id


def test_relationship_sa_relationship(engine):
    class MyUser(BaseUser, table=True):
        __tablename__ = "user"
        group: "Group" = Relationship(sa_relationship=relationship("Group"))

    # Create the database tables
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    user = MyUser(
        username="Deadpond",
        password="Dive Wilson",
        group=Group(name="admin"),
    )

    with Session(engine) as session:
        session.add(user)
        session.commit()
        session.refresh(user)
        assert user.id is not None
        assert user.group is not None


def test_SaColumnTypes(engine):
    class MyUser(PkMixin, table=True):
        __tablename__ = "user"

        id = Column(Integer, primary_key=True)

        firstname: str = Field(default="")
        lastname: str = Field(default="")

        info: str = deferred(Column(String(100)))  # lazy load column

        group_count: int = Field(sa_column=column_property(select(func.count(Group.id))))  # type: ignore
        """The type of the field is int, but the type of the column is sqlalchemy.orm.ColumnProperty"""

        group_count2 = column_property(select(func.count(Group.id)))

        @hybrid_property
        def fullname(self):
            return self.firstname + " " + self.lastname

        @declared_attr
        def group_id(self):
            return Column(ForeignKey("group.id"))

    # Create the database tables
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    # test declared_attr
    assert isinstance(MyUser.group_id, InstrumentedAttribute)

    user = MyUser(
        firstname="Deadpond",
        lastname="Dive Wilson",
        info="info",
        group_count=1,  # readonly
    )

    with Session(engine) as session:
        session.add(user)
        session.commit()
        session.refresh(user)

        # test attribute
        assert user.id is not None
        assert user.fullname == "Deadpond Dive Wilson"
        assert user.group_count == 0
        assert user.group_count2 == 0
        print("user.child_count", user.group_count)
        # test dict
        dct = user.dict()
        assert dct["id"] is not None
        assert "fullname" not in dct
        assert dct["group_count"] == 0

        # test deferred column
        assert "info" not in dct
        assert user.info == "info"  # load info column
        dct = user.dict()
        assert "info" in dct
        assert dct["info"] == "info"
