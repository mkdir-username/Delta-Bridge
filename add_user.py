#!/usr/bin/env python3
"""Add a phone number to users.json whitelist."""

from __future__ import annotations

import sys
import os
import json
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "webui"))
import auth

USERS_FILE: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")


def main() -> None:
    if "--setup-totp" in sys.argv:
        idx = sys.argv.index("--setup-totp")
        if idx + 1 >= len(sys.argv):
            print("Usage: python add_user.py --setup-totp +7XXXXXXXXXX")
            sys.exit(1)
        phone = sys.argv[idx + 1]
        import pyotp

        auth.load_whitelist()
        if auth.get_user_totp_secret(phone):
            print(f"TOTP already configured for {phone}")
            sys.exit(1)
        secret = pyotp.random_base32()
        uri = pyotp.TOTP(secret).provisioning_uri(name=phone, issuer_name="IoE")
        print(f"Secret: {secret}")
        print(f"URI: {uri}")
        print("Add to Authenticator, then enter code to verify:")
        code = input("Code: ").strip()
        if not pyotp.TOTP(secret).verify(code, valid_window=1):
            print("Wrong code. Secret NOT saved.")
            sys.exit(1)
        auth.set_user_totp_secret(phone, secret)
        print("Verified. Saved to users.json")
        sys.exit(0)

    if len(sys.argv) < 2:
        print("Usage: python add_user.py <phone>")
        sys.exit(1)

    phone = sys.argv[1]
    if not phone.startswith("+"):
        phone = "+" + phone

    users: dict[str, Any] = {}
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE) as f:
            users = json.load(f)

    if phone in users:
        print(f"Phone {phone} already in whitelist.")
        sys.exit(0)

    users[phone] = {}

    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

    print(f"Added {phone} to {USERS_FILE}")


if __name__ == "__main__":
    main()
