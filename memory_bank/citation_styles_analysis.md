# Analysis of `src/research_agent/utils/citation_styles.py`

## Purpose:

*   Provides functions to format in-text citations and reference list entries according to specific academic styles (Harvard, APA, MLA, Chicago, IEEE).

## Key Components:

1.  **Helper Imports:** Imports `normalize_author_list` and `parse_single_name` from `./citation_utils.py` for basic name processing.
2.  **Style-Specific Functions:** For each style (Harvard, APA, MLA, Chicago, IEEE), defines functions for:
    *   `format_authors_*_ref_list`: Formats author lists for bibliography (handles "et al.", "&"/"and").
    *   `format_authors_*_intext`: Formats author/year for in-text citations (handles "et al.", "n.d."). MLA omits year. IEEE returns `[#]`.
    *   `format_*_reference`: Formats a full academic reference entry (authors, year, title, venue). Applies style-specific punctuation/formatting.
    *   `format_web_source_*`: Formats a full reference entry for a web source (author/org, title, URL, access date).
3.  **`get_citation_formatters(citation_style)`:**
    *   A factory function returning a dictionary of the four relevant formatting functions (`ref_list`, `intext`, `reference`, `web_source`) based on the input `citation_style` string.
    *   Defaults to Harvard style if the requested style is unknown.

## Observations:

*   **Modular Design:** Clearly separates formatting logic for each style.
*   **Style Coverage:** Implements basic formatting for five common styles.
*   **Dependency:** Relies on `citation_utils.py` for initial name parsing.
*   **IEEE Handling:** Correctly uses `[#]` placeholder for IEEE in-text citations.
*   **Web Source Formatting:** Includes dedicated functions for web sources.
*   **Clean Interface:** `get_citation_formatters` provides a simple way for other modules to access the correct formatting logic.

## Potential Issues:

*   **Rule Completeness:** Citation styles are complex. This implementation covers common cases but might not handle all specific rules (e.g., different source types like books, reports, specific punctuation, DOI handling) according to official guides.
*   **Dependency Risk:** Correctness depends heavily on the assumed functionality of `citation_utils.py`.
*   **Input Assumptions:** Assumes reasonable input for author names, titles, etc. (though downstream filtering in `compilation.py` helps for web sources).
