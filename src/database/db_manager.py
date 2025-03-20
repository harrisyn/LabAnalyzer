import sqlite3
import os
from datetime import datetime
from pathlib import Path

class DatabaseManager:
    """
    Handle database operations for the analyzer data
    """
    def __init__(self, db_file=None):
        if db_file is None:
            db_file = Path(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'astm_data.db')
        self.db_file = db_file
        self.conn = None
        self.init_db()
        
    def init_db(self):
        """Initialize the database with required tables if they don't exist"""
        try:
            self.conn = sqlite3.connect(self.db_file, check_same_thread=False)
            cursor = self.conn.cursor()
            
            # Create patients table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS patients (
                    id INTEGER PRIMARY KEY,
                    patient_id TEXT,
                    sample_id TEXT,
                    name TEXT,
                    dob DATE,
                    sex TEXT,
                    physician TEXT,
                    raw_data TEXT,
                    sync_status TEXT DEFAULT 'local',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create results table with sync_status field
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS results (
                    id INTEGER PRIMARY KEY,
                    patient_id INTEGER,
                    test_code TEXT,
                    value REAL,
                    unit TEXT,
                    flags TEXT,
                    timestamp DATETIME,
                    sync_status TEXT DEFAULT 'local',
                    sequence TEXT,
                    FOREIGN KEY(patient_id) REFERENCES patients(id)
                )
            ''')

            # Check if columns exist, add them if they don't
            cursor.execute("PRAGMA table_info(patients)")
            columns = {info[1] for info in cursor.fetchall()}
            
            if 'raw_data' not in columns:
                cursor.execute('ALTER TABLE patients ADD COLUMN raw_data TEXT')
                self.log_info("Added raw_data column to patients table")
                
            if 'sync_status' not in columns:
                cursor.execute('ALTER TABLE patients ADD COLUMN sync_status TEXT DEFAULT "local"')
                self.log_info("Added sync_status column to patients table")
                
            if 'sample_id' not in columns:
                cursor.execute('ALTER TABLE patients ADD COLUMN sample_id TEXT')
                self.log_info("Added sample_id column to patients table")

            # Check if sequence column exists in results table
            cursor.execute("PRAGMA table_info(results)")
            result_columns = {info[1] for info in cursor.fetchall()}
            
            if 'sequence' not in result_columns:
                cursor.execute('ALTER TABLE results ADD COLUMN sequence TEXT')
                self.log_info("Added sequence column to results table")

            # Create logs table for application events
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    level TEXT,
                    source TEXT,
                    message TEXT
                )
            ''')

            # Create sync history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sync_history (
                    id INTEGER PRIMARY KEY,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status TEXT,
                    message TEXT,
                    results_synced INTEGER DEFAULT 0
                )
            ''')
            
            self.conn.commit()
        except sqlite3.Error as e:
            print(f"Database initialization error: {e}")
            if self.conn:
                self.conn.rollback()
            raise
            
    def _ensure_connection(self):
        """Ensure database connection is active"""
        if not self.conn:
            self.conn = sqlite3.connect(self.db_file, check_same_thread=False)
        return self.conn
            
    def close(self):
        """Close the database connection"""
        if self.conn:
            try:
                self.conn.close()
            except sqlite3.Error as e:
                print(f"Error closing database: {e}")
            finally:
                self.conn = None
            
    def __enter__(self):
        """Context manager entry"""
        self._ensure_connection()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()
    
    def add_patient(self, patient_id, name, dob, sex, physician, raw_data=None, sample_id=None):
        """
        Add a patient to the database with optional raw data and sample ID.
        If an existing patient is found, update their information.
        
        If patient_id is empty but sample_id is provided, use sample_id as patient_id
        """
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()

            # Check for existing patient first by ID
            existing_patient_id = None
            
            # If updating an existing patient directly by database ID
            if isinstance(patient_id, int):
                existing_patient_id = patient_id
            else:
                # First try to find by patient_id if provided
                if patient_id:
                    cursor.execute('SELECT id FROM patients WHERE patient_id = ?', (patient_id,))
                    result = cursor.fetchone()
                    if result:
                        existing_patient_id = result[0]
                
                # If no match found and sample_id is provided, try to find by sample_id
                if not existing_patient_id and sample_id:
                    cursor.execute('SELECT id FROM patients WHERE sample_id = ?', (sample_id,))
                    result = cursor.fetchone()
                    if result:
                        existing_patient_id = result[0]
                    elif not patient_id:
                        # If no patient_id was provided and we still don't have a match,
                        # use sample_id as patient_id for a new record
                        patient_id = sample_id

            # If we found an existing patient, update it
            if existing_patient_id:
                # Build dynamic update query based on provided fields
                update_fields = []
                update_values = []
                
                if name is not None:
                    update_fields.append("name = ?")
                    update_values.append(name)
                    
                if dob is not None:
                    update_fields.append("dob = ?")
                    update_values.append(dob)
                    
                if sex is not None:
                    update_fields.append("sex = ?")
                    update_values.append(sex)
                    
                if physician is not None:
                    update_fields.append("physician = ?")
                    update_values.append(physician)
                    
                if raw_data is not None:
                    update_fields.append("raw_data = ?")
                    update_values.append(raw_data)
                    
                if sample_id is not None:
                    update_fields.append("sample_id = ?")
                    update_values.append(sample_id)
                
                # Only update if we have fields to update
                if update_fields:
                    # Add patient ID to values for the WHERE clause
                    update_values.append(existing_patient_id)
                    
                    # Construct and execute the update query
                    update_query = f"UPDATE patients SET {', '.join(update_fields)} WHERE id = ?"
                    cursor.execute(update_query, update_values)
                    conn.commit()
                    
                return existing_patient_id
            else:
                # Insert new patient
                cursor.execute('''
                    INSERT INTO patients 
                    (patient_id, sample_id, name, dob, sex, physician, raw_data, sync_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'local')
                ''', (patient_id, sample_id, name, dob, sex, physician, raw_data))
                conn.commit()
                return cursor.lastrowid
        except sqlite3.Error as e:
            self.log_error(f"Database error adding patient: {e}")
            conn.rollback()
            return None
    
    def get_patient_id_by_patient_id(self, patient_id):
        """Get the database ID for a patient based on their patient_id"""
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM patients WHERE patient_id = ?', (patient_id,))
            result = cursor.fetchone()
            return result[0] if result else None
        except sqlite3.Error as e:
            self.log_error(f"Database error getting patient ID: {e}")
            return None
    
    def get_patient_id_by_sample_id(self, sample_id):
        """Get the database ID for a patient based on their sample_id"""
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM patients WHERE sample_id = ?', (sample_id,))
            result = cursor.fetchone()
            return result[0] if result else None
        except sqlite3.Error as e:
            self.log_error(f"Database error getting patient ID by sample_id: {e}")
            return None
    
    def add_result(self, patient_id, test_code, value, unit, flags=None, timestamp=None, sequence=None):
        """
        Add a test result to the database
        
        Args:
            patient_id: Database ID of the patient
            test_code: Test code identifier
            value: Test result value
            unit: Unit of measurement
            flags: Any flags for the test result
            timestamp: Timestamp of the result, defaults to current time if not provided
            sequence: Sequence number from ASTM record for maintaining result order
        """
        if timestamp is None:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO results (patient_id, test_code, value, unit, flags, timestamp, sync_status, sequence)
                VALUES (?, ?, ?, ?, ?, ?, 'local', ?)
            ''', (patient_id, test_code, value, unit, flags, timestamp, sequence))
            conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            self.log_error(f"Database error adding result: {e}")
            conn.rollback()
            return None
    
    def get_results(self, limit=100, sync_status=None):
        """Get results from the database with optional sync_status filter"""
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            query = '''
                SELECT r.id, p.patient_id, p.name, r.test_code, r.value, r.unit, r.flags, r.timestamp, r.sync_status
                FROM results r
                JOIN patients p ON r.patient_id = p.id
            '''
            
            params = []
            if sync_status is not None:
                query += " WHERE r.sync_status = ?"
                params.append(sync_status)
                
            query += " ORDER BY r.timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            return cursor.fetchall()
        except sqlite3.Error as e:
            self.log_error(f"Database error getting results: {e}")
            return []
    
    def mark_result_synced(self, result_id):
        """Mark a result as synced"""
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE results SET sync_status = 'synced'
                WHERE id = ?
            ''', (result_id,))
            conn.commit()
            return True
        except sqlite3.Error as e:
            self.log_error(f"Database error marking result synced: {e}")
            conn.rollback()
            return False
    
    def mark_patient_synced(self, patient_db_id):
        """Mark a patient as synced"""
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE patients SET sync_status = 'synced'
                WHERE id = ?
            ''', (patient_db_id,))
            conn.commit()
            return True
        except sqlite3.Error as e:
            self.log_error(f"Database error marking patient synced: {e}")
            conn.rollback()
            return False
    
    def get_patients_for_sync(self, limit=100):
        """Get patients that need to be synced to the remote server"""
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, patient_id, sample_id, name, dob, sex, physician, raw_data, created_at
                FROM patients
                WHERE sync_status = 'local'
                ORDER BY created_at ASC
                LIMIT ?
            ''', (limit,))
            return cursor.fetchall()
        except sqlite3.Error as e:
            self.log_error(f"Database error getting patients for sync: {e}")
            return []
    
    def log_event(self, level, source, message):
        """Log an event to the database"""
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO logs (level, source, message)
                VALUES (?, ?, ?)
            ''', (level, source, message))
            conn.commit()
        except sqlite3.Error as e:
            # Don't recursively log this error
            print(f"Error logging to database: {e}")
            if conn:
                conn.rollback()
    
    def log_info(self, message, source="app"):
        """Log an info event"""
        self.log_event("INFO", source, message)
    
    def log_error(self, message, source="app"):
        """Log an error event"""
        self.log_event("ERROR", source, message)
    
    def log_warn(self, message, source="app"):
        """Log a warning event"""
        self.log_event("WARN", source, message)
    
    def record_sync_attempt(self, status, message, results_synced=0):
        """Record a sync attempt in the history"""
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO sync_history (status, message, results_synced)
                VALUES (?, ?, ?)
            ''', (status, message, results_synced))
            conn.commit()
        except sqlite3.Error as e:
            self.log_error(f"Database error recording sync history: {e}")
            conn.rollback()
            
    def get_sync_history(self, limit=20):
        """Get the sync history"""
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, timestamp, status, message, results_synced
                FROM sync_history
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (limit,))
            return cursor.fetchall()
        except sqlite3.Error as e:
            self.log_error(f"Database error getting sync history: {e}")
            return []
            
    def vacuum(self):
        """Optimize the database by running VACUUM"""
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute("VACUUM")
            conn.commit()
        except sqlite3.Error as e:
            self.log_error(f"Error running VACUUM: {e}")
            
    def cleanup_old_logs(self, days=30):
        """Clean up old log entries"""
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM logs
                WHERE timestamp < datetime('now', '-? days')
            ''', (days,))
            conn.commit()
            return cursor.rowcount
        except sqlite3.Error as e:
            self.log_error(f"Error cleaning up old logs: {e}")
            conn.rollback()
            return 0

    def get_patient_results(self, patient_db_id):
        """Get all results for a specific patient by their database ID"""
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, test_code, value, unit, flags, timestamp, sync_status, sequence
                FROM results
                WHERE patient_id = ?
                ORDER BY CAST(sequence AS INTEGER), timestamp
            ''', (patient_db_id,))
            return cursor.fetchall()
        except sqlite3.Error as e:
            self.log_error(f"Database error getting patient results: {e}")
            return []
            
    def get_patient_by_id(self, patient_db_id):
        """Get patient information by database ID"""
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, patient_id, name, dob, sex, physician, raw_data, sync_status, created_at
                FROM patients
                WHERE id = ?
            ''', (patient_db_id,))
            return cursor.fetchone()
        except sqlite3.Error as e:
            self.log_error(f"Database error getting patient: {e}")
            return None