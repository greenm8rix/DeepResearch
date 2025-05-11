"""
Citation style formatters for different academic citation styles.
This module provides formatting functions for various citation styles including:
- Harvard
- APA
- MLA
- Chicago
- IEEE
"""

import re
from .citation_utils import normalize_author_list, parse_single_name

# Harvard Style Formatters
def format_authors_harvard_ref_list(authors_input):
    """
    Format a list of authors for a Harvard style reference list.
    Example outputs:
      "Smith, J. R. & Doe, J." or "Jones, A., Smith, B. & Brown, C."
    """
    cleaned_names = normalize_author_list(authors_input)
    if not cleaned_names:
        return "Author Unknown"
    formatted_authors = []
    for name in cleaned_names:
        surname, initials = parse_single_name(name)
        if surname == "Unknown":
            continue
        if initials:
            formatted_authors.append(f"{surname}, {initials}")
        else:
            formatted_authors.append(surname)
    if not formatted_authors:
        return "Author Unknown"
    num_authors = len(formatted_authors)
    if num_authors == 1:
        return formatted_authors[0]
    elif num_authors == 2:
        return f"{formatted_authors[0]} & {formatted_authors[1]}"
    else:
        return ", ".join(formatted_authors[:-1]) + " & " + formatted_authors[-1]

def format_authors_harvard_intext(authors_input, year):
    """
    Format authors and year for Harvard in-text citations.
    Example outputs:
      "(Smith & Doe, 2023)" or "(Jones et al., n.d.)"
    """
    year_str = str(year) if year and str(year).strip() else "n.d."
    cleaned_names = normalize_author_list(authors_input)
    if not cleaned_names:
        return f"(Author Unknown, {year_str})"
    surnames = []
    for name in cleaned_names:
        surname, _ = parse_single_name(name)
        if surname != "Unknown":
            surnames.append(surname)
    if not surnames:
        return f"(Author Unknown, {year_str})"
    num_authors = len(surnames)
    if num_authors == 1:
        author_str = surnames[0]
    elif num_authors == 2:
        author_str = f"{surnames[0]} & {surnames[1]}"
    else:
        author_str = f"{surnames[0]} et al."
    return f"({author_str}, {year_str})"

def format_harvard_reference(authors_list, year, title, publication_venue):
    """Format a complete Harvard style reference entry."""
    authors_str = format_authors_harvard_ref_list(authors_list)
    year_str = str(year) if year else "n.d."
    title_str = f"*{title.strip()}*" if title else "*[Title Not Available]*"
    
    ref_str = f"{authors_str} ({year_str}). {title_str}"
    if publication_venue:
        ref_str += f" {publication_venue.strip()}."
    else:
        ref_str += "."
    
    return ref_str

# APA Style Formatters
def format_authors_apa_ref_list(authors_input):
    """
    Format a list of authors for an APA style reference list.
    Example outputs:
      "Smith, J. R., & Doe, J." or "Jones, A., Smith, B., & Brown, C."
    """
    cleaned_names = normalize_author_list(authors_input)
    if not cleaned_names:
        return "Author Unknown"
    formatted_authors = []
    for name in cleaned_names:
        surname, initials = parse_single_name(name)
        if surname == "Unknown":
            continue
        if initials:
            formatted_authors.append(f"{surname}, {initials}")
        else:
            formatted_authors.append(surname)
    if not formatted_authors:
        return "Author Unknown"
    num_authors = len(formatted_authors)
    if num_authors == 1:
        return formatted_authors[0]
    elif num_authors == 2:
        return f"{formatted_authors[0]}, & {formatted_authors[1]}"
    else:
        return ", ".join(formatted_authors[:-1]) + ", & " + formatted_authors[-1]

def format_authors_apa_intext(authors_input, year):
    """
    Format authors and year for APA in-text citations.
    Example outputs:
      "(Smith & Doe, 2023)" or "(Jones et al., n.d.)"
    """
    year_str = str(year) if year and str(year).strip() else "n.d."
    cleaned_names = normalize_author_list(authors_input)
    if not cleaned_names:
        return f"(Author Unknown, {year_str})"
    surnames = []
    for name in cleaned_names:
        surname, _ = parse_single_name(name)
        if surname != "Unknown":
            surnames.append(surname)
    if not surnames:
        return f"(Author Unknown, {year_str})"
    num_authors = len(surnames)
    if num_authors == 1:
        author_str = surnames[0]
    elif num_authors == 2:
        author_str = f"{surnames[0]} & {surnames[1]}"
    else:
        author_str = f"{surnames[0]} et al."
    return f"({author_str}, {year_str})"

def format_apa_reference(authors_list, year, title, publication_venue):
    """Format a complete APA style reference entry."""
    authors_str = format_authors_apa_ref_list(authors_list)
    year_str = str(year) if year else "n.d."
    title_str = title.strip() if title else "[Title Not Available]"
    
    ref_str = f"{authors_str} ({year_str}). {title_str}"
    if publication_venue:
        ref_str += f". {publication_venue.strip()}"
    else:
        ref_str += "."
    
    return ref_str

