from sqlalchemy import Column, ForeignKey, String, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import (
    InstrumentedAttribute,
    column_property,
    declared_attr,
    deferred,
)
from sqlmodel import Field, Relationship, Session, select
from sqlmodel._compat import IS_PYDANTIC_V2

from sqlmodelx import SQLModel
from sqlmodelx.main import SQLModelMetaclass


def test_class_and_metaclass(engine):
    """Test class and metaclass"""
    from sqlmodel import SQLModel as _SQLModel
    from sqlmodel.main import SQLModelMetaclass as _SQLModelMetaclass

    from .models import User

    assert isinstance(User, SQLModelMetaclass)
    assert isinstance(User, _SQLModelMetaclass)
    assert issubclass(User, SQLModel)
    assert issubclass(User, _SQLModel)


def test_base_is_table_and_subclass_is_table(engine):
    """Test base class and subclass are both ORM database tables"""
    from .models import Group, User

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

        nickname_user = session.scalar(select(NickNameUser))
        session.refresh(avatar_user)
        assert nickname_user.nickname == avatar_user.nickname
        # The relationship property of the base class will also be inherited
        assert nickname_user.group.id == avatar_user.group.id

        user = session.exec(select(User)).first()
        assert user.username == avatar_user.username
        assert user.group.id == avatar_user.group.id


def test_base_is_table_and_subclass_is_not_table(engine):
    """Test base class is an ORM database table, the subclass is not"""
    from .models import Group, User

    # Create a pydantic model quickly through inheritance
    class NickNameUserSchema(User, table=False):
        nickname: str = Field(default="")
        if IS_PYDANTIC_V2:
            group: Group = Field(default=None)
        else:
            group_: Group = Field(default=None, alias="group")

    # Create the database tables
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    user = User(username="Deadpond", password="Dive Wilson", group=Group(name="admin"))

    with Session(engine) as session:
        session.add(user)
        session.commit()
        session.refresh(user)
        assert user.id is not None
        assert user.group.id is not None

        user_ex = NickNameUserSchema.from_orm(user)
        # todo: fix bug. when pydantic v2 use from_orm, update parameter is not supported
        # user_ex = NickNameUserSchema.from_orm(user, update={"nickname": "nickname"})
        # assert user_ex.nickname == "nickname"
        assert user_ex.id == user.id
        if IS_PYDANTIC_V2:
            assert user_ex.group.id == user.group.id
        else:
            assert user_ex.group_.id == user.group.id


def test_relationship_sa_relationship(engine):
    from .models import BaseUser, Group

    class MyUser(BaseUser, table=True):
        __tablename__ = "user"
        group: Group = Relationship()

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
    from .models import Group, PkMixin

    class MyUser(PkMixin, table=True):
        __tablename__ = "user"

        firstname: str = Field(default="")
        lastname: str = Field(default="")

        info: str = deferred(Column(String(100)))  # lazy load column

        group_count: int = Field(sa_column=column_property(select(func.count(Group.id)).scalar_subquery()))  # type: ignore
        """The type of the field is int, but the type of the column is sqlalchemy.orm.ColumnProperty"""

        group_count2 = column_property(select(func.count(Group.id)).scalar_subquery())

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
