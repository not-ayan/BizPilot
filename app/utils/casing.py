import re

def to_title_case(name: str) -> str:
    """
    Capitalizes the first letter of each word in a name/product.
    Preserves words that are fully uppercase (e.g., LED, GST, RR) to avoid breaking acronyms.
    Also automatically capitalizes common acronyms (e.g., led -> LED, gst -> GST).
    """
    if not name:
        return ""
    acronyms = {"LED", "GST", "RR", "TV", "AC", "USB", "HDMI", "DTH", "FM", "AM", "DC", "AC/DC"}
    words = name.split()
    result_words = []
    for word in words:
        upper_word = word.upper()
        if upper_word in acronyms:
            result_words.append(upper_word)
        elif word.isupper() and len(word) > 1:
            result_words.append(word)
        else:
            result_words.append(word[0].upper() + word[1:].lower() if len(word) > 0 else word)
    return " ".join(result_words)

def capitalize_sentences(text: str) -> str:
    """
    Capitalizes the first letter of each sentence in a text block, preserving other casings.
    Sentences are assumed to start at the beginning of the text, after standard sentence-ending punctuation (. ! ?) followed by space/newlines, or after newlines.
    """
    if not text:
        return ""
    
    def repl(match):
        return match.group(1) + match.group(2).upper()
    
    return re.sub(r'(^|[.!?]\s+|\n\s*)([a-zA-Z])', repl, text)

def format_customer_message(text: str) -> str:
    """
    Utility wrapper to ensure general customer messages are properly sentence-cased.
    """
    return capitalize_sentences(text)

def calculate_remaining_warranty(sale_date, warranty_info: str) -> str:
    """
    Calculates remaining warranty from sale date based on warranty string.
    Supports years (e.g. 1 Year) and months (e.g. 6 Months).
    Returns 'Expired', 'No Warranty', or 'Active (duration left)'.
    """
    if not warranty_info or "no" in warranty_info.lower() or "none" in warranty_info.lower() or "n/a" in warranty_info.lower():
        return "No Warranty"
    
    import re
    match = re.search(r"(\d+)\s*(year|yr|month|mon|mth)", warranty_info.lower())
    if not match:
        return f"Active ({warranty_info})"
    
    num = int(match.group(1))
    unit = match.group(2)
    
    from datetime import date
    
    # Calculate expiry date
    year_add = 0
    month_add = 0
    if "year" in unit or "yr" in unit:
        year_add = num
    else:
        month_add = num
        
    exp_year = sale_date.year + year_add
    exp_month = sale_date.month + month_add
    while exp_month > 12:
        exp_year += 1
        exp_month -= 12
        
    # Handle end of month boundary
    exp_day = sale_date.day
    import calendar
    _, max_days = calendar.monthrange(exp_year, exp_month)
    if exp_day > max_days:
        exp_day = max_days
        
    expiry_date = date(exp_year, exp_month, exp_day)
    today = date.today()
    
    if today > expiry_date:
        return "Expired"
    if today == expiry_date:
        return "Active (Expires today)"

    def _add_years(d, y):
        try:
            return d.replace(year=d.year + y)
        except ValueError:
            return d.replace(year=d.year + y, day=28)

    def _add_months(d, m):
        y = d.year + (d.month + m - 1) // 12
        new_m = (d.month + m - 1) % 12 + 1
        _, max_d = calendar.monthrange(y, new_m)
        return date(y, new_m, min(d.day, max_d))

    curr = today
    years = 0
    while True:
        nxt = _add_years(curr, 1)
        if nxt <= expiry_date:
            curr = nxt
            years += 1
        else:
            break

    months = 0
    while True:
        nxt = _add_months(curr, 1)
        if nxt <= expiry_date:
            curr = nxt
            months += 1
        else:
            break

    days = (expiry_date - curr).days
        
    parts = []
    if years > 0:
        parts.append(f"{years} year" + ("s" if years > 1 else ""))
    if months > 0:
        parts.append(f"{months} month" + ("s" if months > 1 else ""))
    if days > 0:
        parts.append(f"{days} day" + ("s" if days > 1 else ""))
        
    if not parts:
        return "Active (Expires today)"
        
    if len(parts) == 1:
        duration_str = parts[0]
    elif len(parts) == 2:
        duration_str = f"{parts[0]} and {parts[1]}"
    else:
        duration_str = f"{parts[0]}, {parts[1]}, and {parts[2]}"
        
    return f"Active ({duration_str} left)"

