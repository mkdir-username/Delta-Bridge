#!/usr/bin/env python3
"""Add or update a user in users.json."""
import sys
import os
import json
import getpass

import bcrypt

USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")


def main():
    if len(sys.argv) < 2:
        print("Usage: python add_user.py <username>")
        sys.exit(1)

    username = sys.argv[1]

    users = {}
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE) as f:
            users = json.load(f)

    if username in users:
        answer = input(f"User '{username}' exists. Overwrite? [y/N] ")
        if answer.lower() != "y":
            print("Cancelled.")
            sys.exit(0)

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm: ")
    if password != confirm:
        print("Passwords don't match.")
        sys.exit(1)

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    users[username] = {"password_hash": hashed}

    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

    print(f"User '{username}' saved to {USERS_FILE}")


if __name__ == "__main__":
    main()
