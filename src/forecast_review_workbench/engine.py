"""Review supplied forecasts against an explicit universe, without fitting a model."""

import hashlib
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, localcontext

from .tableio import read_table

NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
ISO_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
ISO_MONTH = re.compile(r"([0-9]{4})-([0-9]{2})\Z")
ISO_QUARTER = re.compile(r"([0-9]{4})-Q([1-4])\Z")
FIELDS = ("target", "unit", "horizon", "transformation", "frequency")


def _text(value, field, limit=500):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{field} must be nonempty text of at most {limit} characters.")
    return value.strip()


def _number(text):
    text = text.strip()
    if len(text) > 128 or not NUMBER.fullmatch(text):
        raise ValueError("Use a finite decimal number without commas, units or percent symbols.")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("The numeric exponent is invalid.") from exc
    if len(value.as_tuple().digits) > 50 or not -100 <= value.adjusted() <= 100:
        raise ValueError(
            "Numeric input is limited to 50 significant digits and adjusted exponents -100..100."
        )
    return value


def _exact(value):
    return "0" if value == 0 else format(value, "f")


def _reported(value):
    with localcontext() as context:
        context.prec = 40
        rounded = +value
        return "0" if rounded == 0 else format(rounded.normalize(), "f")


def _period(text, frequency, excel_date=False):
    if not isinstance(text, str):
        raise ValueError("Dates must use the declared ISO date/period notation.")
    if excel_date:
        text = text[:10]
    match = ISO_QUARTER.fullmatch(text)
    if match and frequency == "quarterly":
        year, quarter = int(match[1]), int(match[2])
        date(year, quarter * 3 - 2, 1)
        return f"{year:04d}-Q{quarter}"
    match = ISO_MONTH.fullmatch(text)
    if match and frequency in {"monthly", "quarterly"}:
        observed = date(int(match[1]), int(match[2]), 1)
    elif ISO_DAY.fullmatch(text):
        observed = date.fromisoformat(text)
    else:
        raise ValueError(
            f"Use strict ISO dates/periods for {frequency} frequency; "
            "week dates and numeric serials are not inferred."
        )
    if frequency == "daily":
        return observed.isoformat()
    if frequency == "monthly":
        return f"{observed.year:04d}-{observed.month:02d}"
    return f"{observed.year:04d}-Q{(observed.month - 1) // 3 + 1}"


def _period_range(start, end, frequency, maximum=5000):
    start, end = _period(start, frequency), _period(end, frequency)
    if start > end:
        raise ValueError("Scope/segment start must not be after its end.")
    if frequency == "daily":
        first = date.fromisoformat(start)
        count = (date.fromisoformat(end) - first).days + 1
        if count > maximum:
            raise ValueError("The expected universe exceeds 5,000 period/entity keys.")
        periods = [(first + timedelta(days=index)).isoformat() for index in range(count)]
    else:
        scale = 12 if frequency == "monthly" else 4
        first = int(start[:4]) * scale + int(start[5:] if frequency == "monthly" else start[-1]) - 1
        last = int(end[:4]) * scale + int(end[5:] if frequency == "monthly" else end[-1]) - 1
        if last - first + 1 > maximum:
            raise ValueError("The expected universe exceeds 5,000 period/entity keys.")
        periods = [
            f"{value // scale:04d}-{value % scale + 1:02d}"
            if frequency == "monthly"
            else f"{value // scale:04d}-Q{value % scale + 1}"
            for value in range(first, last + 1)
        ]
    return periods


def _period_index(period, frequency):
    if frequency == "daily":
        return date.fromisoformat(period).toordinal()
    scale = 12 if frequency == "monthly" else 4
    return int(period[:4]) * scale + int(period[5:] if frequency == "monthly" else period[-1]) - 1


def _shift_period(period, horizon, frequency):
    index = _period_index(period, frequency) + horizon
    try:
        if frequency == "daily":
            return date.fromordinal(index).isoformat()
        scale = 12 if frequency == "monthly" else 4
        year, offset = divmod(index, scale)
        date(year, 1, 1)
        return f"{year:04d}-{offset + 1:02d}" if scale == 12 else f"{year:04d}-Q{offset + 1}"
    except (ValueError, OverflowError) as exc:
        raise ValueError("Forecast target exceeds the supported calendar range.") from exc


