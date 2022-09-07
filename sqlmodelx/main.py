from typing import Dict, Tuple, Any, ForwardRef, List

from pydantic import BaseConfig
from pydantic.fields import ModelField
from pydantic.main import ModelMetaclass
from sqlalchemy import Table, inspect
from sqlalchemy.orm import DeclarativeMeta, relationship, RelationshipProperty, declared_attr
from sqlmodel import SQLModel as _SQLModel
from sqlmodel.main import SQLModelMetaclass as _SQLModelMetaclass, get_column_from_field

def _remove_duplicate_index(table: Table):
    if table.indexes:
        indexes = set()
        names = set()
        for index in table.indexes:
            if index.name not in names:
                names.add(index.name)
                indexes.add(index)
        table.indexes = indexes

class _SQLModelBasesInfo:

    def __init__(self, bases):
        self.is_table = False
        self.tablename = None
        self.columns = {}
        self.sqlmodel_relationships = {}
        for base in bases:
            config = getattr(base, "__config__", None)
            if config and getattr(config, "table", False):
                self.is_table = True
                self.tablename = base.__tablename__
                # noinspection PyProtectedMember
                self.columns.update(base.__table__.columns._index)
                self.sqlmodel_relationships.update(base.__sqlmodel_relationships__)

class SQLModelMetaclass(_SQLModelMetaclass):

    # noinspection PyMissingConstructor
    def __init__(
        cls, classname: str, bases: Tuple[type, ...], dict_: Dict[str, Any], **kw: Any
    ) -> None:
        # Only one of the base classes (or the current one) should be a table model
        # this allows FastAPI cloning a SQLModel for the response_model without
        cls._bases = _SQLModelBasesInfo(bases)
        if getattr(cls.__config__, "table", False) and (not cls._bases.is_table or kw.get('table', False)):
            dict_used = dict_.copy()
            for field_name, field_value in cls.__fields__.items():
                col = cls._bases.columns.get(field_name, None)  # Ensure that the column is unique
                if col is None:
                    col = get_column_from_field(field_value)
                else:
                    setattr(cls, field_name, col)
                dict_used[field_name] = col
            for rel_name, rel_info in cls.__sqlmodel_relationships__.items():
                if rel_info.sa_relationship:
                    # There's a SQLAlchemy relationship declared, that takes precedence
                    # over anything else, use that and continue with the next attribute
                    dict_used[rel_name] = rel_info.sa_relationship
                    continue
                ann = cls.__annotations__[rel_name]
                temp_field = ModelField.infer(
                    name = rel_name,
                    value = rel_info,
                    annotation = ann,
                    class_validators = None,
                    config = BaseConfig,
                )
                relationship_to = temp_field.type_
                if isinstance(temp_field.type_, ForwardRef):
                    relationship_to = temp_field.type_.__forward_arg__
                rel_kwargs: Dict[str, Any] = {}
                if rel_info.back_populates:
                    rel_kwargs["back_populates"] = rel_info.back_populates
                if rel_info.link_model:
                    ins = inspect(rel_info.link_model)
                    local_table = getattr(ins, "local_table")
                    if local_table is None:
                        raise RuntimeError(
                            "Couldn't find the secondary table for "
                            f"model {rel_info.link_model}"
                        )
                    rel_kwargs["secondary"] = local_table
                rel_args: List[Any] = []
                if rel_info.sa_relationship_args:
                    rel_args.extend(rel_info.sa_relationship_args)
                if rel_info.sa_relationship_kwargs:
                    rel_kwargs.update(rel_info.sa_relationship_kwargs)
                rel_value: RelationshipProperty = relationship(
                    relationship_to, *rel_args, **rel_kwargs
                )
                dict_used[rel_name] = rel_value
                setattr(cls, rel_name, rel_value)  # Fix #315
            DeclarativeMeta.__init__(cls, classname, bases, dict_used, **kw)
            if cls._bases.is_table:
                cls.__sqlmodel_relationships__.update(cls._bases.sqlmodel_relationships)
                _remove_duplicate_index(cls.__table__)
        else:
            ModelMetaclass.__init__(cls, classname, bases, dict_)

class SQLModel(_SQLModel, metaclass = SQLModelMetaclass):
    __table_args__ = {'extend_existing': True}

    @declared_attr
    def __tablename__(cls) -> str:
        print(cls, cls._bases, cls._bases.tablename)
        return cls._bases.tablename or cls.__name__.lower()
