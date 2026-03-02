# charity/utils/filenames.py
import re


def safe_filename(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^\w\d\-_.]+", "_", s)
    return s
