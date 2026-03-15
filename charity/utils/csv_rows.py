from __future__ import annotations

from typing import TypedDict

FORMAL_TITLE_TOKENS = {
    "mr",
    "mrs",
    "ms",
    "miss",
    "mx",
    "dr",
    "prof",
    "professor",
    "sir",
    "lady",
    "lord",
    "rev",
    "reverend",
    "fr",
    "father",
    "dame",
}


class RecipientNameParts(TypedDict):
    donor_name: str
    donor_title: str
    donor_first_name: str
    donor_last_name: str


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


def compose_recipient_name(
    *,
    title: str = "",
    first_name: str = "",
    last_name: str = "",
    default: str = "Donor",
) -> str:
    """Build a canonical donor name from structured parts only."""
    structured_name = " ".join(
        part.strip() for part in [title, first_name, last_name] if part and part.strip()
    ).strip()
    if structured_name:
        return structured_name

    return default


def extract_csv_recipient_parts(
    row: dict[str, str], *, default: str = "Donor"
) -> RecipientNameParts:
    """Extract structured donor name parts and a canonical display name from a CSV row."""
    donor_title = get_csv_row_value(row, "title", "salutation")
    donor_first_name = get_csv_row_value(
        row,
        "first name",
        "firstname",
        "first_name",
        "given name",
    )
    donor_last_name = get_csv_row_value(
        row,
        "surname",
        "last name",
        "lastname",
        "last_name",
        "family name",
    )
    return {
        "donor_name": compose_recipient_name(
            title=donor_title,
            first_name=donor_first_name,
            last_name=donor_last_name,
            default=default,
        ),
        "donor_title": donor_title,
        "donor_first_name": donor_first_name,
        "donor_last_name": donor_last_name,
    }


def build_csv_recipient_name(row: dict[str, str], *, default: str = "Donor") -> str:
    """Build the donor display name from flexible CSV columns."""
    return extract_csv_recipient_parts(row, default=default)["donor_name"]


def build_vdm_recipient_name(row: dict[str, str], *, default: str = "Donor") -> str:
    """Build the VDM recipient name from the structured CSV columns only."""
    return extract_csv_recipient_parts(row, default=default)["donor_name"]


def build_email_greeting_line(
    *,
    title: str = "",
    first_name: str = "",
    last_name: str = "",
    default: str = "Supporter",
) -> str:
    """Return an email greeting line without punctuation.

    Greeting rules:
    - If a first name is present, use "Dear <first name>"
    - Otherwise, use "Dear <title> <last name>" when a surname is present
    - Otherwise, ignore title-only data and use the default recipient greeting
    - Otherwise, use the default recipient greeting
    """
    cleaned_first_name = (first_name or "").strip()
    if cleaned_first_name:
        return f"Dear {cleaned_first_name}"

    cleaned_last_name = (last_name or "").strip()
    if cleaned_last_name:
        formal_name = " ".join(
            part.strip() for part in [title, cleaned_last_name] if part and part.strip()
        ).strip()
        return f"Dear {formal_name}"

    return f"Dear {default}"


def build_vdm_greeting_line(
    *,
    title: str = "",
    first_name: str = "",
    last_name: str = "",
    default: str = "Supporter",
) -> str:
    """Backward-compatible alias for VDM-specific call sites."""
    return build_email_greeting_line(
        title=title,
        first_name=first_name,
        last_name=last_name,
        default=default,
    )
