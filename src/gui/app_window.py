"""
Main GUI window for the analyzer application
"""
import asyncio
import os
import sys
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np
import threading
import traceback
import pystray
from PIL import Image
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
        
        self.root.title(self.config.get("app_name", "LabSync"))
        
        # Robust icon setting for both dev and PyInstaller builds
        def get_icon_path():
            # PyInstaller bundle locations
            if getattr(sys, 'frozen', False):
                base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
                candidate = os.path.join(base, "gui", "resources", "icon.ico")
                if os.path.exists(candidate):
                    return candidate
                candidate = os.path.join(os.path.dirname(sys.executable), "gui", "resources", "icon.ico")
                if os.path.exists(candidate):
                    return candidate
            # Dev mode
            candidate = os.path.join(os.path.dirname(__file__), "resources", "icon.ico")
            if os.path.exists(candidate):
                return candidate
            return None

        icon_path = get_icon_path()
        if icon_path:
            try:
                self.root.iconbitmap(icon_path)
            except Exception as e:
                self.logger.warning(f"Failed to set window icon: {e}")
            
        self.root.geometry("900x600")

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
        self.is_hidden = False
        
        # Initialize system tray
        self._init_system_tray()
        
        # Show notification that system tray is active
        if hasattr(self, 'tray_icon') and self.tray_icon:
            self.root.after(2000, lambda: self._show_tray_notification())
        
        # Set up clean shutdown
        self.root.protocol("WM_DELETE_WINDOW", self.on_window_close)
        
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
            # Server is already running - update dashboard
            self.logger.info("UI updated for already running server")
            self._schedule_updates()
            self.update_ui_status()
        else:
            # Server not running - update dashboard to show stopped state
            self.update_ui_status()

    def _init_gui_components(self):
        """Initialize all GUI components"""
        # Configure styles
        style = ttk.Style()
        style.configure("Card.TFrame", background="#f5f5f5", relief="raised", borderwidth=1)
        style.configure("Modern.TButton", padding=5)
        style.configure("Modern.Treeview", rowheight=25)
        
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
        self.scatter_image = None

    def update_ui_status(self):
        """Update UI status (alias for dashboard update)"""
        self._update_dashboard_status()
        
    def _create_menu(self):
        """Create the application menu bar"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
          # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Settings", command=self._show_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit_application)
        
        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Show Scattergram", command=self._show_scattergram)
        view_menu.add_command(label="Hide Scattergram", command=self._hide_scattergram)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Check for Updates", command=self._check_for_updates_manual)
        help_menu.add_separator()
        help_menu.add_command(label="Show Data Paths", command=self._show_data_paths)
        help_menu.add_command(label="About", command=self._show_about)
    def _show_data_paths(self):
        """Show a dialog with the config and database file paths"""
        config_path = self.config.get_config_path() if hasattr(self.config, 'get_config_path') else str(getattr(self.config, 'config_path', 'Unknown'))
        db_path = self.db_manager.get_db_path() if hasattr(self.db_manager, 'get_db_path') else str(getattr(self.db_manager, 'db_file', 'Unknown'))
        msg = f"Config file path:\n{config_path}\n\nDatabase file path:\n{db_path}"
        messagebox.showinfo("Data File Paths", msg)
        
    def _show_settings(self):
        """Show the configuration dialog"""
        dialog = ConfigDialog(self.root, self.config)
        self.root.wait_window(dialog)
        
        if dialog.result:
            # Update window title
            self.root.title(self.config.get("app_name", "LabSync"))
            
            # Auto-reload server configuration in a background thread to prevent UI freeze
            def reload_server_thread():
                try:
                    was_running = self.tcp_server.is_running
                    if was_running:
                        self.log("Restarting server to apply new configuration...")
                        # reload_config will handle stopping
                    
                    # Reload configuration (this blocks while stopping)
                    self.tcp_server.reload_config()
                    
                    # Rebuild listener cards on main thread since config changed
                    self.root.after(0, self._refresh_listener_dashboard)
                    
                    # Refresh dashboard status to show new listeners (via main thread)
                    self.root.after(100, self.update_ui_status)
                    
                    # Restart if it was running
                    if was_running:
                        self.tcp_server.start()
                        self.log("Server host-restarted with new configuration")
                        # Trigger another UI update
                        self.root.after(600, self.update_ui_status)
                    else:
                        self.root.after(0, lambda: messagebox.showinfo(
                            "Configuration Saved", 
                            "Settings saved. Start the server to use new configuration."
                        ))
                except Exception as e:
                    self.logger.error(f"Error reloading server: {e}")
                    self.log(f"Error reloading server: {e}")

            # Start reload in background thread
            threading.Thread(target=reload_server_thread, daemon=True).start()

    def _check_for_updates_manual(self):
        """Manually trigger update check"""
        def run_update_check():
            try:
                # Import here to avoid circular imports
                from ..utils.updater import UpdateChecker
                
                # Show checking message
                self.root.after(0, lambda: messagebox.showinfo(
                    "Update Check", 
                    "Checking for updates..."
                ))
                
                # Create updater instance
                updater = UpdateChecker(current_version=self.config.get('version', '1.0.0'))
                
                # Run the check in async context
                import asyncio
                
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    # Run the update check
                    result = loop.run_until_complete(updater.check_for_updates())
                    
                    # If no update was found, show message
                    if result is False:
                        self.root.after(0, lambda: messagebox.showinfo(
                            "No Updates", 
                            "You are already running the latest version."
                        ))
                            
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror(
                        "Update Check Failed", 
                        f"Failed to check for updates:\n{str(e)}"
                    ))
                finally:
                    loop.close()
                    
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", 
                    f"Update check error: {str(e)}"
                ))
        
        # Run in separate thread to avoid blocking GUI
        thread = threading.Thread(target=run_update_check, daemon=True)
        thread.start()

    def _show_about(self):
        """Show about dialog"""
        version = self.config.get('version', '1.0.0')
        app_name = self.config.get('app_name', 'LabSync')
        
        about_text = f"""{app_name} v{version}

