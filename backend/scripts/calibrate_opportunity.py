"""Generate a deterministic opportunity calibration report pair."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
for path in (BACKEND, BACKEND.parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.config import settings
from app.db import get_connection, init_db
from app.opportunity.calibration import (
    build_calibration_report,
    load_calibration_dataset,
    write_report_pair,
)

MODEL_VERSION = "opportunity-v2.0"
PROFILE_VERSION = "low-cost-curated-multiwallet-v1"
MAX_ERROR_MESSAGE = 160


class CalibrationValidationError(ValueError):
    """Raised when command-line values cannot be used safely."""


def _sanitize_message(message: str) -> str:
    message = " ".join(message.split())
    message = re.sub(r"(?:sqlite|postgres(?:ql)?|mysql)://\S+", "[redacted-url]", message, flags=re.IGNORECASE)
    message = re.sub(r"(--database-url\s+)(\S+)", r"\1[redacted]", message, flags=re.IGNORECASE)
    return message[: MAX_ERROR_MESSAGE - 1] or "operation failed"


class CalibrationArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, f"{_sanitize_message(f'argument error: {message}')}\n")


def parse_as_of(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and return it normalized to UTC."""
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("as-of must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("as-of must include a timezone")
    return parsed.astimezone(UTC)


def _parser() -> argparse.ArgumentParser:
    parser = CalibrationArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, type=parse_as_of)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--database-url")
    return parser


def _validate_output_dir(output_dir: Path) -> Path:
    if output_dir.exists() and not output_dir.is_dir():
        raise CalibrationValidationError(f"output path is not a directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def run_calibration(*, as_of: datetime, output_dir: Path, database_url: str | None = None) -> tuple[Path, Path]:
    """Load, aggregate, and publish one calibration report pair."""
    output_dir = _validate_output_dir(Path(output_dir))
    previous_database_url = settings.database_url
    connection = None
    try:
        if database_url is not None:
            settings.database_url = database_url
        init_db()
        connection = get_connection()
        try:
            dataset = load_calibration_dataset(
                connection,
                model_version=MODEL_VERSION,
                profile_version=PROFILE_VERSION,
            )
            report = build_calibration_report(dataset, as_of=as_of)
            return write_report_pair(report, output_dir)
        finally:
            if connection is not None:
                connection.close()
    finally:
        settings.database_url = previous_database_url


def _public_error(error: Exception, *, secret: str | None = None) -> str:
    message = _sanitize_message(str(error))
    if secret:
        message = message.replace(secret, "[redacted]")
    return message[:MAX_ERROR_MESSAGE] or "operation failed"


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        json_path, markdown_path = run_calibration(
            as_of=args.as_of,
            output_dir=args.output_dir,
            database_url=args.database_url,
        )
        # Keep operator output stable and aggregate-only; report content is on disk.
        report = json_path.read_bytes()
        import json

        payload = json.loads(report)
        windows = payload["windows"]
        print(f"JSON report: {json_path}")
        print(f"Markdown report: {markdown_path}")
        print(f"Linked samples: {payload['data_quality']['linked_sample_count']}")
        for name in ("90d", "180d"):
            print(f"{name} gate: {windows[name]['gate']}; mature samples: {windows[name]['mature_sample_count']}")
        return 0
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else 1
    except CalibrationValidationError as error:
        print(_sanitize_message(f"argument error: {_public_error(error)}"), file=sys.stderr)
        return 2
    except Exception as error:
        supplied_url = locals().get("args").database_url if "args" in locals() else None
        print(
            _sanitize_message(f"{type(error).__name__}: {_public_error(error, secret=supplied_url)}"), file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
