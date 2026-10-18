"""
database.py
------------
Minimal SQLite persistence layer for the C.G.P.I Calculator.

Design: ONE table. Each row is a semester. The subjects for that
semester are stored as a JSON string in `subjects_json`. SGPI and
total_credits are stored too, but they are a CACHE -- always
recomputed by calculations.py from the subjects whenever they change.
The database's job is only to save/load; it never does math.

All queries use parameterized placeholders (?) -- never raw string
formatting -- to avoid SQL injection.
"""

import sqlite3
import json
import os
from decimal import Decimal

DB_PATH = os.path.join(os.path.dirname(__file__), "cgpi.db")


def _json_default(obj):
    """json.dumps doesn't know how to serialize Decimal (used throughout
    calculations.py for accuracy). Convert it to float only at this last
    step, right before writing to storage -- the calculation engine itself
    never touches float."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def get_connection():
    """Open a connection with foreign keys enforced and rows as dicts."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the semesters table if it doesn't already exist.
    Safe to call every time the app starts."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS semesters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester_number INTEGER NOT NULL,
            subjects_json TEXT NOT NULL,
            total_credits REAL NOT NULL,
            sgpi REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def save_semester(semester_number, subjects, total_credits, sgpi, semester_id=None):
    """
    Save a new semester, or update an existing one if semester_id is given.
    `subjects` is a list of cleaned subject dicts (from calculate_sgpi rows),
    stored as JSON text.
    Returns the row id of the saved semester.
    """
    subjects_json = json.dumps(subjects, default=_json_default)
    conn = get_connection()

    if semester_id is None:
        cursor = conn.execute(
            "INSERT INTO semesters (semester_number, subjects_json, total_credits, sgpi) "
            "VALUES (?, ?, ?, ?)",
            (semester_number, subjects_json, float(total_credits), float(sgpi)),
        )
        new_id = cursor.lastrowid
    else:
        conn.execute(
            "UPDATE semesters SET semester_number = ?, subjects_json = ?, "
            "total_credits = ?, sgpi = ? WHERE id = ?",
            (semester_number, subjects_json, float(total_credits), float(sgpi), semester_id),
        )
        new_id = semester_id

    conn.commit()
    conn.close()
    return new_id


def get_all_semesters():
    """Return all semesters, ordered by semester_number, with subjects
    parsed back into Python lists."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM semesters ORDER BY semester_number ASC"
    ).fetchall()
    conn.close()

    result = []
    for row in rows:
        result.append({
            "id": row["id"],
            "semester_number": row["semester_number"],
            "subjects": json.loads(row["subjects_json"]),
            "total_credits": row["total_credits"],
            "sgpi": row["sgpi"],
        })
    return result


def get_semester(semester_id):
    """Return one semester by id, or None if not found."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM semesters WHERE id = ?", (semester_id,)
    ).fetchone()
    conn.close()

    if row is None:
        return None

    return {
        "id": row["id"],
        "semester_number": row["semester_number"],
        "subjects": json.loads(row["subjects_json"]),
        "total_credits": row["total_credits"],
        "sgpi": row["sgpi"],
    }


def delete_semester(semester_id):
    """Delete a semester by id."""
    conn = get_connection()
    conn.execute("DELETE FROM semesters WHERE id = ?", (semester_id,))
    conn.commit()
    conn.close()
