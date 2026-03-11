import json
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from app.core.config import ARCHIVE_INDEX_PATH, GENERATED_REPORTS_DIR
from app.models.schemas import ArchiveAllocationSnapshot, ArchiveIndex, ArchiveRecord, MonthlyAllocationReport


def ensure_archive_index_file() -> None:
    if ARCHIVE_INDEX_PATH.exists():
        return
    ARCHIVE_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVE_INDEX_PATH.write_text(ArchiveIndex().model_dump_json(indent=2), encoding="utf-8")


def load_archive_index() -> ArchiveIndex:
    ensure_archive_index_file()
    content = json.loads(ARCHIVE_INDEX_PATH.read_text(encoding="utf-8"))
    return ArchiveIndex.model_validate(content)


def save_archive_index(index: ArchiveIndex) -> ArchiveIndex:
    ARCHIVE_INDEX_PATH.write_text(index.model_dump_json(indent=2), encoding="utf-8")
    return index


def _owners_from_report(report: MonthlyAllocationReport) -> list[ArchiveAllocationSnapshot]:
    return [
        ArchiveAllocationSnapshot(
            owner_name=item.owner_name,
            share_percent=item.share_percent,
            total_effort_score=item.total_effort_score,
        )
        for item in report.allocations
    ]


def _default_display_name(path: Path) -> str:
    return path.stem.replace("_", " ")


def _fallback_record(path: Path) -> ArchiveRecord:
    generated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    month_match = re.search(r"(\d{4}-\d{2})", path.stem)
    month_label = month_match.group(1) if month_match else generated_at.strftime("%Y-%m")
    return ArchiveRecord(
        filename=path.name,
        display_name=_default_display_name(path),
        month_label=month_label,
        generated_at=generated_at,
        owners=[],
    )


def _sync_index(index: ArchiveIndex) -> ArchiveIndex:
    GENERATED_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    existing_files = {path.name: path for path in GENERATED_REPORTS_DIR.glob("*.pdf")}
    synced: list[ArchiveRecord] = []
    known = {record.filename: record for record in index.archives if record.filename in existing_files}
    for filename, path in existing_files.items():
        synced.append(known.get(filename, _fallback_record(path)))
    synced.sort(key=lambda item: (item.month_label, item.generated_at, item.filename), reverse=True)
    index.archives = synced
    return save_archive_index(index)


def upsert_archive_record(report: MonthlyAllocationReport, output_path: Path) -> ArchiveRecord:
    index = _sync_index(load_archive_index())
    record = ArchiveRecord(
        filename=output_path.name,
        display_name=_default_display_name(output_path),
        month_label=report.month_label,
        generated_at=report.generated_at,
        owners=_owners_from_report(report),
    )
    for idx, current in enumerate(index.archives):
        if current.filename == record.filename:
            index.archives[idx] = record
            break
    else:
        index.archives.append(record)
    index.archives.sort(key=lambda item: (item.month_label, item.generated_at, item.filename), reverse=True)
    save_archive_index(index)
    return record


def _matches_owner(record: ArchiveRecord, owner_name: str | None) -> bool:
    if not owner_name:
        return True
    owner_name_lower = owner_name.lower()
    return any(owner.owner_name.lower() == owner_name_lower for owner in record.owners)


def _matches_month_range(record: ArchiveRecord, start_month: str | None, end_month: str | None) -> bool:
    if start_month and record.month_label < start_month:
        return False
    if end_month and record.month_label > end_month:
        return False
    return True


def list_archive_records(
    start_month: str | None = None,
    end_month: str | None = None,
    owner_name: str | None = None,
) -> list[ArchiveRecord]:
    index = _sync_index(load_archive_index())
    return [
        record
        for record in index.archives
        if _matches_month_range(record, start_month, end_month) and _matches_owner(record, owner_name)
    ]


def _safe_filename(display_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", display_name.strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return f"{cleaned or 'archive'}.pdf"


def rename_archive(filename: str, display_name: str) -> ArchiveRecord:
    index = _sync_index(load_archive_index())
    source = GENERATED_REPORTS_DIR / filename
    if not source.exists():
        raise FileNotFoundError(filename)
    target_name = _safe_filename(display_name)
    target = GENERATED_REPORTS_DIR / target_name
    if target.exists() and target.name != source.name:
        raise FileExistsError(target.name)
    source.rename(target)
    for idx, record in enumerate(index.archives):
        if record.filename == filename:
            updated = record.model_copy(update={"filename": target.name, "display_name": display_name.strip()})
            index.archives[idx] = updated
            save_archive_index(index)
            return updated
    updated = _fallback_record(target).model_copy(update={"display_name": display_name.strip()})
    index.archives.append(updated)
    save_archive_index(index)
    return updated


def delete_archive(filename: str) -> None:
    path = GENERATED_REPORTS_DIR / filename
    if path.exists():
        path.unlink()
    index = load_archive_index()
    index.archives = [record for record in index.archives if record.filename != filename]
    save_archive_index(index)


def export_archives_zip(
    start_month: str | None = None,
    end_month: str | None = None,
    owner_name: str | None = None,
) -> tuple[BytesIO, str]:
    records = list_archive_records(start_month=start_month, end_month=end_month, owner_name=owner_name)
    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
        for record in records:
            file_path = GENERATED_REPORTS_DIR / record.filename
            if file_path.exists():
                archive.writestr(record.filename, file_path.read_bytes())
    buffer.seek(0)
    owner_label = owner_name or "all"
    start_label = start_month or "start"
    end_label = end_month or "end"
    return buffer, f"thermocalc-archives-{start_label}-{end_label}-{owner_label}.zip"