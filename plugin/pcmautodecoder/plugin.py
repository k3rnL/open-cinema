"""PCM Auto Decoder Plugin - provides PCM auto decoder backend capabilities."""

from core.plugin_system.oc_plugin import OCPlugin


class AutoDecoderPlugin(OCPlugin):
    """
    PCM Auto Decoder plugin, provides PCM auto decoder backend capabilities
    """

    @property
    def plugin_name(self):
        return "pcm-auto-decoder"

    def get_urls(self):
        return [ ]
