from copy import copy
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple, Type, cast

from sqlalchemy import Column, Table, inspect
from sqlalchemy.ext.hybrid import hybrid_method, hybrid_property
from sqlalchemy.orm import (
    ColumnProperty,
    DeclarativeMeta,
    InstrumentedAttribute,
    RelationshipProperty,
    declared_attr,
    relationship,
)
from sqlalchemy.util import classproperty, memoized_property
from sqlmodel._compat import (
    IS_PYDANTIC_V2,
    SQLModelConfig,
    Undefined,
    get_annotations,
    get_config_value,
    get_model_fields,
    get_relationship_to,
    get_type_from_field,
    is_table_model_class,
    set_config_value,
)
from sqlmodel.main import (
    BaseConfig,
    FieldInfo,
    Mapped,
    ModelMetaclass,
    RelationshipInfo,
)
from sqlmodel.main import SQLModel as _SQLModel
from sqlmodel.main import SQLModelMetaclass as _SQLModelMetaclass
from sqlmodel.main import get_column_from_field, get_origin, registry

from .enums import Choices
from .sqltypes import ChoiceType

try:
    from functools import cached_property
except ImportError:
    cached_property = memoized_property

SaColumnTypes = (
    Column,
    ColumnProperty,
    hybrid_property,
    declared_attr,
)
__sqlmodel_ignored_types__ = (classproperty, cached_property, memoized_property, hybrid_method, *SaColumnTypes)


class _SQLModelBasesInfo:
    def __init__(self, bases):
        self.is_table = False
        self.tablename = None
        self.columns = {}
        self.sqlmodel_relationships = {}
        self.bases = bases
        for base in bases:
            if not is_table_model_class(base):
                continue
            self.is_table = True
            self.tablename = base.__tablename__
            # noinspection PyProtectedMember
            self.columns.update(base.__table__.columns._index)
            self.sqlmodel_relationships.update(base.__sqlmodel_relationships__)


if IS_PYDANTIC_V2:
    from pydantic._internal._typing_extra import get_cls_type_hints_lenient

    def get_bases_instrumented_attribute_fields(bases):
        """Get the pydantic fields corresponding to the sqlalchemy fields in the bases base class"""
        dict_for_pydantic = {}
        pydantic_annotations = {}
        for base in bases:
            if not isinstance(base, SQLModelMetaclass):
                continue
            if not get_config_value(model=base, parameter="table", default=False):
                continue
            sub = get_cls_type_hints_lenient(base)
            for ann_name, ann_type in sub.items():
                if not hasattr(base, ann_name) or ann_name in dict_for_pydantic:
                    continue
                attr = getattr(base, ann_name)
                if not isinstance(attr, InstrumentedAttribute):
                    continue
                # If the field is a relationship, skip it.
                if isinstance(attr.property, RelationshipProperty):
                    base.__annotations__.pop(ann_name, None)  # 防止跑到pydantic
                    continue
                # If the field is a column, Get the field model_fields from the column.
                # From: pydantic._internal._fields.collect_model_fields
                # if field has no default value and is not in __annotations__ this means that it is
                # defined in a base class and we can take it from there
                model_fields_lookup: dict[str, FieldInfo] = {}
                for x in base.__bases__[::-1]:
                    model_fields_lookup.update(getattr(x, "model_fields", {}))
                model_fields_lookup.update(getattr(base, "model_fields", {}))
                if ann_name in model_fields_lookup:
                    # The field was present on one of the (possibly multiple) base classes
                    # copy the field to make sure typevar substitutions don't cause issues with the base classes
                    field_info = copy(model_fields_lookup[ann_name])
                else:
                    # The field was not found on any base classes; this seems to be caused by fields not getting
                    # generated thanks to models not being fully defined while initializing recursive models.
                    # Nothing stops us from just creating a new FieldInfo for this type hint, so we do this.
                    field_info = FieldInfo.from_annotation(ann_type)
                # End: pydantic._internal._fields.collect_model_fields
                dict_for_pydantic[ann_name] = field_info
                pydantic_annotations[ann_name] = ann_type
        return dict_for_pydantic, pydantic_annotations


