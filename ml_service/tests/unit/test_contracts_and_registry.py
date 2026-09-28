"""Tests for the published contracts and the feature registry.

Both exist to stop the same class of failure: two parts of the system quietly
disagreeing about what a field means. These tests are what make that
disagreement loud.
"""

from __future__ import annotations

import json

import pytest

from monetka.common.config import REPO_ROOT
from monetka.common.events import PAYLOAD_MODELS, EventName
from monetka.contracts.export import (
    diff_against_published,
    export_contracts,
    load_published,
)
from monetka.features import registry
from monetka.ml.features import BEHAVIOUR_FEATURES

CONTRACTS_DIR = REPO_ROOT / "contracts"


# --------------------------------------------------------------- contracts --


def test_every_event_has_a_published_schema() -> None:
    published = load_published()
    assert published, "no contracts published — run `monetka contracts`"
    for event in EventName:
        assert f"{event.value}.schema.json" in published, (
            f"{event.value} has no published JSON Schema"
        )


def test_envelope_schema_is_published() -> None:
    assert "event_envelope.schema.json" in load_published()


def test_contracts_are_up_to_date(tmp_path) -> None:
    """The committed schemas must match the current models.

    If this fails, someone changed an event and did not regenerate: the app team
    and the schema registry are now reading a contract the warehouse no longer
    enforces. Fix with `monetka contracts`.
    """
    export_contracts(tmp_path)
    regenerated = load_published(tmp_path)
    committed = load_published()

    assert set(regenerated) == set(committed), "schema files added or removed"
    stale = [name for name, schema in regenerated.items() if committed[name] != schema]
    assert not stale, f"stale contracts, run `monetka contracts`: {stale}"


def test_schema_change_is_backwards_compatible() -> None:
    """No field removed, no optional field made required.

    Both break data that already exists: historical events keep the old shape
    forever, and a consumer that assumes the new one will fail on them.
    """
    assert diff_against_published() == []


def test_avro_exists_for_every_payload() -> None:
    avro_dir = CONTRACTS_DIR / "avro"
    for event in PAYLOAD_MODELS:
        path = avro_dir / f"{event.value}.avsc"
        assert path.exists(), f"no Avro schema for {event.value}"
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["type"] == "record"
        assert schema["namespace"].startswith("ru.mos.monetka")


def test_avro_optional_fields_have_defaults() -> None:
    """An optional Avro field without a default is unreadable by old consumers."""
    for path in (CONTRACTS_DIR / "avro").glob("*.avsc"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        for field in schema["fields"]:
            if isinstance(field["type"], list) and "null" in field["type"]:
                assert "default" in field, (
                    f"{path.name}: nullable field {field['name']!r} has no default"
                )


def test_published_schemas_carry_no_personal_data() -> None:
    """The privacy guard applied to the contract as published, not just in code."""
    from monetka.common.events import personal_data_reason

    offenders = []
    for name, schema in load_published().items():
        for field in schema.get("properties", {}):
            reason = personal_data_reason(field)
            if reason is not None:
                offenders.append(f"{name}.{field} ({reason})")
    assert not offenders, f"personal-data-shaped fields in published contracts: {offenders}"


# ---------------------------------------------------------------- registry --


def test_every_model_feature_is_declared() -> None:
    """A model may not consume a feature nobody declared.

    An undeclared feature has no owner, no range and no point-in-time rule —
    which means nothing stops the next one from looking into the future.
    """
    undeclared = [name for name in BEHAVIOUR_FEATURES if name not in registry.FEATURES]
    assert not undeclared, f"features used by a model but not declared: {undeclared}"


def test_registry_has_no_unused_features() -> None:
    """A declared feature nobody uses is documentation rotting in place."""
    unused = sorted(set(registry.FEATURES) - set(BEHAVIOUR_FEATURES))
    assert not unused, f"declared but consumed by no model: {unused}"


def test_every_feature_has_a_point_in_time_rule() -> None:
    for feature in registry.FEATURES.values():
        assert feature.window in registry.Window
        assert feature.description.strip(), f"{feature.name} has no description"


def test_ranges_are_sane() -> None:
    for feature in registry.FEATURES.values():
        assert feature.minimum < feature.maximum, f"{feature.name} has an empty range"
        assert feature.minimum <= feature.null_default <= feature.maximum, (
            f"{feature.name}: null default {feature.null_default} is outside its own range"
        )


def test_out_of_range_value_is_rejected() -> None:
    problems = registry.validate_row({"essential_coverage": 1.7})
    assert problems and "outside its declared range" in problems[0]


def test_undeclared_feature_is_reported() -> None:
    problems = registry.validate_row({"made_up_feature": 1.0})
    assert problems and "not declared" in problems[0]


def test_valid_row_passes() -> None:
    row = dict.fromkeys(BEHAVIOUR_FEATURES, 0.5)
    assert registry.validate_row(row) == []


def test_lookup_of_unknown_feature_explains_itself() -> None:
    with pytest.raises(KeyError, match="not declared in the registry"):
        registry.get("nonexistent")


def test_describe_covers_every_feature() -> None:
    assert len(registry.describe()) == len(registry.FEATURES)
