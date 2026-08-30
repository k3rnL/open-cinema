class PluginConcurrencyError(RuntimeError):
    """A plugin resource changed after the client last read it."""

