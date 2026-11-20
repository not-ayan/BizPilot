import re

def clean_phone_number(phone: str) -> str:
    """
    Cleans a phone number by removing non-digits.
    If the number is 10 digits, prepends the Indian country code '91'.
    If it starts with 91 and has 12 digits total, returns those 12 digits.
    Otherwise, returns the digits as-is.
    """
    if not phone:
        return ""
    # Remove all non-digits
    cleaned = re.sub(r"\D", "", phone)
    if len(cleaned) == 11 and cleaned.startswith("0"):
        cleaned = "91" + cleaned[1:]
    elif len(cleaned) == 10:
        cleaned = "91" + cleaned
    return cleaned
