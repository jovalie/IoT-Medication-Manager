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
        ("Grandpa Albert", "Aspirin", "09:00"),
        ("Grandpa Hamad", "Vitamin C", "10:00"),
        ("Auntie Joan", "Lipitor", "20:00"),
    ]
    c.executemany("INSERT INTO patients (name, medicine, time_due) VALUES (?, ?, ?)", patients)
    
    # Get IDs
    c.execute("SELECT id, name FROM patients")
    patient_list = c.fetchall()
    
    # Insert logs for the entire month of November 2025
    year = 2025
    month = 11
    num_days = 30 # November has 30 days
    
    for pid, name in patient_list:
        print(f"Seeding November data for {name}...")
        for day in range(1, num_days + 1):
            log_date = f"{year}-{month:02d}-{day:02d}"
            
            # Create more varied statuses
            if (pid + day) % 5 == 0:
                status = "MISSED"
            elif (pid + day) % 13 == 0:
                status = "PENDING"
            else:
                status = "TAKEN"

            # Don't create future pending logs
            if datetime.strptime(log_date, "%Y-%m-%d").date() > datetime.now().date():
                continue

            # If today is in November, ensure today's status is PENDING
            if datetime.strptime(log_date, "%Y-%m-%d").date() == datetime.now().date():
                status = "PENDING"

            time_taken = None
            if status == "TAKEN":
                time_taken = "09:00:00"
            
            c.execute("""
                INSERT OR IGNORE INTO medication_logs (patient_id, date, time_taken, status, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (pid, log_date, time_taken, status, "Seeded data"))
            
    conn.commit()
    print("Dummy data for November seeded.")

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

