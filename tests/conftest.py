import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from sqlmodelx import SQLModel


@pytest.fixture()
def engine() -> Engine:
    engine_ = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine_)
    yield engine_
    SQLModel.metadata.drop_all(engine_)
