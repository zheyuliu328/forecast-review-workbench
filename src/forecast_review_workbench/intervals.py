"""Review supplied central prediction intervals on one explicitly accepted sample."""

import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal, localcontext

from .engine import _number, _reported, _text
from .probabilities import _day, _fields
from .tableio import read_table


def _contract(value, interval=True):
    names = ["target", "unit", "transformation"] + (["nominal_coverage"] if interval else [])
    _fields(value, names, names, "contract")
    out = {key: _text(value[key], key) for key in names if key != "nominal_coverage"}
    if interval:
        if not isinstance(value["nominal_coverage"], str):
            raise ValueError('nominal_coverage must be an explicit decimal string, such as "0.8".')
        level = _number(value["nominal_coverage"])
        if not 0 < level < 1:
            raise ValueError("nominal_coverage must be strictly between 0 and 1.")
        # Preserve all accepted input digits; no rounding before comparisons/scoring.
        out["nominal_coverage"] = str(level)
    return out


def _entity(value):
    if not isinstance(value, str) or len(value) > 200:
        raise ValueError("Entity must be exact text of at most 200 characters.")
    return value


def _key(origin, target, entity):
    origin, target = _day(origin), _day(target)
    if target <= origin:
        raise ValueError("Target must be after origin; only calendar-day dates are supported.")
    return origin, target, _entity(entity)


def _row_score(y, lower, upper, level):
    with localcontext() as context:
        context.prec = 600
        width = upper - lower
        below, above = y < lower, y > upper
        score = width + 2 / (1 - level) * (max(lower - y, Decimal(0)) + max(y - upper, Decimal(0)))
        return width, score, below, above


def _metrics(rows, sid, level):
    if not rows:
        return None
    with localcontext() as context:
        context.prec = 600
        values = [_row_score(Decimal(r["actual"]), *map(Decimal, r["intervals"][sid]), level) for r in rows]
        n = len(rows)
        return {
            "n": n,
            "empirical_interval_coverage": _reported(
                Decimal(sum(not lo and not hi for _, _, lo, hi in values)) / n
            ),
            "mean_width": _reported(sum((v[0] for v in values), Decimal(0)) / n),
            "mean_interval_score": _reported(sum((v[1] for v in values), Decimal(0)) / n),
            "lower_misses": sum(v[2] for v in values),
            "upper_misses": sum(v[3] for v in values),
        }


