import sqlite3
import os

DB_PATH = 'database.db'

def fix_orphans():
    if not os.path.exists(DB_PATH):
        print("Database does not exist.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get the first user
    cursor.execute("SELECT id, username FROM users ORDER BY id LIMIT 1")
    user = cursor.fetchone()

    if not user:
        print("No users found in database. Cannot assign orphans.")
        conn.close()
        return

    user_id, username = user
    print(f"Assigning orphaned documents to user: {username} (ID: {user_id})")

    # Update orphaned documents
    cursor.execute("UPDATE documents SET user_id = ? WHERE user_id IS NULL", (user_id,))
    rows_affected = cursor.rowcount

    conn.commit()
    conn.close()

    print(f"Successfully updated {rows_affected} documents.")

if __name__ == '__main__':
    fix_orphans()
