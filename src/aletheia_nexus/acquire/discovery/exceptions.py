class DiscoveryError(RuntimeError):
    """Base error for full-text discovery failures."""


class DiscoveryConfigurationError(DiscoveryError):
    """A discovery provider is missing required configuration."""


class DiscoveryNotFoundError(DiscoveryError):
    """A provider has no record for the requested scholarly work."""


class DiscoveryNetworkError(DiscoveryError):
    """A network failure prevented discovery."""


class DiscoveryRequestError(DiscoveryError):
    """A discovery provider rejected the request."""


class DiscoveryRateLimitError(DiscoveryError):
    """A discovery provider rate-limited the request."""


class DiscoveryServiceError(DiscoveryError):
    """A discovery provider failed on the server side."""


class DiscoveryParseError(DiscoveryError):
    """A provider response could not be interpreted reliably."""
