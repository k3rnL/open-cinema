"""Counter log model - tracks counter increments/decrements."""

from django.db import models


class CounterLog(models.Model):
    """
    Simple counter log that tracks increment/decrement operations.

    This is a dummy example to demonstrate plugin-specific models.
    """

    ACTION_CHOICES = [
        ('INCREMENT', 'Increment'),
        ('DECREMENT', 'Decrement'),
        ('RESET', 'Reset'),
    ]

    action = models.CharField(
        max_length=10,
        choices=ACTION_CHOICES,
        help_text="Type of counter action"
    )

    value = models.IntegerField(
        help_text="Counter value after this action"
    )

    comment = models.TextField(
        blank=True,
        help_text="Optional comment about this action"
    )

    timestamp = models.DateTimeField(
        auto_now_add=True,
        help_text="When this action occurred"
    )

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['action']),
        ]

    def __str__(self):
        return f"{self.action} -> {self.value} at {self.timestamp}"
