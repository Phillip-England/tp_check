# Time Punch Break Check

Local Flask app for reviewing time punch PDFs, flagging likely break violations, and exporting a shareable PDF report.

## Rules currently implemented

- If `>= 1:00` exists between the end of one `Regular` segment and the start of the next, the app treats that as a separate shift.
- Each isolated shift is checked independently.
- Shift duration `>= 6:00`: require at least `1` `Unpaid` row within that shift.
- Shift duration `>= 10:00`: require at least `2` `Unpaid` rows within that shift.
- Shift duration `>= 13:00`: require at least `3` `Unpaid` rows within that shift.
- The duration of an `Unpaid` row does not matter; any unpaid punch counts.
- `Break (Conv to Paid)` rows do not count as unpaid breaks.

Worked time is the sum of the employee's `Regular` rows inside each isolated shift.

## What the app shows

- A summary of break violations and compliant days after each upload.
- A break discrepancy view showing who was flagged and why.
- A shift-level punch view so you can inspect the exact isolated shift that was flagged.
- A downloadable PDF report for sending the flagged discrepancies to someone else.

## Skipping employees

Create a `skip.txt` file in the project directory to exclude employees from analysis and PDF reports. Add one exact employee name per line:

```text
Quintanilla, Zoila
```

Blank lines are ignored.

## Run locally

```bash
uv sync
uv run flask --app tp_check.app:create_app run --host 127.0.0.1 --port 8080
```

Then open `http://127.0.0.1:8080`.

## Tests

```bash
uv run pytest
```