def _metrics(pairs):
    if not pairs:
        return None
    with localcontext() as context:
        context.prec = 600
        errors = [prediction - actual for actual, prediction in pairs]
        n = Decimal(len(errors))
        mae = sum((error.copy_abs() for error in errors), Decimal(0)) / n
        rmse = (sum((error * error for error in errors), Decimal(0)) / n).sqrt()
        bias = sum(errors, Decimal(0)) / n
        return {"n": len(errors), "mae": _reported(mae), "rmse": _reported(rmse), "bias": _reported(bias)}


def _baseline_comparison(metrics, baseline, has_baseline):
    if not has_baseline:
        return None
    if metrics is None or baseline is None:
        return {"mae_pct": None, "rmse_pct": None, "reason": "Common-sample comparison is not ready."}
    output, reasons = {}, []
    with localcontext() as context:
        context.prec = 600
        for field in ("mae", "rmse"):
            denominator = Decimal(baseline[field])
            if denominator == 0:
                output[f"{field}_pct"] = None
                reasons.append(f"Baseline {field.upper()} is zero; percentage improvement is undefined.")
            else:
                output[f"{field}_pct"] = _reported(
                    (denominator - Decimal(metrics[field])) / denominator * 100
                )
    return {**output, "reason": " ".join(reasons) if reasons else None}


