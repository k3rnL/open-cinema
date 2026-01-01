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

    def validate_config(self, config_dict: Dict[str, str]) -> tuple[bool, str]:
        """
        Validate configuration using camilladsp.

        Args:
            config_dict: YAML configuration string

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            # Run camilladsp --check
            client = self._get_client()
            result = client.config.validate(config_dict)

            if result is not None:
                logger.info("Configuration validation passed")
                return True, ""
            else:
                logger.error(f"Configuration validation failed for unknown reason")
                return False, "Validation failed"

        except Exception as e:
            logger.error(f"Configuration validation error: {e}")
            return False, str(e)

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
