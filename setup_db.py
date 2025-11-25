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
        
        # Create patients table
        c.execute("""
            CREATE TABLE IF NOT EXISTS patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                medicine TEXT,
                time_due TEXT
            )
        """)
        
        # Create medication_logs table
        c.execute("""
            CREATE TABLE IF NOT EXISTS medication_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                time_taken TEXT,
                status TEXT NOT NULL CHECK(status IN ('TAKEN', 'MISSED', 'PENDING')),
                notes TEXT,
                FOREIGN KEY (patient_id) REFERENCES patients (id),
                UNIQUE(patient_id, date)
            )
        """)
        
        print("Tables created successfully.")
    except sqlite3.Error as e:
        print(f"Error creating tables: {e}")

def seed_data(conn):
    """Insert some dummy data for testing."""
    c = conn.cursor()
    
    # Check if we already have patients
    c.execute("SELECT count(*) FROM patients")
    if c.fetchone()[0] > 0:
        print("Data already exists, skipping seed.")
        return

    # Insert Patients
    patients = [
        ("Grandpa Joe", "Aspirin", "09:00"), 
        ("Grandma Sarah", "Vitamin C", "10:00"), 
        ("Uncle Bob", "Lipitor", "20:00")
    ]
    c.executemany("INSERT INTO patients (name, medicine, time_due) VALUES (?, ?, ?)", patients)
    
    # Get IDs
    c.execute("SELECT id, name FROM patients")
    patient_list = c.fetchall()
    
    # Insert logs for the last 7 days
    today = datetime.now().date()
    statuses = ["TAKEN", "TAKEN", "MISSED", "TAKEN", "PENDING", "TAKEN", "TAKEN"]
    
    for pid, name in patient_list:
        print(f"Seeding data for {name}...")
        for i in range(7):
            day_offset = 6 - i # 6 days ago to today
            log_date = (today - timedelta(days=day_offset)).strftime("%Y-%m-%d")
            status = statuses[i % len(statuses)]
            
            # For "PENDING" (which usually means today/future), let's make past days MISSED if pending
            if status == "PENDING" and day_offset > 0:
                status = "MISSED"
            
            time_taken = None
            if status == "TAKEN":
                time_taken = "09:00:00"
            
            c.execute("""
                INSERT INTO medication_logs (patient_id, date, time_taken, status, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (pid, log_date, time_taken, status, "Routine check"))
            
    conn.commit()
    print("Dummy data seeded.")

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

