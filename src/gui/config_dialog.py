"""
Configuration dialog for application settings
"""
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import re
from datetime import datetime
from ..utils.analyzers import AnalyzerDefinitions

class ConfigDialog(tk.Toplevel):
    # Constants
    COMBOBOX_SELECTED = "<<ComboboxSelected>>"
    
    def __init__(self, parent, config, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.config = config
        self.result = None
        
        # Window setup
        self.title("Configuration Settings")
        self.geometry("500x600")  # Made taller to accommodate all settings
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        
        # Create main container
        main_container = ttk.Frame(self)
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Create a notebook for tabbed interface
        self.notebook = ttk.Notebook(main_container)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # Create tabs
        self.basic_tab = ttk.Frame(self.notebook)
        self.server_tab = ttk.Frame(self.notebook)
        
        # Add tabs to notebook
        self.notebook.add(self.basic_tab, text="Basic Settings")
        self.notebook.add(self.server_tab, text="Server & Sync")
        
        # Create widgets in each tab
        self._create_basic_widgets()
        self._create_server_widgets()
        
        # Create buttons at the bottom - now in a separate frame below the main container
        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        ttk.Button(button_frame, text="Save", command=self._save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=self._cancel).pack(side=tk.RIGHT, padx=5)
        
        # Center the dialog
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'+{x}+{y}')

        # Setup initial state of various options
        self._update_sync_options()
        self._update_auth_options()
        
    def _create_basic_widgets(self):
        """Create basic settings widgets"""
        # Frame for basic settings
        main_frame = ttk.Frame(self.basic_tab, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Basic settings
        basic_frame = ttk.LabelFrame(main_frame, text="Application Settings", padding="5")
        basic_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Port
        ttk.Label(basic_frame, text="Port:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.port_var = tk.StringVar(value=str(self.config.get("port", 5000)))
        port_entry = ttk.Entry(basic_frame, textvariable=self.port_var, width=10)
        port_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        
        # Application name
        ttk.Label(basic_frame, text="Application Name:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.app_name_var = tk.StringVar(value=self.config.get("app_name", "Basic Analyzer"))
        app_name_entry = ttk.Entry(basic_frame, textvariable=self.app_name_var, width=30)
        app_name_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        
        # Analyzer Type
        ttk.Label(basic_frame, text="Analyzer Type:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        self.analyzer_type_var = tk.StringVar(value=self.config.get("analyzer_type", AnalyzerDefinitions.SYSMEX_XN_L))
        analyzer_type_combo = ttk.Combobox(basic_frame, textvariable=self.analyzer_type_var, 
                                         values=AnalyzerDefinitions.get_supported_analyzers(), width=20)
        analyzer_type_combo.grid(row=3, column=1, sticky=tk.W, padx=5, pady=2)
        analyzer_type_combo.bind(self.COMBOBOX_SELECTED, self._on_analyzer_type_changed)
        
        # Protocol
        ttk.Label(basic_frame, text="Protocol:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=2)
        self.protocol_var = tk.StringVar(value=self.config.get("protocol", AnalyzerDefinitions.PROTOCOL_ASTM))
        protocol_combo = ttk.Combobox(basic_frame, textvariable=self.protocol_var, 
                                    values=AnalyzerDefinitions.get_supported_protocols(), width=20)
        protocol_combo.grid(row=4, column=1, sticky=tk.W, padx=5, pady=2)
        
        # Auto-start option
        self.auto_start_var = tk.BooleanVar(value=self.config.get("auto_start", False))
        auto_start_check = ttk.Checkbutton(basic_frame, text="Auto-start server", variable=self.auto_start_var)
        auto_start_check.grid(row=5, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2)
        
    def _on_analyzer_type_changed(self, event):
        """Handle analyzer type selection change"""
        analyzer_type = self.analyzer_type_var.get()
        self.protocol_var.set(AnalyzerDefinitions.get_protocol_for_analyzer(analyzer_type))
        
    def _create_server_widgets(self):
        """Create server and sync settings widgets"""
        main_frame = ttk.Frame(self.server_tab, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # External server settings
        server_frame = ttk.LabelFrame(main_frame, text="External Server", padding="5")
        server_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Enable sync
        self.sync_enabled_var = tk.BooleanVar(value=self.config.get("external_server", {}).get("enabled", False))
        sync_check = ttk.Checkbutton(server_frame, text="Enable External Sync", variable=self.sync_enabled_var)
        sync_check.grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2)
        
        # Server URL
        ttk.Label(server_frame, text="Server URL:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.server_url_var = tk.StringVar(value=self.config.get("external_server", {}).get("url", ""))
        server_url_entry = ttk.Entry(server_frame, textvariable=self.server_url_var, width=40)
        server_url_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        
        # Endpoint path
        ttk.Label(server_frame, text="Endpoint Path:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.endpoint_path_var = tk.StringVar(value=self.config.get("external_server", {}).get("endpoint_path", "/api/results"))
        endpoint_path_entry = ttk.Entry(server_frame, textvariable=self.endpoint_path_var, width=40)
        endpoint_path_entry.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        
        # Request method
        ttk.Label(server_frame, text="HTTP Method:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        self.http_method_var = tk.StringVar(value=self.config.get("external_server", {}).get("http_method", "POST"))
        http_method_combo = ttk.Combobox(server_frame, textvariable=self.http_method_var, 
                                       values=["POST", "PUT", "PATCH"], width=10)
        http_method_combo.grid(row=3, column=1, sticky=tk.W, padx=5, pady=2)
        
        # Sync frequency
        ttk.Label(server_frame, text="Sync Frequency:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=2)
        self.sync_freq_var = tk.StringVar(value=self.config.get("external_server", {}).get("sync_frequency", "scheduled"))
        sync_freq_combo = ttk.Combobox(server_frame, textvariable=self.sync_freq_var, 
                                      values=["realtime", "scheduled", "cron"])
        sync_freq_combo.grid(row=4, column=1, sticky=tk.W, padx=5, pady=2)
        sync_freq_combo.bind(self.COMBOBOX_SELECTED, self._on_sync_freq_changed)
        
        # Create a new frame for additional sync settings
        self.sync_options_frame = ttk.LabelFrame(main_frame, text="Sync Options", padding="5")
        self.sync_options_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # For scheduled sync - time of day
        self.scheduled_time_label = ttk.Label(self.sync_options_frame, text="Scheduled Time:")
        self.scheduled_time_label.grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        
        # Hour selector (0-23)
        self.hour_var = tk.StringVar(value=self.config.get("external_server", {}).get("scheduled_hour", "0"))
        self.hour_selector = ttk.Combobox(self.sync_options_frame, textvariable=self.hour_var, 
                                   values=[str(i).zfill(2) for i in range(24)], width=5)
        self.hour_selector.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        
        self.time_separator = ttk.Label(self.sync_options_frame, text=":")
        self.time_separator.grid(row=0, column=2)
        
        # Minute selector (0-59)
        self.minute_var = tk.StringVar(value=self.config.get("external_server", {}).get("scheduled_minute", "0"))
        self.minute_selector = ttk.Combobox(self.sync_options_frame, textvariable=self.minute_var, 
                                     values=[str(i).zfill(2) for i in range(60)], width=5)
        self.minute_selector.grid(row=0, column=3, sticky=tk.W, padx=5, pady=2)
        
        # For cron sync - cron expression
        self.cron_label = ttk.Label(self.sync_options_frame, text="Cron Expression:")
        self.cron_label.grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        
        self.cron_var = tk.StringVar(value=self.config.get("external_server", {}).get("cron_expression", "0 * * * *"))
        self.cron_entry = ttk.Entry(self.sync_options_frame, textvariable=self.cron_var, width=30)
        self.cron_entry.grid(row=1, column=1, columnspan=3, sticky=tk.W, padx=5, pady=2)
        
        # Add a help text for cron
        self.cron_help = ttk.Label(self.sync_options_frame, 
                            text="Format: minute hour day month weekday (0 * * * * = every hour)")
        self.cron_help.grid(row=2, column=0, columnspan=4, sticky=tk.W, padx=5, pady=2)
        
        # Retry settings
        ttk.Label(self.sync_options_frame, text="Retry Interval (sec):").grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        self.retry_interval_var = tk.StringVar(value=str(self.config.get("external_server", {}).get("retry_interval", 60)))
        retry_entry = ttk.Entry(self.sync_options_frame, textvariable=self.retry_interval_var, width=10)
        retry_entry.grid(row=3, column=1, columnspan=3, sticky=tk.W, padx=5, pady=2)

        # Authentication method frame (moved from auth tab to server tab)
        auth_frame = ttk.LabelFrame(main_frame, text="Authentication Method", padding="5")
        auth_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Authentication method selection
        ttk.Label(auth_frame, text="Method:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.auth_method_var = tk.StringVar(value=self.config.get("external_server", {}).get("auth_method", "api_key"))
        auth_method_combo = ttk.Combobox(auth_frame, textvariable=self.auth_method_var, 
                                       values=["none", "api_key", "bearer_token", "basic_auth", "custom_header", "oauth2"], width=15)
        auth_method_combo.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        auth_method_combo.bind(self.COMBOBOX_SELECTED, self._on_auth_method_changed)
        
        # Authentication details frame
        self.auth_details_frame = ttk.LabelFrame(main_frame, text="Authentication Details", padding="5")
        self.auth_details_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # API Key fields
        self.api_key_label = ttk.Label(self.auth_details_frame, text="API Key:")
        self.api_key_label.grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.api_key_var = tk.StringVar(value=self.config.get("external_server", {}).get("api_key", ""))
        self.api_key_entry = ttk.Entry(self.auth_details_frame, textvariable=self.api_key_var, width=40)
        self.api_key_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        
        self.api_key_header_label = ttk.Label(self.auth_details_frame, text="Header Name:")
        self.api_key_header_label.grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.api_key_header_var = tk.StringVar(value=self.config.get("external_server", {}).get("api_key_header", "X-API-Key"))
        self.api_key_header_entry = ttk.Entry(self.auth_details_frame, textvariable=self.api_key_header_var, width=20)
        self.api_key_header_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        
        # Bearer Token fields
        self.bearer_token_label = ttk.Label(self.auth_details_frame, text="Bearer Token:")
        self.bearer_token_label.grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.bearer_token_var = tk.StringVar(value=self.config.get("external_server", {}).get("bearer_token", ""))
        self.bearer_token_entry = ttk.Entry(self.auth_details_frame, textvariable=self.bearer_token_var, width=40, show="•")
        self.bearer_token_entry.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        
        # Basic Auth fields
        self.username_label = ttk.Label(self.auth_details_frame, text="Username:")
        self.username_label.grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        self.username_var = tk.StringVar(value=self.config.get("external_server", {}).get("username", ""))
        self.username_entry = ttk.Entry(self.auth_details_frame, textvariable=self.username_var, width=20)
        self.username_entry.grid(row=3, column=1, sticky=tk.W, padx=5, pady=2)
        
        self.password_label = ttk.Label(self.auth_details_frame, text="Password:")
        self.password_label.grid(row=4, column=0, sticky=tk.W, padx=5, pady=2)
        self.password_var = tk.StringVar(value=self.config.get("external_server", {}).get("password", ""))
        self.password_entry = ttk.Entry(self.auth_details_frame, textvariable=self.password_var, width=20, show="•")
        self.password_entry.grid(row=4, column=1, sticky=tk.W, padx=5, pady=2)
        
        # Custom Header fields
        self.custom_header_name_label = ttk.Label(self.auth_details_frame, text="Header Name:")
        self.custom_header_name_label.grid(row=5, column=0, sticky=tk.W, padx=5, pady=2)
        self.custom_header_name_var = tk.StringVar(value=self.config.get("external_server", {}).get("custom_header_name", ""))
        self.custom_header_name_entry = ttk.Entry(self.auth_details_frame, textvariable=self.custom_header_name_var, width=20)
        self.custom_header_name_entry.grid(row=5, column=1, sticky=tk.W, padx=5, pady=2)
        
        self.custom_header_value_label = ttk.Label(self.auth_details_frame, text="Header Value:")
        self.custom_header_value_label.grid(row=6, column=0, sticky=tk.W, padx=5, pady=2)
        self.custom_header_value_var = tk.StringVar(value=self.config.get("external_server", {}).get("custom_header_value", ""))
        self.custom_header_value_entry = ttk.Entry(self.auth_details_frame, textvariable=self.custom_header_value_var, width=40)
        self.custom_header_value_entry.grid(row=6, column=1, sticky=tk.W, padx=5, pady=2)
        
        # OAuth2 fields
        self.oauth2_token_url_label = ttk.Label(self.auth_details_frame, text="Token URL:")
        self.oauth2_token_url_label.grid(row=7, column=0, sticky=tk.W, padx=5, pady=2)
        self.oauth2_token_url_var = tk.StringVar(value=self.config.get("external_server", {}).get("oauth2_token_url", ""))
        self.oauth2_token_url_entry = ttk.Entry(self.auth_details_frame, textvariable=self.oauth2_token_url_var, width=40)
        self.oauth2_token_url_entry.grid(row=7, column=1, sticky=tk.W, padx=5, pady=2)
        
        self.client_id_label = ttk.Label(self.auth_details_frame, text="Client ID:")
        self.client_id_label.grid(row=8, column=0, sticky=tk.W, padx=5, pady=2)
        self.client_id_var = tk.StringVar(value=self.config.get("external_server", {}).get("client_id", ""))
        self.client_id_entry = ttk.Entry(self.auth_details_frame, textvariable=self.client_id_var, width=30)
        self.client_id_entry.grid(row=8, column=1, sticky=tk.W, padx=5, pady=2)
        
        self.client_secret_label = ttk.Label(self.auth_details_frame, text="Client Secret:")
        self.client_secret_label.grid(row=9, column=0, sticky=tk.W, padx=5, pady=2)
        self.client_secret_var = tk.StringVar(value=self.config.get("external_server", {}).get("client_secret", ""))
        self.client_secret_entry = ttk.Entry(self.auth_details_frame, textvariable=self.client_secret_var, width=30, show="•")
        self.client_secret_entry.grid(row=9, column=1, sticky=tk.W, padx=5, pady=2)
        
        self.scope_label = ttk.Label(self.auth_details_frame, text="Scope:")
        self.scope_label.grid(row=10, column=0, sticky=tk.W, padx=5, pady=2)
        self.scope_var = tk.StringVar(value=self.config.get("external_server", {}).get("scope", ""))
        self.scope_entry = ttk.Entry(self.auth_details_frame, textvariable=self.scope_var, width=30)
        self.scope_entry.grid(row=10, column=1, sticky=tk.W, padx=5, pady=2)

    def _on_sync_freq_changed(self, event):
        """Handle sync frequency selection change"""
        self._update_sync_options()
    
    def _on_auth_method_changed(self, event):
        """Handle authentication method selection change"""
        self._update_auth_options()
            
    def _update_sync_options(self):
        """Update visibility of sync options based on selected frequency"""
        sync_freq = self.sync_freq_var.get()
        
        # Hide all specific sync option widgets first
        self.scheduled_time_label.grid_remove()
        self.hour_selector.grid_remove()
        self.time_separator.grid_remove()
        self.minute_selector.grid_remove()
        self.cron_label.grid_remove()
        self.cron_entry.grid_remove()
        self.cron_help.grid_remove()
        
        # Show relevant options based on the selected mode
        if sync_freq == "scheduled":
            # Show scheduled time options
            self.scheduled_time_label.grid()
            self.hour_selector.grid()
            self.time_separator.grid()
            self.minute_selector.grid()
        elif sync_freq == "cron":
            # Show cron expression options
            self.cron_label.grid()
            self.cron_entry.grid()
            self.cron_help.grid()
        
        # Note: For "realtime" we don't need to show any specific options
    
    def _update_auth_options(self):
        """Update visibility of authentication options based on selected method"""
        auth_method = self.auth_method_var.get()
        
        # Hide all auth details initially
        for i in range(11):
            for widget in self.auth_details_frame.grid_slaves(row=i):
                widget.grid_remove()
        
        # Show relevant authentication fields based on the selected method
        if auth_method == "api_key":
            self.api_key_label.grid()
            self.api_key_entry.grid()
            self.api_key_header_label.grid()
            self.api_key_header_entry.grid()
        elif auth_method == "bearer_token":
            self.bearer_token_label.grid()
            self.bearer_token_entry.grid()
        elif auth_method == "basic_auth":
            self.username_label.grid()
            self.username_entry.grid()
            self.password_label.grid()
            self.password_entry.grid()
        elif auth_method == "custom_header":
            self.custom_header_name_label.grid()
            self.custom_header_name_entry.grid()
            self.custom_header_value_label.grid()
            self.custom_header_value_entry.grid()
        elif auth_method == "oauth2":
            self.oauth2_token_url_label.grid()
            self.oauth2_token_url_entry.grid()
            self.client_id_label.grid()
            self.client_id_entry.grid()
            self.client_secret_label.grid()
            self.client_secret_entry.grid()
            self.scope_label.grid()
            self.scope_entry.grid()
            
    def _validate_cron_expression(self, cron_expr):
        """Basic validation for cron expressions"""
        parts = cron_expr.split()
        if len(parts) != 5:
            return False
            
        for part in parts:
            # Check if part is either * or contains valid numbers
            if part != '*' and not all(c in '0123456789,-/' for c in part):
                return False
        return True

    def _validate_sync_settings(self):
        """Validate sync-related settings"""
        sync_freq = self.sync_freq_var.get()
        
        if sync_freq == "scheduled":
            hour = int(self.hour_var.get())
            minute = int(self.minute_var.get())
            
            if not (0 <= hour <= 23):
                raise ValueError("Hour must be between 0 and 23")
                
            if not (0 <= minute <= 59):
                raise ValueError("Minute must be between 0 and 59")
                
        elif sync_freq == "cron":
            if not self._validate_cron_expression(self.cron_var.get()):
                raise ValueError("Invalid cron expression format")
        
        retry_interval = int(self.retry_interval_var.get())
        if retry_interval < 10:
            raise ValueError("Retry interval must be at least 10 seconds")

    def _get_auth_config(self):
        """Get authentication configuration based on selected method"""
        auth_method = self.auth_method_var.get()
        config = {"auth_method": auth_method}
        
        if auth_method == "api_key":
            config.update({
                "api_key": self.api_key_var.get(),
                "api_key_header": self.api_key_header_var.get()
            })
        elif auth_method == "bearer_token":
            config.update({
                "bearer_token": self.bearer_token_var.get()
            })
        elif auth_method == "basic_auth":
            config.update({
                "username": self.username_var.get(),
                "password": self.password_var.get()
            })
        elif auth_method == "custom_header":
            config.update({
                "custom_header_name": self.custom_header_name_var.get(),
                "custom_header_value": self.custom_header_value_var.get()
            })
        elif auth_method == "oauth2":
            if not self.oauth2_token_url_var.get():
                raise ValueError("Token URL is required for OAuth2 authentication")
                
            config.update({
                "oauth2_token_url": self.oauth2_token_url_var.get(),
                "client_id": self.client_id_var.get(),
                "client_secret": self.client_secret_var.get(),
                "scope": self.scope_var.get()
            })
            
        return config

    def _save(self):
        """Save the configuration"""
        try:
            # Basic validation
            analyzer_type = self.analyzer_type_var.get()
            protocol = self.protocol_var.get()
            port = int(self.port_var.get())
            
            # Verify analyzer and protocol compatibility
            correct_protocol = AnalyzerDefinitions.get_protocol_for_analyzer(analyzer_type)
            if protocol != correct_protocol:
                messagebox.showwarning(
                    "Configuration Warning", 
                    f"{analyzer_type} typically uses {correct_protocol} protocol. " +
                    "Your selection may not work correctly."
                )
            
            # Validate sync settings
            self._validate_sync_settings()
            
            # Get authentication config
            auth_config = self._get_auth_config()
            
            # Prepare external server config
            external_server_config = {
                "enabled": self.sync_enabled_var.get(),
                "url": self.server_url_var.get(),
                "endpoint_path": self.endpoint_path_var.get(),
                "http_method": self.http_method_var.get(),
                "sync_frequency": self.sync_freq_var.get(),
                "scheduled_hour": self.hour_var.get(),
                "scheduled_minute": self.minute_var.get(),
                "cron_expression": self.cron_var.get(),
                "retry_interval": int(self.retry_interval_var.get()),
                **auth_config
            }
                
            # Update configuration
            self.config.update(
                port=port,
                app_name=self.app_name_var.get(),
                analyzer_type=analyzer_type,
                protocol=protocol,
                auto_start=self.auto_start_var.get(),
                external_server=external_server_config
            )
            
            self.result = True
            self.destroy()
            
        except ValueError as e:
            messagebox.showerror("Invalid Input", str(e))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save configuration: {str(e)}")

    def _cancel(self):
        """Cancel the dialog"""
        self.result = False
        self.destroy()