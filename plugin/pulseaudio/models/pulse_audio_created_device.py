from django.db import models


class PulseAudioCreatedModule(models.Model):

    module_id = models.IntegerField(null=False)

    class Meta:
        app_label = 'api'