import logging
from typing import Dict, Any

import yaml

from api.models import Pipeline

logger = logging.getLogger(__name__)


class CamillaDSPConfigBuilder:
    """Builds CamillaDSP YAML configuration from Pipeline models."""

    def __init__(self):
        self.config = {}

    def build_config(self, pipeline: Pipeline) -> Dict[str, Any]:
        """
        Build a complete CamillaDSP configuration from a Pipeline object.

        Args:
            pipeline: Pipeline model instance

        Returns:
            Dictionary representation of CamillaDSP config (YAML-ready)
        """
        logger.info(f"Building CamillaDSP config for pipeline: {pipeline.name}")

        config = {
            'title': pipeline.name,
            'devices': self._build_devices_section(pipeline),
        }

        # Add mixer if needed (channels differ or mixer explicitly set)
        mixer_config, mixer_name = self._build_mixer_section(pipeline)
        if mixer_config:
            config['mixers'] = mixer_config

        # Add filters if pipeline has any
        filters = pipeline.filters.filter(enabled=True).order_by('order')

        # Build pipeline section (processing chain)
        pipeline_chain = []

        # Add mixer to pipeline chain if present
        if mixer_name:
            pipeline_chain.append({
                'type': 'Mixer',
                'name': mixer_name
            })

        # Add filters to pipeline chain
        if filters.exists():
            config['filters'] = self._build_filters_section(filters)
            pipeline_chain.extend(self._build_filter_pipeline_steps(filters))

        # Only add pipeline section if there are steps
        if pipeline_chain:
            config['pipeline'] = pipeline_chain

        print(f'ouioui {pipeline_chain} {mixer_name}')

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
            },
            'chunksize': pipeline.chunksize,
            'samplerate': pipeline.samplerate
        }

        # Enable resampling if pipeline samplerate differs from input device
        if input_dev.sample_rate != pipeline.samplerate:
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

    def _build_mixer_section(self, pipeline) -> tuple[Dict[str, Any] | None, str | None]:
        """
        Build the mixer section of the config.

        Returns:
            Tuple of (mixer_config_dict, mixer_name) or (None, None) if no mixer needed
        """
        from api.models import Mixer

        input_channels = pipeline.input_device.channels
        output_channels = pipeline.output_device.channels

        # If channels match and no explicit mixer set, no mixer needed
        if input_channels == output_channels and not pipeline.mixer:
            return None, None

        # Use explicit mixer if set
        if pipeline.mixer:
            mixer = pipeline.mixer
        else:
            # Auto-create mixer for channel conversion
            mixer = Mixer.create_default_mixer(input_channels, output_channels)
            # Save it to database for reuse
            try:
                existing = Mixer.objects.filter(name=mixer.name).first()
                if existing:
                    mixer = existing
                else:
                    mixer.save()
                    # Assign to pipeline
                    pipeline.mixer = mixer
                    pipeline.save()
            except Exception as e:
                logger.warning(f"Could not save auto-generated mixer: {e}")

        # Build mixer config
        mixer_config = {
            mixer.name: {
                'channels': {
                    'in': mixer.input_channels,
                    'out': mixer.output_channels
                },
                'mapping': []
            }
        }

        # Add mapping entries
        for dest_mapping in mixer.mapping:
            mapping_entry = {
                'dest': dest_mapping['dest'],
                'sources': []
            }

            for source in dest_mapping['sources']:
                source_entry = {
                    'channel': source['channel'],
                    'gain': source['gain'],
                    'inverted': source.get('inverted', False)
                }
                mapping_entry['sources'].append(source_entry)

            mixer_config[mixer.name]['mapping'].append(mapping_entry)

        return mixer_config, mixer.name

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

    def _build_filter_pipeline_steps(self, filters) -> list:
        """Build the filter steps for the pipeline section."""
        steps = []

        for filter_obj in filters:
            filter_name = f"{filter_obj.filter_type.lower()}_{filter_obj.id}"
            steps.append({
                'type': 'Filter',
                'channel': 0,  # Apply to all channels by default
                'names': [filter_name]
            })

        return steps

    def to_yaml(self, pipeline: Pipeline) -> str:
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
