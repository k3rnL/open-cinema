from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0050_camilladsp_profile"),
    ]

    # No installation has legacy user data to preserve. Delete dependent
    # tables before their parents so SQLite never needs to rebuild the old
    # multi-table-inheritance models with an empty field set.
    operations = [
        migrations.DeleteModel(name="AudioPipelineApplyEvent"),
        migrations.DeleteModel(name="AudioPipelineNodePosition"),
        migrations.DeleteModel(name="AudioPipelineEdge"),
        migrations.DeleteModel(name="AutoDecoderNodeState"),
        migrations.DeleteModel(name="PulseAudioPipeNodeState"),
        migrations.DeleteModel(name="PulseAudioTunnelNodeState"),
        migrations.DeleteModel(name="AudioPipelineDeviceNode"),
        migrations.DeleteModel(name="CamillaDSPAudioPipelineNode"),
        migrations.DeleteModel(name="AutoDecoderNode"),
        migrations.DeleteModel(name="PulseAudioPipeNode"),
        migrations.DeleteModel(name="PulseAudioTunnelNode"),
        migrations.DeleteModel(name="Filter"),
        migrations.DeleteModel(name="AudioPipelineApplyJob"),
        migrations.DeleteModel(name="AudioPipelineNodeSlot"),
        migrations.DeleteModel(name="AudioPipelineNode"),
        migrations.DeleteModel(name="CamillaDSPPipeline"),
        migrations.DeleteModel(name="AudioPipeline"),
        migrations.DeleteModel(name="PulseAudioCreatedModule"),
        migrations.DeleteModel(name="KnownAudioDevice"),
        migrations.DeleteModel(name="Mixer"),
        migrations.DeleteModel(name="PreferencesAudioBackend"),
        migrations.DeleteModel(name="AudioDevice"),
    ]
