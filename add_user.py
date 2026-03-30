#!/usr/bin/env python3
"""Add a phone number to users.json whitelist."""
import sys
import os
import json

USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")


def main():
    if len(sys.argv) < 2:
        print("Usage: python add_user.py <phone>")
        sys.exit(1)

    phone = sys.argv[1]
    if not phone.startswith("+"):
        phone = "+" + phone

    users = {}
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
