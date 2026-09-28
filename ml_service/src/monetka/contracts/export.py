"""Publish the event contracts as machine-readable schemas.

The Pydantic models in ``common/events.py`` are the source of truth, but they
are only readable by Python. Three other parties need the same contract:

* the **Android app**, which produces the events;
* the **schema registry**, which rejects an incompatible producer at publish
  time rather than at 3 a.m. in a DAG;
* **anyone reviewing the submission**, who should be able to read what the app
  sends without reading Python.

So the schemas are *generated*, never hand-written. A hand-written copy is a
second source of truth, and the two diverge the first week.

Two formats, for different jobs:

``jsonschema``  documentation and validation. Carries the field descriptions.
``avro``        the wire format for Kafka, and what the schema registry uses to
                decide whether a new producer is backwards compatible.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from monetka.common.config import REPO_ROOT
from monetka.common.events import (
    PAYLOAD_MODELS,
    SCHEMA_VERSION,
    EventEnvelope,
    EventName,
)
from monetka.common.logging import get_logger

log = get_logger("contracts.export")

CONTRACTS_DIR = REPO_ROOT / "contracts"
JSONSCHEMA_DIR = CONTRACTS_DIR / "jsonschema"
AVRO_DIR = CONTRACTS_DIR / "avro"

AVRO_NAMESPACE = "ru.mos.monetka.events.v1"

#: JSON Schema type -> Avro type. Anything not listed here is a modelling
#: mistake rather than a missing mapping: the contract deliberately uses a small
#: set of primitives so it survives the trip to Kotlin and back.
_AVRO_PRIMITIVES: dict[str, Any] = {
    "string": "string",
    "integer": "long",
    "number": "double",
    "boolean": "boolean",
}


def _avro_field_type(spec: dict[str, Any], required: bool) -> Any:
    """Translate one JSON Schema property into an Avro type."""
    # Enums become Avro strings rather than Avro enums on purpose: adding a value
    # to an Avro enum is a breaking change for old consumers, while the closed
    # vocabulary is already enforced by the Pydantic contract and by dbt's
    # accepted_values tests. Content should not need a schema migration.
    if "enum" in spec or spec.get("type") == "string":
        avro: Any = "string"
    elif "$ref" in spec or spec.get("type") == "object":
        avro = {"type": "map", "values": "string"}
    elif spec.get("type") == "array":
        avro = {"type": "array", "items": "string"}
    elif spec.get("type") in _AVRO_PRIMITIVES:
        avro = _AVRO_PRIMITIVES[spec["type"]]
    elif "anyOf" in spec:
        # Optional fields arrive as anyOf[T, null]; take the first concrete type.
        concrete = [s for s in spec["anyOf"] if s.get("type") != "null"]
        avro = _avro_field_type(concrete[0], required=True) if concrete else "string"
    else:
        avro = "string"

    return avro if required else ["null", avro]


def _payload_to_avro(event: EventName, schema: dict[str, Any]) -> dict[str, Any]:
    required = set(schema.get("required", []))
    fields = []
    for name, spec in schema.get("properties", {}).items():
        is_required = name in required
        field: dict[str, Any] = {
            "name": name,
            "type": _avro_field_type(spec, is_required),
        }
        if not is_required:
            field["default"] = None
        if spec.get("description"):
            field["doc"] = spec["description"]
        fields.append(field)

    return {
        "type": "record",
        "name": "".join(part.title() for part in event.value.split("_")) + "Payload",
        "namespace": AVRO_NAMESPACE,
        "doc": schema.get("description", f"Payload of {event.value}"),
        "fields": fields,
    }


def export_contracts(destination: Path | None = None) -> dict[str, int]:
    """Write JSON Schema and Avro for the envelope and every payload."""
    root = destination or CONTRACTS_DIR
    json_dir = root / "jsonschema"
    avro_dir = root / "avro"
    json_dir.mkdir(parents=True, exist_ok=True)
    avro_dir.mkdir(parents=True, exist_ok=True)

    written = {"jsonschema": 0, "avro": 0}

    envelope_schema = EventEnvelope.model_json_schema()
    envelope_schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    envelope_schema["$id"] = f"{AVRO_NAMESPACE}.EventEnvelope"
    envelope_schema["x-monetka-schema-version"] = SCHEMA_VERSION
    (json_dir / "event_envelope.schema.json").write_text(
        json.dumps(envelope_schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    written["jsonschema"] += 1

    for event, model in sorted(PAYLOAD_MODELS.items(), key=lambda kv: kv[0].value):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"{AVRO_NAMESPACE}.{event.value}"
        schema["x-monetka-event"] = event.value
        schema["x-monetka-schema-version"] = SCHEMA_VERSION
        (json_dir / f"{event.value}.schema.json").write_text(
            json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written["jsonschema"] += 1

        (avro_dir / f"{event.value}.avsc").write_text(
            json.dumps(_payload_to_avro(event, schema), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        written["avro"] += 1

    (root / "README.md").write_text(_index_markdown(), encoding="utf-8")
    log.info("contracts_exported", **written, destination=str(root))
    return written


def _index_markdown() -> str:
    lines = [
        "# Контракты событий",
        "",
        "**Сгенерировано.** Не редактировать вручную — правки исчезнут при",
        "следующем `monetka contracts`. Источник истины —",
        "[`src/monetka/common/events.py`](../src/monetka/common/events.py).",
        "",
        f"Версия схемы: **{SCHEMA_VERSION}**",
        "",
        "| Событие | JSON Schema | Avro |",
        "|:---|:---|:---|",
    ]
    for event in sorted(PAYLOAD_MODELS, key=lambda e: e.value):
        lines.append(
            f"| `{event.value}` "
            f"| [json](jsonschema/{event.value}.schema.json) "
            f"| [avsc](avro/{event.value}.avsc) |"
        )
    lines += [
        "",
        "Конверт события: [`event_envelope.schema.json`](jsonschema/event_envelope.schema.json).",
        "",
        "## Совместимость",
        "",
        "Тест `tests/unit/test_contracts.py::test_contracts_are_up_to_date` падает,",
        "если сгенерированные схемы разошлись с моделями. Тест",
        "`test_schema_change_is_backwards_compatible` падает, если из контракта",
        "пропало поле или обязательное поле добавлено без значения по умолчанию —",
        "то есть если новая версия приложения сломает уже собранные данные.",
        "",
        "## Почему перечисления выгружены строками",
        "",
        "Добавление значения в Avro enum ломает старых потребителей. Закрытость",
        "словаря уже обеспечена контрактом Pydantic и тестами dbt",
        "`accepted_values`, поэтому новое задание или новая позиция каталога не",
        "должны требовать миграции схемы.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Compatibility checking
# ---------------------------------------------------------------------------


def load_published(directory: Path | None = None) -> dict[str, dict[str, Any]]:
    """Read the schemas currently committed to the repository."""
    json_dir = (directory or CONTRACTS_DIR) / "jsonschema"
    if not json_dir.exists():
        return {}
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(json_dir.glob("*.schema.json"))
    }


def diff_against_published(directory: Path | None = None) -> list[str]:
    """Breaking changes between the committed schemas and the current models.

    «Breaking» means breaking for data that already exists:

    * a removed field — every historical row keeps it, and consumers read it;
    * a newly required field — old events do not carry it, so they stop
      validating retroactively.

    Adding an optional field is fine, and is how the contract is meant to grow.
    """
    import tempfile

    published = load_published(directory)
    if not published:
        return []

    with tempfile.TemporaryDirectory() as tmp:
        export_contracts(Path(tmp))
        current = load_published(Path(tmp))

    problems: list[str] = []
    for name, old in published.items():
        new = current.get(name)
        if new is None:
            problems.append(f"{name}: schema removed entirely")
            continue

        old_props = set(old.get("properties", {}))
        new_props = set(new.get("properties", {}))
        for missing in sorted(old_props - new_props):
            problems.append(f"{name}: field '{missing}' removed")

        old_required = set(old.get("required", []))
        new_required = set(new.get("required", []))
        for added in sorted(new_required - old_required):
            problems.append(f"{name}: field '{added}' became required — historical events lack it")

    return problems
