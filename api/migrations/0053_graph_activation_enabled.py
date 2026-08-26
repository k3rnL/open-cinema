from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0052_managed_audio_adapter"),
    ]

    operations = [
        migrations.AddField(
            model_name="graphactivation",
            name="enabled",
            field=models.BooleanField(default=True),
        ),
    ]