# MLA Style Formatters
def format_authors_mla_ref_list(authors_input):
    """
    Format a list of authors for an MLA style reference list.
    Example outputs:
      "Smith, John R." or "Jones, Alice, et al."
    """
    cleaned_names = normalize_author_list(authors_input)
    if not cleaned_names:
        return "Author Unknown"
    
    if len(cleaned_names) == 1:
        surname, initials = parse_single_name(cleaned_names[0])
        if surname == "Unknown":
            return "Author Unknown"
        return f"{surname}, {initials.replace('.', '')}" if initials else surname
    else:
        # First author reversed, then "et al."
        surname, initials = parse_single_name(cleaned_names[0])
        if surname == "Unknown":
            return "Author Unknown"
        return f"{surname}, {initials.replace('.', '')} et al." if initials else f"{surname} et al."

def format_authors_mla_intext(authors_input):
    """
    Format authors for MLA in-text citations (no year).
    Example outputs:
      "(Smith)" or "(Jones et al.)"
    """
    cleaned_names = normalize_author_list(authors_input)
    if not cleaned_names:
        return "(Author Unknown)"
    surnames = []
    for name in cleaned_names:
        surname, _ = parse_single_name(name)
        if surname != "Unknown":
            surnames.append(surname)
    if not surnames:
        return "(Author Unknown)"
    num_authors = len(surnames)
    if num_authors == 1:
        author_str = surnames[0]
    else:
        author_str = f"{surnames[0]} et al."
    return f"({author_str})"

def format_mla_reference(authors_list, year, title, publication_venue):
    """Format a complete MLA style reference entry."""
    authors_str = format_authors_mla_ref_list(authors_list)
    title_str = f'"{title.strip()}"' if title else '"[Title Not Available]"'
    
    ref_str = f"{authors_str}. {title_str}"
    if publication_venue:
        ref_str += f", {publication_venue.strip()}"
    if year:
        ref_str += f", {year}"
    ref_str += "."
    
    return ref_str

# Chicago Style Formatters
def format_authors_chicago_ref_list(authors_input):
    """
    Format a list of authors for a Chicago style reference list.
    Example outputs:
      "Smith, John R." or "Jones, Alice, Smith, Bob, and Brown, Carol"
    """
    cleaned_names = normalize_author_list(authors_input)
    if not cleaned_names:
        return "Author Unknown"
    formatted_authors = []
    for name in cleaned_names:
        surname, initials = parse_single_name(name)
        if surname == "Unknown":
            continue
        if initials:
            formatted_authors.append(f"{surname}, {initials}")
        else:
            formatted_authors.append(surname)
    if not formatted_authors:
        return "Author Unknown"
    num_authors = len(formatted_authors)
    if num_authors == 1:
        return formatted_authors[0]
    elif num_authors == 2:
        return f"{formatted_authors[0]} and {formatted_authors[1]}"
    else:
        return ", ".join(formatted_authors[:-1]) + ", and " + formatted_authors[-1]

def format_authors_chicago_intext(authors_input, year):
    """
    Format authors and year for Chicago in-text citations.
    Example outputs:
      "(Smith 2023)" or "(Jones et al. n.d.)"
    """
    year_str = str(year) if year and str(year).strip() else "n.d."
    cleaned_names = normalize_author_list(authors_input)
    if not cleaned_names:
        return f"(Author Unknown {year_str})"
    surnames = []
    for name in cleaned_names:
        surname, _ = parse_single_name(name)
        if surname != "Unknown":
            surnames.append(surname)
    if not surnames:
        return f"(Author Unknown {year_str})"
    num_authors = len(surnames)
    if num_authors == 1:
        author_str = surnames[0]
    elif num_authors == 2:
        author_str = f"{surnames[0]} and {surnames[1]}"
    else:
        author_str = f"{surnames[0]} et al."
    return f"({author_str} {year_str})"

def format_chicago_reference(authors_list, year, title, publication_venue):
    """Format a complete Chicago style reference entry."""
    authors_str = format_authors_chicago_ref_list(authors_list)
    year_str = str(year) if year else "n.d."
    title_str = f'"{title.strip()}"' if title else '"[Title Not Available]"'
    
    ref_str = f"{authors_str}. {title_str}"
    if publication_venue:
        ref_str += f". {publication_venue.strip()}"
    ref_str += f", {year_str}."
    
    return ref_str

