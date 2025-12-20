"""Open Cinema version information."""

__version__ = "0.0.1"
__version_info__ = tuple(int(i) for i in __version__.split("."))

# Semantic versioning
MAJOR = __version_info__[0]
MINOR = __version_info__[1]
PATCH = __version_info__[2]
