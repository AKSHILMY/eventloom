"""Tests for eventloom.contrib.pydantic_v1.partial.build_partial_model."""

from eventloom.contrib.pydantic_v1.partial import build_partial_model

from ._models import Address, Person, Section, Tag


def test_scalar_fields_pass_through():
    person = build_partial_model(Person, {"name": "Ada", "age": 36})
    assert person.name == "Ada"
    assert person.age == 36
    assert not hasattr(person, "address") or person.address is None
    assert "address" not in person.__fields_set__


def test_absent_fields_are_omitted_not_defaulted():
    person = build_partial_model(Person, {"name": "Ada"})
    assert "name" in person.__fields_set__
    assert "age" not in person.__fields_set__


def test_none_value_is_passed_through():
    person = build_partial_model(Person, {"name": None})
    assert person.name is None
    assert "name" in person.__fields_set__


def test_shape_singleton_nested_model_recurses():
    person = build_partial_model(Person, {"address": {"city": "London"}})
    assert isinstance(person.address, Address)
    assert person.address.city == "London"
    assert "country" not in person.address.__fields_set__


def test_shape_list_of_models_recurses_each_element():
    person = build_partial_model(Person, {"tags": [{"label": "a"}, {"label": "b"}]})
    assert [t.label for t in person.tags] == ["a", "b"]
    assert all(isinstance(t, Tag) for t in person.tags)


def test_list_of_scalars_passes_through():
    person = build_partial_model(Person, {"nicknames": ["Ada", "The Countess"]})
    assert person.nicknames == ["Ada", "The Countess"]


def test_shape_dict_of_models_recurses_each_value():
    person = build_partial_model(Person, {"offices": {"hq": {"city": "London"}}})
    assert isinstance(person.offices["hq"], Address)
    assert person.offices["hq"].city == "London"


def test_shape_set_of_models_falls_back_to_list_when_unhashable():
    # Tag instances built via construct() aren't guaranteed hashable —
    # the set-fallback-to-list defensive path should kick in.
    person = build_partial_model(Person, {"labels": [{"label": "a"}, {"label": "b"}]})
    assert isinstance(person.labels, list)
    assert [t.label for t in person.labels] == ["a", "b"]


def test_shape_tuple_ellipsis_of_models_recurses_and_returns_tuple():
    person = build_partial_model(Person, {"coordinates": [{"label": "a"}, {"label": "b"}]})
    assert isinstance(person.coordinates, tuple)
    assert [t.label for t in person.coordinates] == ["a", "b"]


def test_non_dict_data_returns_empty_construct():
    person = build_partial_model(Person, None)  # type: ignore[arg-type]
    assert person.__fields_set__ == set()


def test_deeply_nested_partial_growth_across_simulated_stream():
    # Simulates progressively-more-complete dicts from parse_partial_json.
    section = build_partial_model(Section, {"criterias": [{"title": "Clarity"}]})
    assert section.criterias[0].title == "Clarity"
    assert "applicable" not in section.criterias[0].__fields_set__

    section = build_partial_model(
        Section, {"criterias": [{"title": "Clarity", "applicable": True, "score": 4.5}]}
    )
    c = section.criterias[0]
    assert (c.title, c.applicable, c.score) == ("Clarity", True, 4.5)
