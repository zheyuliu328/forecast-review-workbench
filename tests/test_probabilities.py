import copy
import json
from decimal import Decimal, localcontext

import pytest

from forecast_review_workbench.example import _file
from forecast_review_workbench.probabilities import render, review_probabilities


def request():
    event = "Invented event: count exceeds a fixed threshold within two observation steps."
    origins = ["2025-01-01", "2025-01-02", "2025-01-03"]

    def source(sid, label=False):
        headers = ["Origin", "Label", "Available"] if label else ["Origin", "Probability"]
        rows = (
            [[o, y, a] for o, y, a in zip(origins, [0, 1, 1], ["2025-01-02", "2025-01-03", "2025-01-04"])]
            if label
            else [[o, p] for o, p in zip(origins, [0.25, 0.75, 0.9] if sid == "a" else [0.5, 0.5, 0.5])]
        )
        return {
            "id": sid,
            "event_definition": event,
            "source_note": "Original invented test; no model fit.",
            "file": _file(sid + ".csv", headers, rows),
            "mapping": {
                "origin": "Origin",
                "entity": None,
                **({"label": "Label", "available": "Available"} if label else {"probability": "Probability"}),
            },
        }

    return {
        "task": "binary_event_review",
        "schema_version": 1,
        "event_definition": event,
        "evaluation_as_of": "2025-01-03",
        "expected_keys": [{"origin": o, "entity": ""} for o in origins],
        "labels": source("labels", True),
        "candidates": [source("a")],
        "baseline": source("baseline"),
        "accept_common_sample": True,
    }


def test_availability_frozen_sample_and_acceptance():
    q = request()
    old = copy.deepcopy(q)
    r = review_probabilities(q)
    assert q == old
    assert (r["expected"], r["common"], r["excluded"]) == (3, 2, 1)
    assert r["evaluation_rows"][2]["states"]["labels"] == "pending"
    assert r["metrics"]["a"]["brier"] == "0.0625"
    with localcontext() as c:
        c.prec = 700
        assert abs(Decimal(r["metrics"]["a"]["log_loss"]) + (Decimal(3) / 4).ln()) < Decimal("1e-40")
    q["accept_common_sample"] = False
    assert all(x is None for x in review_probabilities(q)["metrics"].values())
    q["accept_common_sample"] = True
    q["evaluation_as_of"] = "2025-01-04"
    assert review_probabilities(q)["metrics"]["a"]["brier"] == "0.045"


def test_impossible_endpoints_preserve_brier_and_zero_loss_endpoints():
    q = request()
    q["evaluation_as_of"] = "2025-01-04"
    q["candidates"][0]["file"] = _file(
        "a.csv", ["Origin", "Probability"], [["2025-01-01", 0], ["2025-01-02", 1], ["2025-01-03", 0]]
    )
    r = review_probabilities(q)
    m = r["metrics"]["a"]
    assert m["log_loss"] is None and m["log_loss_status"] == "infinite" and m["impossible_events"] == 1
    assert abs(Decimal(m["brier"]) - Decimal(1) / 3) < Decimal("1e-27")
    assert "Infinite" in render(r)
    json.dumps(r, allow_nan=False)
    q["candidates"][0]["file"] = _file(
        "a.csv", ["Origin", "Probability"], [["2025-01-01", 0], ["2025-01-02", 1], ["2025-01-03", 1]]
    )
    assert review_probabilities(q)["metrics"]["a"]["log_loss"] == "0"


@pytest.mark.parametrize("label,p", [(0, "0." + "9" * 49), (1, "0." + "9" * 49), (1, "1e-100")])
def test_probability_precision_before_arithmetic(label, p):
    q = request()
    q.pop("baseline")
    q["expected_keys"] = q["expected_keys"][:1]
    q["labels"]["file"] = _file(
        "labels.csv", ["Origin", "Label", "Available"], [["2025-01-01", label, "2025-01-02"]]
    )
    q["candidates"][0]["file"] = _file("a.csv", ["Origin", "Probability"], [["2025-01-01", p]])
    m = review_probabilities(q)["metrics"]["a"]
    with localcontext() as c:
        c.prec = 700
        probability = Decimal(p)
        ll = -(probability if label else 1 - probability).ln()
        bs = (probability - label) ** 2
        assert abs(Decimal(m["log_loss"]) - ll) <= ll * Decimal("1e-39")
        assert abs(Decimal(m["brier"]) - bs) <= bs * Decimal("1e-39")
    assert m["impossible_events"] == 0 and m["log_loss_status"] == "finite"


