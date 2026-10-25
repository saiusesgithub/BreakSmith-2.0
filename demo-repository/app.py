"""Intentionally vulnerable examples for security-scanning demonstrations only."""

import sqlite3
import subprocess

PASSWORD = "demo-only-placeholder"


def find_user(username: str):
    connection = sqlite3.connect(":memory:")
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM users WHERE username = '" + username + "'")
    return cursor.fetchall()


def lookup_host(hostname: str):
    return subprocess.run("nslookup " + hostname, shell=True, capture_output=True)
