import logging
from typing import Optional

from .config_builder import CamillaDSPConfigBuilder
from .client import CamillaDSPClient

logger = logging.getLogger(__name__)


class CamillaDSPManager:
    """High-level manager for CamillaDSP operations."""

    def __init__(self, websocket_host: str = "localhost", websocket_port: int = 1234):
        """
        Initialize CamillaDSP manager.

        Args:
            websocket_host: Websocket server host
            websocket_port: Websocket server port
        """
        self.config_builder = CamillaDSPConfigBuilder()
        self.client = CamillaDSPClient(websocket_host, websocket_port)

    def activate_pipeline(self, pipeline) -> tuple[bool, str]:
        """
        Activate a pipeline by building its config and applying it to CamillaDSP.

        Args:
            pipeline: Pipeline model instance

        Returns:
            Tuple of (success, message)
        """
        try:
            logger.info(f"Activating pipeline: {pipeline.name}")

            # Check if input/output devices are active
            if not pipeline.input_device.active:
                msg = f"Input device '{pipeline.input_device.name}' is not currently connected"
                logger.warning(msg)
                return False, msg

            if not pipeline.output_device.active:
                msg = f"Output device '{pipeline.output_device.name}' is not currently connected"
                logger.warning(msg)
                return False, msg

            # Build configuration
            config_dict = self.config_builder.build_config(pipeline)

            # Validate configuration structure
            try:
                self.config_builder.validate_config(config_dict)
            except ValueError as e:
                logger.error(f"Config validation failed: {e}")
                return False, f"Invalid configuration: {e}"

            # Convert to YAML for CamillaDSP validation
            config_yaml = self.config_builder.to_yaml(pipeline)

            # Validate with CamillaDSP binary
            is_valid, error_msg = self.client.validate_config(config_yaml)
            if not is_valid:
                return False, f"CamillaDSP validation failed: {error_msg}"

            # Apply configuration
            success = self.client.apply_config(config_dict)
            if not success:
                return False, "Failed to apply configuration to CamillaDSP"

            # Update pipeline status in database
            pipeline.active = True
            pipeline.save()

            # Deactivate other pipelines
            from api.models import Pipeline
            Pipeline.objects.exclude(id=pipeline.id).update(active=False)

            logger.info(f"Successfully activated pipeline: {pipeline.name}")
            return True, f"Pipeline '{pipeline.name}' activated successfully"

        except Exception as e:
            logger.error(f"Failed to activate pipeline: {e}", exc_info=True)
            return False, f"Error activating pipeline: {str(e)}"

    def deactivate_pipeline(self, pipeline) -> tuple[bool, str]:
        """
        Deactivate a pipeline.

        Args:
            pipeline: Pipeline model instance

        Returns:
            Tuple of (success, message)
        """
        try:
            pipeline.active = False
            pipeline.save()
            logger.info(f"Deactivated pipeline: {pipeline.name}")
            return True, f"Pipeline '{pipeline.name}' deactivated"
        except Exception as e:
            logger.error(f"Failed to deactivate pipeline: {e}")
            return False, f"Error deactivating pipeline: {str(e)}"

    def get_active_pipeline(self):
        """
        Get the currently active pipeline.

        Returns:
            Pipeline instance or None
        """
        from api.models import Pipeline
        return Pipeline.objects.filter(active=True).first()

    def get_status(self) -> dict:
        """
        Get comprehensive status of CamillaDSP and active pipeline.

        Returns:
            Status dictionary
        """
        camilla_status = self.client.get_status()
        active_pipeline = self.get_active_pipeline()

        status = {
            'camilladsp': camilla_status,
            'active_pipeline': None
        }

        if active_pipeline:
            status['active_pipeline'] = {
                'id': active_pipeline.id,
                'name': active_pipeline.name,
                'input_device': {
                    'name': active_pipeline.input_device.name,
                    'active': active_pipeline.input_device.active
                },
                'output_device': {
                    'name': active_pipeline.output_device.name,
                    'active': active_pipeline.output_device.active
                }
            }

        return status

    def get_current_config(self) -> Optional[dict]:
        """
        Get the current active configuration from CamillaDSP.

        Returns:
            Configuration dictionary or None
        """
        return self.client.get_current_config()

    def reload_config(self) -> tuple[bool, str]:
        """
        Reload the current CamillaDSP configuration.

        Returns:
            Tuple of (success, message)
        """
        try:
            success = self.client.reload()
            if success:
                return True, "Configuration reloaded successfully"
            else:
                return False, "Failed to reload configuration"
        except Exception as e:
            logger.error(f"Error reloading config: {e}")
            return False, f"Error: {str(e)}"