def test_missing_duplicate_and_invalid_rows_stay_visible():
    q = request()
    q["baseline"]["file"] = _file("b.csv", ["Origin", "Probability"], [["2025-01-01", 0.5]])
    r = review_probabilities(q)
    assert r["common"] == 1
    q["baseline"]["file"] = _file(
        "b.csv",
        ["Origin", "Probability"],
        [["2025-01-01", 0.5], ["2025-01-01", 0.5], ["bad", 0.1], ["2025-01-09", 0.1]],
    )
    r = review_probabilities(q)
    assert r["common"] == 0 and not r["comparison_ready"]
    rows = [x for x in r["input_rows"] if x["source"] == "baseline"]
    assert [x["status"] for x in rows] == ["duplicate", "duplicate", "invalid", "outside_scope"]
    assert len(r["evaluation_rows"]) == 3


def test_contract_conflict_future_origin_and_pending_blank_label():
    q = request()
    q["evaluation_as_of"] = "2025-01-01"
    q["labels"]["file"] = _file(
        "labels.csv",
        ["Origin", "Label", "Available"],
        [["2025-01-01", "", "2025-01-02"], ["2025-01-02", 1, "2025-01-03"]],
    )
    r = review_probabilities(q)
    assert r["evaluation_rows"][0]["states"]["labels"] == "pending"
    assert r["evaluation_rows"][1]["states"]["labels"] == "not_yet_issued"
    q = request()
    q["candidates"][0]["event_definition"] = "Opposite event"
    r = review_probabilities(q)
    assert r["contract_errors"] and not r["comparison_ready"] and r["metrics"]["a"] is None
    q = request()
    q["expected_keys"] *= 2
    with pytest.raises(ValueError, match="unique"):
        review_probabilities(q)


def test_report_escapes_and_unsupported_fields_fail():
    q = request()
    q["event_definition"] = "<script>unsafe</script>"
    for s in [q["labels"], *q["candidates"], q["baseline"]]:
        s["event_definition"] = q["event_definition"]
    q["candidates"][0]["source_note"] = "<script>source note</script>"
    q["candidates"][0]["file"] = _file("bad.csv", ["Origin", "Probability"], [["2025-01-01", "invalid"]])
    result = review_probabilities(q)
    report = render(result)
    assert "<script>" not in report
    assert "&lt;script&gt;source note&lt;/script&gt;" in report
    assert result["sources"][1]["sha256"] in report
    assert "a / candidate" in report and "bad.csv / CSV / 1" in report
    assert "<td>a</td><td>2</td><td>invalid</td>" in report
    assert "Brier = sum((p - y)^2) / n" in report and "nats per event" in report
    q["fit_model"] = True
    with pytest.raises(ValueError, match="unsupported"):
        review_probabilities(q)


@pytest.mark.parametrize("entity", [7, None, "007"])
def test_excel_entity_identity_is_never_inferred(entity):
    import base64
    import io

    from openpyxl import Workbook

    q = request()
    q.pop("baseline")
    q["expected_keys"] = [{"origin": "2025-01-01", "entity": "007" if entity == "007" else "7"}]
    expected = q["expected_keys"][0]["entity"]
    q["labels"]["mapping"]["entity"] = "Entity"
    q["labels"]["file"] = _file(
        "labels.csv", ["Origin", "Entity", "Label", "Available"], [["2025-01-01", expected, 0, "2025-01-02"]]
    )
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Origin", "Entity", "Probability"])
    sheet.append(["2025-01-01", entity, 0.25])
    sheet["B2"].number_format = "000"
    buffer = io.BytesIO()
    workbook.save(buffer)
    q["candidates"][0]["mapping"]["entity"] = "Entity"
    q["candidates"][0]["file"] = {
        "name": "candidate.xlsx",
        "content_base64": base64.b64encode(buffer.getvalue()).decode(),
    }
    result = review_probabilities(q)
    assert result["common"] == (1 if entity == "007" else 0)
    row = next(r for r in result["input_rows"] if r["source"] == "a")
    assert row["status"] == ("valid" if entity == "007" else "invalid")
    if entity != "007":
        assert "exact text" in row["reason"]
