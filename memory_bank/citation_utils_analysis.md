# Analysis of `src/research_agent/utils/citation_utils.py`

## Purpose:

*   Provides low-level utility functions for normalizing and parsing author names, intended for use by `citation_styles.py`.

## Core Functions:

*   **`normalize_author_list(authors_input)`:**
    *   Takes varied author input (list of strings, list of dicts with 'name' key, None).
    *   Returns a standardized list of cleaned, non-empty author name strings.
*   **`parse_single_name(name)`:**
    *   Takes a single name string.
    *   Attempts to parse it into `(surname, initials_string)`.
    *   Handles "Surname, Given" and "Given Surname" formats.
    *   Includes logic for common multi-part surname prefixes (e.g., "van", "von").
    *   Returns `("Unknown", "")` on failure.

## Observations:

*   **Normalization:** `normalize_author_list` is crucial for handling inconsistent input formats.
*   **Parsing Heuristics:** `parse_single_name` uses reasonable logic for common Western name structures.
*   **Parsing Limitations:** Name parsing is complex; this function may not handle all global name formats, titles, or suffixes correctly.

## Identified Issues:

*   **Duplicated Code:** Contains definitions for `format_authors_harvard_ref_list` and `format_authors_harvard_intext`. These functions are **redundant** as they are also defined and used from `citation_styles.py`. They should be removed from this file.
