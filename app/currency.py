from __future__ import annotations

import os
import re


def currency_from_env() -> tuple[str, str]:
    code = os.getenv("RL_CURRENCY", "INR").upper()
    symbols = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}
    symbol = symbols.get(code, f"{code} ")
    return code, symbol


def fix_currency(text: str, code: str, symbol: str) -> str:
    if code == "INR":
        # Replace $ / USD / Rs. / Rs before a number with INR symbol.
        pattern = r"(?:US\$|\$|USD\s?|Rs\.?\s?)(?=\d)"
        return re.sub(pattern, symbol, text)
    # For other currencies replace INR symbol or Rs. before a number.
    pattern = r"(?:₹|Rs\.?\s?)(?=\d)"
    return re.sub(pattern, symbol, text)


def format_money(amount: float, symbol: str) -> str:
    return f"{symbol}{amount:,.2f}"
