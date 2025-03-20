"""
External server synchronization module
"""
import asyncio
import aiohttp
import json
import logging
import time
from datetime import datetime
from croniter import croniter

class SyncManager:
    """
    Handles synchronization of local data to external server
    Supports real-time, scheduled, and cron-based synchronization
    """
    def __init__(self, config, db_manager, logger=None):
        """
        Initialize the sync manager
        
        Args:
            config: Configuration object with sync settings
            db_manager: Database manager for accessing data to sync
            logger: Logger for sync events
        """
        self.config = config
        self.db_manager = db_manager
        self.logger = logger or logging.getLogger(__name__)
        self.running = False
        self.task = None
        self.last_sync_time = None
        self.tasks = []  # Track all async tasks
        
        # Get the retry interval from config or use default
        ext_server_config = self.config.get("external_server", {})
        self.retry_delay = int(ext_server_config.get("retry_interval", 60))
        self.initial_retry_delay = self.retry_delay  # Keep the initial value for resets
        self.max_retry_delay = 300  # Maximum retry delay (5 minutes)

    async def start(self):
        """Start the sync manager based on configuration"""
        if not self._is_sync_enabled():
            self.logger.info("External server sync is disabled in configuration")
            return False
            
        # Cancel any existing tasks
        await self.stop()
            
        # Start sync based on frequency
        sync_frequency = self._get_sync_frequency()
        
        try:
            if sync_frequency == "realtime":
                self.task = asyncio.create_task(self._sync_realtime())
            elif sync_frequency == "scheduled":
                hour, minute = self._get_scheduled_time()
                self.task = asyncio.create_task(self._sync_scheduled_time(hour, minute))
            elif sync_frequency == "cron":
                cron_expr = self._get_cron_expression()
                self.task = asyncio.create_task(self._sync_cron(cron_expr))
            else:
                self.logger.error(f"Unknown sync frequency: {sync_frequency}")
                return False
                
            self.tasks.append(self.task)
            self.running = True
            self.logger.info(f"Started external sync with {sync_frequency} frequency")
            self.db_manager.log_info(f"Started external sync ({sync_frequency})", "sync")
            return True
            
        except Exception as e:
            self.logger.error(f"Error starting sync manager: {e}")
            return False

    async def stop(self):
        """Stop the sync manager"""
        if not self.running:
            return
            
        self.running = False  # Set this first to signal tasks to stop
        
        # Cancel all tasks
        for task in self.tasks:
            if not task.done():
                try:
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=2.0)
                    except asyncio.TimeoutError:
                        self.logger.warning("Timeout waiting for sync task to stop")
                    except asyncio.CancelledError:
                        pass  # This is expected
                except Exception as e:
                    self.logger.error(f"Error cancelling task: {e}")

        # Clear task list
        self.tasks.clear()
        self.task = None
            
        self.logger.info("Stopped external sync")

    async def sync_now(self):
        """
        Perform an immediate sync
        
        Returns:
            Tuple (success, message, count) - success status, message, and count of records synced
        """
        try:
            # Get local results that haven't been synced yet
            results = self._get_pending_results()
            if not results:
                message = "No new records to sync"
                self.logger.info(message)
                return True, message, 0
                
            # Convert to JSON payload for sending to server
            payload = self._prepare_payload(results)
            
            # Send to external server
            success, message = await self._send_to_server(payload)
            
            # Update sync status if successful
            if success:
                for result_id in [r[0] for r in results]:
                    self.db_manager.mark_result_synced(result_id)
                
                # Record successful sync
                self.db_manager.record_sync_attempt("success", message, len(results))
                self.last_sync_time = datetime.now()
                self.retry_delay = 5  # Reset backoff on success
                
                self.logger.info(f"Successfully synced {len(results)} records")
                return True, message, len(results)
            else:
                # Record failed sync
                self.db_manager.record_sync_attempt("failed", message, 0)
                self.logger.error(f"Sync failed: {message}")
                return False, message, 0
                
        except Exception as e:
            error_msg = f"Error during sync: {str(e)}"
            self.logger.error(error_msg)
            self.db_manager.record_sync_attempt("error", error_msg, 0)
            return False, error_msg, 0
    
    async def _sync_realtime(self):
        """Sync data in real-time (immediately when new data arrives)"""
        self.logger.info("Starting real-time sync")
        try:
            while self.running:  # Check running flag
                try:
                    # Check for any pending results
                    await self.sync_now()
                except Exception as e:
                    self.logger.error(f"Error in real-time sync cycle: {e}")
                # Wait a short time before checking again
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            self.logger.info("Real-time sync cancelled")
        finally:
            # Cleanup any remaining connections
            await self._cleanup_connections()

    async def _sync_scheduled(self, interval_minutes):
        """Sync data on a scheduled interval"""
        self.logger.info(f"Starting scheduled sync every {interval_minutes} minutes")
        try:
            while True:
                await self.sync_now()
                # Wait for the specified interval
                await asyncio.sleep(interval_minutes * 60)
        except asyncio.CancelledError:
            self.logger.info("Scheduled sync cancelled")
            raise
    
    async def _sync_cron(self, cron_expr):
        """Sync data on a cron schedule"""
        self.logger.info(f"Starting cron-based sync with schedule: {cron_expr}")
        try:
            while True:
                # Calculate time until next execution
                now = datetime.now()
                cron = croniter(cron_expr, now)
                next_time = cron.get_next(datetime)
                
                # Wait until next scheduled time
                wait_seconds = (next_time - now).total_seconds()
                self.logger.info(f"Next sync scheduled for {next_time.isoformat()} "
                                f"(in {wait_seconds:.1f} seconds)")
                
                await asyncio.sleep(wait_seconds)
                
                # Run sync
                await self.sync_now()
                
        except asyncio.CancelledError:
            self.logger.info("Cron-based sync cancelled")
            raise
    
    async def _send_to_server(self, payload):
        """
        Send data to external server
        
        Args:
            payload: Data payload to send
            
        Returns:
            Tuple (success, message) - success status and message
        """
        if not hasattr(self, '_session'):
            self._session = aiohttp.ClientSession()
        
        # Get base URL
        base_url = self._get_server_url()
        if not base_url:
            return False, "Server URL not configured"
        
        # Get endpoint path and construct full URL
        ext_server_config = self.config.get("external_server", {})
        endpoint_path = ext_server_config.get("endpoint_path", "/api/results")
        url = f"{base_url.rstrip('/')}/{endpoint_path.lstrip('/')}"
        
        # Get HTTP method
        http_method = ext_server_config.get("http_method", "POST").lower()
        
        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        # Get authentication method and prepare headers
        auth_method = ext_server_config.get("auth_method", "api_key")
        
        if auth_method == "api_key":
            api_key = ext_server_config.get("api_key", "")
            api_key_header = ext_server_config.get("api_key_header", "X-API-Key")
            if api_key:
                headers[api_key_header] = api_key
                
        elif auth_method == "bearer_token":
            token = ext_server_config.get("bearer_token", "")
            if token:
                headers["Authorization"] = f"Bearer {token}"
                
        elif auth_method == "custom_header":
            header_name = ext_server_config.get("custom_header_name", "")
            header_value = ext_server_config.get("custom_header_value", "")
            if header_name and header_value:
                headers[header_name] = header_value
        
        # Prepare auth for session
        auth = None
        if auth_method == "basic_auth":
            username = ext_server_config.get("username", "")
            password = ext_server_config.get("password", "")
            if username:  # Password can be empty
                auth = aiohttp.BasicAuth(username, password)
        
        # OAuth2 token handling
        access_token = None
        if auth_method == "oauth2":
            access_token = await self._get_oauth2_token()
            if access_token:
                headers["Authorization"] = f"Bearer {access_token}"
            else:
                return False, "Failed to obtain OAuth2 token"
        
        try:
            async with aiohttp.ClientSession() as session:
                http_methods = {
                    "post": session.post,
                    "put": session.put,
                    "patch": session.patch
                }
                
                method = http_methods.get(http_method, session.post)
                
                self.logger.debug(f"Sending {http_method.upper()} request to {url}")
                
                async with method(url, json=payload, headers=headers, auth=auth) as response:
                    if response.status in (200, 201, 202, 204):
                        # Reset retry delay on success
                        self.retry_delay = self.initial_retry_delay
                        return True, f"Success: HTTP {response.status}"
                    else:
                        error_text = await response.text()
                        return False, f"HTTP Error {response.status}: {error_text}"
                        
        except aiohttp.ClientError as e:
            # Apply exponential backoff for retry
            self.retry_delay = min(self.retry_delay * 2, self.max_retry_delay)
            return False, f"Connection error: {str(e)}. Will retry in {self.retry_delay} seconds."
        except Exception as e:
            if isinstance(e, asyncio.CancelledError):
                raise  # Re-raise CancelledError to handle it properly
            return False, f"Error sending data to server: {str(e)}"
        finally:
            if not self.running:
                # Close session if we're shutting down
                await self._session.close()
                self._session = None
            
    async def _get_oauth2_token(self):
        """
        Get OAuth2 access token from token endpoint
        
        Returns:
            str: Access token if successful, None otherwise
        """
        ext_server_config = self.config.get("external_server", {})
        token_url = ext_server_config.get("oauth2_token_url", "")
        client_id = ext_server_config.get("client_id", "")
        client_secret = ext_server_config.get("client_secret", "")
        scope = ext_server_config.get("scope", "")
        
        if not token_url or not client_id:
            self.logger.error("OAuth2 token URL or client ID not configured")
            return None
            
        try:
            # Check if we have a cached token that's still valid
            if hasattr(self, 'oauth2_token') and hasattr(self, 'oauth2_token_expires'):
                if datetime.now() < self.oauth2_token_expires:
                    # Token still valid, reuse it
                    self.logger.debug("Reusing existing OAuth2 token")
                    return self.oauth2_token
            
            # Prepare token request
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json"
            }
            
            data = {
                "grant_type": "client_credentials",
                "client_id": client_id,
            }
            
            if client_secret:
                data["client_secret"] = client_secret
                
            if scope:
                data["scope"] = scope
                
            auth = None
            # Some servers expect client credentials in the Authorization header
            if client_secret:
                auth = aiohttp.BasicAuth(client_id, client_secret)
            
            self.logger.debug(f"Requesting OAuth2 token from {token_url}")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(token_url, data=data, headers=headers, auth=auth) as response:
                    if response.status == 200:
                        token_data = await response.json()
                        
                        # Extract token and expiry
                        access_token = token_data.get("access_token")
                        expires_in = token_data.get("expires_in", 3600)  # Default to 1 hour
                        
                        if access_token:
                            # Store token and expiry time (with a small safety margin)
                            self.oauth2_token = access_token
                            self.oauth2_token_expires = datetime.now() + \
                                                     datetime.timedelta(seconds=int(expires_in * 0.9))
                            self.logger.info("Successfully obtained OAuth2 token")
                            return access_token
                            
                    error_text = await response.text()
                    self.logger.error(f"Failed to get OAuth2 token: HTTP {response.status}: {error_text}")
                    return None
                    
        except Exception as e:
            self.logger.error(f"Error obtaining OAuth2 token: {str(e)}")
            return None
    
    async def sync_patient(self, patient_data):
        """
        Sync a specific patient's data to the external server
        
        Args:
            patient_data: Dictionary containing patient info and results
            
        Returns:
            bool: True if sync was successful, False otherwise
        """
        if not self._is_sync_enabled():
            self.logger.info("External server sync is disabled in configuration")
            return False
            
        try:
            # Prepare payload for this specific patient
            payload = {
                "instance_id": self.config.get("instance_id", "unknown"),
                "analyzer_type": self.config.get("analyzer_type", "unknown"),
                "timestamp": datetime.now().isoformat(),
                "patient": patient_data["patient"],
                "results": patient_data["results"]
            }
            
            # Send to external server
            success, message = await self._send_to_server(payload)
            
            if success:
                # Update sync status for patient and results
                patient_id = patient_data["patient"]["db_id"]
                self.db_manager.mark_patient_synced(patient_id)
                
                # Update sync status for all results
                for result in patient_data["results"]:
                    self.db_manager.mark_result_synced(result["id"])
                
                self.last_sync_time = datetime.now()
                self.logger.info(f"Successfully synced patient {patient_data['patient']['patient_id']}")
                return True
            else:
                self.logger.error(f"Failed to sync patient: {message}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error syncing patient: {e}")
            return False

    async def sync_patient_realtime(self, patient_id):
        """
        Sync a patient's data immediately in real-time mode
        
        Args:
            patient_id: Database ID of the patient to sync
            
        Returns:
            bool: True if sync was successful, False otherwise
        """
        if not self._is_sync_enabled():
            return False
            
        # Only sync in realtime if configured for realtime mode
        if self._get_sync_frequency() != "realtime":
            self.logger.debug(f"Skipping real-time sync for patient {patient_id} - not in real-time mode")
            return False
            
        try:
            # Get patient information
            patient = self.db_manager.get_patient_by_id(patient_id)
            if not patient:
                self.logger.error(f"Cannot sync patient {patient_id} - not found in database")
                return False
                
            # Format patient info for sync
            patient_info = {
                "db_id": patient[0],
                "patient_id": patient[1],
                "name": patient[2],
                "dob": patient[3],
                "sex": patient[4],
                "physician": patient[5]
            }
            
            # Get patient's results
            results = self.db_manager.get_patient_results(patient_id)
            if not results:
                self.logger.info(f"No results to sync for patient {patient_id}")
                # Still mark the patient as synced since we've seen them
                self.db_manager.mark_patient_synced(patient_id)
                return True
                
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
                    "sequence": sequence
                })
            
            # Create patient data payload
            patient_data = {
                "patient": patient_info,
                "results": formatted_results
            }
            
            # Send to external server
            return await self.sync_patient(patient_data)
            
        except Exception as e:
            self.logger.error(f"Error in real-time sync for patient {patient_id}: {e}")
            return False

    def _get_pending_results(self):
        """Get results that haven't been synced yet"""
        return self.db_manager.get_results(sync_status="local")
    
    def _prepare_payload(self, results):
        """
        Prepare data payload for sending to external server
        
        Args:
            results: List of result records from database
            
        Returns:
            Dictionary with formatted data for sending
        """
        payload = {
            "instance_id": self.config.get("instance_id", "unknown"),
            "analyzer_type": self.config.get("analyzer_type", "unknown"),
            "timestamp": datetime.now().isoformat(),
            "results": []
        }
        
        for result in results:
            result_id, patient_id, patient_name, test_code, value, unit, flags, timestamp, _ = result
            
            # Format result data
            payload["results"].append({
                "id": result_id,
                "patient_id": patient_id,
                "patient_name": patient_name,
                "test_code": test_code,
                "value": value,
                "unit": unit,
                "flags": flags,
                "timestamp": timestamp
            })
            
        return payload
    
    def _is_sync_enabled(self):
        """Check if external sync is enabled in config"""
        ext_server_config = self.config.get("external_server", {})
        return ext_server_config.get("enabled", False)
    
    def _get_sync_frequency(self):
        """Get the configured sync frequency"""
        ext_server_config = self.config.get("external_server", {})
        return ext_server_config.get("sync_frequency", "scheduled").lower()
    
    def _get_sync_interval(self):
        """Get the scheduled sync interval in minutes"""
        ext_server_config = self.config.get("external_server", {})
        return int(ext_server_config.get("sync_interval", 15))
    
    def _get_cron_schedule(self):
        """Get the cron schedule expression"""
        ext_server_config = self.config.get("external_server", {})
        return ext_server_config.get("cron_schedule", "0 * * * *")  # Default: every hour
    
    def _get_server_url(self):
        """Get the external server URL"""
        ext_server_config = self.config.get("external_server", {})
        return ext_server_config.get("url", "")
    
    def _get_api_key(self):
        """Get the API key for the external server"""
        ext_server_config = self.config.get("external_server", {})
        return ext_server_config.get("api_key", "")

    def _get_scheduled_time(self):
        """Get the scheduled time for daily sync (hour and minute)"""
        ext_server_config = self.config.get("external_server", {})
        hour = int(ext_server_config.get("scheduled_hour", 0))
        minute = int(ext_server_config.get("scheduled_minute", 0))
        return hour, minute
        
    def _get_cron_expression(self):
        """Get the cron expression for sync"""
        ext_server_config = self.config.get("external_server", {})
        return ext_server_config.get("cron_expression", "0 * * * *")  # Default: every hour
        
    async def _sync_scheduled_time(self, hour, minute):
        """
        Sync data at a specific time each day
        
        Args:
            hour: Hour of day (0-23)
            minute: Minute of hour (0-59)
        """
        self.logger.info(f"Starting scheduled daily sync at {hour:02d}:{minute:02d}")
        try:
            while True:
                # Calculate time until next scheduled run
                now = datetime.now()
                next_run = datetime(now.year, now.month, now.day, hour, minute)
                
                # If today's scheduled time has passed, schedule for tomorrow
                if next_run <= now:
                    next_run = next_run.replace(day=now.day + 1)
                    
                # Calculate wait time in seconds
                wait_seconds = (next_run - now).total_seconds()
                
                self.logger.info(f"Next sync scheduled for {next_run.isoformat()} "
                                f"(in {wait_seconds:.1f} seconds)")
                
                # Wait until scheduled time
                await asyncio.sleep(wait_seconds)
                
                # Run sync
                self.logger.info(f"Running scheduled sync at {datetime.now().isoformat()}")
                await self.sync_now()
                
                # Add a small delay to prevent potential double-runs
                await asyncio.sleep(60)
                
        except asyncio.CancelledError:
            self.logger.info("Scheduled time sync cancelled")
            raise

    async def _cleanup_connections(self):
        """Cleanup any remaining aiohttp connections"""
        try:
            # If there's an active session, close it
            if hasattr(self, '_session') and self._session:
                await self._session.close()
                self._session = None
        except Exception as e:
            self.logger.error(f"Error cleaning up connections: {e}")