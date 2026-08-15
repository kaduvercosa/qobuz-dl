class QobuzDLException(Exception):
    """Base exception for Qobuz-DL."""
    pass

class AuthenticationError(QobuzDLException):
    """Failed to authenticate with Qobuz API."""
    pass

class ItemNotFoundError(QobuzDLException):
    """Requested item was not found on Qobuz."""
    pass

class DownloadError(QobuzDLException):
    """Error occurred during audio stream download."""
    pass

class GeoRestrictedError(QobuzDLException):
    """Track or album is geo-restricted or subscription does not permit access."""
    pass

class GeoblockingError(GeoRestrictedError):
    """Alias for GeoRestrictedError."""
    pass

class TaggingError(QobuzDLException):
    """Error tagging audio file with metadata or album art."""
    pass