def _request(payload):
    if (
        not isinstance(payload, dict)
        or type(payload.get("schema_version")) is not int
        or payload["schema_version"] not in (1, 2)
    ):
        raise ValueError("Use review schema_version 1 or 2.")
    rolling = payload["schema_version"] == 2
    scope, contract = payload.get("scope"), payload.get("contract")
    if not isinstance(scope, dict) or not isinstance(contract, dict):
        raise ValueError(
            "Declare the expected scope and a common target/unit/horizon/transformation contract."
        )
    frequency = scope.get("frequency")
    if not isinstance(frequency, str) or frequency not in {"daily", "monthly", "quarterly"}:
        raise ValueError("Choose daily, monthly or quarterly frequency.")
    common_contract = {
        field: _text(contract.get(field), field) for field in ("target", "unit", "transformation")
    }
    if rolling:
        horizons = contract.get("horizons")
        if (
            not isinstance(horizons, list)
            or not horizons
            or len(horizons) > 5000
            or any(type(h) is not int or not 1 <= h <= 5000 for h in horizons)
            or len(set(horizons)) != len(horizons)
        ):
            raise ValueError("Horizons must be distinct positive integers from 1 to 5,000.")
        common_contract["horizons"] = sorted(horizons)
    else:
        if type(contract.get("horizon")) is not int or contract["horizon"] < 1:
            raise ValueError("Forecast horizon must be a positive integer in the declared frequency.")
        common_contract["horizon"] = contract["horizon"]
    common_contract["frequency"] = frequency
    actual, candidates, baseline = payload.get("actual"), payload.get("candidates"), payload.get("baseline")
    if not isinstance(actual, dict) or not isinstance(candidates, list) or not 1 <= len(candidates) <= 5:
        raise ValueError("Supply an actual table and between one and five candidate tables.")
    if baseline is not None and not isinstance(baseline, dict):
        raise ValueError("The optional baseline must be a source object.")
    definitions, seen = [("actual", "Actual", "actual", actual)], {"actual"}
    for role, sources in (
        ("candidate", candidates),
        ("baseline", [baseline] if baseline is not None else []),
    ):
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError("Every candidate/baseline must be a source object.")
            identifier = _text(source.get("id"), "Model ID", 100)
            if identifier in seen:
                raise ValueError("Candidate/baseline IDs must be distinct and cannot be 'actual'.")
            seen.add(identifier)
            definitions.append((identifier, _text(source.get("name"), "Model name", 200), role, source))
    mappings = []
    for identifier, _name, _role, source in definitions:
        mapping = source.get("mapping")
        if not isinstance(mapping, dict):
            raise ValueError(f"{identifier}: map the date and numeric value columns.")
        for field in ("date", "value"):
            if not isinstance(mapping.get(field), str) or not mapping[field].strip():
                raise ValueError(f"{identifier}: choose a {field} column.")
        entity = mapping.get("entity")
        if entity is not None and (not isinstance(entity, str) or not entity.strip()):
            raise ValueError(f"{identifier}: choose an entity column or null for one series.")
        columns = [mapping["date"], mapping["value"], entity]
        if rolling and _role != "actual":
            if not isinstance(mapping.get("origin"), str) or not mapping["origin"].strip():
                raise ValueError(f"{identifier}: choose an origin column.")
            horizon_column = mapping.get("horizon")
            if horizon_column is not None and (
                not isinstance(horizon_column, str) or not horizon_column.strip()
            ):
                raise ValueError(f"{identifier}: choose a horizon column or null to derive it.")
            columns.extend([mapping["origin"], horizon_column])
        elif mapping.get("origin") is not None or mapping.get("horizon") is not None:
            raise ValueError(f"{identifier}: origin/horizon mappings apply only to schema 2 predictions.")
        selected = [column for column in columns if column is not None]
        if len(set(selected)) != len(selected):
            raise ValueError(f"{identifier}: mapped columns must be distinct.")
        mappings.append(entity is not None)
    if any(mappings) and not all(mappings):
        raise ValueError("If any source maps entities, every source must map entities.")
    entities = scope.get("entities", [])
    if not isinstance(entities, list) or any(
        not isinstance(entity, str) or not entity.strip() for entity in entities
    ):
        raise ValueError("Expected entities must be an explicit list of nonempty exact text IDs.")
    if len(set(entities)) != len(entities):
        raise ValueError("Expected entity IDs must be unique exact text values.")
    if (all(mappings) and not entities) or (not any(mappings) and entities):
        raise ValueError(
            "Entity mappings require explicit expected entity IDs; "
            "a single series must use an empty entity list."
        )
    entity_keys = entities if entities else [""]
    start_field, end_field = ("origin_start", "origin_end") if rolling else ("start", "end")
    horizon_count = len(common_contract["horizons"]) if rolling else 1
    periods = _period_range(
        scope.get(start_field),
        scope.get(end_field),
        frequency,
        max(1, 5000 // (len(entity_keys) * horizon_count)),
    )
    if len(periods) * len(entity_keys) * horizon_count > 5000:
        raise ValueError("The expected universe exceeds 5,000 period/entity keys.")
    accepted = payload.get("accept_common_sample", False)
    if type(accepted) is not bool:
        raise ValueError("Common-sample acceptance must be an explicit true/false value.")
    segments = payload.get("segments", [])
    if not isinstance(segments, list) or len(segments) > 20:
        raise ValueError("Supply at most 20 period segments.")
    normalized_segments = []
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError("Each segment needs a name, start and end.")
        name = _text(segment.get("name"), "Segment name", 200)
        bounds = _period_range(segment.get("start"), segment.get("end"), frequency)
        normalized_segments.append({"name": name, "start": bounds[0], "end": bounds[-1]})
    if len({segment["name"] for segment in normalized_segments}) != len(normalized_segments):
        raise ValueError("Segment names must be distinct.")
    normalized_scope = {
        start_field: periods[0],
        end_field: periods[-1],
        "frequency": frequency,
        "entities": entities,
    }
    expected = (
        [
            (_shift_period(origin, horizon, frequency), entity, origin)
            for origin in periods
            for horizon in common_contract["horizons"]
            for entity in entity_keys
        ]
        if rolling
        else [(period, entity) for period in periods for entity in entity_keys]
    )
    return (
        definitions,
        common_contract,
        normalized_scope,
        expected,
        normalized_segments,
        accepted,
    )


def review(payload):
    """Return complete coverage first; aggregate comparable metrics only after acceptance."""
    definitions, contract, scope, expected, segments, accepted = _request(payload)
    rolling = payload["schema_version"] == 2
    universe = set(expected)
    actual_universe = {key[:2] for key in expected}

    def source_key(identifier, key):
        return key[:2] if identifier == "actual" else key

    def row_key(row):
        return (row["period"], row["entity"], row["origin"]) if rolling else (row["period"], row["entity"])

    def horizon_for(key):
        return _period_index(key[0], scope["frequency"]) - _period_index(key[2], scope["frequency"])

    sources, input_rows, issues, contract_errors, groups_by_source = [], [], [], [], {}
    public_fields = (
        "source_id",
        "row",
        "raw_date",
        "raw_value",
        "raw_entity",
        "period",
        "entity",
        "value",
        "status",
    )

    if rolling:
        public_fields += ("raw_origin", "raw_horizon", "origin", "horizon")

    def issue(identifier, row, period, entity, code, detail, origin=None, horizon=None):
        record = {
            "source_id": identifier,
            "row": row,
            "period": period,
            "entity": entity,
            "code": code,
            "detail": detail,
        }
        if rolling:
            record.update(origin=origin, horizon=horizon)
        issues.append(record)
        return record

    for identifier, name, role, source in definitions:
        declared = source.get("contract")
        if not isinstance(declared, dict):
            raise ValueError(f"{name}: supply the source's declared contract.")
        normalized_contract = {}
        fields = tuple(
            field for field in contract if not (rolling and role == "actual" and field == "horizons")
        )
        for field in fields:
            received = declared.get(field)
            if isinstance(received, str):
                received = received.strip()
            elif field == "horizons" and isinstance(received, list) and all(type(h) is int for h in received):
                received = sorted(received)
            elif received is not None and type(received) is not int:
                received = repr(received)
            normalized_contract[field] = received
            if type(received) is not type(contract[field]) or received != contract[field]:
                contract_errors.append(
                    {
                        "source_id": identifier,
                        "field": field,
                        "expected": contract[field],
                        "received": received,
                    }
                )
        source_note = source.get("source_note", "")
        if not isinstance(source_note, str) or len(source_note) > 4000:
            raise ValueError(f"{name}: source note must be text of at most 4,000 characters.")
        try:
            table = read_table(source.get("file"), source.get("sheet"), source.get("header_row", 1))
        except ValueError as exc:
            raise ValueError(f"{name}: {exc}") from exc
        mapping_fields = ("date", "value", "entity") + (
            ("origin", "horizon") if rolling and role != "actual" else ()
        )
        mapping = {key: source["mapping"].get(key) for key in mapping_fields}
        if any(column not in table["headers"] for column in mapping.values() if column is not None):
            raise ValueError(f"{name}: a mapped column is absent; inspect the selected sheet/header again.")
        sources.append(
            {
                "id": identifier,
                "name": name,
                "role": role,
                "file_name": table["file_name"],
                "sha256": table["sha256"],
                "mapping": mapping,
                "contract": normalized_contract,
                "source_note": source_note,
                "sheet": table["sheet"],
                "header_row": table["header_row"],
                "rows": len(table["rows"]),
                "blank_rows_ignored": table["blank_rows_ignored"],
            }
        )
        groups, entries = defaultdict(list), []
        for raw in table["rows"]:
            cells = raw["cells"]
            date_cell, value_cell = cells[mapping["date"]], cells[mapping["value"]]
            entity_cell = (
                cells[mapping["entity"]] if mapping["entity"] is not None else {"text": "", "kind": "text"}
            )
            entry = {
                "source_id": identifier,
                "row": raw["row"],
                "raw_date": date_cell["text"],
                "raw_value": value_cell["text"],
                "raw_entity": entity_cell["text"],
                "period": None,
                "entity": None,
                "value": None,
                "status": "valid",
                "errors": [],
            }
            if date_cell["kind"] == "formula":
                entry["errors"].append(
                    (
                        "formula_cell",
                        "Selected date is an Excel formula; provide independently checked frozen values.",
                    )
                )
            elif date_cell["kind"] not in {"text", "date"}:
                entry["errors"].append(
                    (
                        "invalid_date",
                        "Date is not ISO text or an Excel date cell; numeric serials are not inferred.",
                    )
                )
            else:
                try:
                    entry["period"] = _period(
                        date_cell["text"], scope["frequency"], date_cell["kind"] == "date"
                    )
                except ValueError as exc:
                    entry["errors"].append(("invalid_date", str(exc)))
            if mapping["entity"] is None:
                entry["entity"] = ""
            elif entity_cell["kind"] == "formula":
                entry["errors"].append(
                    ("formula_cell", "Selected entity is an Excel formula; provide a stable text identifier.")
                )
            elif not entity_cell["text"].strip():
                entry["errors"].append(
                    ("missing_entity", "Entity ID is missing; no expected entity is inferred.")
                )
            elif entity_cell["kind"] != "text":
                entry["errors"].append(
                    ("invalid_entity", "Entity IDs must be stored as text to preserve leading zeros.")
                )
            else:
                entry["entity"] = entity_cell["text"]
            if value_cell["kind"] == "formula":
                entry["errors"].append(
                    (
                        "formula_cell",
                        "Selected value is an Excel formula; cached results cannot establish freshness.",
                    )
                )
            elif value_cell["kind"] not in {"number", "text"}:
                entry["errors"].append(
                    (
                        "invalid_numeric",
                        "Value must be a finite decimal number, not a blank, boolean, date or error cell.",
                    )
                )
            else:
                try:
                    entry["value"] = _exact(_number(value_cell["text"]))
                except ValueError as exc:
                    entry["errors"].append(("invalid_numeric", str(exc)))
            if rolling:
                entry.update(raw_origin=None, raw_horizon=None, origin=None, horizon=None)
                if role != "actual":
                    origin_cell = cells[mapping["origin"]]
                    entry["raw_origin"] = origin_cell["text"]
                    try:
                        if origin_cell["kind"] not in {"text", "date"}:
                            raise ValueError(
                                "Origin must be ISO text or a frozen Excel date, "
                                "not a formula or numeric serial."
                            )
                        entry["origin"] = _period(
                            origin_cell["text"], scope["frequency"], origin_cell["kind"] == "date"
                        )
                        if entry["period"] is not None:
                            entry["horizon"] = _period_index(
                                entry["period"], scope["frequency"]
                            ) - _period_index(entry["origin"], scope["frequency"])
                            if entry["horizon"] <= 0:
                                entry["errors"].append(
                                    ("invalid_horizon", "Target must be strictly after the forecast origin.")
                                )
                            elif entry["horizon"] not in contract["horizons"]:
                                entry["errors"].append(
                                    (
                                        "unselected_horizon",
                                        "Derived horizon is outside the explicitly selected horizons.",
                                    )
                                )
                    except ValueError as exc:
                        entry["errors"].append(("invalid_origin", str(exc)))
                    if mapping.get("horizon") is not None:
                        horizon_cell = cells[mapping["horizon"]]
                        entry["raw_horizon"] = horizon_cell["text"]
                        try:
                            if horizon_cell["kind"] not in {"text", "number"}:
                                raise ValueError("Mapped horizon must be a frozen positive integer.")
                            declared_horizon = _number(horizon_cell["text"])
                            if (
                                declared_horizon <= 0
                                or declared_horizon != declared_horizon.to_integral_value()
                            ):
                                raise ValueError("Mapped horizon must be a positive integer.")
                            if entry["horizon"] is not None and declared_horizon != entry["horizon"]:
                                entry["errors"].append(
                                    ("horizon_mismatch", "Mapped horizon differs from target minus origin.")
                                )
                        except ValueError as exc:
                            entry["errors"].append(("invalid_horizon", str(exc)))
            key = (entry["period"], entry["entity"])
            if rolling and role != "actual":
                key += (entry["origin"],)
            if None not in key:
                groups[key].append(entry)
                if key not in (actual_universe if role == "actual" else universe):
                    entry["errors"].append(
                        (
                            "outside_scope",
                            "Key is outside the explicit expected period/entity universe; "
                            "retained but excluded.",
                        )
                    )
            if entry["errors"]:
                entry["status"] = entry["errors"][0][0]
            entries.append(entry)
        for key, members in groups.items():
            if len(members) > 1:
                for entry in members:
                    entry["status"] = "duplicate"
                    entry["errors"].append(
                        (
                            "duplicate",
                            "Multiple source rows normalize to this key; "
                            "none is paired, averaged or selected.",
                        )
                    )
        for entry in entries:
            for code, detail in entry["errors"]:
                issue(
                    identifier,
                    entry["row"],
                    entry["period"],
                    entry["entity"],
                    code,
                    detail,
                    entry.get("origin"),
                    entry.get("horizon"),
                )
            input_rows.append({field: entry[field] for field in public_fields})
        groups_by_source[identifier] = groups

    states, values = {}, {}
    for identifier, _name, _role, _source in definitions:
        state, parsed = {}, {}
        for key in expected:
            members = groups_by_source[identifier].get(source_key(identifier, key), [])
            if not members:
                state[key] = "missing"
                issue(
                    identifier,
                    None,
                    key[0],
                    key[1],
                    "missing",
                    "No source row matches this expected key; check extraction coverage and mapping.",
                    key[2] if rolling else None,
                    horizon_for(key) if rolling else None,
                )
            elif len(members) > 1:
                state[key] = "duplicate"
            elif members[0]["errors"]:
                state[key] = "invalid"
            else:
                state[key] = "valid"
                parsed[key] = Decimal(members[0]["value"])
        states[identifier], values[identifier] = state, parsed
    common = [
        key
        for key in expected
        if all(states[identifier][key] == "valid" for identifier, *_rest in definitions)
    ]
    common_set = set(common)
    ready = accepted and bool(common) and not contract_errors
    issues_by_key = defaultdict(list)
    for item in issues:
        issues_by_key[
            (item["period"], item["entity"], item.get("origin"))
            if rolling
            else (item["period"], item["entity"])
        ].append(item)
    rows = []
    for key in expected:
        actual_value = values["actual"].get(key)
        residuals = {}
        for identifier, _name, _role, _source in definitions[1:]:
            predicted = values[identifier].get(key)
            with localcontext() as context:
                context.prec = 600
                residuals[identifier] = (
                    _exact(predicted - actual_value)
                    if not contract_errors and actual_value is not None and predicted is not None
                    else None
                )
        rows.append(
            {
                **({"origin": key[2], "horizon": horizon_for(key)} if rolling else {}),
                "period": key[0],
                "entity": key[1],
                "actual": _exact(actual_value) if actual_value is not None else None,
                "predictions": {
                    identifier: _exact(values[identifier][key]) if key in values[identifier] else None
                    for identifier, *_rest in definitions[1:]
                },
                "residuals": residuals,
                "included": key in common_set,
                "reasons": [
                    {field: item[field] for field in ("source_id", "code", "detail")}
                    for item in (
                        issues_by_key[key]
                        + (
                            [
                                item
                                for item in issues_by_key[(key[0], key[1], None)]
                                if item["source_id"] == "actual"
                            ]
                            if rolling
                            else []
                        )
                    )
                ],
                "source_rows": {
                    identifier: [
                        row["row"]
                        for row in groups_by_source[identifier].get(source_key(identifier, key), [])
                    ]
                    for identifier, *_rest in definitions
                },
            }
        )
    baseline_id = next(
        (identifier for identifier, _name, role, _source in definitions if role == "baseline"), None
    )
    shared_metrics = {
        identifier: _metrics([(values["actual"][key], values[identifier][key]) for key in common])
        if ready
        else None
        for identifier, *_rest in definitions[1:]
    }
    models = []
    for identifier, name, role, _source in definitions[1:]:
        own_keys = [key for key in expected if key in values["actual"] and key in values[identifier]]
        coverage = {
            "expected": len(expected),
            **{
                state: sum(value == state for value in states[identifier].values())
                for state in ("valid", "missing", "duplicate", "invalid")
            },
            "outside_scope": sum(
                row["source_id"] == identifier
                and row["period"] is not None
                and row["entity"] is not None
                and (not rolling or row["origin"] is not None)
                and row_key(row) not in universe
                for row in input_rows
            ),
        }
        metrics = shared_metrics[identifier]
        models.append(
            {
                "id": identifier,
                "name": name,
                "role": role,
                "coverage": coverage,
                "available_metrics": _metrics(
                    [(values["actual"][key], values[identifier][key]) for key in own_keys]
                )
                if not contract_errors
                else None,
                "metrics": metrics,
                "vs_baseline": _baseline_comparison(
                    metrics, shared_metrics.get(baseline_id), baseline_id is not None
                ),
            }
        )
    segment_results = []
    for segment in segments:
        keys = [key for key in common if segment["start"] <= key[0] <= segment["end"]]
        segment_results.append(
            {
                **segment,
                "n": len(keys),
                "metrics": {
                    identifier: _metrics([(values["actual"][key], values[identifier][key]) for key in keys])
                    for identifier, *_rest in definitions[1:]
                }
                if ready
                else None,
            }
        )
    horizon_results = []
    if rolling:
        for horizon in contract["horizons"]:
            selected = [key for key in expected if horizon_for(key) == horizon]
            selected_common = [key for key in selected if key in common_set]
            horizon_results.append(
                {
                    "horizon": horizon,
                    "expected": len(selected),
                    "common": len(selected_common),
                    "excluded": len(selected) - len(selected_common),
                    "metrics": {
                        identifier: _metrics(
                            [(values["actual"][key], values[identifier][key]) for key in selected_common]
                        )
                        for identifier, *_rest in definitions[1:]
                    }
                    if ready
                    else None,
                }
            )
    # Partition the already-fixed global sample, never reselect it per model/group.
    grouped_keys = {}
    for key in expected:
        identity = (key[1], horizon_for(key) if rolling else contract["horizon"])
        grouped_keys.setdefault(identity, []).append(key)
    group_results = []
    for (entity, horizon), keys in sorted(grouped_keys.items()):
        selected = [key for key in keys if key in common_set]
        metrics = (
            {
                identifier: _metrics([(values["actual"][key], values[identifier][key]) for key in selected])
                for identifier, *_rest in definitions[1:]
            }
            if ready
            else None
        )
        group_results.append(
            {
                "entity": entity,
                "horizon": horizon,
                "expected": len(keys),
                "common": len(selected),
                "excluded": len(keys) - len(selected),
                "metrics": metrics,
                "vs_baseline": {
                    identifier: _baseline_comparison(
                        metrics.get(identifier), metrics.get(baseline_id), baseline_id is not None
                    )
                    for identifier, *_rest in definitions[1:]
                }
                if metrics is not None
                else None,
            }
        )
    analytical = {
        "schema_version": payload["schema_version"],
        "sources": sources,
        "scope": scope,
        "contract": contract,
        "segments": segments,
        "accept_common_sample": accepted,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            analytical, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()
    return {
        "schema_version": payload["schema_version"],
        "fingerprint": fingerprint,
        "title": _text(payload.get("title", "Forecast review"), "Title", 300),
        "scope": scope,
        "contract": contract,
        "accepted_common_sample": accepted,
        "comparison_ready": ready,
        **(
            {
                "horizon_results": horizon_results,
                "weighting": (
                    "Each forecast key has equal weight; "
                    "overlapping targets are not independent observations."
                ),
            }
            if rolling
            else {}
        ),
        "summary": {
            **({"unique_actual_keys": len(actual_universe)} if rolling else {}),
            "expected": len(expected),
            "common": len(common),
            "excluded": len(expected) - len(common),
            "extra_rows": sum(item["code"] == "outside_scope" for item in issues),
            "blocking_issues": len(issues) + len(contract_errors),
        },
        "sources": sources,
        "models": models,
        "rows": rows,
        "input_rows": input_rows,
        "issues": issues,
        "contract_errors": contract_errors,
        "segments": segment_results,
        "group_results": group_results,
        "warnings": [
            "Entity/horizon groups partition the accepted global common sample; "
            "pooled errors can conceal group deterioration and differences in scale. "
            "No equal-entity average, automatic winner or significance claim is inferred.",
            "Supplied prediction files do not establish training independence, "
            "forecast-origin timing or model approval.",
            "Available-sample metrics use each source's own actual intersection "
            "and are not comparable across models.",
            "Common-sample metrics require explicit acceptance; "
            "missing or invalid values are never filled with zero.",
            "Bias is prediction minus actual. Baseline percentages are "
            "(baseline minus candidate) / baseline × 100; positive means improvement.",
            "Dates normalize only at the explicitly declared frequency; "
            "normalization can expose duplicate keys.",
            "Calculations use bounded Decimal inputs and 600-digit working precision; "
            "metrics are reported to 40 significant digits.",
            "Source notes and definitions are caller declarations, not independently verified provenance.",
        ],
    }
