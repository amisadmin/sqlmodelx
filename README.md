<h2 align="center">
  SQLModelX
</h2>
<p align="center">
    <em>SQLModelX is an extension of the SQLModel library.</em><br/>
</p>
<p align="center">
    <a href="https://github.com/amisadmin/sqlmodelx/actions/workflows/pytest.yml" target="_blank">
        <img src="https://github.com/amisadmin/sqlmodelx/actions/workflows/pytest.yml/badge.svg" alt="Pytest">
    </a>
    <a href="https://pypi.org/project/sqlmodelx" target="_blank">
        <img src="https://badgen.net/pypi/v/sqlmodelx?color=blue" alt="Package version">
    </a>
    <a href="https://gitter.im/amisadmin/fastapi-amis-admin">
        <img src="https://badges.gitter.im/amisadmin/fastapi-amis-admin.svg" alt="Chat on Gitter"/>
    </a>
    <a href="https://jq.qq.com/?_wv=1027&k=U4Dv6x8W" target="_blank">
        <img src="https://badgen.net/badge/qq%E7%BE%A4/229036692/orange" alt="229036692">
    </a>
</p>

## Install

```bash
pip install sqlmodelx
```

## Usage

```python
from datetime import datetime
from typing import List

from sqlmodel import Field, Relationship, Session, select

from sqlmodelx import SQLModel
from sqlmodelx.main import SQLModelMetaclass

class PkMixin(SQLModel):
    id: int = Field(default = None, primary_key = True, nullable = False)

class BaseUser(PkMixin):
    username: str = Field(default = '', nullable = False)
    password: str = Field(default = '', nullable = False)
    create_time: datetime = Field(default_factory = datetime.now, nullable = False)
    group_id: int = Field(default = None, nullable = True, foreign_key = 'group.id')

class User(BaseUser, table = True):
    __tablename__ = 'user'
    group: 'Group' = Relationship(back_populates = 'users')

class Group(SQLModel, table = True):
    id: int = Field(default = None, primary_key = True, nullable = False)
    name: str = Field(default = '', nullable = False)
    create_time: datetime = Field(default_factory = datetime.now, nullable = False)
    users: List[User] = Relationship(
        back_populates = 'group',
        sa_relationship_kwargs = {"enable_typechecks": False}
    )

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
    class NickNameUser(User, table = True):
        nickname: str = Field(default = '')

    # Extend the user ORM model to add a field
    class AvatarUser(NickNameUser, table = True):
        avatar: str = Field(default = '')

    # Create the database tables
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    avatar_user = AvatarUser(
        username = "Deadpond",
        password = "Dive Wilson",
        nickname = 'nickname',
        avatar = 'avatar',
        group = Group(name = 'admin'),
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
    class NickNameUserSchema(User, table = False):
        nickname: str = Field(default = '')

    user = User(
        username = "Deadpond",
        password = "Dive Wilson",
        group = Group(name = 'admin')
    )

    with Session(engine) as session:
        session.add(user)
        session.commit()
        session.refresh(user)
        assert user.id is not None
        assert user.group.id is not None

        user_ex = NickNameUserSchema.from_orm(user, update = {'nickname': 'nickname'})
        assert user_ex.id == user.id
        assert user_ex.nickname == 'nickname'
        assert user_ex.group is None

```

## License

According to the `Apache2.0` protocol.