def get_column_from_field2(field: Any) -> Column:  # type: ignore
    if IS_PYDANTIC_V2:
        field_info = field
    else:
        field_info = field.field_info
    sa_column = getattr(field_info, "sa_column", Undefined)
    if isinstance(sa_column, SaColumnTypes):
        return sa_column
    if isinstance(field_info.default, SaColumnTypes):
        return field_info.default
    type_ = get_type_from_field(field)
    # Support for choices enums
    if issubclass(type_, Choices):
        setattr(field_info, "sa_type", ChoiceType(type_))
    return get_column_from_field(field)


def _remove_duplicate_index(table: Table):
    if table.indexes:
        indexes = set()
        names = set()
        for index in table.indexes:
            if index.name not in names:
                names.add(index.name)
                indexes.add(index)
        table.indexes = indexes


def get_existed_instrumented_attribute(new_cls, name: str) -> Optional[InstrumentedAttribute]:
    for mapper in new_cls._sa_registry.mappers:
        class_ = mapper.class_
        if class_.__tablename__ != new_cls.__tablename__:
            continue
        col = getattr(class_, name, None)
        if col is not None:
            return col
    return None


def get_existed_table_column(tables: Mapping[str, Table], table_name: str, column_name: str) -> Optional[Column]:
    table = tables.get(table_name)
    if table is None:
        return None
    return table.columns.get(column_name)


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
        original_annotations = get_annotations(class_dict)
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
        # SQLModelx, If it is pydantic v2, you need to get the fields from the model_fields in bases
        if IS_PYDANTIC_V2:
            bases_fields, bases_ann = get_bases_instrumented_attribute_fields(bases)
            dict_for_pydantic = {**bases_fields, **dict_for_pydantic}
            pydantic_annotations = {**bases_ann, **pydantic_annotations}
        # End
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
            if not (key.startswith("__") and key.endswith("__"))  # skip dunder methods and attributes
        }
        config_kwargs = {key: kwargs[key] for key in kwargs.keys() & allowed_config_kwargs}
        new_cls = ModelMetaclass.__new__(cls, name, bases, dict_used, **config_kwargs)
        new_cls.__annotations__ = {
            **relationship_annotations,
            **pydantic_annotations,
            **new_cls.__annotations__,
        }

        def get_config(name: str) -> Any:
            config_class_value = get_config_value(model=new_cls, parameter=name, default=Undefined)
            if config_class_value is not Undefined:
                return config_class_value
            kwarg_value = kwargs.get(name, Undefined)
            if kwarg_value is not Undefined:
                return kwarg_value
            return Undefined

        # SQLModelx, First check the config attribute from the kwargs.
        set_config_value(model=new_cls, parameter="table", value=kwargs.get("table", False))
        # end
        config_table = get_config("table")
        if config_table is True:
            for k, v in get_model_fields(new_cls).items():
                # SQLModelx, Ensure that the column is unique
                if hasattr(new_cls, k):
                    continue
                # col = get_existed_instrumented_attribute(new_cls, k)
                col = get_existed_table_column(new_cls._sa_registry.metadata.tables, new_cls.__tablename__, k)
                if col is not None:
                    setattr(new_cls, k, col)
                    continue
                col = get_column_from_field2(v)
                # Set the column name to the field name if it's not set
                field_info = v if IS_PYDANTIC_V2 else v.field_info
                col.comment = getattr(col, "comment", None) or field_info.title or field_info.description
                # End
                setattr(new_cls, k, col)
            # Set a config flag to tell FastAPI that this should be read with a field
            # in orm_mode instead of preemptively converting it to a dict.
            # This could be done by reading new_cls.model_config['table'] in FastAPI, but
            # that's very specific about SQLModel, so let's have another config that
            # other future tools based on Pydantic can use.
            set_config_value(model=new_cls, parameter="read_from_attributes", value=True)
            # For compatibility with older versions
            # TODO: remove this in the future
            set_config_value(model=new_cls, parameter="read_with_orm_mode", value=True)

        config_registry = get_config("registry")
        if config_registry not in {Undefined, False, None}:
            config_registry = cast(registry, config_registry)
            # If it was passed by kwargs, ensure it's also set in config
            set_config_value(model=new_cls, parameter="registry", value=config_table)
            setattr(new_cls, "_sa_registry", config_registry)  # noqa: B010
            setattr(new_cls, "metadata", config_registry.metadata)  # noqa: B010
            setattr(new_cls, "__abstract__", True)  # noqa: B010
        return new_cls

    # Override SQLAlchemy, allow both SQLAlchemy and plain Pydantic models
    def __init__(cls, classname: str, bases: Tuple[type, ...], dict_: Dict[str, Any], **kw: Any) -> None:
        # Only one of the base classes (or the current one) should be a table model
        # this allows FastAPI cloning a SQLModel for the response_model without
        # trying to create a new SQLAlchemy, for a new table, with the same name, that
        # triggers an error
        # SQLModelx, support multiple inheritance
        # If the SQLModel model is a sqlalchemy model, then table=True must be passed when declaring.
        if kw.get("table", False):
            for rel_name, rel_info in cls.__sqlmodel_relationships__.items():
                if rel_info.sa_relationship:
                    # There's a SQLAlchemy relationship declared, that takes precedence
                    # over anything else, use that and continue with the next attribute
                    setattr(cls, rel_name, rel_info.sa_relationship)  # Fix #315
                    continue
                raw_ann = cls.__annotations__[rel_name]
                origin = get_origin(raw_ann)
                if origin is Mapped:
                    ann = raw_ann.__args__[0]
                else:
                    ann = raw_ann
                    # Plain forward references, for models not yet defined, are not
                    # handled well by SQLAlchemy without Mapped, so, wrap the
                    # annotations in Mapped here
                    cls.__annotations__[rel_name] = Mapped[ann]  # type: ignore[valid-type]
                relationship_to = get_relationship_to(name=rel_name, rel_info=rel_info, annotation=ann)
                rel_kwargs: Dict[str, Any] = {}
                if rel_info.back_populates:
                    rel_kwargs["back_populates"] = rel_info.back_populates
                if rel_info.link_model:
                    ins = inspect(rel_info.link_model)
                    local_table = getattr(ins, "local_table", None)  # noqa: B009
                    if local_table is None:
                        raise RuntimeError("Couldn't find the secondary table for " f"model {rel_info.link_model}")
                    rel_kwargs["secondary"] = local_table
                rel_args: List[Any] = []
                if rel_info.sa_relationship_args:
                    rel_args.extend(rel_info.sa_relationship_args)
                if rel_info.sa_relationship_kwargs:
                    rel_kwargs.update(rel_info.sa_relationship_kwargs)
                rel_value = relationship(relationship_to, *rel_args, **rel_kwargs)
                setattr(cls, rel_name, rel_value)  # Fix #315
            # SQLAlchemy no longer uses dict_
            # Ref: https://github.com/sqlalchemy/sqlalchemy/commit/428ea01f00a9cc7f85e435018565eb6da7af1b77
            # Tag: 1.4.36
            DeclarativeMeta.__init__(cls, classname, bases, dict_, **kw)

            cls._bases = _SQLModelBasesInfo(bases)
            if cls._bases.is_table:
                cls.__sqlmodel_relationships__.update(cls._bases.sqlmodel_relationships)
            _remove_duplicate_index(cls.__table__)
            # End
        else:
            ModelMetaclass.__init__(cls, classname, bases, dict_, **kw)


class SQLModel(_SQLModel, metaclass=SQLModelMetaclass):
    # SQLModelx, support cached_property,hybrid_method,hybrid_property
    __table_args__ = {"extend_existing": True}
    if IS_PYDANTIC_V2:
        model_config = SQLModelConfig(
            from_attributes=True,
            ignored_types=__sqlmodel_ignored_types__,
        )
    else:

        class Config:
            orm_mode = True
            keep_untouched = __sqlmodel_ignored_types__

    # End