def review_intervals(request):
    _fields(
        request,
        [
            "task",
            "schema_version",
            "title",
            "contract",
            "expected_keys",
            "actual",
            "candidates",
            "accept_common_sample",
        ],
        [
            "task",
            "schema_version",
            "contract",
            "expected_keys",
            "actual",
            "candidates",
            "accept_common_sample",
        ],
        "request",
    )
    if (
        request["task"] != "interval_review"
        or type(request["schema_version"]) is not int
        or request["schema_version"] != 1
    ):
        raise ValueError("Use interval_review schema_version 1.")
    json.dumps(request, allow_nan=False)
    if type(request["accept_common_sample"]) is not bool:
        raise ValueError("Common-sample acceptance must be an explicit boolean.")
    contract = _contract(request["contract"])
    level = Decimal(contract["nominal_coverage"])
    expected = request["expected_keys"]
    if not isinstance(expected, list) or not 1 <= len(expected) <= 5000:
        raise ValueError("Declare 1–5000 expected origin/target/entity keys.")
    keys = []
    for entry in expected:
        _fields(entry, ["origin", "target", "entity"], ["origin", "target", "entity"], "expected key")
        keys.append(_key(entry["origin"], entry["target"], entry["entity"]))
    if len(set(keys)) != len(keys):
        raise ValueError("Expected keys must be unique.")
    candidates = request["candidates"]
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 5:
        raise ValueError("Provide 1–5 interval candidates.")
    declared_entities = {key[2] for key in keys}
    if "" in declared_entities and len(declared_entities) > 1:
        raise ValueError("Do not mix the unnamed single series with named entities.")
    sources = [("actual", request["actual"])] + [("candidate", s) for s in candidates]
    seen, parsed, metadata, records, conflicts = set(), {}, [], [], []
    for role, source in sources:
        _fields(
            source,
            ["id", "file", "mapping", "contract", "source_note", "sheet", "header_row"],
            ["id", "file", "mapping", "contract", "source_note"],
            "source",
        )
        sid = source["id"]
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", sid) or sid in seen:
            raise ValueError("Use unique source IDs beginning with a letter, then letters/digits/_/-.")
        seen.add(sid)
        source_contract = _contract(source["contract"], role != "actual")
        common_contract = (
            contract if role != "actual" else {k: v for k, v in contract.items() if k != "nominal_coverage"}
        )
        same = all(
            Decimal(value) == Decimal(common_contract[k])
            if k == "nominal_coverage"
            else value == common_contract[k]
            for k, value in source_contract.items()
        )
        if not same:
            conflicts.append(
                f"{sid}: contract differs from the common target, unit, transformation or nominal coverage."
            )
        _text(source["source_note"], f"{sid}: source_note", 2000)
        fields = (
            ["target", "entity", "actual"]
            if role == "actual"
            else ["origin", "target", "entity", "lower", "upper"]
        )
        mapping = source["mapping"]
        _fields(mapping, fields, fields, f"{sid}: mapping")
        columns = [v for v in mapping.values() if v is not None]
        if any(not isinstance(v, str) or not v for v in columns) or len(set(columns)) != len(columns):
            raise ValueError(f"{sid}: mapped columns must be distinct nonempty text.")
        if any(mapping[k] is None for k in fields if k != "entity"):
            raise ValueError(f"{sid}: only entity mapping may be null.")
        if (mapping["entity"] is None) != (declared_entities == {""}):
            raise ValueError(f"{sid}: entity mapping must match the declared named/unnamed universe.")
        table = read_table(source["file"], source.get("sheet"), source.get("header_row", 1))
        if set(columns) - set(table["headers"]):
            raise ValueError(f"{sid}: mapped column missing from {table['file_name']}.")
        metadata.append(
            {k: v for k, v in table.items() if k != "rows"}
            | {
                "id": sid,
                "role": role,
                "mapping": mapping,
                "contract": source_contract,
                "source_note": source["source_note"],
            }
        )
        valid_universe = {(k[1], k[2]) for k in keys} if role == "actual" else set(keys)
        grouped = defaultdict(list)
        for row in table["rows"]:
            record = {"source": sid, "row": row["row"], "raw": row["cells"], "status": "invalid", "key": None}
            records.append(record)
            try:

                def cell(field):
                    column = mapping[field]
                    if column is None:
                        return ""
                    item = row["cells"][column]
                    if item["kind"] in ("formula", "error", "boolean"):
                        raise ValueError(f"{field}: formulas/errors/booleans are not accepted.")
                    if field == "entity" and (item["kind"] != "text" or not item["text"]):
                        raise ValueError("Mapped entity IDs must be nonempty exact text.")
                    return (
                        item["text"][:10]
                        if item["kind"] == "date" and field in ("origin", "target")
                        else item["text"]
                    )

                key = (
                    (_day(cell("target")), _entity(cell("entity")))
                    if role == "actual"
                    else _key(cell("origin"), cell("target"), cell("entity"))
                )
                record["key"] = list(key)
                grouped[key].append(record)
                if role == "actual":
                    record["actual"] = str(_number(cell("actual")))
                else:
                    lower, upper = _number(cell("lower")), _number(cell("upper"))
                    if lower > upper:
                        raise ValueError("Lower bound exceeds upper bound; bounds are never swapped.")
                    record["interval"] = [str(lower), str(upper)]
                record["status"] = "valid" if key in valid_universe else "outside_scope"
            except (ValueError, TypeError) as exc:
                record["reason"] = str(exc)
        for members in grouped.values():
            if len(members) > 1:
                for record in members:
                    record.update(status="duplicate", reason="All occurrences of this key are excluded.")
        parsed[sid] = grouped
    actual_id, candidate_ids = metadata[0]["id"], [s["id"] for s in metadata[1:]]
    evaluation = []
    for origin, target, entity in keys:
        states, selected = {}, {}
        for source in metadata:
            sid = source["id"]
            key = (target, entity) if sid == actual_id else (origin, target, entity)
            members = parsed[sid].get(key, [])
            states[sid] = members[0]["status"] if len(members) == 1 else "duplicate" if members else "missing"
            if states[sid] == "valid":
                selected[sid] = members[0]
        included = all(s == "valid" for s in states.values()) and not conflicts
        evaluation.append(
            {
                "origin": origin,
                "target": target,
                "entity": entity,
                "horizon_days": (date.fromisoformat(target) - date.fromisoformat(origin)).days,
                "included": included,
                "states": states,
                "actual": selected.get(actual_id, {}).get("actual"),
                "intervals": {sid: selected[sid]["interval"] for sid in candidate_ids if sid in selected},
            }
        )
    common = [r for r in evaluation if r["included"]]
    ready = bool(request["accept_common_sample"] and common and not conflicts)
    metrics = {sid: _metrics(common, sid, level) if ready else None for sid in candidate_ids}
    groups = []
    for entity, horizon in sorted({(r["entity"], r["horizon_days"]) for r in evaluation}):
        rows = [r for r in evaluation if r["entity"] == entity and r["horizon_days"] == horizon]
        included = [r for r in rows if r["included"]]
        groups.append(
            {
                "entity": entity,
                "horizon_days": horizon,
                "expected": len(rows),
                "common": len(included),
                "metrics": {sid: _metrics(included, sid, level) if ready else None for sid in candidate_ids},
            }
        )
    return {
        "task": "interval_review",
        "schema_version": 1,
        "title": _text(request.get("title", "Prediction interval review"), "title", 300),
        "contract": contract,
        "accepted_common_sample": request["accept_common_sample"],
        "comparison_ready": ready,
        "expected": len(keys),
        "common": len(common),
        "excluded": len(keys) - len(common),
        "contract_errors": conflicts,
        "sources": metadata,
        "input_rows": records,
        "evaluation_rows": evaluation,
        "metrics": metrics,
        "group_results": groups,
        "fingerprint": hashlib.sha256(
            json.dumps(request, sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
        "limits": [
            "Supplied central intervals only; no fitting, calibration, construction or automatic winner.",
            "Empirical interval coverage measures containment, not input-row completeness.",
            "Equal weight per common forecast key; overlapping targets are not independent observations.",
            "Origin and expected universe are declarations, not proof of issuance or training independence.",
            "All candidates must declare the same nominal coverage, target, unit and transformation.",
            "A short sample with 100% containment does not establish calibration or future coverage.",
            "Calendar dates and day horizons only; no intraday ordering or significance tests.",
            "600-digit arithmetic; metrics reported to 40 digits. Width and score use target units.",
        ],
    }


def main(argv=None):
    import argparse
    from pathlib import Path

    from .exporter import write_bundle
    from .interval_exports import build_interval_bundle
    from .server import _resolve_files, load_json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Frozen interval request, or paths relative to this JSON")
    parser.add_argument("--output", type=Path, required=True, help="New directory; existing paths refused")
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("Choose a new output directory; existing paths are never replaced.")
        with args.input.open("rb") as stream:
            raw = stream.read(40 * 1024 * 1024 + 1)
        if len(raw) > 40 * 1024 * 1024:
            raise ValueError("Request exceeds 40 MiB.")
        request = _resolve_files(load_json(raw), args.input.absolute().parent)
        if len(json.dumps(request).encode()) > 40 * 1024 * 1024:
            raise ValueError("Combined encoded request exceeds 40 MiB.")
        files, result = build_interval_bundle(request)
        write_bundle(files, args.output)
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "comparison_ready": result["comparison_ready"],
                    "common": result["common"],
                    "fingerprint": result["fingerprint"],
                }
            )
        )
        return 0 if result["comparison_ready"] else 1
    except (ValueError, TypeError, KeyError, OSError) as exc:
        parser.exit(2, f"Interval review failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
