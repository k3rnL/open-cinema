from django.db import models
from django.core.exceptions import ValidationError


class Mixer(models.Model):
    """Represents a CamillaDSP mixer configuration for channel mapping."""

    name = models.CharField(
        max_length=255,
        unique=True,
        help_text="Mixer name (e.g., 'stereo_to_6ch')"
    )
    description = models.TextField(
        blank=True,
        help_text="Optional description of this mixer"
    )

    # Channel configuration
    input_channels = models.IntegerField(
        help_text="Number of input channels"
    )
    output_channels = models.IntegerField(
        help_text="Number of output channels"
    )

    # Mapping configuration stored as JSON
    mapping = models.JSONField(
        help_text="Channel mapping configuration (list of destination mappings)"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def clean(self):
        """Validate mixer configuration."""
        if self.input_channels < 1:
            raise ValidationError({'input_channels': 'Must have at least 1 input channel'})

        if self.output_channels < 1:
            raise ValidationError({'output_channels': 'Must have at least 1 output channel'})

        # Validate mapping structure
        if not isinstance(self.mapping, list):
            raise ValidationError({'mapping': 'Mapping must be a list'})

        if len(self.mapping) != self.output_channels:
            raise ValidationError({
                'mapping': f'Mapping must have exactly {self.output_channels} destination entries'
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.input_channels}→{self.output_channels} channels)"

    @staticmethod
    def create_default_mixer(input_channels: int, output_channels: int) -> 'Mixer':
        """
        Create a default mixer configuration for upmixing or downmixing.

        Args:
            input_channels: Number of input channels
            output_channels: Number of output channels

        Returns:
            Mixer instance (not saved to database)
        """
        name = f"auto_{input_channels}ch_to_{output_channels}ch"
        mapping = []

        if input_channels == output_channels:
            # Pass-through: map each input to corresponding output
            for ch in range(output_channels):
                mapping.append({
                    'dest': ch,
                    'sources': [
                        {
                            'channel': ch,
                            'gain': 0.0,
                            'inverted': False
                        }
                    ]
                })

        elif input_channels == 2 and output_channels == 6:
            # Stereo to 5.1 upmix
            # 0: Front Left (L)
            # 1: Front Right (R)
            # 2: Center (L+R mixed, -6dB)
            # 3: LFE (L+R mixed, -12dB for subwoofer)
            # 4: Surround Left (L, -3dB)
            # 5: Surround Right (R, -3dB)
            mapping = [
                # Front Left
                {'dest': 0, 'sources': [{'channel': 0, 'gain': 0.0, 'inverted': False}]},
                # Front Right
                {'dest': 1, 'sources': [{'channel': 1, 'gain': 0.0, 'inverted': False}]},
                # Center (mix L+R)
                {'dest': 2, 'sources': [
                    {'channel': 0, 'gain': -6.0, 'inverted': False},
                    {'channel': 1, 'gain': -6.0, 'inverted': False}
                ]},
                # LFE (mix L+R for subwoofer)
                {'dest': 3, 'sources': [
                    {'channel': 0, 'gain': -12.0, 'inverted': False},
                    {'channel': 1, 'gain': -12.0, 'inverted': False}
                ]},
                # Surround Left
                {'dest': 4, 'sources': [{'channel': 0, 'gain': -3.0, 'inverted': False}]},
                # Surround Right
                {'dest': 5, 'sources': [{'channel': 1, 'gain': -3.0, 'inverted': False}]}
            ]

        elif input_channels == 6 and output_channels == 2:
            # 5.1 to stereo downmix
            # L = FL + 0.707*C + 0.707*SL
            # R = FR + 0.707*C + 0.707*SR
            mapping = [
                # Left output
                {'dest': 0, 'sources': [
                    {'channel': 0, 'gain': 0.0, 'inverted': False},    # Front Left
                    {'channel': 2, 'gain': -3.0, 'inverted': False},   # Center (-3dB = 0.707)
                    {'channel': 4, 'gain': -3.0, 'inverted': False}    # Surround Left
                ]},
                # Right output
                {'dest': 1, 'sources': [
                    {'channel': 1, 'gain': 0.0, 'inverted': False},    # Front Right
                    {'channel': 2, 'gain': -3.0, 'inverted': False},   # Center (-3dB = 0.707)
                    {'channel': 5, 'gain': -3.0, 'inverted': False}    # Surround Right
                ]}
            ]

        elif input_channels < output_channels:
            # Generic upmix: duplicate channels and fill with silence
            for out_ch in range(output_channels):
                in_ch = out_ch if out_ch < input_channels else 0
                mapping.append({
                    'dest': out_ch,
                    'sources': [
                        {
                            'channel': in_ch,
                            'gain': 0.0,
                            'inverted': False
                        }
                    ]
                })

        else:
            # Generic downmix: drop extra channels
            for out_ch in range(output_channels):
                mapping.append({
                    'dest': out_ch,
                    'sources': [
                        {
                            'channel': out_ch,
                            'gain': 0.0,
                            'inverted': False
                        }
                    ]
                })

        return Mixer(
            name=name,
            description=f"Auto-generated mixer: {input_channels} to {output_channels} channels",
            input_channels=input_channels,
            output_channels=output_channels,
            mapping=mapping
        )
