from datetime import date

from fastapi import Response
from sqlalchemy.orm import Session

from src.constants.customer_attribute import ATTRIBUTES
from src.services import dim_service, privacy
from src.utils.csv_export import to_csv
from src.utils.pagination import pagination

DIM_COLUMNS = ("business_key", "full_name", "mobile", "org_code", "customer_level", "city", "channel",
               "valid_from", "valid_to", "version", "version_source")


def current(db: Session, search: str = "", level: str = "", page: int = 1, page_size: int = 20) -> dict:
    return dim_service.current_dims(db, search, level, pagination(page, page_size))


def as_of(db: Session, as_of_date: str, search: str = "", level: str = "", page: int = 1, page_size: int = 20) -> dict:
    try:
        parsed = date.fromisoformat(as_of_date)
    except ValueError:
        parsed = date.today()
    return dim_service.as_of_query(db, parsed, search, level, pagination(page, page_size))


def export_as_of(db: Session, as_of_date: str) -> Response:
    parsed = date.fromisoformat(as_of_date)
    rows = dim_service.as_of_rows(db, parsed)
    retracted = privacy.confirmed_retraction_keys(db)
    payload = []
    for row in rows:
        attributes = privacy.redact_if_retracted(row.attributes, row.business_key, retracted)
        payload.append(
            {
                "business_key": row.business_key,
                "full_name": attributes.get("full_name", ""),
                "mobile": attributes.get("mobile", ""),
                "org_code": attributes.get("org_code", ""),
                "customer_level": attributes.get("customer_level", ""),
                "city": attributes.get("city", ""),
                "channel": attributes.get("channel", ""),
                "valid_from": row.valid_from.isoformat(),
                "valid_to": row.valid_to.isoformat() if row.valid_to else "",
                "version": row.version,
                "version_source": row.version_source,
            }
        )
    csv_text = to_csv(DIM_COLUMNS, payload)
    filename = f"scdchain_asof_{parsed.isoformat()}.csv"
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def history(db: Session, business_key: str) -> dict:
    return dim_service.history(db, business_key)


def attributes() -> dict:
    return {"items": ATTRIBUTES}
