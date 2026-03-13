from __future__ import annotations

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
    if fallback_name:
        return fallback_name

    explicit_name = get_csv_row_value(row, "donor_name", "donor name", "name", "full name")
    if explicit_name:
        return explicit_name

    return default


def build_vdm_recipient_name(row: dict[str, str], *, default: str = "Donor") -> str:
    """Build the VDM recipient name from the structured CSV columns only."""
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


def build_email_greeting_line(name: str, *, default: str = "Supporter") -> str:
    """Return an email greeting line without punctuation.

    Friendly first-name greetings keep the "Dear" prefix, while formal
    title-based greetings render as "Ms Smith" instead of "Dear Ms Smith".
    """
    cleaned_name = (name or "").strip() or default
    first_token = cleaned_name.split()[0].rstrip(".").lower() if cleaned_name.split() else ""
    if first_token in FORMAL_TITLE_TOKENS:
        return cleaned_name
    return f"Dear {cleaned_name}"


def build_vdm_greeting_line(name: str, *, default: str = "Supporter") -> str:
    """Backward-compatible alias for VDM-specific call sites."""
    return build_email_greeting_line(name, default=default)
