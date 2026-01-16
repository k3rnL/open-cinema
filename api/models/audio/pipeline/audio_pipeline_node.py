from enum import Enum

from django.db import models

from api.models.audio.audio_pipeline import AudioPipeline

class SlotDirection(Enum):
    INPUT = 1
    OUTPUT = 2
    ALL = 3

class SlotType(Enum):
    AUDIO = 1
    CONTROL = 2

class Slot:

    def __init__(self, name: str, type: SlotType, direction: SlotDirection):
        self.name = name
        self.type = type
        self.direction = direction

    def to_dict(self):
        return {
            "name": self.name,
            "type": self.type.name,         # or .value
            "direction": self.direction.name
        }

class AudioPipelineNode(models.Model):

    type_name = models.CharField(
        max_length=255,
        default=None,
        null=False,
        help_text="The type of the node, e.g. 'AudioProcessor'"
    )

    pipeline = models.ForeignKey(AudioPipeline, on_delete=models.CASCADE)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    static_slots: list[Slot] = []

    def get_dynamic_slots_schematics(self) -> list[Slot]:
        return []

