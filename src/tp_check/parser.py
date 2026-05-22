from __future__ import annotations

import io
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from pypdf import PdfReader

WORK_TYPES = {"Regular"}
UNPAID_BREAK_TYPES = {"Unpaid"}
NON_COMPLIANT_BREAK_TYPES = {"Break (Conv to Paid)"}

EMPLOYEE_HEADER_RE = re.compile(r"^[A-Za-z][A-Za-z ,.'()/-]+$")
PUNCH_LINE_RE = re.compile(
    r"^\s*(?P<weekday>Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+"
    r"(?P<date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<time_in>\d{1,2}:\d{2}\s*[ap]\*?)\s+"
    r"(?P<time_out>\d{1,2}:\d{2}\s*[ap]\*?)\s+"
    r"(?P<total>\d{1,2}:\d{2})\s+"
    r"(?P<pay_type>Regular|Unpaid|Break \(Conv to Paid\))\b"
)


@dataclass(slots=True)
class PunchEntry:
    employee_name: str
    work_date: datetime
    time_in: str
    time_out: str
    total_minutes: int
    pay_type: str
    raw_line: str


@dataclass(slots=True)
class DayRecord:
    employee_name: str
    work_date: datetime
    all_entries: list[PunchEntry]
    work_segments: list[PunchEntry]
    unpaid_breaks: list[PunchEntry]
    converted_breaks: list[PunchEntry]

    @property
    def worked_minutes(self) -> int:
        return sum(entry.total_minutes for entry in self.work_segments)

    @property
    def work_date_label(self) -> str:
        return self.work_date.strftime("%a, %m/%d/%Y")

    @property
    def shift_span_label(self) -> str:
        if not self.all_entries:
            return ""

        earliest_entry = min(self.all_entries, key=lambda entry: parse_clock_time(entry.time_in))
        latest_entry = max(self.all_entries, key=lambda entry: parse_clock_time(entry.time_out))
        return f"{format_clock_time(earliest_entry.time_in)} to {format_clock_time(latest_entry.time_out)}"


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def parse_pdf_bytes(pdf_bytes: bytes) -> list[DayRecord]:
    return parse_time_punch_text(extract_text_from_pdf_bytes(pdf_bytes))


def parse_time_punch_text(text: str) -> list[DayRecord]:
    current_employee: str | None = None
    grouped: dict[tuple[str, datetime], DayRecord] = {}

    for raw_line in iter_clean_lines(text.splitlines()):
        if should_ignore_line(raw_line):
            continue

        if EMPLOYEE_HEADER_RE.match(raw_line) and "," in raw_line:
            current_employee = raw_line.strip()
            continue

        match = PUNCH_LINE_RE.match(raw_line)
        if not match or current_employee is None:
            continue

        entry = build_entry(current_employee, raw_line, match)
        key = (entry.employee_name, entry.work_date)
        day_record = grouped.setdefault(
            key,
            DayRecord(
                employee_name=entry.employee_name,
                work_date=entry.work_date,
                all_entries=[],
                work_segments=[],
                unpaid_breaks=[],
                converted_breaks=[],
            ),
        )
        day_record.all_entries.append(entry)

        if entry.pay_type in WORK_TYPES:
            day_record.work_segments.append(entry)
        elif entry.pay_type in UNPAID_BREAK_TYPES:
            day_record.unpaid_breaks.append(entry)
        elif entry.pay_type in NON_COMPLIANT_BREAK_TYPES:
            day_record.converted_breaks.append(entry)

    return sorted(grouped.values(), key=lambda record: (record.employee_name, record.work_date))


def iter_clean_lines(lines: Iterable[str]) -> Iterable[str]:
    for line in lines:
        cleaned = " ".join(line.replace("\x0c", " ").split()).strip()
        if cleaned:
            yield cleaned


def should_ignore_line(line: str) -> bool:
    ignored_prefixes = (
        "Employee Time Detail",
        "From ",
        "Employee Totals",
        "All Employees Grand Total",
        "Punch types of",
        "* - clock-in time or clock-out time",
        "04/",
        "05/",
        "06/",
        "07/",
        "08/",
        "09/",
        "10/",
        "11/",
        "12/",
    )
    ignored_exact = {
        "Employee",
        "Date",
        "Name",
        "Time In",
        "Time Out",
        "Total Time",
        "Pay Type",
        "Wage Rate",
        "Regular Hours Wages Overtime Hours Wages Total Wages",
    }
    if line.startswith(ignored_prefixes):
        return True
    if line in ignored_exact:
        return True
    if "Southroads Shopping Center FSU" in line:
        return True
    if "Page " in line and " of " in line:
        return True
    return False


def build_entry(employee_name: str, raw_line: str, match: re.Match[str]) -> PunchEntry:
    work_date = datetime.strptime(match.group("date"), "%m/%d/%Y")
    time_in = match.group("time_in")
    time_out = match.group("time_out")
    return PunchEntry(
        employee_name=employee_name,
        work_date=work_date,
        time_in=time_in.replace("*", ""),
        time_out=time_out.replace("*", ""),
        total_minutes=parse_duration_to_minutes(match.group("total")),
        pay_type=match.group("pay_type"),
        raw_line=raw_line,
    )


def parse_duration_to_minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def parse_clock_time(value: str) -> int:
    normalized = normalize_meridiem(value)
    parsed = datetime.strptime(normalized, "%I:%M %p")
    return parsed.hour * 60 + parsed.minute


def format_clock_time(value: str) -> str:
    normalized = normalize_meridiem(value)
    parsed = datetime.strptime(normalized, "%I:%M %p")
    return parsed.strftime("%I:%M %p").lstrip("0")


def normalize_meridiem(value: str) -> str:
    collapsed = " ".join(value.split()).strip().lower()
    if collapsed.endswith("a"):
        return f"{collapsed[:-1].strip()} AM"
    if collapsed.endswith("p"):
        return f"{collapsed[:-1].strip()} PM"
    return collapsed.upper()
