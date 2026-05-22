from __future__ import annotations

from dataclasses import dataclass
import time
from pathlib import Path
from tempfile import gettempdir
from textwrap import wrap
from uuid import uuid4

from flask import abort

from .analyzer import AnalysisResult, BreakViolation, ShiftRecord
from .parser import format_clock_time

REPORT_DIR = Path(gettempdir()) / "tp_check_reports"
REPORT_RETENTION_SECONDS = 24 * 60 * 60
MAX_LINE_LENGTH = 88


@dataclass(slots=True)
class StyledLine:
    text: str
    font: str = "regular"


def save_uploaded_pdf(pdf_bytes: bytes) -> str:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    purge_expired_reports()
    report_id = uuid4().hex
    (REPORT_DIR / f"{report_id}.pdf").write_bytes(pdf_bytes)
    return report_id


def load_uploaded_pdf(report_id: str) -> bytes:
    if not report_id.isalnum():
        abort(404)

    file_path = REPORT_DIR / f"{report_id}.pdf"
    if not file_path.exists():
        abort(404)

    return file_path.read_bytes()


def purge_expired_reports(now: float | None = None) -> None:
    if not REPORT_DIR.exists():
        return

    current_time = now or time.time()
    for file_path in REPORT_DIR.glob("*.pdf"):
        if current_time - file_path.stat().st_mtime > REPORT_RETENTION_SECONDS:
            file_path.unlink(missing_ok=True)


def build_pdf_report(
    *,
    filename: str,
    analysis: AnalysisResult,
    shift_records: list[ShiftRecord],
) -> bytes:
    lines: list[StyledLine] = [
        StyledLine("Time Punch Break Check Report", font="bold"),
        StyledLine(""),
        StyledLine(f"Source file: {filename}"),
        StyledLine(f"Break violations: {len(analysis.violations)}"),
        StyledLine(f"Compliant shifts: {analysis.compliant_shifts}"),
        StyledLine(f"Shifts requiring breaks: {analysis.total_shifts_considered}"),
        StyledLine(""),
    ]

    if analysis.violations:
        lines.append(StyledLine("Break discrepancies", font="bold"))
        lines.append(StyledLine(""))
        record_lookup = {
            (record.employee_name, record.work_date_label, record.shift_span_label): record
            for record in shift_records
        }
        violations_by_employee: dict[str, list[BreakViolation]] = {}
        for violation in analysis.violations:
            violations_by_employee.setdefault(violation.employee_name, []).append(violation)

        for employee_name in sorted(violations_by_employee):
            lines.append(StyledLine(employee_name, font="bold"))
            for index, violation in enumerate(
                sorted(
                    violations_by_employee[employee_name],
                    key=lambda item: (item.work_date_sort_key, item.shift_span_label),
                ),
                start=1,
            ):
                record = record_lookup.get(
                    (
                        violation.employee_name,
                        violation.work_date_label,
                        violation.shift_span_label,
                    )
                )
                lines.extend(build_violation_section(index, violation, record))
            lines.append(StyledLine(""))
    else:
        lines.append(StyledLine("No break discrepancies were detected."))

    return render_text_pdf(lines)


def build_violation_section(
    index: int,
    violation: BreakViolation,
    record: ShiftRecord | None,
) -> list[StyledLine]:
    section = [
        StyledLine(f"{index}. {violation.work_date_label}"),
        StyledLine(f"Shift: {violation.shift_span_label}"),
        StyledLine(f"Worked: {violation.worked_hours_label}"),
        StyledLine(
            "Discrepancy: "
            f"Shift of {violation.worked_hours_label} found with {violation.actual_breaks} "
            f"break(s); expected {violation.required_breaks} break(s) based on duration."
        ),
        StyledLine(f"Reason: {violation.reason}"),
    ]

    if record and record.all_entries:
        section.append(StyledLine("Punches:"))
        for entry in record.all_entries:
            section.append(
                StyledLine(
                    "  "
                    f"{format_clock_time(entry.time_in)} - {format_clock_time(entry.time_out)} | "
                    f"{entry.total_minutes // 60}:{entry.total_minutes % 60:02d} | {entry.pay_type}"
                )
            )
    section.append(StyledLine(""))

    return section


def render_text_pdf(lines: list[StyledLine]) -> bytes:
    pages = paginate_lines(lines)

    objects: list[bytes] = []
    regular_font_object_id = 3 + (2 * len(pages))
    bold_font_object_id = regular_font_object_id + 1

    catalog = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects.append(catalog)

    kids = " ".join(f"{3 + (page_index * 2)} 0 R" for page_index in range(len(pages)))
    pages_object = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
    objects.append(pages_object)

    for page_index, page_lines in enumerate(pages):
        page_object_id = 3 + (page_index * 2)
        content_object_id = page_object_id + 1
        page_object = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {regular_font_object_id} 0 R /F2 {bold_font_object_id} 0 R >> >> "
            f"/Contents {content_object_id} 0 R >>"
        ).encode()
        objects.append(page_object)

        stream = build_page_stream(page_lines)
        content_object = (
            f"<< /Length {len(stream)} >>\nstream\n".encode()
            + stream
            + b"\nendstream"
        )
        objects.append(content_object)

    regular_font_object = b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"
    bold_font_object = b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier-Bold >>"
    objects.append(regular_font_object)
    objects.append(bold_font_object)

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{object_id} 0 obj\n".encode())
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())

    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF"
        ).encode()
    )
    return bytes(pdf)


def paginate_lines(lines: list[StyledLine]) -> list[list[StyledLine]]:
    wrapped: list[StyledLine] = []
    for line in lines:
        if not line.text:
            wrapped.append(StyledLine(""))
            continue

        wrapped.extend(
            StyledLine(text=part, font=line.font)
            for part in (
                wrap(line.text, width=MAX_LINE_LENGTH, subsequent_indent="    ") or [""]
            )
        )

    page_height = 50
    return [
        wrapped[index : index + page_height]
        for index in range(0, len(wrapped), page_height)
    ] or [[]]


def build_page_stream(lines: list[StyledLine]) -> bytes:
    commands = [b"BT", b"/F1 10 Tf", b"14 TL", b"54 738 Td"]
    first_line = True
    for line in lines:
        font_name = "F2" if line.font == "bold" else "F1"
        escaped = escape_pdf_text(line.text)
        if first_line:
            commands.append(f"/{font_name} 10 Tf".encode())
            commands.append(f"({escaped}) Tj".encode())
            first_line = False
        else:
            commands.append(b"T*")
            commands.append(f"/{font_name} 10 Tf".encode())
            commands.append(f"({escaped}) Tj".encode())
    commands.append(b"ET")
    return b"\n".join(commands)


def escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
