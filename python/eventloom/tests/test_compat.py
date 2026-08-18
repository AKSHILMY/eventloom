"""Tests for `eventloom.core._compat` — the version-neutral helpers that let
`StreamEnvelope`/`EventEmitter` accept a Pydantic-v1-style payload
(`eventloom.contrib.pydantic_v1`) alongside the usual Pydantic v2 one."""

from pydantic import BaseModel as V2BaseModel
from pydantic.v1 import BaseModel as V1BaseModel

from eventloom.core import _compat


class V2Model(V2BaseModel):
    name: str | None = None
    bio: str | None = None


class V1Model(V1BaseModel):
    name: str | None = None
    bio: str | None = None


def test_is_v1_style_distinguishes_v1_from_v2_instances_and_classes():
    assert _compat.is_v1_style(V1Model(name="Ada")) is True
    assert _compat.is_v1_style(V1Model) is True
    assert _compat.is_v1_style(V2Model(name="Ada")) is False
    assert _compat.is_v1_style(V2Model) is False


def test_is_v1_style_false_for_plain_dict():
    assert _compat.is_v1_style({"name": "Ada"}) is False


def test_dump_json_safe_v2_matches_model_dump():
    instance = V2Model(name="Ada")
    assert _compat.dump_json_safe(instance) == instance.model_dump(mode="json")


def test_dump_json_safe_v1_returns_plain_dict():
    instance = V1Model(name="Ada")
    assert _compat.dump_json_safe(instance) == {"name": "Ada", "bio": None}


def test_dump_json_safe_exclude_unset_v1_only_includes_set_fields():
    instance = V1Model(name="Ada")
    assert _compat.dump_json_safe(instance, exclude_unset=True) == {"name": "Ada"}


def test_dump_json_safe_exclude_unset_v2_only_includes_set_fields():
    instance = V2Model(name="Ada")
    assert _compat.dump_json_safe(instance, exclude_unset=True) == {"name": "Ada"}


def test_validate_v2_schema_returns_v2_instance():
    result = _compat.validate(V2Model, {"name": "Ada"})
    assert isinstance(result, V2Model)
    assert result.name == "Ada"


def test_validate_v1_schema_returns_v1_instance():
    result = _compat.validate(V1Model, {"name": "Ada"})
    assert isinstance(result, V1Model)
    assert result.name == "Ada"
