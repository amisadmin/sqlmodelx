from typing import Any, Dict, List, Set, Tuple, Type

from pydantic import BaseConfig
from pydantic.fields import ModelField, Undefined
from pydantic.main import ModelMetaclass
from pydantic.typing import ForwardRef, resolve_annotations
from sqlalchemy import inspect
from sqlalchemy.orm import RelationshipProperty, relationship
from sqlalchemy.orm.decl_api import DeclarativeMeta
from sqlmodel import SQLModel as _SQLModel
from sqlmodel.main import SQLModelMetaclass as _SQLModelMetaclass, get_column_from_field, RelationshipInfo

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

    # From Pydantic
    def __new__(
        cls,
        name: str,
        bases: Tuple[Type[Any], ...],
        class_dict: Dict[str, Any],
        **kwargs: Any,
    ) -> Any:
        relationships: Dict[str, RelationshipInfo] = {}
        dict_for_pydantic = {}
        original_annotations = resolve_annotations(
            class_dict.get("__annotations__", {}), class_dict.get("__module__", None)
        )
        pydantic_annotations = {}
        relationship_annotations = {}
        for k, v in class_dict.items():
            if isinstance(v, RelationshipInfo):
                relationships[k] = v
            else:
                dict_for_pydantic[k] = v
        for k, v in original_annotations.items():
            if k in relationships:
                relationship_annotations[k] = v
            else:
                pydantic_annotations[k] = v
        dict_used = {
            **dict_for_pydantic,
            "__weakref__": None,
            "__sqlmodel_relationships__": relationships,
            "__annotations__": pydantic_annotations,
        }
        # Duplicate logic from Pydantic to filter config kwargs because if they are
        # passed directly including the registry Pydantic will pass them over to the
        # superclass causing an error
        allowed_config_kwargs: Set[str] = {
            key
            for key in dir(BaseConfig)
            if not (
                key.startswith("__") and key.endswith("__")
            )  # skip dunder methods and attributes
        }
        pydantic_kwargs = kwargs.copy()
        config_kwargs = {
            key: pydantic_kwargs.pop(key)
            for key in pydantic_kwargs.keys() & allowed_config_kwargs
        }
        new_cls = ModelMetaclass.__new__(cls, name, bases, dict_used, **config_kwargs)
        new_cls.__annotations__ = {
            **relationship_annotations,
            **pydantic_annotations,
            **new_cls.__annotations__,
        }

        def get_config(name: str, default: Any = Undefined) -> Any:
            kwarg_value = kwargs.get(name, default)
            if kwarg_value is not Undefined:
                # If it was passed by kwargs, ensure it's also set in config
                setattr(new_cls.__config__, name, kwarg_value)
                return kwarg_value
            return getattr(new_cls.__config__, name, default)

        config_table = get_config("table", False)
        if config_table is True:
            # # If it was passed by kwargs, ensure it's also set in config
            # new_cls.__config__.table = config_table
            for k, v in new_cls.__fields__.items():
                # Ensure that the column is unique
                if not hasattr(new_cls, k):
                    col = get_column_from_field(v)
                    setattr(new_cls, k, col)
            # Set a config flag to tell FastAPI that this should be read with a field
            # in orm_mode instead of preemptively converting it to a dict.
            # This could be done by reading new_cls.__config__.table in FastAPI, but
            # that's very specific about SQLModel, so let's have another config that
            # other future tools based on Pydantic can use.
            new_cls.__config__.read_with_orm_mode = True

        config_registry = get_config("registry")
        if config_registry is not Undefined:
            # config_registry = cast(registry, config_registry)
            # # If it was passed by kwargs, ensure it's also set in config
            # new_cls.__config__.registry = config_table
            setattr(new_cls, "_sa_registry", config_registry)
            setattr(new_cls, "metadata", config_registry.metadata)
            setattr(new_cls, "__abstract__", True)
        return new_cls

    # noinspection PyMissingConstructor
    def __init__(
        cls, classname: str, bases: Tuple[type, ...], dict_: Dict[str, Any], **kw: Any
    ) -> None:
        # Only one of the base classes (or the current one) should be a table model
        # this allows FastAPI cloning a SQLModel for the response_model without
        cls._bases = _SQLModelBasesInfo(bases)
        if kw.get('table', False):
            dict_used = dict_.copy()
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
        else:
            ModelMetaclass.__init__(cls, classname, bases, dict_)

class SQLModel(_SQLModel, metaclass = SQLModelMetaclass):
    __table_args__ = {'extend_existing': True}
