from django.db import models
from django_enum import EnumField


class SlotDirection(models.IntegerChoices):
    INPUT = 1, 'INPUT'
    OUTPUT = 2, 'OUTPUT'
    ALL = 3, 'ALL'

class SlotType(models.IntegerChoices):
    DEVICE_AUDIO_OUTPUT = 1, 'DEVICE_AUDIO_OUTPUT'
    DEVICE_AUDIO_INPUT = 2, 'DEVICE_AUDIO_INPUT'
    AUDIO_CONSUMER = 3, 'AUDIO_CONSUMER'
    AUDIO_PRODUCER = 4, 'AUDIO_PRODUCER'



class AudioPipelineNodeSlot(models.Model):

    name = models.CharField(
        max_length=255,
        help_text="A unique name to identify this slot on it's node"
    )

    nice_name = models.CharField(
        max_length=255,
        null=True,
        help_text="A nice name for this slot"
    )

    type = EnumField(SlotType, null=False)
    direction = EnumField(SlotDirection, null=False)

    node = models.ForeignKey('AudioPipelineNode', null=False, on_delete=models.CASCADE, related_name='slots')

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "nice_name": self.name,
            "type": self.type.label,         # or .value
            "direction": self.direction.label,
            "node": self.node.id
        }

