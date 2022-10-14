import pytest
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base, declared_attr
from sqlmodel import Session


@pytest.mark.skip("dev")
def test_sqlalchemy_features(engine):
    from sqlalchemy.ext.hybrid import hybrid_property

    Base = declarative_base()

    class Group(Base):
        __tablename__ = "group"
        id = Column(Integer, primary_key=True)
        name = Column(String)

    class MyUser(Base):
        __tablename__ = "user"
        id = Column(Integer, primary_key=True)
        firstname = Column(String(50))
        lastname = Column(String(50))

        @hybrid_property
        def fullname(self):
            return self.firstname + " " + self.lastname

        @declared_attr
        def group_id(self):
            return Column(ForeignKey("group.id"))

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    group = Group(name="admin")

    user = MyUser(
        firstname="Deadpond",
        lastname="Dive Wilson",
    )

    with Session(engine) as session:
        session.add(group)
        session.commit()
        session.refresh(group)
        assert group.id is not None
        user.group_id = group.id
        session.add(user)
        session.commit()
        session.refresh(user)
        assert user.id is not None
        assert user.fullname == "Deadpond Dive Wilson"
