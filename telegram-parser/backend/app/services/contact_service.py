"""Contact import / listing / deletion.

The previous implementation only returned ``count`` and committed on
every row, which was both slow and silent on errors. The current
implementation:

* batches all rows into a single transaction,
* validates each row individually and reports failures in the result,
* returns a structured report ``{imported, skipped_duplicates, errors}``
  so the UI can show meaningful feedback,
* normalises usernames (trim ``@`` / whitespace) and phone numbers.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import openpyxl
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_

from app.models.contact import Contact
from app.schemas.contact import ContactCreate


CONTACT_HEADERS = {"telegram_id", "username", "first_name", "last_name", "phone_number"}

_PHONE_NORMALIZE_RE = re.compile(r"[^\d+]")


@dataclass
class ContactImportReport:
    inserted: int = 0
    skipped_duplicates: int = 0
    skipped_empty: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "imported": self.inserted,
            "skipped_duplicates": self.skipped_duplicates,
            "skipped_empty": self.skipped_empty,
            "errors": self.errors,
            "total_processed": self.inserted
            + self.skipped_duplicates
            + self.skipped_empty
            + len(self.errors),
        }


def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    cleaned = str(value).strip()
    return cleaned or None


def _normalize_username(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = value.strip().lstrip("@").lower()
    return value or None


def _normalize_phone(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    digits = _PHONE_NORMALIZE_RE.sub("", str(value))
    return digits or None


def build_contact_from_value(value: str, group_id: int | None = None) -> Optional[ContactCreate]:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.startswith("@"):
        return ContactCreate(username=_normalize_username(raw), group_id=group_id, source="manual_pool")
    if re.fullmatch(r"\+?\d{7,15}", raw):
        return ContactCreate(phone_number=_normalize_phone(raw), group_id=group_id, source="manual_pool")
    if re.fullmatch(r"\d{5,}", raw):
        return ContactCreate(telegram_id=raw, group_id=group_id, source="manual_pool")
    if re.fullmatch(r"[A-Za-z0-9_]{5,32}", raw):
        return ContactCreate(username=_normalize_username(raw), group_id=group_id, source="manual_pool")
    return None


def _build_contact_create(row: dict[str, Any]) -> Optional[ContactCreate]:
    """Build a ``ContactCreate`` from a raw dict.

    Returns ``None`` if the row is empty (no identifying column).
    Raises ``ValueError`` for malformed rows with details.
    """
    telegram_id = _clean(row.get("telegram_id"))
    username = _normalize_username(_clean(row.get("username")))
    first_name = _clean(row.get("first_name"))
    last_name = _clean(row.get("last_name"))
    phone = _normalize_phone(_clean(row.get("phone_number")))

    if not any([telegram_id, username, phone]):
        # No identifying column at all → silently skipped.
        return None

    return ContactCreate(
        group_id=row.get("group_id"),
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        phone_number=phone,
        source=row.get("_source") or "csv_upload",
    )


async def _contact_exists(
    db: AsyncSession, contact_in: ContactCreate, project_id: int = 1
) -> bool:
    identifiers = []
    if contact_in.telegram_id:
        identifiers.append(Contact.telegram_id == contact_in.telegram_id)
    if contact_in.username:
        identifiers.append(Contact.username == contact_in.username)
    if contact_in.phone_number:
        identifiers.append(Contact.phone_number == contact_in.phone_number)
    if not identifiers:
        return True
    result = await db.execute(
        select(Contact.id)
        .where(Contact.project_id == project_id, or_(*identifiers))
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def create_contact(db: AsyncSession, contact_in: ContactCreate) -> Contact:
    db_obj = Contact(**contact_in.model_dump())
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def get_contacts(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    project_id: int = 1,
    group_id: int | None = None,
) -> list[Contact]:
    query = select(Contact).where(Contact.project_id == project_id)
    if group_id:
        query = query.where(Contact.group_id == group_id)
    result = await db.execute(query.offset(skip).limit(limit))
    return list(result.scalars().all())


async def get_contacts_count(db: AsyncSession) -> int:
    result = await db.execute(select(func.count(Contact.id)))
    return result.scalar() or 0


async def delete_contact(db: AsyncSession, contact_id: int, project_id: int = 1) -> bool:
    result = await db.execute(
        select(Contact).where(Contact.id == contact_id, Contact.project_id == project_id)
    )
    contact = result.scalar_one_or_none()
    if not contact:
        return False
    await db.delete(contact)
    await db.commit()
    return True


def _validate_headers(fieldnames: Any) -> None:
    if not fieldnames:
        raise ValueError("File has no header row")
    if not CONTACT_HEADERS.intersection(fieldnames):
        raise ValueError(
            "File must include at least one of: "
            + ", ".join(sorted(CONTACT_HEADERS))
        )


async def bulk_upload_contacts_csv(
    db: AsyncSession,
    file_content: bytes,
    source: str = "csv_upload",
    project_id: int = 1,
) -> dict[str, Any]:
    """Import contacts from a CSV file.

    Returns a structured report that the UI can display verbatim.
    """
    try:
        content = file_content.decode("utf-8")
    except UnicodeDecodeError:
        content = file_content.decode("latin-1")

    stream = io.StringIO(content)
    reader = csv.DictReader(stream)
    _validate_headers(reader.fieldnames)

    report = ContactImportReport()
    new_rows: list[Contact] = []

    for row_index, row in enumerate(reader, start=2):  # header is row 1
        try:
            contact_in = _build_contact_create({**row, "_source": source})
            if contact_in is None:
                report.skipped_empty += 1
                continue
            if await _contact_exists(db, contact_in, project_id=project_id):
                report.skipped_duplicates += 1
                continue
            new_rows.append(Contact(**contact_in.model_dump(), project_id=project_id))
        except Exception as e:  # noqa: BLE001 — surface any row error
            report.errors.append({"row": row_index, "reason": str(e)[:200]})

    if new_rows:
        db.add_all(new_rows)
        await db.commit()
        report.inserted = len(new_rows)

    return report.to_dict()


async def bulk_upload_contacts_excel(
    db: AsyncSession,
    file_content: bytes,
    source: str = "excel_upload",
    project_id: int = 1,
) -> dict[str, Any]:
    """Import contacts from an .xlsx file."""
    stream = io.BytesIO(file_content)
    wb = openpyxl.load_workbook(stream)
    sheet = wb.active

    headers = [str(cell.value).strip() if cell.value is not None else "" for cell in sheet[1]]
    _validate_headers(headers)

    report = ContactImportReport()
    new_rows: list[Contact] = []

    for row_index, row in enumerate(
        sheet.iter_rows(min_row=2, values_only=True), start=2
    ):
        raw = dict(zip(headers, row))
        try:
            contact_in = _build_contact_create({**raw, "_source": source})
            if contact_in is None:
                report.skipped_empty += 1
                continue
            if await _contact_exists(db, contact_in, project_id=project_id):
                report.skipped_duplicates += 1
                continue
            new_rows.append(Contact(**contact_in.model_dump(), project_id=project_id))
        except Exception as e:  # noqa: BLE001
            report.errors.append({"row": row_index, "reason": str(e)[:200]})

    if new_rows:
        db.add_all(new_rows)
        await db.commit()
        report.inserted = len(new_rows)

    return report.to_dict()
