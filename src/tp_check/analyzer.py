from __future__ import annotations

from dataclasses import dataclass

from .parser import DayRecord, PunchEntry, format_clock_time, parse_clock_time

SPLIT_SHIFT_GAP_MINUTES = 60


@dataclass(slots=True)
class BreakViolation:
    employee_name: str
    work_date_label: str
    work_date_sort_key: str
    shift_span_label: str
    worked_minutes: int
    worked_hours_label: str
    required_breaks: int
    actual_breaks: int
    converted_breaks: int
    reason: str


@dataclass(slots=True)
class ShiftRecord:
    employee_name: str
    work_date_label: str
    work_date_sort_key: str
    shift_span_label: str
    worked_minutes: int
    work_segments: list[PunchEntry]
    unpaid_breaks: list[PunchEntry]
    converted_breaks: list[PunchEntry]
    all_entries: list[PunchEntry]


@dataclass(slots=True)
class AnalysisResult:
    violations: list[BreakViolation]
    compliant_shifts: int
    total_shifts_considered: int


def analyze_day_records(day_records: list[DayRecord]) -> AnalysisResult:
    violations: list[BreakViolation] = []
    compliant_shifts = 0
    total_shifts_considered = 0

    for record in day_records:
        for shift_record in split_day_record_into_shifts(record):
            required_breaks = determine_required_breaks(shift_record.worked_minutes)
            if required_breaks == 0:
                continue

            total_shifts_considered += 1
            actual_breaks = len(shift_record.unpaid_breaks)
            converted_breaks = len(shift_record.converted_breaks)

            reasons: list[str] = []
            if actual_breaks < required_breaks:
                reasons.append(
                    f"Shift of {format_minutes(shift_record.worked_minutes)} hours found with {actual_breaks} break(s); expected {required_breaks} break(s) based on duration."
                )
            if converted_breaks and actual_breaks < required_breaks:
                reasons.append(
                    f"{converted_breaks} converted paid break row(s) do not count as unpaid breaks"
                )

            if reasons:
                violations.append(
                    BreakViolation(
                        employee_name=shift_record.employee_name,
                        work_date_label=shift_record.work_date_label,
                        work_date_sort_key=shift_record.work_date_sort_key,
                        shift_span_label=shift_record.shift_span_label,
                        worked_minutes=shift_record.worked_minutes,
                        worked_hours_label=format_minutes(shift_record.worked_minutes),
                        required_breaks=required_breaks,
                        actual_breaks=actual_breaks,
                        converted_breaks=converted_breaks,
                        reason="; ".join(reasons),
                    )
                )
            else:
                compliant_shifts += 1

    return AnalysisResult(
        violations=violations,
        compliant_shifts=compliant_shifts,
        total_shifts_considered=total_shifts_considered,
    )


def split_day_record_into_shifts(day_record: DayRecord) -> list[ShiftRecord]:
    if not day_record.work_segments:
        return []

    sorted_segments = sorted(
        day_record.work_segments, key=lambda entry: parse_clock_time(entry.time_in)
    )
    grouped_segments: list[list[PunchEntry]] = [[sorted_segments[0]]]
    for segment in sorted_segments[1:]:
        previous_segment = grouped_segments[-1][-1]
        gap_minutes = parse_clock_time(segment.time_in) - parse_clock_time(previous_segment.time_out)
        if gap_minutes >= SPLIT_SHIFT_GAP_MINUTES:
            grouped_segments.append([segment])
        else:
            grouped_segments[-1].append(segment)

    shift_records: list[ShiftRecord] = []
    for segments in grouped_segments:
        shift_start = parse_clock_time(segments[0].time_in)
        shift_end = parse_clock_time(segments[-1].time_out)
        unpaid_breaks = find_unpaid_breaks_within_shift(day_record, segments)
        converted_breaks = find_entries_within_shift(day_record.converted_breaks, shift_start, shift_end)
        shift_records.append(
            ShiftRecord(
                employee_name=day_record.employee_name,
                work_date_label=day_record.work_date_label,
                work_date_sort_key=day_record.work_date.strftime("%Y-%m-%d"),
                shift_span_label=(
                    f"{format_clock_time(segments[0].time_in)} to "
                    f"{format_clock_time(segments[-1].time_out)}"
                ),
                worked_minutes=sum(entry.total_minutes for entry in segments),
                work_segments=segments,
                unpaid_breaks=unpaid_breaks,
                converted_breaks=converted_breaks,
                all_entries=sorted(
                    [*segments, *unpaid_breaks, *converted_breaks],
                    key=lambda entry: parse_clock_time(entry.time_in),
                ),
            )
        )

    return shift_records


def build_shift_records(day_records: list[DayRecord]) -> list[ShiftRecord]:
    shift_records: list[ShiftRecord] = []
    for day_record in day_records:
        shift_records.extend(split_day_record_into_shifts(day_record))
    return shift_records


def find_unpaid_breaks_within_shift(
    day_record: DayRecord,
    work_segments: list[PunchEntry],
) -> list[PunchEntry]:
    unpaid_breaks: list[PunchEntry] = []
    for previous_segment, next_segment in zip(work_segments, work_segments[1:]):
        previous_end = parse_clock_time(previous_segment.time_out)
        next_start = parse_clock_time(next_segment.time_in)
        unpaid_breaks.extend(
            entry
            for entry in day_record.unpaid_breaks
            if previous_end <= parse_clock_time(entry.time_in)
            and parse_clock_time(entry.time_out) <= next_start
        )
    return unpaid_breaks


def find_entries_within_shift(
    entries: list[PunchEntry],
    shift_start: int,
    shift_end: int,
) -> list[PunchEntry]:
    return [
        entry
        for entry in entries
        if shift_start <= parse_clock_time(entry.time_in)
        and parse_clock_time(entry.time_out) <= shift_end
    ]


def determine_required_breaks(worked_minutes: int) -> int:
    if worked_minutes >= 13 * 60:
        return 3
    if worked_minutes >= 10 * 60:
        return 2
    if worked_minutes >= 6 * 60:
        return 1
    return 0


def format_minutes(total_minutes: int) -> str:
    return f"{total_minutes // 60}:{total_minutes % 60:02d}"
