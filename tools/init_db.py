#!/usr/bin/env python3
"""
Database initialization script
Run this once before starting any bots
"""

import sqlite3
import os

DATABASE_PATH = "trading_data.db"
MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "migrations")

def run_migrations():
    """Run all migration SQL files in order"""
    print("Initializing trading database...")

    # Get all migration files sorted by number
    migration_files = sorted([
        f for f in os.listdir(MIGRATIONS_DIR)
        if f.endswith('.sql')
    ])

    if not migration_files:
        print("No migration files found!")
        return

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    for migration_file in migration_files:
        migration_path = os.path.join(MIGRATIONS_DIR, migration_file)
        print(f"  Running {migration_file}...")

        with open(migration_path, 'r') as f:
            sql = f.read()

        try:
            cursor.executescript(sql)
            conn.commit()
            print(f"    Done")
        except Exception as e:
            print(f"    Error: {e}")
            # Continue with other migrations

    cursor.close()
    conn.close()

    print(f"\nDatabase initialized at: {DATABASE_PATH}")
    print("You can now start your bots!")

if __name__ == "__main__":
    run_migrations()
