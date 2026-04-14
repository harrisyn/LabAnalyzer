import sqlite3
import os
import threading
from datetime import datetime
from pathlib import Path


class DatabaseManager:
    """
    Handle database operations for the analyzer data.
    Thread-safe implementation using RLock for all database operations.
    """
    
    def __init__(self, db_file=None):
        # Use LOCALAPPDATA for persistent database storage
        default_dir = Path(os.getenv('LOCALAPPDATA')) / 'LabSync'
        default_dir.mkdir(parents=True, exist_ok=True)
        if db_file is None:
            db_file = default_dir / 'astm_data.db'
        self.db_file = db_file
        self.conn = None
        self.lock = threading.RLock()  # Reentrant lock for nested calls
        self.init_db()
        
    def _ensure_connection(self):
        """Ensure database connection is active. Must be called within lock."""
        if not self.conn:
            self.conn = sqlite3.connect(str(self.db_file), check_same_thread=False)
        return self.conn
        
    def init_db(self):
        """Initialize the database with required tables if they don't exist"""
        with self.lock:
            try:
                conn = self._ensure_connection()
                cursor = conn.cursor()
                
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
                        listener_port INTEGER,
                        listener_name TEXT,
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
                    
                if 'sync_status' not in columns:
                    cursor.execute('ALTER TABLE patients ADD COLUMN sync_status TEXT DEFAULT "local"')
                    
                if 'sample_id' not in columns:
                    cursor.execute('ALTER TABLE patients ADD COLUMN sample_id TEXT')
                    
                if 'listener_port' not in columns:
                    cursor.execute('ALTER TABLE patients ADD COLUMN listener_port INTEGER')
                    
                if 'listener_name' not in columns:
                    cursor.execute('ALTER TABLE patients ADD COLUMN listener_name TEXT')

                # Check if sequence column exists in results table
                cursor.execute("PRAGMA table_info(results)")
                result_columns = {info[1] for info in cursor.fetchall()}
                
                if 'sequence' not in result_columns:
                    cursor.execute('ALTER TABLE results ADD COLUMN sequence TEXT')

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
                
                conn.commit()
            except sqlite3.Error as e:
                print(f"Database initialization error: {e}")
                if self.conn:
                    self.conn.rollback()
                raise
            
    def close(self):
        """Close the database connection"""
        with self.lock:
            if self.conn:
                try:
                    self.conn.close()
                except sqlite3.Error as e:
                    print(f"Error closing database: {e}")
                finally:
                    self.conn = None
            
    def __enter__(self):
        """Context manager entry"""
        with self.lock:
            self._ensure_connection()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()
    
    def add_patient(self, patient_id, name, dob, sex, physician, raw_data=None, sample_id=None, 
                    listener_port=None, listener_name=None):
        """
        Add a patient to the database with optional raw data and sample ID.
        If an existing patient is found, update their information.
        
        If patient_id is empty but sample_id is provided, use sample_id as patient_id
        
        Args:
            listener_port: Port number of the listener that received this data
            listener_name: Name of the listener that received this data
            
        Returns:
            Database ID of the patient (new or existing)
        """
        with self.lock:
            try:
                conn = self._ensure_connection()
                cursor = conn.cursor()

                # Check for existing patient first by ID
                existing_patient_id = None
                
                # If updating an existing patient directly by database ID
                patient_id = patient_id.split('^')[0].strip() if '^' in patient_id else patient_id
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
                        sample_id = sample_id.split('^')[0].strip() if '^' in sample_id else sample_id
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
                        
                    if listener_port is not None:
                        update_fields.append("listener_port = ?")
                        update_values.append(listener_port)
                        
                    if listener_name is not None:
                        update_fields.append("listener_name = ?")
                        update_values.append(listener_name)
                    
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
                        (patient_id, sample_id, name, dob, sex, physician, raw_data, sync_status, listener_port, listener_name)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'local', ?, ?)
                    ''', (patient_id, sample_id, name, dob, sex, physician, raw_data, listener_port, listener_name))
                    conn.commit()
                    return cursor.lastrowid
            except sqlite3.Error as e:
                self.log_error(f"Database error adding patient: {e}")
                if self.conn:
                    self.conn.rollback()
                return None
    
    def get_patient_id_by_patient_id(self, patient_id):
        """Get the database ID for a patient based on their patient_id"""
        with self.lock:
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
        with self.lock:
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
        Add or update a test result in the database.
        If a result with the same patient_id and test_code already exists, it will be updated.
        
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
            
        with self.lock:
            try:
                conn = self._ensure_connection()
                cursor = conn.cursor()
                
                # Check if result already exists for this patient and test code
                cursor.execute('''
                    SELECT id FROM results 
                    WHERE patient_id = ? AND test_code = ?
                ''', (patient_id, test_code))
                existing = cursor.fetchone()
                
                if existing:
                    # Update existing result
                    cursor.execute('''
                        UPDATE results 
                        SET value = ?, unit = ?, flags = ?, timestamp = ?, sync_status = 'local', sequence = ?
                        WHERE patient_id = ? AND test_code = ?
                    ''', (value, unit, flags, timestamp, sequence, patient_id, test_code))
                    conn.commit()
                    return existing[0]
                else:
                    # Insert new result
                    cursor.execute('''
                        INSERT INTO results (patient_id, test_code, value, unit, flags, timestamp, sync_status, sequence)
                        VALUES (?, ?, ?, ?, ?, ?, 'local', ?)
                    ''', (patient_id, test_code, value, unit, flags, timestamp, sequence))
                    conn.commit()
                    return cursor.lastrowid
            except sqlite3.Error as e:
                self.log_error(f"Database error adding result: {e}")
                if self.conn:
                    self.conn.rollback()
                return None
    
    def get_results(self, limit=100, sync_status=None):
        """Get results with optional sync status filter"""
        with self.lock:
            try:
                conn = self._ensure_connection()
                cursor = conn.cursor()
                query = '''
                    SELECT r.id, p.patient_id, p.sample_id, p.name, r.test_code, r.value, r.unit, r.flags, r.timestamp, r.sync_status
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
        with self.lock:
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
                if self.conn:
                    self.conn.rollback()
                return False
    
    def mark_patient_synced(self, patient_db_id):
        """Mark a patient as synced"""
        with self.lock:
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
                if self.conn:
                    self.conn.rollback()
                return False
    
    def get_patients_for_sync(self, limit=100):
        """Get patients that need to be synced to the remote server"""
        with self.lock:
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
        with self.lock:
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
                if self.conn:
                    self.conn.rollback()
    
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
        with self.lock:
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
                if self.conn:
                    self.conn.rollback()
                
    def get_sync_history(self, limit=20):
        """Get the sync history"""
        with self.lock:
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
        with self.lock:
            try:
                conn = self._ensure_connection()
                cursor = conn.cursor()
                cursor.execute("VACUUM")
                conn.commit()
            except sqlite3.Error as e:
                self.log_error(f"Error running VACUUM: {e}")
            
    def cleanup_old_logs(self, days=30):
        """Clean up old log entries"""
        with self.lock:
            try:
                conn = self._ensure_connection()
                cursor = conn.cursor()
                cursor.execute(f'''
                    DELETE FROM logs
                    WHERE timestamp < datetime('now', '-{days} days')
                ''')
                conn.commit()
                return cursor.rowcount
            except sqlite3.Error as e:
                self.log_error(f"Database error cleaning up logs: {e}")
                if self.conn:
                    self.conn.rollback()
                return 0

    def get_patient_results(self, patient_db_id):
        """Get all results for a specific patient by their database ID"""
        with self.lock:
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
        with self.lock:
            try:
                conn = self._ensure_connection()
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, patient_id, sample_id, name, dob, sex, physician, raw_data, sync_status, created_at
                    FROM patients
                    WHERE id = ?
                ''', (patient_db_id,))
                return cursor.fetchone()
            except sqlite3.Error as e:
                self.log_error(f"Database error getting patient: {e}")
                return None
    
    def get_recent_patients(self, limit=50):
        """Get recently added patients"""
        with self.lock:
            try:
                conn = self._ensure_connection()
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, patient_id, sample_id, name, dob, sex, physician, 
                           sync_status, listener_port, listener_name, created_at
                    FROM patients
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (limit,))
                return cursor.fetchall()
            except sqlite3.Error as e:
                self.log_error(f"Database error getting recent patients: {e}")
                return []
    
    def get_stats(self):
        """Get database statistics"""
        with self.lock:
            try:
                conn = self._ensure_connection()
                cursor = conn.cursor()
                
                # Count patients
                cursor.execute('SELECT COUNT(*) FROM patients')
                patient_count = cursor.fetchone()[0]
                
                # Count results
                cursor.execute('SELECT COUNT(*) FROM results')
                result_count = cursor.fetchone()[0]
                
                # Count unsynced
                cursor.execute("SELECT COUNT(*) FROM patients WHERE sync_status = 'local'")
                unsynced_patients = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM results WHERE sync_status = 'local'")
                unsynced_results = cursor.fetchone()[0]
                
                return {
                    'patient_count': patient_count,
                    'result_count': result_count,
                    'unsynced_patients': unsynced_patients,
                    'unsynced_results': unsynced_results
                }
            except sqlite3.Error as e:
                self.log_error(f"Database error getting stats: {e}")
                return {
                    'patient_count': 0,
                    'result_count': 0,
                    'unsynced_patients': 0,
                    'unsynced_results': 0
                }
    
    def get_patient_sync_status(self, patient_db_id):
        """Get sync status for a specific patient"""
        with self.lock:
            try:
                conn = self._ensure_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT sync_status FROM patients WHERE id = ?', (patient_db_id,))
                result = cursor.fetchone()
                return result[0] if result else None
            except sqlite3.Error as e:
                self.log_error(f"Database error getting patient sync status: {e}")
                return None
    
    def get_recent_patients_filtered(self, listener_filter=None, limit=100):
        """
        Get recent patients with optional listener filter.
        
        Args:
            listener_filter: Optional listener name to filter by
            limit: Maximum number of patients to return
        
        Returns:
            List of patient tuples
        """
        with self.lock:
            try:
                conn = self._ensure_connection()
                cursor = conn.cursor()
                
                query = '''
                    SELECT id, patient_id, name, dob, sex, physician, sample_id, 
                           created_at, sync_status, listener_port, listener_name
                    FROM patients
                '''
                params = []
                
                if listener_filter:
                    query += " WHERE listener_name = ?"
                    params.append(listener_filter)
                
                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)
                
                cursor.execute(query, params)
                return cursor.fetchall()
            except sqlite3.Error as e:
                self.log_error(f"Database error getting recent patients: {e}")
                return []
    
    def get_unique_listener_names(self):
        """Get all unique listener names from patients table"""
        with self.lock:
            try:
                conn = self._ensure_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT listener_name FROM patients WHERE listener_name IS NOT NULL")
                return [row[0] for row in cursor.fetchall() if row[0]]
            except sqlite3.Error as e:
                self.log_error(f"Database error getting listener names: {e}")
                return []
    
    def search_patients(self, search_query, limit=100):
        """
        Search patients by patient_id, sample_id, or name.
        
        Args:
            search_query: Search string
            limit: Maximum results
            
        Returns:
            List of matching patient tuples
        """
        with self.lock:
            try:
                conn = self._ensure_connection()
                cursor = conn.cursor()
                
                search_pattern = f"%{search_query}%"
                cursor.execute('''
                    SELECT id, patient_id, name, dob, sex, physician, sample_id, 
                           created_at, sync_status, listener_port, listener_name
                    FROM patients
                    WHERE patient_id LIKE ? OR sample_id LIKE ? OR name LIKE ?
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (search_pattern, search_pattern, search_pattern, limit))
                return cursor.fetchall()
            except sqlite3.Error as e:
                self.log_error(f"Database error searching patients: {e}")
                return []
    
    def update_sync_status(self, patient_db_id, status):
        """Update sync status for a patient"""
        with self.lock:
            try:
                conn = self._ensure_connection()
                cursor = conn.cursor()
                cursor.execute('UPDATE patients SET sync_status = ? WHERE id = ?', (status, patient_db_id))
                conn.commit()
                return True
            except sqlite3.Error as e:
                self.log_error(f"Database error updating sync status: {e}")
                if self.conn:
                    self.conn.rollback()
                return False