Laboratory Data Analysis and Synchronization Tool

Features:
• Real-time data processing from multiple analyzer protocols
• ASTM, HL7, and proprietary protocol support
• Data synchronization with external systems
• Result visualization and reporting
• System tray integration

© 2025 TechNotes Consult - harrisyn@gmail.com"""
        
        messagebox.showinfo("About", about_text)

    def _create_status_frame(self):
        """Create the status section with listener dashboard"""
        status_frame = ttk.LabelFrame(self.main_container, text="System Dashboard")
        status_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Dashboard container
        dashboard = ttk.Frame(status_frame)
        dashboard.pack(fill=tk.X, padx=5, pady=5)
        
        # Left side: Global controls and status
        controls_frame = ttk.Frame(dashboard)
        controls_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5)
        
        # Server status indicator
        self.server_status = ttk.Label(controls_frame, text="Server Stopped", foreground="red")
        self.server_status.pack(anchor=tk.W, pady=2)
        
        # Global stats
        stats_frame = ttk.Frame(controls_frame)
        stats_frame.pack(anchor=tk.W, pady=5)
        self.connection_status = ttk.Label(stats_frame, text="Total Clients: 0")
        self.connection_status.pack(anchor=tk.W)
        self.sync_status = ttk.Label(stats_frame, text="Sync: Disabled")
        self.sync_status.pack(anchor=tk.W)
        
        # Main Start/Stop button
        self.start_button = ttk.Button(controls_frame, text="Start Server", command=self.start_server, width=15)
        self.start_button.pack(pady=10)
        
        # Right side: Scrollable Listener Cards
        listeners_container = ttk.Frame(dashboard)
        listeners_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)
        
        # Canvas for scrolling
        self.dashboard_canvas = tk.Canvas(listeners_container, height=120)
        scrollbar = ttk.Scrollbar(listeners_container, orient="horizontal", command=self.dashboard_canvas.xview)
        
        self.listeners_frame = ttk.Frame(self.dashboard_canvas)
        self.listeners_frame.bind(
            "<Configure>",
            lambda e: self.dashboard_canvas.configure(scrollregion=self.dashboard_canvas.bbox("all"))
        )
        
        self.dashboard_canvas.create_window((0, 0), window=self.listeners_frame, anchor="nw")
        self.dashboard_canvas.configure(xscrollcommand=scrollbar.set)
        
        self.dashboard_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Store references to listener widgets for updates
        self.listener_widgets = {}
        
        # Initial population of listener cards
        self._refresh_listener_dashboard()

    def _refresh_listener_dashboard(self):
        """Refresh the listener cards based on configuration"""
        # Clear existing
        for widget in self.listeners_frame.winfo_children():
            widget.destroy()
        self.listener_widgets = {}
        
        listeners = self.config.get_listeners()
        
        for listener in listeners:
            port = listener.get("port")
            card = self._create_listener_card(listener)
            card.pack(side=tk.LEFT, padx=5, pady=5)
            self.listener_widgets[port] = card

    def _create_listener_card(self, listener_config):
        """Create a UI card for a single listener"""
        port = listener_config.get("port")
        name = listener_config.get("name", "Unknown")
        analyzer = listener_config.get("analyzer_type", "Unknown")
        protocol = listener_config.get("protocol", "Unknown")
        
        frame = ttk.Frame(self.listeners_frame, style="Card.TFrame", padding=10, relief="raised", borderwidth=1)
        
        # Header
        header = ttk.Label(frame, text=name, font=("TkDefaultFont", 10, "bold"), cursor="hand2")
        header.pack(anchor=tk.W)
        
        # Details
        details_label = ttk.Label(frame, text=f"{analyzer} ({protocol})", cursor="hand2")
        details_label.pack(anchor=tk.W)
        port_label = ttk.Label(frame, text=f"Port: {port}", cursor="hand2")
        port_label.pack(anchor=tk.W)
        
        # Status indicators - store references to update later
        status_label = ttk.Label(frame, text="● Offline", foreground="gray", cursor="hand2")
        status_label.pack(anchor=tk.W, pady=(5,0))
        
        clients_label = ttk.Label(frame, text="Clients: 0", cursor="hand2")
        clients_label.pack(anchor=tk.W)
        
        # Store references in the frame widget itself
        frame.status_label = status_label
        frame.clients_label = clients_label
        frame.listener_name = name  # Store name for filtering
        
        # Make entire card clickable to filter by this listener
        def on_card_click(event):
            self._filter_by_listener(name)
        
        # Bind click to frame and all children
        frame.bind("<Button-1>", on_card_click)
        for child in frame.winfo_children():
            child.bind("<Button-1>", on_card_click)
        
        return frame

    def _update_dashboard_status(self):
        """Periodic update of dashboard status"""
        if not self.tcp_server:
            return

        # Update global server status
        if self.tcp_server.is_running:
            self.server_status.config(text="Server Running", foreground="green")
            self.start_button.config(state=tk.DISABLED, text="Running")
        else:
            self.server_status.config(text="Server Stopped", foreground="red")
            self.start_button.config(state=tk.NORMAL, text="Start Server")

        # Update global client count
        total_clients = self.tcp_server.get_client_count()
        self.connection_status.config(text=f"Total Clients: {total_clients}")

        # Update individual listener cards
        all_clients = self.tcp_server.get_clients()
        
        for port, widget in self.listener_widgets.items():
            # Count clients for this port
            port_clients = len([c for c in all_clients.values() 
                              if c.get("local_port") == port and c.get("status") == "connected"])
            
            # Update widgets
            if self.tcp_server.is_running:
                widget.status_label.config(text="● Online", foreground="green")
                widget.clients_label.config(text=f"Clients: {port_clients}")
            else:
                widget.status_label.config(text="● Offline", foreground="gray")
                widget.clients_label.config(text="Clients: 0")
    
    # Placeholder for existing connection_count_label if it was used elsewhere
    # We'll just ignore it or remove references if safe, 
    # but to be safe let's ensure 'connection_count_label' exists but is hidden if we want to avoid breaking
    # other methods that might reference it directly.
    # Looking at code 'self.connection_count_label' was packed at bottom of status_frame.
    # We replaced status_frame, so we should define it if needed.
    # I'll add a property to handle backward compatibility just in case.
    @property
    def connection_count_label(self):
        return self.connection_status

    def _create_data_frame(self):
        """Create the data display section with patient view"""
        # Create patient frame
        self.patient_frame = ttk.Frame(self.main_container)
        self.patient_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Create filter toggle frame
        filter_toggle_frame = ttk.Frame(self.patient_frame)
        filter_toggle_frame.pack(fill=tk.X, padx=5, pady=(0, 2))
        
        # Add filter toggle button
        self.filter_visible = tk.BooleanVar(value=False)
        self.toggle_button = ttk.Button(filter_toggle_frame, text="▼ Show Filters", command=self._toggle_filters)
        self.toggle_button.pack(side=tk.LEFT)
        
        # Add filter frame
        self.filter_frame = ttk.LabelFrame(self.patient_frame, text="Filters")
        
        # Date range filter
        date_frame = ttk.Frame(self.filter_frame)
        date_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(date_frame, text="Date Range:").pack(side=tk.LEFT, padx=(0, 5))
        self.date_range_var = tk.StringVar(value="All")
        date_range_combo = ttk.Combobox(date_frame, textvariable=self.date_range_var, 
                                      values=["All", "Today", "Last 7 Days", "Last 30 Days", "Custom"], 
                                      width=15)
        date_range_combo.pack(side=tk.LEFT, padx=5)
        date_range_combo.bind("<<ComboboxSelected>>", self._on_date_range_changed)
        
        # Custom date range inputs
        self.custom_date_frame = ttk.Frame(date_frame)
        ttk.Label(self.custom_date_frame, text="From:").pack(side=tk.LEFT, padx=5)
        self.date_from_var = tk.StringVar()
        self.date_from_entry = ttk.Entry(self.custom_date_frame, textvariable=self.date_from_var, width=10)
        self.date_from_entry.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(self.custom_date_frame, text="To:").pack(side=tk.LEFT, padx=5)
        self.date_to_var = tk.StringVar()
        self.date_to_entry = ttk.Entry(self.custom_date_frame, textvariable=self.date_to_var, width=10)
        self.date_to_entry.pack(side=tk.LEFT, padx=2)
        
        # Status filter
        status_frame = ttk.Frame(self.filter_frame)
        status_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(status_frame, text="Sync Status:").pack(side=tk.LEFT, padx=(0, 5))
        self.status_filter_var = tk.StringVar(value="Not Synced")  # Changed default to "Not Synced"
        status_combo = ttk.Combobox(status_frame, textvariable=self.status_filter_var,
                                  values=["All", "Synced", "Not Synced"], width=15)
        status_combo.pack(side=tk.LEFT, padx=5)
        status_combo.bind("<<ComboboxSelected>>", self._on_filter_changed)
        
        # Listener filter
        ttk.Label(status_frame, text="Listener:").pack(side=tk.LEFT, padx=(15, 5))
        self.listener_filter_var = tk.StringVar(value="All")
        self.listener_filter_combo = ttk.Combobox(status_frame, textvariable=self.listener_filter_var,
                                                   values=["All"], width=20)
        self.listener_filter_combo.pack(side=tk.LEFT, padx=5)
        self.listener_filter_combo.bind("<<ComboboxSelected>>", self._on_filter_changed)
        
        # Search frame
        search_frame = ttk.Frame(self.filter_frame)
        search_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT, padx=(0, 5))
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=30)
        search_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.search_var.trace_add("write", lambda *args: self._on_filter_changed())
        
        # Apply filter button
        ttk.Button(self.filter_frame, text="Apply Filters", 
                  command=self._on_filter_changed).pack(side=tk.RIGHT, padx=5, pady=5)
        
        # Clear listener filter button
        ttk.Button(self.filter_frame, text="Clear Listener Filter", 
                  command=self._clear_listener_filter).pack(side=tk.RIGHT, padx=5, pady=5)
        
        # Hide filter frame initially
        self.filter_frame.pack_forget()
        
        # Setup patient treeview with Listener column
        self.patient_tree = ttk.Treeview(self.patient_frame, 
                                       columns=("ID", "Name", self.COLUMN_SAMPLE_ID, "Sex", 
                                              "Date", "Listener", self.COLUMN_SYNC_STATUS, "Actions"))
        self.patient_tree.heading("#0", text="")
        self.patient_tree.heading("ID", text="Patient ID", command=lambda: self._treeview_sort_column(self.patient_tree, "ID"))
        self.patient_tree.heading("Name", text="Name", command=lambda: self._treeview_sort_column(self.patient_tree, "Name"))
        self.patient_tree.heading(self.COLUMN_SAMPLE_ID, text=self.COLUMN_SAMPLE_ID, 
                                command=lambda: self._treeview_sort_column(self.patient_tree, self.COLUMN_SAMPLE_ID))
        self.patient_tree.heading("Sex", text="Sex", command=lambda: self._treeview_sort_column(self.patient_tree, "Sex"))
        self.patient_tree.heading("Date", text="Date", command=lambda: self._treeview_sort_column(self.patient_tree, "Date"))
        self.patient_tree.heading("Listener", text="Listener", command=lambda: self._treeview_sort_column(self.patient_tree, "Listener"))
        self.patient_tree.heading(self.COLUMN_SYNC_STATUS, text=self.COLUMN_SYNC_STATUS, 
                                command=lambda: self._treeview_sort_column(self.patient_tree, self.COLUMN_SYNC_STATUS))
        self.patient_tree.heading("Actions", text="Actions")
        
        # Configure patient column widths
        self.patient_tree.column("#0", width=0, stretch=tk.NO)
        self.patient_tree.column("ID", width=80)
        self.patient_tree.column("Name", width=150)
        self.patient_tree.column(self.COLUMN_SAMPLE_ID, width=80)
        self.patient_tree.column("Sex", width=40)
        self.patient_tree.column("Date", width=120)
        self.patient_tree.column("Listener", width=100)
        self.patient_tree.column(self.COLUMN_SYNC_STATUS, width=80)
        self.patient_tree.column("Actions", width=100)
        
        # Add scrollbar to patient treeview
        patient_scrollbar = ttk.Scrollbar(self.patient_frame, orient=tk.VERTICAL, command=self.patient_tree.yview)
        self.patient_tree.configure(yscrollcommand=patient_scrollbar.set)
        
        # Pack patient elements
        self.patient_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        patient_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind click event to patient tree for showing patient results and sync
        self.patient_tree.tag_bind("view_results", "<Button-1>", self._on_view_results_click)
        self.patient_tree.tag_bind("sync", "<Button-1>", self._on_sync_click)

    def _toggle_filters(self):
        """Toggle the visibility of the filter frame"""
        if self.filter_visible.get():
            self.filter_frame.pack_forget()
            self.toggle_button.config(text="▼ Show Filters")
            self.filter_visible.set(False)
        else:
            self.filter_frame.pack(fill=tk.X, padx=5, pady=(0, 5), after=self.toggle_button.winfo_parent())
            self.toggle_button.config(text="▲ Hide Filters")
            self.filter_visible.set(True)

    def _clear_listener_filter(self):
        """Clear the listener filter and show all records"""
        if hasattr(self, 'listener_filter_var'):
            self.listener_filter_var.set("All")
        self._on_filter_changed()
        
    def _filter_by_listener(self, listener_name):
        """Filter records by specific listener (called when clicking a listener card)"""
        if hasattr(self, 'listener_filter_var'):
            self.listener_filter_var.set(listener_name)
            # Show filters panel if hidden
            if not self.filter_visible.get():
                self._toggle_filters()
            self._on_filter_changed()

    def _on_view_results_click(self, event):
        """Handle click on 'View Results' button in patient tree"""
        # Get the item ID that was clicked
        item_id = self.patient_tree.identify_row(event.y)
        if not item_id:
            return
            
        # Get the column ID that was clicked
        column_id = self.patient_tree.identify_column(event.x)
        if column_id != "#8":  # "#8" is the "Actions" column (1-indexed, after adding Listener column)
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
        
        # Create results treeview with sorting
        results_tree = ttk.Treeview(results_frame, style="Modern.Treeview",
                                   columns=("Test", "Value", "Unit", "Flags", "Time", "Status"))
        results_tree.heading("#0", text="ID", command=lambda: self._treeview_sort_column(results_tree, "#0", is_num=True))
        results_tree.heading("Test", text="Test", command=lambda: self._treeview_sort_column(results_tree, "Test"))
        results_tree.heading("Value", text="Value", command=lambda: self._treeview_sort_column(results_tree, "Value", is_num=True))
        results_tree.heading("Unit", text="Unit", command=lambda: self._treeview_sort_column(results_tree, "Unit"))
        results_tree.heading("Flags", text="Flags", command=lambda: self._treeview_sort_column(results_tree, "Flags"))
        results_tree.heading("Time", text="Time", command=lambda: self._treeview_sort_column(results_tree, "Time"))
        results_tree.heading("Status", text="Status", command=lambda: self._treeview_sort_column(results_tree, "Status"))
        
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
            
    def update_connection_count(self):
        """Callback for connection updates"""
        self._update_dashboard_status()

    def _update_patients_display(self):
        """Update the patients treeview with latest data"""
        try:
            # Clear existing items
            for item in self.patient_tree.get_children():
                self.patient_tree.delete(item)
            
            # Get filter values
            listener_filter = getattr(self, 'listener_filter_var', None)
            listener_filter_value = listener_filter.get() if listener_filter else "All"
                
            # Build query with optional listener filter
            query = '''
                SELECT id, patient_id, name, dob, sex, physician, sample_id, created_at, sync_status, listener_port, listener_name
                FROM patients
            '''
            params = []
            
            # Add listener filter if needed
            if listener_filter_value and listener_filter_value != "All":
                query += " WHERE listener_name = ?"
                params.append(listener_filter_value)
            
            query += " ORDER BY created_at DESC LIMIT 100"
            
            # Get latest patients
            conn = self.db_manager._ensure_connection()
            cursor = conn.cursor()
            cursor.execute(query, params)
            patients = cursor.fetchall()
            
            # Collect unique listener names for filter dropdown
            listener_names = set()
            
            # Add to patient treeview
            for patient in patients:
                db_id, patient_id, name, _, sex, _, sample_id, created_at, sync_status, listener_port, listener_name = patient
                
                # Collect listener names
                if listener_name:
                    listener_names.add(listener_name)
                
                # Format date
                created_date = created_at[:16] if created_at else "-"  # Get only the date part
                
                # Format listener display
                listener_display = listener_name if listener_name else (f"Port {listener_port}" if listener_port else "-")
                
                # Determine sync status and action buttons
                sync_status = sync_status or "local"
                actions = "View Results"
                
                # Add sync button if remote sync is configured and not yet synced
                if self.config.get("external_server", {}).get("enabled", False):
                    if sync_status != "synced":
                        actions += " | Sync"
                
                # Create item with appropriate tags (now includes Listener column)
                item_id = self.patient_tree.insert("", tk.END,
                           values=(patient_id, name, sample_id, sex, created_date, listener_display, sync_status, actions))
                
                # Apply tags for clickable actions
                tags = ["view_results"]
                if sync_status != "synced" and self.config.get("external_server", {}).get("enabled", False):
                    tags.append("sync")
                self.patient_tree.item(item_id, tags=tuple(tags))
            
            # Update listener filter dropdown with available listeners
            if hasattr(self, 'listener_filter_combo'):
                # Also get all unique listener names from database
                cursor.execute("SELECT DISTINCT listener_name FROM patients WHERE listener_name IS NOT NULL")
                all_listeners = [row[0] for row in cursor.fetchall() if row[0]]
                listener_values = ["All"] + sorted(all_listeners)
                self.listener_filter_combo['values'] = listener_values
                
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
        if column_id != "#8":  # "#8" is the "Actions" column (after adding Listener column)
            return
            
        # Check if click was on the Sync part
        item_values = self.patient_tree.item(item_id)["values"]
        if len(item_values) < 8 or "Sync" not in str(item_values[7]):
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
        """Add a message to the log display with thread safety"""
        try:
            # Execute in a thread-safe way through the event loop
            self.root.after(0, lambda: self._add_log_to_ui(message))
        except Exception as e:
            print(f"Error logging to UI: {e}")

    def _add_log_to_ui(self, message):
        """Add a log message to the UI"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if hasattr(self, 'log_text') and self.log_text.winfo_exists():
            self.log_text.insert(tk.END, f"{timestamp} - {message}\n")
            self.log_text.see(tk.END)

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
        """Start the TCP server in a non-blocking way"""
        if self.tcp_server.is_running:
            self.logger.warning("Server is already running")
            return
        
        # Update UI immediately to provide feedback
        self.server_status.config(text="Server: Starting...")
        
        # Start the server (non-blocking)
        self.tcp_server.start()

    def server_started(self):
        """Update UI when server starts"""
        self._update_dashboard_status()
        self.log("Server started successfully")

    def server_stopped(self):
        """Update UI when server stops"""
        self._update_dashboard_status()
        self.log("Server stopped")

    def update_connection_count(self):
        """Update the connection count display"""
        if self.tcp_server:
            count = self.tcp_server.get_client_count()
            self.connection_status.config(text=f"Connections: {count}")
            self.connection_count_label.config(text=f"Connections: {count}")

    def log_connection(self, host, port):
        """Log a new connection"""
        self.log(f"New connection from {host}:{port}")

    def log_disconnection(self, host, port):
        """Log a disconnection"""
        self.log(f"Client {host}:{port} disconnected")

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
            
    def on_closing(self, force=False):
        """Handle window closing
        
        Args:
            force: If True, completely exit the application even if in-progress tasks exist
        """
        try:
            # Set shutdown flag first
            self.is_shutting_down = True
            
            # Log shutdown
            self.logger.info("Application closing initiated")
            
            # Stop system tray icon
            if hasattr(self, 'tray_icon') and self.tray_icon:
                try:
                    self.tray_icon.stop()
                except Exception as e:
                    self.logger.warning(f"Error stopping tray icon: {e}")
            
            # Remove logger callback
            try:
                self.logger.remove_ui_callback(self._handle_log_message)
            except Exception as e:
                self.logger.warning(f"Error removing logger callback: {e}")
            
            # Create event loop for cleanup if needed
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            # Run cleanup in the loop with timeout
            try:
                # Stop sync manager with timeout to prevent hanging
                if self.sync_manager:
                    task = asyncio.ensure_future(self.sync_manager.stop())
                    loop.run_until_complete(asyncio.wait_for(task, timeout=3.0))
            except (asyncio.TimeoutError, Exception) as e:
                self.logger.warning(f"Sync manager shutdown timed out or failed: {e}")
            
            # Stop the server synchronously after sync manager
            if self.tcp_server and self.tcp_server.is_running:
                try:
                    self.tcp_server.stop_sync()
                except Exception as e:
                    self.logger.warning(f"Error stopping TCP server: {e}")
            
            # Set destroyed flag
            self.is_destroyed = True
            
            # Explicitly stop any running threads
            import threading
            for thread in threading.enumerate():
                if thread is not threading.current_thread() and thread.daemon is False:
                    self.logger.info(f"Non-daemon thread still running: {thread.name}")
            
            # Close the window and destroy all child windows
            for widget in list(self.root.children.values()):
                if isinstance(widget, tk.Toplevel):
                    try:
                        widget.destroy()
                    except Exception as e:
                        self.logger.warning(f"Error destroying child window: {e}")
            
            # Quit and destroy
            try:
                self.root.quit()
                self.root.destroy()
            except Exception as e:
                self.logger.warning(f"Error quitting/destroying root: {e}")
                
            # Force exit if requested
            if force:
                self.logger.info("Forcing application exit")
                import os
                import sys
                try:
                    # Try to use sys.exit first for a more graceful exit
                    sys.exit(0)
                except SystemExit:
                    # This exception is expected, but we'll catch it to add logging
                    self.logger.info("sys.exit executed")
                except Exception as e:
                    self.logger.error(f"Error during sys.exit: {e}")
                    # Fall back to os._exit for hard exit
                    os._exit(0)
                
        except Exception as e:
            self.logger.error(f"Error during shutdown: {str(e)}\n{traceback.format_exc()}")
            try:
                self.root.quit()
                self.root.destroy()
            except:
                pass
                
            # Force exit if requested
            if force:
                import os
                import sys
                try:
                    sys.exit(0)
                except:
                    os._exit(0)
                
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
        self.update_ui_status()
        self.log("Server auto-started successfully")
        
        # Start periodic updates
        self._schedule_updates()

    def _server_start_failed_ui_update(self):
        """Update UI after server failed to start"""
        self.server_status.config(text=self.STATUS_SERVER_FAILED)
        self.start_button.config(state=tk.NORMAL)
        self.log("Failed to auto-start server")

    def _treeview_sort_column(self, tree, col, is_num=False, reverse=False):
        """Sort treeview column when header is clicked."""
        # Get all items in the tree
        items = [(tree.set(item, col) if col != "#0" else tree.item(item)["text"], item) for item in tree.get_children("")]
        
        # Sort the items
        items.sort(reverse=reverse, 
                  key=lambda x: (float(x[0]) if is_num and x[0].replace('.','',1).isdigit() else x[0].lower()))
        
        # Rearrange items in sorted positions
        for index, (_, item) in enumerate(items):
            tree.move(item, "", index)
        
        # Reverse sort next time
        tree.heading(col, command=lambda: self._treeview_sort_column(tree, col, is_num, not reverse))

    def _on_date_range_changed(self, event=None):
        """Handle date range selection change"""
        if self.date_range_var.get() == "Custom":
            self.custom_date_frame.pack(side=tk.LEFT, padx=5)
        else:
            self.custom_date_frame.pack_forget()
        self._on_filter_changed()

    def _on_filter_changed(self, event=None):
        """Handle filter changes and update the display"""
        try:
            # Clear existing items
            for item in self.patient_tree.get_children():
                self.patient_tree.delete(item)
            
            # Build the WHERE clause based on filters
            where_clauses = []
            params = []
            
            # Date filter
            date_range = self.date_range_var.get()
            if date_range != "All":
                if date_range == "Today":
                    where_clauses.append("DATE(created_at) = DATE('now')")
                elif date_range == "Last 7 Days":
                    where_clauses.append("created_at >= datetime('now', '-7 days')")
                elif date_range == "Last 30 Days":
                    where_clauses.append("created_at >= datetime('now', '-30 days')")
                elif date_range == "Custom":
                    if self.date_from_var.get():
                        where_clauses.append("created_at >= ?")
                        params.append(f"{self.date_from_var.get()} 00:00:00")
                    if self.date_to_var.get():
                        where_clauses.append("created_at <= ?")
                        params.append(f"{self.date_to_var.get()} 23:59:59")
            
            # Status filter
            status_filter = self.status_filter_var.get()
            if status_filter != "All":
                if status_filter == "Synced":
                    where_clauses.append("sync_status = 'synced'")
                else:  # Not Synced
                    where_clauses.append("(sync_status IS NULL OR sync_status != 'synced')")
            
            # Search filter
            search_text = self.search_var.get().strip()
            if search_text:
                where_clauses.append("(patient_id LIKE ? OR name LIKE ? OR sample_id LIKE ?)")
                search_param = f"%{search_text}%"
                params.extend([search_param, search_param, search_param])
            
            # Construct the final query
            query = '''
                SELECT id, patient_id, name, dob, sex, physician, sample_id, created_at, sync_status
                FROM patients
            '''
            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)
            query += " ORDER BY created_at DESC LIMIT 100"
            
            # Execute query
            conn = self.db_manager._ensure_connection()
            cursor = conn.cursor()
            cursor.execute(query, params)
            patients = cursor.fetchall()
            
            # Add filtered results to treeview
            for patient in patients:
                _, patient_id, name, _, sex, _, sample_id, created_at, sync_status = patient
                created_date = created_at[:16] if created_at else "-"
                sync_status = sync_status or "Not Synced"
                actions = "View Results"
                
                if self.config.get("external_server", {}).get("enabled", False):
                    if sync_status != "synced":
                        actions += " | Sync"
                
                item_id = self.patient_tree.insert("", tk.END,
                    values=(patient_id, name, sample_id, sex, created_date, sync_status, actions))
                
                tags = ["view_results"]
                if sync_status != "synced" and self.config.get("external_server", {}).get("enabled", False):
                    tags.append("sync")
                self.patient_tree.item(item_id, tags=tuple(tags))
        except Exception as e:
            self.logger.error(f"Error applying filters: {e}")
            messagebox.showerror("Error", f"Failed to apply filters: {str(e)}")

    def _get_icon_paths(self):
        """Get possible icon file paths for both development and packaged environments"""
        import sys
        
        # Base paths to try
        base_paths = []
        
        # For PyInstaller packaged app
        if getattr(sys, 'frozen', False):
            # Running in a PyInstaller bundle
            bundle_dir = os.path.dirname(sys.executable)
            base_paths.extend([
                bundle_dir,  # Icon files copied to root
                os.path.join(bundle_dir, 'gui', 'resources'),
                os.path.join(bundle_dir, 'src', 'gui', 'resources'),
                os.path.join(bundle_dir, '_internal'),  # PyInstaller internal folder
                os.path.join(bundle_dir, '_internal', 'gui', 'resources'),
                os.path.join(bundle_dir, '_internal', 'src', 'gui', 'resources'),
            ])
            # Also try sys._MEIPASS which is the PyInstaller temp folder
            if hasattr(sys, '_MEIPASS'):
                meipass = sys._MEIPASS
                base_paths.extend([
                    meipass,
                    os.path.join(meipass, 'gui', 'resources'),
                    os.path.join(meipass, 'src', 'gui', 'resources'),
                ])
        
        # For development environment
        current_dir = os.path.dirname(__file__)
        base_paths.extend([
            os.path.join(current_dir, "resources"),
            os.path.join(os.path.dirname(current_dir), "gui", "resources"),
            os.path.join(os.path.dirname(os.path.dirname(current_dir)), "gui", "resources"),
        ])
        
        # Add absolute path from project root
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        base_paths.append(os.path.join(project_root, "src", "gui", "resources"))
        
        # Generate full icon paths
        icon_paths = []
        icon_files = ["icon.ico", "icon.png"]
        
        for base_path in base_paths:
            for icon_file in icon_files:
                icon_path = os.path.join(base_path, icon_file)
                if icon_path not in icon_paths:  # Avoid duplicates
                    icon_paths.append(icon_path)
        
        # Log the paths being checked for debugging
        # if hasattr(self, 'logger'):
        #     self.logger.debug(f"Checking icon paths: {icon_paths}")
        
        return icon_paths

    def _init_system_tray(self):
        """Initialize system tray icon and menu"""
        try:
            # Load icon for system tray - try multiple paths and formats
            icon_paths = self._get_icon_paths()
            
            self.tray_image = None
            for icon_path in icon_paths:
                if os.path.exists(icon_path):
                    try:
                        self.tray_image = Image.open(icon_path)
                        # Convert to RGBA if needed for better compatibility
                        if self.tray_image.mode != 'RGBA':
                            self.tray_image = self.tray_image.convert('RGBA')
                        # Resize to standard tray icon size
                        self.tray_image = self.tray_image.resize((32, 32), Image.Resampling.LANCZOS)
                        # self.logger.info(f"Loaded tray icon from: {icon_path}")
                        break
                    except Exception as e:
                        # self.logger.warning(f"Failed to load icon from {icon_path}: {e}")
                        continue
            
            if self.tray_image is None:
                # Create a simple default icon if no file exists
                self.tray_image = Image.new('RGBA', (32, 32), color=(0, 120, 215, 255))  # Windows blue
                # self.logger.warning("Using default tray icon - no icon file found")
            
            # Create system tray menu
            self.tray_menu = pystray.Menu(
                pystray.MenuItem("Show", self.show_window, default=True),
                pystray.MenuItem("Hide", self.hide_window),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Settings", self._show_settings),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit", self.quit_application)
            )
            
            # Create system tray icon
            self.tray_icon = pystray.Icon(
                "LabSync",
                self.tray_image,
                "LabSync - Lab Data Analyzer",
                self.tray_menu
            )
            
            # Start tray icon in background thread
            self.tray_thread = threading.Thread(target=self._run_tray, daemon=True)
            self.tray_thread.start()
            
        except Exception as e:
            self.logger.warning(f"Failed to initialize system tray: {e}")
            self.tray_icon = None

    def _run_tray(self):
        """Run the system tray icon"""
        if self.tray_icon:
            self.tray_icon.run()

    def _show_tray_notification(self):
        """Show initial system tray notification"""
        try:
            if hasattr(self.tray_icon, 'notify'):
                self.tray_icon.notify("LabSync is running in the system tray. Click the X button to minimize to tray.")
        except Exception as e:
            self.logger.debug(f"Could not show tray notification: {e}")

    def show_window(self, icon=None, item=None):
        """Show the main window"""
        if self.is_hidden:
            self.root.after(0, self._show_window_main_thread)

    def _show_window_main_thread(self):
        """Show window in main thread"""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.is_hidden = False

    def hide_window(self, icon=None, item=None):
        """Hide the main window to system tray"""
        self.root.withdraw()
        self.is_hidden = True

    def on_window_close(self):
        """Handle window close button - minimize to tray instead of closing"""
        if self.tray_icon:
            self.hide_window()
            # Show a notification that the app is still running
            if hasattr(self.tray_icon, 'notify'):
                self.tray_icon.notify("LabSync is still running in the system tray")
        else:
            # Fallback to normal closing if tray isn't available
            self.quit_application()

    def quit_application(self, icon=None, item=None):
        """Actually quit the application"""
        self.on_closing(force=True)