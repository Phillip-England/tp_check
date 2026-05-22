from __future__ import annotations

from dataclasses import dataclass

from flask import Flask, Response, render_template, request

from .analyzer import (
    AnalysisResult,
    BreakViolation,
    ShiftRecord,
    analyze_day_records,
    build_shift_records,
)
from .parser import parse_pdf_bytes
from .reporting import build_pdf_report, load_uploaded_pdf, save_uploaded_pdf
from .skiplist import filter_skipped_employees


@dataclass(slots=True)
class EmployeeCard:
    employee_name: str
    violations: list[BreakViolation]
    shift_records: list[ShiftRecord]

    @property
    def flagged_shifts(self) -> int:
        return len(self.violations)

    @property
    def total_worked_minutes(self) -> int:
        return sum(record.worked_minutes for record in self.shift_records)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

    @app.route("/", methods=["GET", "POST"])
    def index():
        context = {
            "filename": None,
            "analysis": None,
            "error": None,
            "report_id": None,
            "employee_cards": [],
        }
        if request.method == "POST":
            uploaded_file = request.files.get("pdf")
            if uploaded_file is None or not uploaded_file.filename:
                context["error"] = "Choose a time punch PDF to analyze."
                return render_template("index.html", **context)

            if not uploaded_file.filename.lower().endswith(".pdf"):
                context["error"] = "Only PDF files are supported."
                return render_template("index.html", **context)

            try:
                pdf_bytes = uploaded_file.read()
                records = filter_skipped_employees(parse_pdf_bytes(pdf_bytes))
                analysis = analyze_day_records(records)
                shift_records = build_shift_records(records)
                context["analysis"] = analysis
                context["employee_cards"] = build_employee_cards(shift_records, analysis)
                context["filename"] = uploaded_file.filename
                context["report_id"] = save_uploaded_pdf(pdf_bytes)
            except Exception as exc:  # pragma: no cover
                context["error"] = f"Could not process the PDF: {exc}"

        return render_template("index.html", **context)

    @app.get("/reports/<report_id>.pdf")
    def export_report(report_id: str) -> Response:
        pdf_bytes = load_uploaded_pdf(report_id)
        records = filter_skipped_employees(parse_pdf_bytes(pdf_bytes))
        analysis = analyze_day_records(records)
        report = build_pdf_report(
            filename=f"analysis-{report_id}.pdf",
            analysis=analysis,
            shift_records=build_shift_records(records),
        )
        return Response(
            report,
            mimetype="application/pdf",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="time-punch-break-report-{report_id[:8]}.pdf"'
                )
            },
        )

    return app


def main() -> None:
    app = create_app()
    app.run(debug=True, host="127.0.0.1", port=8080)


def build_employee_cards(
    shift_records: list[ShiftRecord],
    analysis: AnalysisResult,
) -> list[EmployeeCard]:
    violations_by_employee: dict[str, list[BreakViolation]] = {}
    for violation in analysis.violations:
        violations_by_employee.setdefault(violation.employee_name, []).append(violation)

    records_by_employee: dict[str, list[ShiftRecord]] = {}
    for shift_record in shift_records:
        records_by_employee.setdefault(shift_record.employee_name, []).append(shift_record)

    employee_names = sorted(violations_by_employee)
    cards: list[EmployeeCard] = []
    for employee_name in employee_names:
        employee_violations = sorted(
            violations_by_employee[employee_name],
            key=lambda item: (item.work_date_sort_key, item.shift_span_label),
        )
        violation_keys = {
            (item.work_date_label, item.shift_span_label) for item in employee_violations
        }
        cards.append(
            EmployeeCard(
                employee_name=employee_name,
                violations=employee_violations,
                shift_records=sorted(
                    [
                        shift_record
                        for shift_record in records_by_employee.get(employee_name, [])
                        if (shift_record.work_date_label, shift_record.shift_span_label)
                        in violation_keys
                    ],
                    key=lambda record: (record.work_date_sort_key, record.shift_span_label),
                ),
            )
        )
    return cards


if __name__ == "__main__":
    main()
