import sqlite3
import os
from datetime import datetime, timedelta

DB_NAME = "medication_manager.db"

def create_connection():
    try:
        conn = sqlite3.connect(DB_NAME)
        return conn
    except sqlite3.Error as e:
        print(f"Error connecting to database: {e}")
        return None

def create_tables(conn):
    try:
        c = conn.cursor()
        
        # Drop old tables if they exist to ensure clean slate with new schema
        c.execute("DROP TABLE IF EXISTS medication_logs")
        c.execute("DROP TABLE IF EXISTS patients")
        c.execute("DROP TABLE IF EXISTS medications")

        # Create patients table
        c.execute("""
            CREATE TABLE IF NOT EXISTS patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
        """)
        
        # Create a new medications table
        c.execute("""
            CREATE TABLE IF NOT EXISTS medications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                medicine_name TEXT NOT NULL,
                time_due TEXT NOT NULL,
                FOREIGN KEY (patient_id) REFERENCES patients (id)
            )
        """)

        # Recreate medication_logs table to link to medications instead of patients
        c.execute("""
            CREATE TABLE IF NOT EXISTS medication_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                medication_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                time_taken TEXT,
                status TEXT NOT NULL CHECK(status IN ('TAKEN', 'MISSED', 'PENDING')),
                notes TEXT,
                FOREIGN KEY (medication_id) REFERENCES medications (id),
                UNIQUE(medication_id, date)
            )
        """)
        
        print("Tables created successfully with new schema.")
    except sqlite3.Error as e:
        print(f"Error creating tables: {e}")

def seed_data(conn):
    """Insert dummy data for testing with new schema."""
    c = conn.cursor()
    
    c.execute("SELECT count(*) FROM patients")
    if c.fetchone()[0] > 0:
        print("Data already exists, skipping seed.")
        return

    # Insert Patients
    patients = [("Grandpa Albert",), ("Grandpa Hamad",), ("Auntie Joan",)]
    c.executemany("INSERT INTO patients (name) VALUES (?)", patients)
    
    # Insert Medications for each patient
    c.execute("SELECT id, name FROM patients")
    patient_list = c.fetchall()
    
    medications_to_add = []
    for pid, name in patient_list:
        medications_to_add.append((pid, "Medication 1 (Aspirin)", "08:00"))
        medications_to_add.append((pid, "Medication 2 (Vitamin D)", "12:00"))
        medications_to_add.append((pid, "Medication 3 (Metformin)", "20:00"))
    
    c.executemany("INSERT INTO medications (patient_id, medicine_name, time_due) VALUES (?, ?, ?)", medications_to_add)

    # Seed logs for the entire month of November 2025
    c.execute("SELECT id, patient_id FROM medications")
    all_meds = c.fetchall()

    year = 2025
    month = 11
    num_days = 30 
    today_date = datetime.now().date()
    
    for med_id, patient_id in all_meds:
        for day in range(1, num_days + 1):
            log_date = f"{year}-{month:02d}-{day:02d}"
            log_date_obj = datetime.strptime(log_date, "%Y-%m-%d").date()

            if log_date_obj > today_date: continue

            if (med_id + day) % 6 == 0: status = "MISSED"
            else: status = "TAKEN"

            if log_date_obj == today_date: status = "PENDING"
            
            time_taken = "09:00:00" if status == "TAKEN" else None
            
            c.execute("""
                INSERT OR IGNORE INTO medication_logs (medication_id, date, time_taken, status, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (med_id, log_date, time_taken, status, "Seeded data"))
            
    conn.commit()
    print("Dummy data for November seeded with new schema.")


def main():
    if os.path.exists(DB_NAME):
        print(f"Database {DB_NAME} already exists.")
    
    conn = create_connection()
    if conn:
        create_tables(conn)
        seed_data(conn)
        conn.close()
        print("Database setup complete.")

if __name__ == "__main__":
    main()

