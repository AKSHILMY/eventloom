import json

from eventloom import StreamEnvelope

from ._models import ChartData


def test_envelope_round_trips_to_json_with_wire_protocol_fields():
    envelope = StreamEnvelope[ChartData](
        type="chart.data",
        id="chart-1",
        seq=0,
        data=ChartData(labels=["Q1", "Q2"], values=[1.0, 2.0]),
        strategy="replace",
        done=True,
    )

    parsed = json.loads(envelope.to_json())

    # These are the exact field names the wire protocol (plan section 2) and
    # the TypeScript `StreamEnvelope` type must agree on.
    assert set(parsed.keys()) == {"type", "id", "seq", "data", "strategy", "done", "ts"}
    assert parsed["type"] == "chart.data"
    assert parsed["id"] == "chart-1"
    assert parsed["seq"] == 0
    assert parsed["strategy"] == "replace"
    assert parsed["done"] is True
    assert parsed["data"] == {"labels": ["Q1", "Q2"], "values": [1.0, 2.0]}
    assert isinstance(parsed["ts"], str) and parsed["ts"]  # ISO timestamp, non-empty


def test_envelope_defaults():
    envelope = StreamEnvelope[ChartData](
        type="chart.data",
        id="chart-1",
        seq=0,
        data=ChartData(labels=[], values=[]),
    )
    assert envelope.strategy == "replace"
    assert envelope.done is False


def test_to_sse_formats_as_data_line():
    envelope = StreamEnvelope[ChartData](
        type="chart.data", id="chart-1", seq=0, data=ChartData(labels=[], values=[])
    )
    sse = envelope.to_sse()
    assert sse.startswith("data: ")
    assert sse.endswith("\n\n")


def test_merge_strategy_excludes_unset_fields_so_partials_dont_clobber_each_other():
    from ._models import UserProfile

    # Regression test: a naive `.model_dump_json()` would serialize
    # `UserProfile(name="Ada")` as `{"name": "Ada", "bio": null}`, and a
    # frontend doing `{...existing, ...incoming}` on two such envelopes would
    # let the second event's `bio: null` overwrite the first event's `name`
    # when *its* unset `name` field got serialized as null. `to_json()` must
    # only include fields the caller actually set.
    first = StreamEnvelope[UserProfile](
        type="user.partial", id="profile-1", seq=0, data=UserProfile(name="Ada Lovelace"), strategy="merge"
    )
    second = StreamEnvelope[UserProfile](
        type="user.partial",
        id="profile-1",
        seq=1,
        data=UserProfile(bio="Mathematician"),
        strategy="merge",
        done=True,
    )

    first_data = json.loads(first.to_json())["data"]
    second_data = json.loads(second.to_json())["data"]

    assert first_data == {"name": "Ada Lovelace"}
    assert second_data == {"bio": "Mathematician"}

    # Simulate the frontend's shallow merge (EventStore.apply's "merge" branch).
    merged = {**first_data, **second_data}
    assert merged == {"name": "Ada Lovelace", "bio": "Mathematician"}


def test_replace_and_append_strategies_include_all_fields_even_if_unset():
    from ._models import UserProfile

    envelope = StreamEnvelope[UserProfile](
        type="user.partial", id="profile-1", seq=0, data=UserProfile(name="Ada"), strategy="replace"
    )
    data = json.loads(envelope.to_json())["data"]
    assert data == {"name": "Ada", "bio": None}