# IEEE Style Formatters
def format_authors_ieee_ref_list(authors_input):
    """
    Format a list of authors for an IEEE style reference list.
    Example outputs:
      "J. R. Smith" or "A. Jones, B. Smith and C. Brown"
    """
    cleaned_names = normalize_author_list(authors_input)
    if not cleaned_names:
        return "Author Unknown"
    formatted_authors = []
    for name in cleaned_names:
        surname, initials = parse_single_name(name)
        if surname == "Unknown":
            continue
        if initials:
            formatted_authors.append(f"{initials} {surname}")
        else:
            formatted_authors.append(surname)
    if not formatted_authors:
        return "Author Unknown"
    num_authors = len(formatted_authors)
    if num_authors == 1:
        return formatted_authors[0]
    elif num_authors == 2:
        return f"{formatted_authors[0]} and {formatted_authors[1]}"
    else:
        return ", ".join(formatted_authors[:-1]) + ", and " + formatted_authors[-1]

def format_authors_ieee_intext(authors_input):
    """
    Format authors for IEEE in-text citations (uses numbers).
    Example outputs:
      "[1]" (IEEE uses numbered references, not author names in text)
    """
    # IEEE uses numbered references, so this is a placeholder
    # The actual number will be determined by the reference list order
    return "[#]"

def format_ieee_reference(authors_list, year, title, publication_venue):
    """Format a complete IEEE style reference entry."""
    authors_str = format_authors_ieee_ref_list(authors_list)
    title_str = f'"{title.strip()}"' if title else '"[Title Not Available]"'
    
    ref_str = f"{authors_str}, {title_str}"
    if publication_venue:
        ref_str += f", {publication_venue.strip()}"
    if year:
        ref_str += f", {year}"
    ref_str += "."
    
    return ref_str

# Web Source Formatters for different citation styles
def format_web_source_harvard(author_org, title, url, access_date):
    """Format a web source in Harvard style."""
    author_str = author_org if author_org and author_org != "Unknown Author/Org" else "Web Source"
    title_str = f"*{title.strip()}*" if title and title != "Untitled Page" else "*[Title Not Available]*"
    return f"{author_str}. (Accessed {access_date}). {title_str}. Retrieved from {url}"

def format_web_source_apa(author_org, title, url, access_date):
    """Format a web source in APA style."""
    author_str = author_org if author_org and author_org != "Unknown Author/Org" else "Web Source"
    title_str = title.strip() if title and title != "Untitled Page" else "[Title Not Available]"
    return f"{author_str}. ({access_date}). {title_str}. Retrieved from {url}"

def format_web_source_mla(author_org, title, url, access_date):
    """Format a web source in MLA style."""
    author_str = author_org if author_org and author_org != "Unknown Author/Org" else "Web Source"
    title_str = f'"{title.strip()}"' if title and title != "Untitled Page" else '"[Title Not Available]"'
    return f"{author_str}. {title_str}. {access_date}, {url}."

def format_web_source_chicago(author_org, title, url, access_date):
    """Format a web source in Chicago style."""
    author_str = author_org if author_org and author_org != "Unknown Author/Org" else "Web Source"
    title_str = f'"{title.strip()}"' if title and title != "Untitled Page" else '"[Title Not Available]"'
    return f"{author_str}. {title_str}. Accessed {access_date}. {url}."

def format_web_source_ieee(author_org, title, url, access_date):
    """Format a web source in IEEE style."""
    author_str = author_org if author_org and author_org != "Unknown Author/Org" else "Web Source"
    title_str = f'"{title.strip()}"' if title and title != "Untitled Page" else '"[Title Not Available]"'
    return f"{author_str}, {title_str}. [Online]. Available: {url}. Accessed: {access_date}."

# Factory functions to get formatters based on citation style
def get_citation_formatters(citation_style="harvard"):
    """
    Get the appropriate citation formatters for the specified style.
    
    Args:
        citation_style (str): The citation style to use. 
                             Options: "harvard", "apa", "mla", "chicago", "ieee"
    
    Returns:
        dict: A dictionary containing formatter functions for the specified style
    """
    citation_style = citation_style.lower()
    
    formatters = {
        "harvard": {
            "ref_list": format_authors_harvard_ref_list,
            "intext": format_authors_harvard_intext,
            "reference": format_harvard_reference,
            "web_source": format_web_source_harvard
        },
        "apa": {
            "ref_list": format_authors_apa_ref_list,
            "intext": format_authors_apa_intext,
            "reference": format_apa_reference,
            "web_source": format_web_source_apa
        },
        "mla": {
            "ref_list": format_authors_mla_ref_list,
            "intext": format_authors_mla_intext,
            "reference": format_mla_reference,
            "web_source": format_web_source_mla
        },
        "chicago": {
            "ref_list": format_authors_chicago_ref_list,
            "intext": format_authors_chicago_intext,
            "reference": format_chicago_reference,
            "web_source": format_web_source_chicago
        },
        "ieee": {
            "ref_list": format_authors_ieee_ref_list,
            "intext": format_authors_ieee_intext,
            "reference": format_ieee_reference,
            "web_source": format_web_source_ieee
        }
    }
    
    # Default to Harvard if style not found
    return formatters.get(citation_style, formatters["harvard"])
