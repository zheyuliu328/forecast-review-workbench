"""In-memory, invented file fixtures exercise the upload-to-table boundary."""

import base64
import csv
import io
import json
from datetime import datetime
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook

from forecast_review_workbench import tableio


def uploaded(name, content):
    return {"name": name, "content_base64": base64.b64encode(content).decode("ascii")}


def csv_file(rows, name="test.csv"):
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows(rows)
    return uploaded(name, stream.getvalue().encode("utf-8"))


def excel_file(extra_sheet=False):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Forecasts"
    sheet.append(["Invented example"])
    sheet.append(["Date", "Entity", "Prediction"])
    sheet.append([datetime(2024, 1, 31, 12), "0007", "=1+1"])
    if extra_sheet:
        workbook.create_sheet("Other")
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return uploaded("predictions.xlsx", stream.getvalue())


def rewrite_xlsx(file, change):
    stream = io.BytesIO()
    with ZipFile(io.BytesIO(base64.b64decode(file["content_base64"]))) as source:
        with ZipFile(stream, "w", ZIP_DEFLATED) as target:
            for member in source.infolist():
                value = change(member.filename, source.read(member.filename))
                if value is not None:
                    target.writestr(member, value)
    return uploaded(file["name"], stream.getvalue())


def test_csv_inspection_and_blank_row_accounting_preserve_text_ids():
    file = csv_file([["Month", "Entity", "Value"], ["2024-01", "001", "10"], [], ["2024-02", "1", "11"]])
    inspection = tableio.inspect_table(file)
    assert inspection == {
        "sheets": [],
        "sheet": None,
        "header_row": 1,
        "headers": ["Month", "Entity", "Value"],
        "preview": [["2024-01", "001", "10"], ["2024-02", "1", "11"]],
        "row_count": 2,
        "error": None,
    }
    table = tableio.read_table(file)
    assert table["blank_rows_ignored"] == [3]
    assert [row["row"] for row in table["rows"]] == [2, 4]
    assert table["rows"][0]["cells"]["Entity"] == {"text": "001", "kind": "text"}


def test_ambiguous_excel_returns_sheets_and_header_error_retains_raw_preview():
    file = excel_file(extra_sheet=True)
    inspection = tableio.inspect_table(file)
    assert inspection["sheets"] == ["Forecasts", "Other"]
    assert inspection["error"] and inspection["headers"] == []
    wrong = tableio.inspect_table(file, "Forecasts", 20)
    assert wrong["error"] and wrong["preview"][0] == ["Invented example"]
    selected = tableio.inspect_table(file, "Forecasts", 2)
    assert selected["error"] is None and selected["row_count"] == 1
    assert selected["preview"][0] == ["2024-01-31T12:00:00", "0007", "=1+1"]


def test_excel_dates_and_formulas_are_typed_without_evaluation():
    table = tableio.read_table(excel_file(), header_row=2)
    cells = table["rows"][0]["cells"]
    assert cells["Date"]["kind"] == "date"
    assert cells["Prediction"] == {"kind": "formula", "text": "=1+1"}


def test_excel_array_formula_has_stable_text_instead_of_object_memory_address():
    file = rewrite_xlsx(
        excel_file(),
        lambda name, data: (
            data.replace(b"<f>1+1</f>", b'<f t="array" ref="C3">1+1</f>')
            if name == "xl/worksheets/sheet1.xml"
            else data
        ),
    )
    first = tableio.read_table(file, header_row=2)
    second = tableio.read_table(file, header_row=2)
    assert first == second
    assert first["rows"][0]["cells"]["Prediction"] == {"kind": "formula", "text": "=1+1"}


def test_excel_incorrect_saved_dimension_does_not_hide_rows():
    file = rewrite_xlsx(
        excel_file(),
        lambda name, data: data.replace(b"A1:C3", b"A1:A1") if name == "xl/worksheets/sheet1.xml" else data,
    )
    assert tableio.inspect_table(file, header_row=2)["row_count"] == 1


@pytest.mark.parametrize(
    "defect", ["missing_content_types", "malformed_workbook", "malformed_worksheet", "entity_expansion"]
)
def test_broken_excel_reports_actionable_structure_errors(defect):
    def change(name, content):
        if defect == "missing_content_types" and name == "[Content_Types].xml":
            return None
        if name == {
            "malformed_workbook": "xl/workbook.xml",
            "malformed_worksheet": "xl/worksheets/sheet1.xml",
        }.get(defect):
            return b"<broken><not-closed>"
        if defect == "entity_expansion" and name == "[Content_Types].xml":
            return b'<!DOCTYPE Types [<!ENTITY x "expanded">]><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">&x;</Types>'
        return content

    file = rewrite_xlsx(excel_file(), change)
    inspection = tableio.inspect_table(file, header_row=2)
    assert inspection["error"]
    with pytest.raises(ValueError):
        tableio.read_table(file, header_row=2)
    json.dumps(inspection, allow_nan=False)


@pytest.mark.parametrize(
    "rows",
    [
        [["Date", "Value", "Value"], ["2024-01", "1", "2"]],
        [["Date", ""], ["2024-01", "1"]],
        [["Date", "Value"], ["2024-01", "1", "extra"]],
    ],
)
def test_ambiguous_csv_shapes_are_not_silently_repaired(rows):
    file = csv_file(rows)
    assert tableio.inspect_table(file)["error"]
    with pytest.raises(ValueError):
        tableio.read_table(file)


@pytest.mark.parametrize(
    "file",
    [
        {"name": "bad.csv", "content_base64": "not base64"},
        uploaded("bad.csv", b"\xff\xff"),
        uploaded("bad.xlsm", b"unsupported"),
        uploaded("bad.xlsx", b"not a zip"),
    ],
)
def test_invalid_uploads_remain_actionable_json_errors(file):
    result = tableio.inspect_table(file)
    assert result["error"]
    json.dumps(result, allow_nan=False)


def test_invalid_inspection_controls_do_not_leak_nan_to_json():
    result = tableio.inspect_table(
        csv_file([["Date", "Value"]]), header_row=float("nan"), sheet={"bad": "shape"}
    )
    assert result["error"]
    json.dumps(result, allow_nan=False)


def test_uploaded_name_is_never_opened_as_a_path(monkeypatch):
    import builtins

    def no_disk(*args, **kwargs):
        raise AssertionError("Browser filenames must not trigger filesystem access")

    monkeypatch.setattr(builtins, "open", no_disk)
    result = tableio.inspect_table(
        csv_file([["Date", "Value"], ["2024-01", "3"]], name="/untrusted/not-a-real-file.csv")
    )
    assert result["row_count"] == 1 and result["error"] is None


def test_row_column_and_original_byte_limits(monkeypatch):
    monkeypatch.setattr(tableio, "MAX_ROWS", 1)
    assert tableio.inspect_table(csv_file([["Date", "Value"], ["2024-01", "1"], ["2024-02", "2"]]))["error"]
    monkeypatch.setattr(tableio, "MAX_COLUMNS", 1)
    assert tableio.inspect_table(csv_file([["Date", "Value"]]))["error"]
    monkeypatch.setattr(tableio, "MAX_BYTES", 3)
    assert tableio.inspect_table(uploaded("large.csv", b"abcd"))["error"]


def test_excel_expanded_size_limit_is_checked_before_workbook_parse():
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"x" * (20 * 1024 * 1024 + 1))
    result = tableio.inspect_table(uploaded("compressed.xlsx", stream.getvalue()))
    assert "expanded-size" in result["error"]
