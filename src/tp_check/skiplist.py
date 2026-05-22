from __future__ import annotations

from pathlib import Path

from .parser import DayRecord

SKIP_FILE = Path("skip.txt")


def load_skipped_employee_names(skip_file: Path = SKIP_FILE) -> set[str]:
    if not skip_file.exists():
        return set()

    return {
        line.strip()
        for line in skip_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def filter_skipped_employees(
    day_records: list[DayRecord],
    skipped_employee_names: set[str] | None = None,
) -> list[DayRecord]:
    names_to_skip = skipped_employee_names or load_skipped_employee_names()
    if not names_to_skip:
        return day_records

    return [
        record
        for record in day_records
        if record.employee_name not in names_to_skip
    ]
