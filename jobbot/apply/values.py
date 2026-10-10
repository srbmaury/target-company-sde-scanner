"""Format confirmed profile values for phone and numeric controls."""
import re
from decimal import Decimal


def meaningful_label(label):
    return bool(re.search(r"[A-Za-z]{2}", label or "")) and label != "(unlabelled field)"


def format_value(profile, field, label, value, has_dial_picker=False):
    text = str(value)
    if re.search(r"phone|mobile", label, re.I):
        national = re.sub(r"\D", "", str(profile.get("personal.phone", value)))
        dial = str(profile.get("personal.phone_country_code", ""))
        maxlen = field.get("maxlength", -1)
        # A box pre-filled with just "+91" (an input mask, as on Keka) keeps that prefix: type the national
        # number only, or "+91" + "+919876543210" is cut off at maxlength.
        prefilled = re.fullmatch(r"\s*\+?\d{1,4}\s*", str(field.get("value") or ""))
        if has_dial_picker or field.get("dial_code") or prefilled or (maxlen > 0 and maxlen <= len(national)):
            if maxlen > 0 and maxlen < len(national):
                raise ValueError("phone field cannot hold the complete national number")
            return national
        full = (dial + national) if dial else national
        if maxlen > 0 and len(full) > maxlen:
            return national  # a phone widget reserves its own prefix characters
        return full
    numeric = field.get("type") == "number" or field.get("inputmode") in ("numeric", "decimal")
    if numeric and re.search(r"salary|compensation|\bctc\b", label, re.I):
        key = "current" if re.search(r"current|present", label, re.I) else "expected"
        lpa = profile.get(f"work.{key}_ctc_lpa")
        if lpa is None:
            raise ValueError("missing confirmed numeric salary")
        unit = field.get("unit") or profile.get("automation.numeric_salary_unit", "")
        if re.search(r"lpa|lakh", label + " " + unit, re.I):
            return str(lpa)
        if re.search(r"\binr\b|rupees|₹|annual.*amount", label + " " + unit, re.I):
            return str(int(Decimal(str(lpa)) * 100000))
        raise ValueError("numeric salary needs a confirmed LPA or annual INR unit")
    if numeric:
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)(?:\s+(?:days?(?: notice)?|years?|months?))?\s*", text, re.I)
        if not match:
            raise ValueError("answer is not a numeric amount")
        return match[1]
    return text
