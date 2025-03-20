"""
Main GUI window for the analyzer application
"""
import asyncio
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np
import threading
import traceback
from .config_dialog import ConfigDialog

class ApplicationWindow:
    """Main application window"""
    # Constants for UI strings
    COLUMN_SAMPLE_ID = "Sample ID"
    COLUMN_SYNC_STATUS = "Sync Status"
    STYLE_CARD_FRAME = "Card.TFrame"
    STYLE_MODERN_BUTTON = "Modern.TButton"
    STATUS_SERVER_STARTING = "Server: Starting..."
    STATUS_SERVER_FAILED = "Server: Failed to Start"
    
    def __init__(self, root, config, db_manager, tcp_server, sync_manager, logger, loop):
        self.root = root
        self.config = config
        self.db_manager = db_manager
        self.tcp_server = tcp_server
        self.sync_manager = sync_manager
        self.logger = logger
        self.loop = loop
        
        self.root.title(self.config.get("app_name", "XN-L Interface"))
        self.root.geometry("1200x800")

        # Create main container
        self.main_container = ttk.Frame(self.root)
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Create the interface components
        self._init_gui_components()
        
        # Initialize update tasks
        self.update_tasks = []
        self.server_task = None
        self.sync_task = None
        
        # Initialize flags
        self.is_shutting_down = False
        self.is_destroyed = False
        
        # Set up clean shutdown
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Check server status and update UI appropriately
        self._check_server_status()
        
        # Auto-start server if configured and not already running
        # Schedule it after a short delay to ensure UI is fully rendered first
        if self.config.get("auto_start", False) and not self.tcp_server.is_running:
            self.logger.info("Auto-starting server based on configuration")
            # Delay auto-start by 800ms to ensure UI is fully rendered
            self.root.after(800, self._auto_start_server_threaded)
            
    def _check_server_status(self):
        """Check if the server is already running and update UI accordingly"""
        if self.tcp_server and self.tcp_server.is_running:
            # Server is already running - update UI elements
            port = self.config.get('port', 5000)
            self.server_status.config(text=f"Server: Running on port {port}")
            self.port_status.config(text=f"Port: {port} (Active)")
            self.start_button.config(state=tk.DISABLED)
            
            # Log that UI was updated for existing server
            self.logger.info("UI updated for already running server")
            
            # Start periodic updates for an already running server
            self._schedule_updates()
        else:
            # Server not running
            self.start_button.config(state=tk.NORMAL)

    def _init_gui_components(self):
        """Initialize all GUI components"""
        # Create menu
        self._create_menu()
        
        # Create interface sections
        self._create_status_frame()
        self._create_data_frame()
        self._create_log_frame()
        
        # Initialize scattergram variables (but don't create frame yet)
        self.scatter_frame = None
        self.figure = None
        self.scatter_plot = None
        self.scatter_canvas = None

    def _create_menu(self):
        """Create the application menu bar"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Settings", command=self._show_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_closing)
        
        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Show Scattergram", command=self._show_scattergram)
        view_menu.add_command(label="Hide Scattergram", command=self._hide_scattergram)
        
    def _show_settings(self):
        """Show the configuration dialog"""
        dialog = ConfigDialog(self.root, self.config)
        self.root.wait_window(dialog)
        
        if dialog.result:
            # Update window title
            self.root.title(self.config.get("app_name", "XN-L Interface"))
            
            # If server is running, show restart message
            if self.start_button['state'] == tk.DISABLED:
                messagebox.showinfo(
                    "Restart Required",
                    "Please restart the server for the new settings to take effect."
                )

    def _create_status_frame(self):
        """Create the status section"""
        status_frame = ttk.LabelFrame(self.main_container, text="System Status")
        status_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Server status
        self.server_status = ttk.Label(status_frame, text="Server: Stopped")
        self.server_status.pack(side=tk.LEFT, padx=5)
        
        # Connection status
        self.connection_status = ttk.Label(status_frame, text="Connections: 0")
        self.connection_status.pack(side=tk.LEFT, padx=5)
        
        # Sync status
        self.sync_status = ttk.Label(status_frame, text="Sync: Disabled")
        self.sync_status.pack(side=tk.LEFT, padx=5)
        
        # Port display
        self.port_status = ttk.Label(status_frame, text=f"Port: {self.config.get('port', 5000)}")
        self.port_status.pack(side=tk.LEFT, padx=5)
        
        # Control buttons
        self.start_button = ttk.Button(status_frame, text="Start Server", command=self.start_server)
        self.start_button.pack(side=tk.RIGHT, padx=5)
        
        # Connection count label
        self.connection_count_label = tk.Label(self.main_container, text="Connections: 0")
        self.connection_count_label.pack()

    def _create_data_frame(self):
        """Create the data display section with patient view"""
        # Create patient frame
        self.patient_frame = ttk.Frame(self.main_container)
        self.patient_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Setup patient treeview
        self.patient_tree = ttk.Treeview(self.patient_frame, 
                                       columns=("ID", "Name", self.COLUMN_SAMPLE_ID, "Sex", 
                                              "Date", self.COLUMN_SYNC_STATUS, "Actions"))
        self.patient_tree.heading("#0", text="")
        self.patient_tree.heading("ID", text="Patient ID")
        self.patient_tree.heading("Name", text="Name")
        self.patient_tree.heading(self.COLUMN_SAMPLE_ID, text=self.COLUMN_SAMPLE_ID)
        self.patient_tree.heading("Sex", text="Sex")
        self.patient_tree.heading("Date", text="Date")
        self.patient_tree.heading(self.COLUMN_SYNC_STATUS, text=self.COLUMN_SYNC_STATUS)
        self.patient_tree.heading("Actions", text="Actions")
        
        # Configure patient column widths
        self.patient_tree.column("#0", width=0, stretch=tk.NO)
        self.patient_tree.column("ID", width=100)
        self.patient_tree.column("Name", width=200)
        self.patient_tree.column(self.COLUMN_SAMPLE_ID, width=100)
        self.patient_tree.column("Sex", width=50)
        self.patient_tree.column("Date", width=150)
        self.patient_tree.column(self.COLUMN_SYNC_STATUS, width=100)
        self.patient_tree.column("Actions", width=150)
        
        # Add scrollbar to patient treeview
        patient_scrollbar = ttk.Scrollbar(self.patient_frame, orient=tk.VERTICAL, command=self.patient_tree.yview)
        self.patient_tree.configure(yscrollcommand=patient_scrollbar.set)
        
        # Pack patient elements
        self.patient_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        patient_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind click event to patient tree for showing patient results and sync
        self.patient_tree.tag_bind("view_results", "<Button-1>", self._on_view_results_click)
        self.patient_tree.tag_bind("sync", "<Button-1>", self._on_sync_click)

    def _on_view_results_click(self, event):
        """Handle click on 'View Results' button in patient tree"""
        # Get the item ID that was clicked
        item_id = self.patient_tree.identify_row(event.y)
        if not item_id:
            return
            
        # Get the column ID that was clicked
        column_id = self.patient_tree.identify_column(event.x)
        if column_id != "#7":  # "#7" is the "Actions" column (1-indexed)
            return
            
        # Get patient ID from the tree item
        patient_id = self.patient_tree.item(item_id, "values")[0]
        
        # Show a dialog with patient results
        self._show_patient_results(patient_id)
        
    def _show_patient_results(self, patient_id):
        """Show results for the selected patient with sync functionality"""
        # Create a toplevel window
        results_window = tk.Toplevel(self.root)
        results_window.title(f"Results for Patient {patient_id}")
        results_window.geometry("800x500")
        results_window.transient(self.root)
        results_window.grab_set()
        
        # Center the window relative to the main window
        self._center_window(results_window)
        
        # Create a treeview for results
        results_frame = ttk.Frame(results_window, padding=10, style=self.STYLE_CARD_FRAME)
        results_frame.pack(fill=tk.BOTH, expand=True)
        
        # Get patient info and determine sync status
        patient_info = self._get_patient_info(patient_id)
        sync_status = "Not Synced"
        if patient_info:
            # Get the actual sync status from database
            conn = self.db_manager._ensure_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT sync_status FROM patients WHERE id = ?', (patient_info['db_id'],))
            result = cursor.fetchone()
            if result and result[0]:
                sync_status = result[0]
        
            # Create header with patient info
            header_frame = ttk.Frame(results_frame, style=self.STYLE_CARD_FRAME)
            header_frame.pack(fill=tk.X, pady=(0, 10))
            
            info_text = f"Patient: {patient_info.get('name', 'Unknown')} (ID: {patient_id})"
            ttk.Label(header_frame, text=info_text, 
                     style="Modern.TLabel",
                     font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, anchor=tk.W)
            
            # Add sync button with appropriate label based on sync status
            sync_frame = ttk.Frame(header_frame, style=self.STYLE_CARD_FRAME)
            sync_frame.pack(side=tk.RIGHT)
            
            if self.config.get("external_server", {}).get("enabled", False):
                if sync_status.lower() == "synced":
                    sync_btn = ttk.Button(sync_frame, text="Re-Sync", 
                                        style=self.STYLE_MODERN_BUTTON,
                                        command=lambda: self._sync_from_results(patient_info, results_window))
                else:
                    sync_btn = ttk.Button(sync_frame, text="Sync", 
                                        style=self.STYLE_MODERN_BUTTON,
                                        command=lambda: self._sync_from_results(patient_info, results_window))
                sync_btn.pack(side=tk.RIGHT, padx=5)
                
                # Add sync status indicator
                status_label = ttk.Label(sync_frame, text=f"Status: {sync_status}", style="Modern.TLabel")
                status_label.pack(side=tk.RIGHT, padx=10)
        
        # Create results treeview
        results_tree = ttk.Treeview(results_frame, style="Modern.Treeview",
                                   columns=("Test", "Value", "Unit", "Flags", "Time", "Status"))
        results_tree.heading("#0", text="ID")
        results_tree.heading("Test", text="Test")
        results_tree.heading("Value", text="Value")
        results_tree.heading("Unit", text="Unit")
        results_tree.heading("Flags", text="Flags")
        results_tree.heading("Time", text="Time")
        results_tree.heading("Status", text="Status")
        
        # Configure column widths
        results_tree.column("#0", width=50)
        results_tree.column("Test", width=100)
        results_tree.column("Value", width=100)
        results_tree.column("Unit", width=80)
        results_tree.column("Flags", width=80)
        results_tree.column("Time", width=150)
        results_tree.column("Status", width=80)
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(results_frame, orient=tk.VERTICAL, command=results_tree.yview)
        results_tree.configure(yscrollcommand=scrollbar.set)
        
        # Pack elements
        results_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Add a close button
        button_frame = ttk.Frame(results_window, style=self.STYLE_CARD_FRAME)
        button_frame.pack(fill=tk.X, pady=10, padx=10)
        ttk.Button(button_frame, text="Close", 
                  style=self.STYLE_MODERN_BUTTON,
                  command=results_window.destroy).pack(side=tk.RIGHT)
        
        # Populate with results
        self._populate_patient_results(results_tree, patient_id)
    
    def _center_window(self, window):
        """Center a window relative to the main window"""
        window.update_idletasks()
        
        # Get main window position and dimensions
        main_x = self.root.winfo_x()
        main_y = self.root.winfo_y()
        main_width = self.root.winfo_width()
        main_height = self.root.winfo_height()
        
        # Get popup dimensions
        popup_width = window.winfo_width()
        popup_height = window.winfo_height()
        
        # Calculate centered position
        x = main_x + (main_width - popup_width) // 2
        y = main_y + (main_height - popup_height) // 2
        
        # Set position
        window.geometry(f"+{x}+{y}")
    
    def _sync_from_results(self, patient_info, results_window):
        """Handle sync/resync from the results window"""
        if not patient_info or not self.config.get("external_server", {}).get("enabled", False):
            messagebox.showerror("Sync Error", "Sync is not configured or patient information is missing", parent=results_window)
            return
        
        # Show a sync in progress message
        sync_message = tk.Toplevel(results_window)
        sync_message.title("Sync Status")
        sync_message.transient(results_window)
        sync_message.grab_set()
        
        # Center the message window
        self._center_window(sync_message)
        
        # Add message
        ttk.Label(sync_message, text="Syncing data...", padding=20).pack()
        
        # Start sync in a separate thread to not block UI
        def run_sync():
            success = False
            try:
                # Create a new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Prepare sync data - we need to get results async
                patient_id = patient_info["patient_id"]
                results = loop.run_until_complete(self._get_patient_results_async(patient_id))
                
                # Create sync data
                sync_data = {
                    "patient": patient_info,
                    "results": results
                }
                
                # Perform the sync
                success = loop.run_until_complete(self.sync_manager.sync_patient(sync_data))
                
                # Close the loop
                loop.close()
                
                # Update UI from the main thread
                self.root.after(0, lambda: self._handle_sync_result(success, patient_info, sync_message, results_window))
                
            except Exception as e:
                self.logger.error(f"Error in sync thread: {e}")
                # Update UI from the main thread
                self.root.after(0, lambda: self._handle_sync_result(False, patient_info, sync_message, results_window, str(e)))
        
        # Start the sync thread
        sync_thread = threading.Thread(target=run_sync)
        sync_thread.daemon = True
        sync_thread.start()
    
    def _handle_sync_result(self, success, patient_info, sync_message, results_window, error_message=None):
        """Handle the result of a sync operation"""
        try:
            # Close the sync message dialog
            sync_message.destroy()
            
            if success:
                # Update database
                self.db_manager.mark_patient_synced(patient_info["db_id"])
                
                # Show success message
                messagebox.showinfo("Sync Complete", 
                                  f"Patient {patient_info['patient_id']} data successfully synced.", 
                                  parent=results_window)
                
                # Update the main patient display
                self._update_patients_display()
                
                # Close the results window and reopen with updated info
                results_window.destroy()
                self._show_patient_results(patient_info['patient_id'])
                
            else:
                # Show error message
                error_text = f"Failed to sync patient data. {error_message if error_message else ''}"
                messagebox.showerror("Sync Failed", error_text, parent=results_window)
        
        except Exception as e:
            self.logger.error(f"Error handling sync result: {e}")
            messagebox.showerror("Error", f"An error occurred: {e}", parent=results_window)

    def _get_patient_info(self, patient_id):
        """Get patient information from the database"""
        try:
            # Query database for patient info
            conn = self.db_manager._ensure_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, patient_id, name, dob, sex, physician, sample_id
                FROM patients
                WHERE patient_id = ?
            ''', (patient_id,))
            result = cursor.fetchone()
            
            if result:
                db_id, patient_id, name, dob, sex, physician, sample_id = result
                return {
                    "db_id": db_id,
                    "patient_id": patient_id,
                    "name": name,
                    "dob": dob,
                    "sex": sex,
                    "physician": physician,
                    "sample_id": sample_id
                }
            return None
        except Exception as e:
            self.logger.error(f"Error getting patient info: {e}")
            return None
            
    def _populate_patient_results(self, tree, patient_id):
        """Populate the results tree with results for a specific patient"""
        try:
            # Clear the tree
            for item in tree.get_children():
                tree.delete(item)
                
            # Get the database ID for the patient
            patient_db_id = self.db_manager.get_patient_id_by_patient_id(patient_id)
            if not patient_db_id:
                return
                
            # Query database for results - use the updated get_patient_results method to get ordered results
            results = self.db_manager.get_patient_results(patient_db_id)
            
            # Add results to the tree
            for result in results:
                result_id, test_code, value, unit, flags, timestamp, sync_status, _ = result
                tree.insert("", tk.END, text=str(result_id),
                          values=(test_code, value, unit, flags, timestamp, sync_status))
                
        except Exception as e:
            self.logger.error(f"Error populating patient results: {e}")
            
    def update_results(self):
        """Update the results display with latest data"""
        try:
            if not self.db_manager:
                self.logger.warning("Database manager not initialized")
                return

            # Update patient treeview
            self._update_patients_display()
            
        except Exception as e:
            self.logger.error(f"Error updating results: {e}")
            
    def _update_patients_display(self):
        """Update the patients treeview with latest data"""
        try:
            # Clear existing items
            for item in self.patient_tree.get_children():
                self.patient_tree.delete(item)
                
            # Get latest patients (limited to most recent)
            conn = self.db_manager._ensure_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, patient_id, name, dob, sex, physician, sample_id, created_at, sync_status
                FROM patients
                ORDER BY created_at DESC
                LIMIT 100
            ''')
            patients = cursor.fetchall()
            
            # Add to patient treeview
            for patient in patients:
                _, patient_id, name, _, sex, _, sample_id, created_at, sync_status = patient
                
                # Format date
                created_date = created_at[:16] if created_at else "-"  # Get only the date part
                
                # Determine sync status and action buttons
                sync_status = sync_status or "Not Synced"
                actions = "View Results"
                
                # Add sync button if remote sync is configured and not yet synced
                if self.config.get("external_server", {}).get("enabled", False):
                    if sync_status != "synced":
                        actions += " | Sync"
                
                # Create item with appropriate tags
                item_id = self.patient_tree.insert("", tk.END,
                           values=(patient_id, name, sample_id, sex, created_date, sync_status, actions))
                
                # Apply tags for clickable actions
                tags = ["view_results"]
                if sync_status != "synced" and self.config.get("external_server", {}).get("enabled", False):
                    tags.append("sync")
                self.patient_tree.item(item_id, tags=tuple(tags))
                
        except Exception as e:
            self.logger.error(f"Error updating patients display: {e}")

    def _on_sync_click(self, event):
        """Handle click on 'Sync' button in patient tree"""
        # Get the item ID that was clicked
        item_id = self.patient_tree.identify_row(event.y)
        if not item_id:
            return
            
        # Get the column ID that was clicked
        column_id = self.patient_tree.identify_column(event.x)
        if column_id != "#7":  # "#7" is the "Actions" column
            return
            
        # Check if click was on the Sync part
        item_values = self.patient_tree.item(item_id)["values"]
        if len(item_values) < 7 or "Sync" not in item_values[6]:
            return
            
        # Get patient ID and attempt sync
        patient_id = item_values[0]
        
        # Create a function to run async code in a separate thread
        def run_sync_in_thread():
            try:
                # Create a new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Run the async function in this loop
                loop.run_until_complete(self._sync_patient(patient_id))
                
                # Close the loop
                loop.close()
            except Exception as e:
                self.logger.error(f"Error in sync thread: {e}")
                self.log(f"Error syncing patient {patient_id}", "ERROR")
        
        # Start a thread to run the async function
        sync_thread = threading.Thread(target=run_sync_in_thread)
        sync_thread.daemon = True
        sync_thread.start()

    async def _sync_patient(self, patient_id):
        """Sync patient data to remote server"""
        try:
            # Get patient info and results
            patient_info = self._get_patient_info(patient_id)
            if not patient_info:
                raise ValueError("Patient information not found")

            # Prepare sync data
            sync_data = {
                "patient": patient_info,
                "results": await self._get_patient_results_async(patient_id)
            }

            # Attempt to sync via sync manager
            success = await self.sync_manager.sync_patient(sync_data)
            
            if success:
                # Update patient sync status in database
                self.db_manager.mark_patient_synced(patient_info["db_id"])
                
                # Update UI
                self._update_patients_display()  # Refresh the whole display
                self.log(f"Successfully synced patient {patient_id}")
            else:
                self.log(f"Failed to sync patient {patient_id}")

        except Exception as e:
            self.logger.error(f"Error syncing patient {patient_id}: {e}")
            self.log(f"Error syncing patient {patient_id}")

    async def _get_patient_results_async(self, patient_id):
        """Get patient results asynchronously for sync operations"""
        try:
            # Get the database ID for the patient
            patient_db_id = self.db_manager.get_patient_id_by_patient_id(patient_id)
            if not patient_db_id:
                return []
                
            # Get results using the db_manager's get_patient_results method which orders by sequence
            results = self.db_manager.get_patient_results(patient_db_id)
            
            # Format results for sync
            formatted_results = []
            for result in results:
                result_id, test_code, value, unit, flags, timestamp, sync_status, sequence = result
                formatted_results.append({
                    "id": result_id,
                    "test_code": test_code,
                    "value": value,
                    "unit": unit,
                    "flags": flags,
                    "timestamp": timestamp,
                    "sync_status": sync_status,
                    "sequence": sequence
                })
            
            return formatted_results
        except Exception as e:
            self.logger.error(f"Error getting patient results: {e}")
            return []

    def _update_sync_status(self, patient_db_id, success):
        """Update the sync status for a patient and their results"""
        try:
            if success:
                # Mark patient as synced
                self.db_manager.mark_patient_synced(patient_db_id)
                
                # Mark all results for this patient as synced
                conn = self.db_manager._ensure_connection()
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE results 
                    SET sync_status = 'synced'
                    WHERE patient_id = ?
                ''', (patient_db_id,))
                conn.commit()
                
                # Update the display
                self._update_patients_display()
        except Exception as e:
            self.logger.error(f"Error updating sync status: {e}")

    def _create_log_frame(self):
        """Create the log display section"""
        log_frame = ttk.LabelFrame(self.main_container, text="System Log")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Create log text widget
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Add a clear log button
        clear_log_btn = ttk.Button(log_frame, text="Clear Log", command=self._clear_log)
        clear_log_btn.pack(side=tk.LEFT, padx=5, pady=2)
        
        # Add log level filter
        ttk.Label(log_frame, text="Filter:").pack(side=tk.LEFT, padx=5, pady=2)
        self.log_filter = ttk.Combobox(log_frame, values=["All", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.log_filter.set("All")
        self.log_filter.pack(side=tk.LEFT, padx=5, pady=2)
        
        # Create a lock for thread safety when updating the log
        self.log_lock = threading.Lock()
        
        # Register callback with logger for real-time updates
        self.logger.add_ui_callback(self._handle_log_message)
        
    def _clear_log(self):
        """Clear the log display"""
        self.log_text.delete(1.0, tk.END)
    
    def _handle_log_message(self, timestamp, level, message):
        """Handle real-time log messages from the logger"""
        try:
            # Use a lock to prevent concurrent modifications to the UI
            with self.log_lock:
                if self.is_destroyed or not self.root.winfo_exists():
                    return
                
                # Apply filter
                current_filter = self.log_filter.get()
                if current_filter != "All" and current_filter != level:
                    return
                
                # Format and insert the message
                self.root.after(0, lambda: self._insert_log_message(timestamp, level, message))
        except Exception as e:
            print(f"Error handling log message: {e}")
    
    def _insert_log_message(self, timestamp, level, message):
        """Insert a log message into the log text widget"""
        try:
            if not self.log_text.winfo_exists():
                return
                
            # Format the message
            formatted_message = f"{timestamp} - [{level}] {message}\n"
            
            # Insert the message
            self.log_text.insert(tk.END, formatted_message)
            
            # Apply color based on level
            last_line = self.log_text.get("end-2c linestart", "end-1c")
            start = f"end-{len(last_line)+1}c linestart"
            end = "end-1c"
            
            # Configure tags for different log levels
            if level == "ERROR" or level == "CRITICAL":
                self.log_text.tag_add("error", start, end)
                self.log_text.tag_config("error", foreground="red")
            elif level == "WARNING":
                self.log_text.tag_add("warning", start, end)
                self.log_text.tag_config("warning", foreground="orange")
            
            # Scroll to the bottom
            self.log_text.see(tk.END)
            
        except Exception as e:
            print(f"Error inserting log message: {e}")
    
    def log(self, message, level="INFO"):
        """Add a message to the log display"""
        # Forward to the logger which will call back through _handle_log_message
        if hasattr(self.logger, level.lower()):
            getattr(self.logger, level.lower())(message)
            
    def _show_scattergram(self):
        """Show the scattergram frame"""
        if not self.scatter_frame:
            self.scatter_frame = ttk.LabelFrame(self.main_container, text="Scattergram")
            self.scatter_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            
            # Create matplotlib figure
            self.figure = plt.Figure(figsize=(6, 4), dpi=100)
            self.scatter_plot = self.figure.add_subplot(111)
            self.scatter_canvas = FigureCanvasTkAgg(self.figure, self.scatter_frame)
            self.scatter_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
            
            # Initialize empty plot
            self.update_scattergram(np.zeros((256, 256)))
    
    def _hide_scattergram(self):
        """Hide the scattergram frame"""
        if self.scatter_frame:
            self.scatter_frame.pack_forget()
            self.scatter_frame = None
            self.figure = None
            self.scatter_plot = None
            self.scatter_canvas = None
            
    def log(self, message):
        """Add a message to the log display"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            # Only update UI in a thread-safe way
            self.root.after(0, lambda: self._safe_add_log_to_ui(message, timestamp))
        except Exception as e:
            print(f"Error logging to UI: {e}")
    
    def _safe_add_log_to_ui(self, message, timestamp):
        """Thread-safe method to add logs to the UI"""
        try:
            # Use a lock to prevent concurrent modifications to the UI
            with self.log_lock:
                # Only try to access UI elements if the window still exists
                if self.is_destroyed or not self.root.winfo_exists():
                    return
                    
                self._add_log_to_ui(message, timestamp)
        except Exception as e:
            print(f"Error adding log to UI: {e}")
    
    def _add_log_to_ui(self, message, timestamp):
        """Add a log message to the UI with filtering"""
        # Apply filter - with safety check
        try:
            if hasattr(self, 'log_filter') and self.log_filter.winfo_exists():
                filter_val = self.log_filter.get().lower()
                if filter_val != "all" and filter_val not in message.lower():
                    return
        except Exception as e:
            # If there's any error with the filter, show the message anyway
            print(f"Error applying log filter: {e}")
        
        # Insert into text widget
        if hasattr(self, 'log_text') and self.log_text.winfo_exists():
            self.log_text.insert(tk.END, f"{timestamp} - {message}\n")
            self.log_text.see(tk.END)
            
            # Highlight error messages
            if "error" in message.lower():
                # Find the line we just added
                line_count = int(self.log_text.index('end-1c').split('.')[0])
                line_start = f"{line_count}.0"
                line_end = f"{line_count}.end"
                self.log_text.tag_add("error", line_start, line_end)
                self.log_text.tag_config("error", foreground="red")
        
    def update_scattergram(self, data):
        """Update the scattergram display"""
        if self.scatter_frame and self.scatter_plot:
            self.scatter_plot.clear()
            self.scatter_plot.imshow(data, cmap='viridis')
            self.scatter_canvas.draw()
        
    async def _start_server_async(self):
        """Async method to start the server"""
        try:
            # Update UI to show starting state
            self.root.after(0, lambda: [
                self.server_status.config(text=self.STATUS_SERVER_STARTING),
                self.start_button.config(state=tk.DISABLED)
            ])
            
            # Start the server
            start_success = await self.tcp_server.start()
            
            if not start_success:
                # Handle failure - reset UI state
                self.root.after(0, lambda: [
                    self.server_status.config(text=self.STATUS_SERVER_FAILED),
                    self.start_button.config(state=tk.NORMAL)
                ])
                return False
            
            # Server started successfully - update UI
            port = self.config.get('port', 5000)
            self.root.after(0, lambda: [
                self.server_status.config(text=f"Server: Running on port {port}"),
                self.start_button.config(state=tk.DISABLED),
                self.port_status.config(text=f"Port: {port} (Active)")
            ])
            
            # Start sync manager if enabled
            if self.config.get("external_server", {}).get("enabled", False):
                await self.sync_manager.start()
                
            return True
            
        except Exception as e:
            self.logger.error(f"Error in async server start: {e}")
            self.logger.error(traceback.format_exc())
            
            # Reset UI on error
            self.root.after(0, lambda: [
                self.server_status.config(text="Server: Error"),
                self.start_button.config(state=tk.NORMAL)
            ])
            return False

    def start_server(self):
        """Start the TCP server in a separate thread"""
        if self.tcp_server.is_running:
            self.logger.error("Server is already running.")
            return

        try:
            # Update UI immediately
            self.db_manager.log_info("Starting server...", source="app")
            self.log("Starting server...")
            self.start_button.config(state=tk.DISABLED)
            self.server_status.config(text=self.STATUS_SERVER_STARTING)

            start_thread = threading.Thread(target=self._start_server_worker)
            start_thread.daemon = True
            start_thread.start()

        except Exception as e:
            self.logger.error(f"Error initiating server start: {e}")
            self._handle_server_error(str(e))

    def _handle_server_error(self, error_msg):
        """Handle server start errors in the main thread"""
        self.start_button.config(state=tk.NORMAL)
        self.server_status.config(text="Server: Error")
        messagebox.showerror("Error", f"Failed to start server: {error_msg}")

    def _start_server_worker(self):
        """Worker method to handle server startup in a separate thread"""
        try:
            # Setup sync manager if needed
            if hasattr(self.tcp_server, 'sync_manager') and self.tcp_server.sync_manager is None:
                self.tcp_server.sync_manager = self.sync_manager
                if self.sync_manager and self.tcp_server.parser:
                    self.tcp_server.parser.set_sync_manager(self.sync_manager)

            # Start the server
            start_success = self.tcp_server.start()

            # Update UI in main thread
            if start_success:
                self.root.after(0, self._server_started_ui_update)
                
                # Start sync manager in a separate thread if enabled
                if self.config.get("external_server", {}).get("enabled", False):
                    sync_thread = threading.Thread(target=self._start_sync_worker)
                    sync_thread.daemon = True
                    sync_thread.start()
            else:
                self.root.after(0, self._server_start_failed_ui_update)

        except Exception as e:
            self.logger.error(f"Error in server start thread: {e}")
            self.root.after(0, lambda: self._handle_server_error(str(e)))

    def _start_sync_worker(self):
        """Worker method to handle sync manager startup"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.sync_manager.start())
            loop.close()
        except Exception as sync_err:
            self.logger.error(f"Error starting sync manager: {sync_err}")

    def _server_started_ui_update(self):
        """Update UI after server has started successfully"""
        port = self.config.get('port', 5000)
        self.server_status.config(text=f"Server: Running on port {port}")
        self.port_status.config(text=f"Port: {port} (Active)")
        self.start_button.config(state=tk.DISABLED)
        self.log("Server started successfully")
        
        # Start periodic updates
        self._schedule_updates()

    def _server_start_failed_ui_update(self):
        """Update UI after server failed to start"""
        self.server_status.config(text=self.STATUS_SERVER_FAILED)
        self.start_button.config(state=tk.NORMAL)
        self.log("Failed to start server. Check logs for details.")
        messagebox.showerror("Error", "Failed to start server. Check logs for details.")

    def server_started(self):
        """Handle server started notification"""
        self.logger.info("Server has started. Updating UI.")
        self.start_button.config(state=tk.DISABLED)  # Disable start button
        self.update_connection_count()  # Update connection count when server starts

    def server_stopped(self):
        """Handle server stopped notification"""
        self.start_button.config(state=tk.NORMAL)  # Enable start button
        self.update_connection_count()  # Update connection count when server stops

    def update_connection_count(self):
        """Update the connection count label"""
        connection_count = len(self.tcp_server.clients)  # Assuming clients is a dictionary of connected clients
        self.connection_count_label.config(text=f"Connections: {connection_count}")

    async def _cleanup(self):
        """Clean up async resources"""
        try:
            # Set flags to prevent further GUI updates
            self.is_shutting_down = True
            
            # Cancel any remaining tasks
            for task in self.update_tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                        
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            
    def on_closing(self):
        """Handle window closing"""
        try:
            # Set shutdown flag first
            self.is_shutting_down = True
            
            # Remove logger callback
            self.logger.remove_ui_callback(self._handle_log_message)

            # Create event loop for cleanup if needed
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Run cleanup in the loop
            if self.sync_manager:
                loop.run_until_complete(self.sync_manager.stop())

            # Stop the server synchronously after sync manager
            if self.tcp_server and self.tcp_server.is_running:
                self.tcp_server.stop_sync()
            
            # Set destroyed flag
            self.is_destroyed = True
            
            # Close the window
            self.root.quit()
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")
            self.root.quit()  # Ensure window closes even if there's an error
                
    def _schedule_updates(self):
        """Schedule periodic GUI updates"""
        def update():
            try:
                # Check if window exists and we're not shutting down
                if not self.is_destroyed and not self.is_shutting_down and hasattr(self, 'root') and self.root.winfo_exists():
                    self.update_results()
                    self.update_ui_status()  # Changed from update_status to update_ui_status
                    self.root.after(1000, update)
            except Exception as e:
                if not self.is_shutting_down:  # Only log if not intentionally shutting down
                    self.logger.error(f"Error in periodic update: {e}")
    
    def update_ui_status(self):
        """Update UI status elements"""
        try:
            if not self.tcp_server or not self.sync_manager:
                return
                
            # Update connection count
            client_count = len([c for c in self.tcp_server.get_clients().values()
                              if c["status"] == "connected"])
            self.connection_status.config(text=f"Connections: {client_count}")
            
            # Update sync status
            if self.sync_manager.running:
                last_sync = self.sync_manager.last_sync_time
                if last_sync:
                    self.sync_status.config(text=f"Last Sync: {last_sync.strftime('%H:%M:%S')}")
                else:
                    self.sync_status.config(text="Sync: Active")
            else:
                self.sync_status.config(text="Sync: Disabled")
        except Exception as e:
            self.logger.error(f"Error updating UI status: {e}")

    def log_connection(self, address, port):
        """Log connections from other servers to the port"""
        message = f"Connection from {address}:{port}"
        self.log(message)
        self.logger.info(message)

    def log_disconnection(self, address, port):
        """Log disconnections from other servers to the port"""
        message = f"Disconnection from {address}:{port}"
        self.log(message)
        self.logger.info(message)

    def _auto_start_server_threaded(self):
        """Auto-start server in a separate thread to prevent UI freezing"""
        self.logger.info("Running auto-start in a separate thread")
        
        # Update UI first to show starting state
        self.server_status.config(text=self.STATUS_SERVER_STARTING)
        self.start_button.config(state=tk.DISABLED)
        
        # Function to run in a separate thread
        def start_server_thread():
            try:
                # Start the server
                success = self.tcp_server.start()
                
                # Update UI from main thread based on result
                if success:
                    self.root.after(0, lambda: self._server_started_ui_update())
                    
                    # Start sync manager if enabled
                    if self.config.get("external_server", {}).get("enabled", False):
                        try:
                            # Create a new event loop for the sync manager
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            loop.run_until_complete(self.sync_manager.start())
                            loop.close()
                        except Exception as sync_err:
                            self.logger.error(f"Error starting sync manager: {sync_err}")
                else:
                    self.root.after(0, lambda: self._server_start_failed_ui_update())
            except Exception as e:
                self.logger.error(f"Error in auto-start thread: {e}")
                self.root.after(0, lambda: self._server_start_failed_ui_update())
        
        # Start the thread
        thread = threading.Thread(target=start_server_thread)
        thread.daemon = True
        thread.start()

    def _server_started_ui_update(self):
        """Update UI after server has started successfully"""
        port = self.config.get('port', 5000)
        self.server_status.config(text=f"Server: Running on port {port}")
        self.port_status.config(text=f"Port: {port} (Active)")
        self.start_button.config(state=tk.DISABLED)
        self.log("Server auto-started successfully")
        
        # Start periodic updates
        self._schedule_updates()

    def _server_start_failed_ui_update(self):
        """Update UI after server failed to start"""
        self.server_status.config(text=self.STATUS_SERVER_FAILED)
        self.start_button.config(state=tk.NORMAL)
        self.log("Failed to auto-start server")