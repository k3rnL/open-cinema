import logging
from typing import Dict, Any

import yaml

logger = logging.getLogger(__name__)


class CamillaDSPConfigBuilder:
    """Builds CamillaDSP YAML configuration from Pipeline models."""

    def __init__(self):
        self.config = {}

    def build_config(self, pipeline) -> Dict[str, Any]:
        """
        Build a complete CamillaDSP configuration from a Pipeline object.

        Args:
            pipeline: Pipeline model instance

        Returns:
            Dictionary representation of CamillaDSP config (YAML-ready)
        """
        logger.info(f"Building CamillaDSP config for pipeline: {pipeline.name}")

        config = {
            'devices': self._build_devices_section(pipeline),
        }

        # Add filters if pipeline has any
        filters = pipeline.filters.filter(enabled=True).order_by('order')
        if filters.exists():
            config['filters'] = self._build_filters_section(filters)
            config['pipeline'] = self._build_pipeline_section(filters)

        logger.debug(f"Generated config: {config}")
        return config

    def _build_devices_section(self, pipeline) -> Dict[str, Any]:
        """Build the devices section of the config."""
        input_dev = pipeline.input_device
        output_dev = pipeline.output_device

        devices = {
            'capture': {
                'type': self._map_backend_to_camilla_type(input_dev.backend),
                'channels': input_dev.channels,
                'device': input_dev.name,
                'format': input_dev.format,
            },
            'playback': {
                'type': self._map_backend_to_camilla_type(output_dev.backend),
                'channels': output_dev.channels,
                'device': output_dev.name,
                'format': output_dev.format,
            }
        }

        # Add sample rate if devices match, otherwise use resampling
        if input_dev.sample_rate == output_dev.sample_rate:
            devices['samplerate'] = input_dev.sample_rate
        else:
            devices['samplerate'] = output_dev.sample_rate
            devices['capture']['extra_samples'] = 0
            devices['enable_resampling'] = True
            devices['resampler_type'] = 'Synchronous'

        return devices

    def _map_backend_to_camilla_type(self, backend: str) -> str:
        """Map audio backend name to CamillaDSP device type."""
        backend_mapping = {
            'pulseaudio': 'Pulse',
            'alsa': 'Alsa',
            'jack': 'Jack',
            'coreaudio': 'CoreAudio',
            'wasapi': 'Wasapi',
        }
        return backend_mapping.get(backend.lower(), 'Pulse')

    def _build_filters_section(self, filters) -> Dict[str, Any]:
        """Build the filters section of the config."""
        filters_dict = {}

        for filter_obj in filters:
            filter_name = f"{filter_obj.filter_type.lower()}_{filter_obj.id}"
            filters_dict[filter_name] = {
                'type': filter_obj.filter_type,
                **filter_obj.config
            }

        return filters_dict

    def _build_pipeline_section(self, filters) -> list:
        """Build the pipeline section (processing chain)."""
        pipeline = []

        for filter_obj in filters:
            filter_name = f"{filter_obj.filter_type.lower()}_{filter_obj.id}"
            pipeline.append({
                'type': 'Filter',
                'channel': 0,  # Apply to all channels by default
                'names': [filter_name]
            })

        return pipeline

    def to_yaml(self, pipeline) -> str:
        """
        Generate YAML string from Pipeline model.

        Args:
            pipeline: Pipeline model instance

        Returns:
            YAML string representation of config
        """
        config = self.build_config(pipeline)
        return yaml.dump(config, default_flow_style=False, sort_keys=False)

    def validate_config(self, config: Dict[str, Any]) -> bool:
        """
        Validate that the config has required sections.

        Args:
            config: Configuration dictionary

        Returns:
            True if valid, raises ValueError otherwise
        """
        required_sections = ['devices']
        for section in required_sections:
            if section not in config:
                raise ValueError(f"Missing required section: {section}")

        devices = config['devices']
        if 'capture' not in devices or 'playback' not in devices:
            raise ValueError("Devices section must contain 'capture' and 'playback'")

        return True
