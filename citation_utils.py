import re

def normalize_author_list(authors_input):
    """
    Normalize various author input formats into a list of non-empty name strings.
    Handles:
      - None input or non-list input,
      - Lists containing strings or dictionaries (looking for a 'name' key).
    """
    if not isinstance(authors_input, list):
        return []
    cleaned_names = []
    for item in authors_input:
        name_str = None
        if isinstance(item, str):
            name_str = item.strip()
        elif isinstance(item, dict):
            name_value = item.get('name')
            if isinstance(name_value, str):
                name_str = name_value.strip()
        if name_str:
            cleaned_names.append(name_str)
    return cleaned_names

def parse_single_name(name: str) -> tuple[str, str]:
    """
    Parses a single name string into (surname, initials_string).
    Handles common Western formats reasonably well, but has limitations.
    Returns: (surname, initials) e.g., ("Smith", "J. R.") or ("Plato", "")
    """
    if not name:
        return "Unknown", ""

    name = name.strip()
    parts = name.split(',')  

    if len(parts) > 1:
        
        surname = parts[0].strip()
        given_names_part = parts[1].strip()
        initials = []
        for part in re.split(r'\s+|\.', given_names_part): 
            part = part.strip()
            if part and part[0].isalpha():  
                initials.append(part[0].upper() + ".")
        initials_str = " ".join(initials)  
    else:
        
        name_parts = name.split()
        if not name_parts:
            return "Unknown", ""

        potential_surname_parts = []
        given_name_parts = []
        surname_found = False

        
        idx = len(name_parts) - 1
        while idx >= 0:
            part = name_parts[idx]
            potential_surname_parts.insert(0, part)
            
            is_prefix = (idx > 0 and part.lower() in ["van", "von", "de", "di", "la", "le"])
           
            if not is_prefix or len(potential_surname_parts) > 1:
                
                if idx == 0 or (idx > 0 and name_parts[idx-1].lower() not in ["van", "von", "de", "di", "la", "le"]):
                    surname_found = True
                    break  
            idx -= 1

        if surname_found:
            surname = " ".join(potential_surname_parts)
            given_name_parts = name_parts[:idx]
        else:
            
            surname = name_parts[-1]
            given_name_parts = name_parts[:-1]

        initials = []
        for part in given_name_parts:
            part = part.strip().rstrip('.')  
            if part and part[0].isalpha():  
                initials.append(part[0].upper() + ".")
            elif part and len(part) > 1 and part.endswith('.'):
                initials.append(part.upper() if not part.endswith("..") else part[:-1].upper())
        initials_str = " ".join(initials)
    if not surname:
        surname = "Unknown"

    return surname, initials_str

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
