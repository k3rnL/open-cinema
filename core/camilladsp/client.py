import logging
import subprocess
import signal
import os
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class CamillaDSPClient:
    """Client for communicating with CamillaDSP process."""

    def __init__(self, websocket_host: str = "localhost", websocket_port: int = 1234):
        """
        Initialize CamillaDSP client.

        Args:
            websocket_host: Websocket server host
            websocket_port: Websocket server port
        """
        self.host = websocket_host
        self.port = websocket_port
        self._pycamilladsp = None

    def _get_client(self):
        """Get or create pycamilladsp client instance."""
        if self._pycamilladsp is None:
            try:
                import camilladsp
                self._pycamilladsp = camilladsp.CamillaClient(self.host, self.port)
                self._pycamilladsp.connect()
                logger.info(f"Connected to CamillaDSP websocket at {self.host}:{self.port}")
            except ImportError:
                logger.warning("pycamilladsp not installed, websocket features unavailable")
                raise
            except Exception as e:
                logger.error(f"Failed to connect to CamillaDSP websocket: {e}")
                raise

        return self._pycamilladsp

    def get_status(self) -> Dict[str, Any]:
        """
        Get CamillaDSP process status.

        Returns:
            Dictionary with status information
        """
        try:
            client = self._get_client()
            state = client.general.state()
            return {
                'connected': True,
                'state': state.value if hasattr(state, 'value') else str(state),
                'websocket': f"{self.host}:{self.port}"
            }
        except Exception as e:
            logger.error(f"Failed to get CamillaDSP status: {e}")
            return {
                'connected': False,
                'error': str(e)
            }

    def get_current_config(self) -> Optional[Dict[str, Any]]:
        """
        Retrieve the currently active configuration from CamillaDSP.

        Returns:
            Configuration dictionary or None if unavailable
        """
        try:
            client = self._get_client()
            config = client.config.active()
            logger.info("Retrieved current CamillaDSP config")
            return config
        except Exception as e:
            logger.error(f"Failed to get current config: {e}")
            return None

    def apply_config(self, config: Dict[str, Any]) -> bool:
        """
        Apply a new configuration to CamillaDSP via websocket.

        Args:
            config: Configuration dictionary

        Returns:
            True if successful, False otherwise
        """
        try:
            client = self._get_client()
            client.config.set_active(config)
            logger.info("Successfully applied new CamillaDSP config via websocket")
            return True
        except Exception as e:
            logger.error(f"Failed to apply config via websocket: {e}")
            logger.info("Attempting fallback to SIGHUP method")
            return self._reload_via_sighup()

    def reload(self) -> bool:
        """
        Reload the current configuration.

        Returns:
            True if successful, False otherwise
        """
        try:
            client = self._get_client()
            client.general.reload()
            logger.info("Successfully reloaded CamillaDSP config")
            return True
        except Exception as e:
            logger.error(f"Failed to reload config: {e}")
            return self._reload_via_sighup()

    def _reload_via_sighup(self) -> bool:
        """
        Fallback method: reload config by sending SIGHUP signal to CamillaDSP process.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Find CamillaDSP process
            result = subprocess.run(
                ['pgrep', '-f', 'camilladsp'],
                capture_output=True,
                text=True
            )

            if result.returncode != 0 or not result.stdout.strip():
                logger.error("CamillaDSP process not found")
                return False

            pid = int(result.stdout.strip().split()[0])
            os.kill(pid, signal.SIGHUP)
            logger.info(f"Sent SIGHUP to CamillaDSP process (PID: {pid})")
            return True

        except Exception as e:
            logger.error(f"Failed to send SIGHUP: {e}")
            return False

    def validate_config(self, config_yaml: str, config_path: str = "/tmp/camilla_check.yml") -> tuple[bool, str]:
        """
        Validate configuration using camilladsp --check command.

        Args:
            config_yaml: YAML configuration string
            config_path: Temporary file path for validation

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            # Write config to temporary file
            with open(config_path, 'w') as f:
                f.write(config_yaml)

            # Run camilladsp --check
            result = subprocess.run(
                ['camilladsp', '--check', config_path],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                logger.info("Configuration validation passed")
                return True, ""
            else:
                error_msg = result.stderr or result.stdout
                logger.error(f"Configuration validation failed: {error_msg}")
                return False, error_msg

        except subprocess.TimeoutExpired:
            logger.error("Configuration validation timed out")
            return False, "Validation timed out"
        except FileNotFoundError:
            logger.error("camilladsp binary not found in PATH")
            return False, "camilladsp binary not found"
        except Exception as e:
            logger.error(f"Configuration validation error: {e}")
            return False, str(e)
        finally:
            # Clean up temporary file
            try:
                if os.path.exists(config_path):
                    os.remove(config_path)
            except Exception as e:
                logger.warning(f"Failed to remove temporary config file: {e}")

    def disconnect(self):
        """Disconnect from CamillaDSP websocket."""
        if self._pycamilladsp:
            try:
                self._pycamilladsp.disconnect()
                logger.info("Disconnected from CamillaDSP websocket")
            except Exception as e:
                logger.error(f"Error disconnecting from websocket: {e}")
            finally:
                self._pycamilladsp = None
