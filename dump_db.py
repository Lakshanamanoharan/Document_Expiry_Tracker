import sqlite3
import os

DB_PATH = 'database.db'

def dump_db():
    if not os.path.exists(DB_PATH):
        print("Database does not exist.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("--- USERS ---")
    cursor.execute("SELECT id, username FROM users")
    for row in cursor.fetchall():
        print(dict(row))

    print("\n--- DOCUMENTS ---")
    cursor.execute("SELECT * FROM documents")
    for row in cursor.fetchall():
        print(dict(row))

    conn.close()

if __name__ == '__main__':
    dump_db()
