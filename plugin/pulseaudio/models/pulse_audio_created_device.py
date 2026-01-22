from django.db import models


class PulseAudioCreatedModule(models.Model):

    module_id = models.IntegerField(null=False)

    internal_id = models.CharField(null=False, max_length=36)

    class Meta:
        app_label = 'api'