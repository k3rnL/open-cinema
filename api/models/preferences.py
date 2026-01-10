from django.db import models


class Preferences(models.Model):

    @classmethod
    def get_preferences(cls) -> "Preferences":
        """
        Return the singleton Preferences row.
        Creates it with defaults if it doesn't exist.
        """
        obj, _ = Preferences.objects.get_or_create(pk=1)
        return obj
