from django.db import models


class AutoDecoderNodeState(models.Model):

    node = models.OneToOneField('AutoDecoderNode', on_delete=models.CASCADE)

    pid = models.IntegerField(null=False)

    class Meta:
        app_label = 'api'