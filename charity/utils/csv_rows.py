from __future__ import annotations


def get_csv_row_value(row: dict[str, str], *candidate_headers: str) -> str:
    """Return the first non-empty value matching any candidate header."""
    for candidate in candidate_headers:
        normalized_candidate = candidate.strip().lower()
        for key, value in row.items():
            if key and key.strip().lower() == normalized_candidate:
                text = str(value).strip() if value is not None else ""
                if text:
                    return text
    return ""


def build_csv_recipient_name(row: dict[str, str], *, default: str = "Donor") -> str:
    """Build the donor display name from flexible CSV columns."""
    explicit_name = get_csv_row_value(row, "donor_name", "donor name", "name", "full name")
    if explicit_name:
        return explicit_name

    first_name = get_csv_row_value(row, "first name", "firstname", "first_name", "given name")
    if first_name:
        return first_name

    title = get_csv_row_value(row, "title", "salutation")
    surname = get_csv_row_value(
        row,
        "surname",
        "last name",
        "lastname",
        "last_name",
        "family name",
    )
    fallback_name = " ".join(part for part in [title, surname] if part).strip()

    return fallback_name or default
