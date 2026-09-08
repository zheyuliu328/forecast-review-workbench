"""Exact, source-accounted reconciliation of additive financial result files."""

import base64
import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, localcontext

from . import __version__
from .tableio import read_table

IDENTITY = ("record_id", "date", "measure", "risk_type", "tenor")
DIMENSIONS = ("date", "measure", "risk_type", "tenor", "currency", "unit")
FIELDS = ("record_id", "date", "measure", "risk_type", "tenor", "currency", "unit", "value")
ROW_STATUSES = (
    "pass",
    "breach",
    "missing_left",
    "missing_right",
    "duplicate",
    "invalid",
    "definition_conflict",
)
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def decimal_value(value):
    text = str(value).strip()
    if isinstance(value, bool) or len(text) > 256 or not NUMBER.fullmatch(text):
        raise ValueError("Expected a finite decimal number, without currency signs or thousands separators.")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("Expected a finite decimal number.") from exc
    if not number.is_finite() or len(number.as_tuple().digits) > 100 or abs(number.adjusted()) > 120:
        raise ValueError("Numbers must have at most 100 digits and a decimal magnitude from 1e-120 to 1e120.")
    return number


def _text(value, name, *, empty=False, limit=200):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError(
            f"{name} must be {'optional' if empty else 'nonempty'} text of at most {limit} characters."
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{name} contains a control character.")
    return value


def _date(cell):
    text = cell["text"]
    if cell["kind"] == "date" and "T" in text:
        timestamp = datetime.fromisoformat(text)
        if timestamp.time() != time(0) or timestamp.tzinfo is not None:
            raise ValueError(
                "Use date-only values; intraday timestamps are outside this comparison contract."
            )
        text = timestamp.date().isoformat()
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
        raise ValueError("Date must use YYYY-MM-DD or a date-only Excel cell.")
    return date.fromisoformat(text).isoformat()


def _intake(source, source_id, *, totals=False):
    if not isinstance(source, dict) or not isinstance(source.get("mapping"), dict):
        raise ValueError(f"Choose a file and field mappings for {source_id}.")
    file = source.get("file")
    if not isinstance(file, dict) or "path" in file:
        raise ValueError("Browser sources must contain selected file bytes, not server paths.")
    table = read_table(file, source.get("sheet"), source.get("header_row", 1))
    if not table["rows"]:
        raise ValueError(f"{source_id} has no nonempty data rows.")
    mapping, defaults = source["mapping"], source.get("defaults", {})
    if not isinstance(defaults, dict) or set(mapping) - set(FIELDS) or set(defaults) - set(DIMENSIONS):
        raise ValueError("Use only the documented result fields and default declarations.")
    required = {"value"} if totals else {"record_id", "value"}
    for field in required:
        if not mapping.get(field):
            raise ValueError(f"Map {field} for {source_id}.")
    columns = [value for field, value in mapping.items() if value and (field != "record_id" or not totals)]
    if any(not isinstance(column, str) or column not in table["headers"] for column in columns):
        raise ValueError("A mapped column is absent from the selected header row.")
    if len(set(columns)) != len(columns):
        raise ValueError("Map each selected column to one result field only.")
    for field in ("date", "measure", "currency", "unit"):
        if not mapping.get(field):
            _text(defaults.get(field), f"Default {field} for {source_id}")
    selected_fields = FIELDS[1:] if totals else FIELDS
    rows = []
    for source_row in table["rows"]:
        raw, values, errors = {}, {}, []
        for field in selected_fields:
            column = mapping.get(field)
            cell = (
                source_row["cells"][column] if column else {"text": defaults.get(field, ""), "kind": "text"}
            )
            raw[field] = cell["text"]
            try:
                if cell["kind"] in {"formula", "boolean", "error"}:
                    raise ValueError("Selected formulas, booleans and Excel errors are not accepted.")
                if field == "value":
                    values[field] = str(decimal_value(cell["text"]))
                elif field == "date":
                    values[field] = _date(cell)
                else:
                    if cell["kind"] not in {"text", "blank"}:
                        raise ValueError("Identifiers and declarations must be stored as text.")
                    values[field] = _text(cell["text"], field, empty=field in {"risk_type", "tenor"})
            except (ValueError, TypeError) as exc:
                values[field] = None
                errors.append(f"{field}: {exc}")
        identity = tuple(values.get(field) for field in IDENTITY)
        group = tuple(values.get(field) for field in DIMENSIONS)
        group_key = digest(group) if all(value is not None for value in group) else None
        key = (
            digest(identity)
            if not totals and all(value is not None for value in identity)
            else group_key
            if totals
            else f"invalid:{source_id}:{source_row['row']}"
        )
        if key is None:
            key = f"invalid:{source_id}:{source_row['row']}"
        rows.append(
            {
                "source_id": source_id,
                "row": source_row["row"],
                "raw": raw,
                "values": values,
                "errors": errors,
                "record_key": key,
                "group_key": group_key,
            }
        )
    metadata = {
        key: table[key] for key in ("file_name", "sha256", "sheet", "header_row", "blank_rows_ignored")
    }
    metadata.update(
        {
            "id": source_id,
            "name": _text(source.get("name", source_id), "Source name"),
            "rows": len(rows),
            "mapping": mapping,
            "defaults": defaults,
        }
    )
    return rows, metadata


def _difference(reference, challenger, absolute, relative):
    difference = challenger - reference
    allowed = absolute + relative * abs(reference)
    return {
        "difference": str(difference),
        "absolute_difference": str(abs(difference)),
        "allowed_difference": str(allowed),
        "status": "pass" if abs(difference) <= allowed else "breach",
    }


def _empty_difference():
    return {"difference": None, "absolute_difference": None, "allowed_difference": None}


def _compare_row(key, left, right, absolute, relative):
    examples = left or right
    identity = {field: examples[0]["values"].get(field) for field in IDENTITY}
    a = left[0] if len(left) == 1 else None
    b = right[0] if len(right) == 1 else None
    result = {
        "record_key": key,
        "identity": identity,
        "reference": a["values"].get("value") if a else None,
        "challenger": b["values"].get("value") if b else None,
        "source_rows": {"left": [row["row"] for row in left], "right": [row["row"] for row in right]},
        "reasons": [],
        **_empty_difference(),
    }
    for field in ("currency", "unit"):
        result[f"reference_{field}"] = a["values"].get(field) if a else None
        result[f"challenger_{field}"] = b["values"].get(field) if b else None
    if len(left) > 1 or len(right) > 1:
        result["status"] = "duplicate"
        result["reasons"].append(
            "A source repeats this identity; duplicate rows are never paired or dropped."
        )
    elif any(row["errors"] for row in left + right):
        result["status"] = "invalid"
    elif not left or not right:
        result["status"] = "missing_left" if not left else "missing_right"
        result["reasons"].append(
            "The identity is absent from the reference."
            if not left
            else "The identity is absent from the challenger."
        )
    elif any(a["values"][field] != b["values"][field] for field in ("currency", "unit")):
        result["status"] = "definition_conflict"
        result["reasons"].append("Currency or unit declarations differ; numerical comparison is blocked.")
    else:
        result.update(
            _difference(Decimal(result["reference"]), Decimal(result["challenger"]), absolute, relative)
        )
        if result["status"] == "breach":
            result["reasons"].append("The row difference exceeds the declared tolerance.")
    result["reasons"].extend(
        f"{row['source_id']} row {row['row']}: {error}" for row in left + right for error in row["errors"]
    )
    return result


def _buckets(rows):
    groups = defaultdict(list)
    identities = Counter(row["record_key"] for row in rows)
    for row in rows:
        if row["group_key"] is not None:
            groups[row["group_key"]].append(row)
    result = {}
    for key, members in groups.items():
        reasons = []
        if any(member["errors"] for member in members):
            reasons.append("A raw member is invalid.")
        if any(identities[member["record_key"]] > 1 for member in members):
            reasons.append("A raw member identity is duplicated.")
        result[key] = {
            "dimensions": {field: members[0]["values"][field] for field in DIMENSIONS},
            "sum": None
            if reasons
            else sum((Decimal(member["values"]["value"]) for member in members), Decimal(0)),
            "rows": len(members),
            "reasons": reasons,
            "record_keys": sorted({member["record_key"] for member in members}),
        }
    return result


def _groups(left, right, comparisons, absolute, relative):
    output = []
    for key in sorted(set(left) | set(right)):
        a, b = left.get(key), right.get(key)
        reasons = []
        keys = sorted(set((a or {}).get("record_keys", []) + (b or {}).get("record_keys", [])))
        result = {
            "group_key": key,
            "dimensions": (a or b)["dimensions"],
            "reference": str(a["sum"]) if a and a["sum"] is not None else None,
            "challenger": str(b["sum"]) if b and b["sum"] is not None else None,
            "reference_rows": a["rows"] if a else 0,
            "challenger_rows": b["rows"] if b else 0,
            "record_keys": keys,
            "offsetting_breaches": False,
            **_empty_difference(),
        }
        if not a or not b:
            reasons.append("This group is absent from one source; net comparison is incomplete.")
        for bucket in (a, b):
            if bucket:
                reasons.extend(bucket["reasons"])
        bad_rows = [
            comparisons[record_key] for record_key in keys if comparisons[record_key]["status"] != "pass"
        ]
        if bad_rows:
            reasons.append(
                f"{len(bad_rows)} member identities require attention; a net match cannot clear them."
            )
        if a and b and a["sum"] is not None and b["sum"] is not None:
            result.update(_difference(a["sum"], b["sum"], absolute, relative))
            result["offsetting_breaches"] = result["status"] == "pass" and any(
                row["status"] == "breach" for row in bad_rows
            )
            if result["status"] == "breach":
                reasons.append("The group net difference also exceeds tolerance.")
        result["status"] = "attention" if reasons else "pass"
        result["reasons"] = reasons
        output.append(result)
    return output


def _reported(side, buckets, totals, absolute, relative):
    by_key = defaultdict(list)
    for row in totals:
        by_key[row["group_key"] or row["record_key"]].append(row)
    output = []
    for key in sorted(set(buckets) | set(by_key)):
        bucket, supplied = buckets.get(key), by_key.get(key, [])
        sample = supplied[0] if supplied else None
        dimensions = (
            bucket["dimensions"] if bucket else {field: sample["values"].get(field) for field in DIMENSIONS}
        )
        result = {
            "side": side,
            "group_key": key,
            "dimensions": dimensions,
            "calculated": str(bucket["sum"]) if bucket and bucket["sum"] is not None else None,
            "reported": sample["values"].get("value") if len(supplied) == 1 else None,
            "source_rows": [row["row"] for row in supplied],
            "reasons": [],
            **_empty_difference(),
        }
        if len(supplied) > 1:
            result["status"] = "duplicate"
            result["reasons"].append("The reported totals repeat this group.")
        elif any(row["errors"] for row in supplied):
            result["status"] = "invalid"
        elif not bucket or not supplied:
            result["status"] = "missing_raw" if not bucket else "missing_reported"
            result["reasons"].append(
                "A reported group has no raw members."
                if not bucket
                else "The raw group is absent from the supplied totals."
            )
        elif bucket["sum"] is None:
            result["status"] = "blocked"
            result["reasons"].extend(bucket["reasons"])
        else:
            result.update(_difference(bucket["sum"], Decimal(result["reported"]), absolute, relative))
            if result["status"] == "breach":
                result["reasons"].append("The supplied total does not tie to its own source rows.")
        result["reasons"].extend(error for row in supplied for error in row["errors"])
        output.append(result)
    return output


def reconcile(request):
    if (
        not isinstance(request, dict)
        or type(request.get("schema_version")) is not int
        or request["schema_version"] != 1
    ):
        raise ValueError("Use a schema_version 1 comparison request.")
    additive = request.get("additive", False)
    if type(additive) is not bool:
        raise ValueError("Additivity requires an explicit boolean declaration.")
    if not additive and any(request.get(side) is not None for side in ("left_totals", "right_totals")):
        raise ValueError("Confirm within-group additivity before comparing reported totals.")
    absolute = decimal_value(request.get("absolute_tolerance", "0.01"))
    relative = decimal_value(request.get("relative_tolerance", "0.0001"))
    if absolute < 0 or relative < 0:
        raise ValueError("Tolerances cannot be negative.")
    title = _text(request.get("title", "Financial result reconciliation"), "Title", limit=160)
    rows_by_source, sources = {}, []
    for source_id in ("left", "right", "left_totals", "right_totals"):
        if source_id.endswith("totals") and request.get(source_id) is None:
            continue
        rows, source = _intake(request.get(source_id), source_id, totals=source_id.endswith("totals"))
        rows_by_source[source_id] = rows
        sources.append(source)
    left, right = defaultdict(list), defaultdict(list)
    for side, index in (("left", left), ("right", right)):
        for row in rows_by_source[side]:
            index[row["record_key"]].append(row)
    with localcontext() as context:
        context.prec = 600
        compared = [
            _compare_row(key, left[key], right[key], absolute, relative)
            for key in sorted(set(left) | set(right))
        ]
        compared.sort(key=lambda row: tuple(str(row["identity"].get(field) or "") for field in IDENTITY))
        group_rows, reported = [], []
        if additive:
            buckets = {side: _buckets(rows_by_source[side]) for side in ("left", "right")}
            group_rows = _groups(
                buckets["left"],
                buckets["right"],
                {row["record_key"]: row for row in compared},
                absolute,
                relative,
            )
            for side in ("left", "right"):
                if f"{side}_totals" in rows_by_source:
                    reported.extend(
                        _reported(side, buckets[side], rows_by_source[f"{side}_totals"], absolute, relative)
                    )
    counts = Counter(row["status"] for row in compared)
    tolerances = {
        "absolute": str(absolute),
        "relative": str(relative),
        "formula": "abs(challenger-reference) <= absolute + relative*abs(reference)",
        "relative_input": "ratio, not percent",
    }
    fingerprint = digest(
        {
            "tool_version": __version__,
            "protocol": "additive-reconciliation-v1",
            "sources": sources,
            "additive": additive,
            "tolerances": tolerances,
        }
    )
    return {
        "schema_version": 1,
        "title": title,
        "fingerprint": fingerprint,
        "additive": additive,
        "tolerances": tolerances,
        "sources": sources,
        "summary": {
            "expected": len(compared),
            "left_rows": len(rows_by_source["left"]),
            "right_rows": len(rows_by_source["right"]),
            "comparable": counts["pass"] + counts["breach"],
            **{key: counts[key] for key in ROW_STATUSES},
            "groups": len(group_rows),
            "group_attention": sum(group["status"] != "pass" for group in group_rows),
            "reported_totals_attention": sum(row["status"] != "pass" for row in reported),
        },
        "rows": compared,
        "groups": group_rows,
        "reported_totals": reported,
        "input_rows": [row for rows in rows_by_source.values() for row in rows],
        "warnings": [
            "Coverage is the union of supplied identities; "
            "records missing from both files cannot be discovered here.",
            "Default units, dates and additivity are caller declarations, not verified source facts.",
            "A net match does not clear member breaches, duplicates, invalid values or missing identities.",
            "This tool supports explicitly additive groups; "
            "it does not implement nonlinear margin aggregation.",
            "Manual acceptance of a difference does not change its calculated status.",
        ],
    }


def reconciliation_example():
    headers = ["Position", "AsOf", "Metric", "Risk", "Tenor", "CCY", "Unit", "Amount"]
    mapping = dict(zip(FIELDS, headers))

    def source(name, rows, totals=False):
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(headers[1:] if totals else headers)
        writer.writerows(rows)
        return {
            "name": name,
            "file": {
                "name": name.lower().replace(" ", "-") + ".csv",
                "content_base64": base64.b64encode(stream.getvalue().encode()).decode(),
            },
            "sheet": None,
            "header_row": 1,
            "mapping": {key: value for key, value in mapping.items() if not totals or key != "record_id"},
            "defaults": {},
        }

    prefix = ["2025-06-30", "PV", "FX", "1Y", "USD", "USD"]
    left = [["001", *prefix, "100"], ["002", *prefix, "200"], ["003", *prefix, "50"]]
    right = [["001", *prefix, "110"], ["002", *prefix, "190"], ["003", *prefix, "50"]]
    return {
        "schema_version": 1,
        "title": "Equal totals can conceal two offsetting breaches",
        "left": source("Reference", left),
        "right": source("Challenger", right),
        "left_totals": source("Reference totals", [[*prefix, "350"]], True),
        "right_totals": source("Challenger totals", [[*prefix, "355"]], True),
        "absolute_tolerance": "0.01",
        "relative_tolerance": "0",
        "additive": True,
    }
