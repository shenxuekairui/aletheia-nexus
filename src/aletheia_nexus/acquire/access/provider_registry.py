from aletheia_nexus.acquire.access.base_provider import BaseBrowserProvider
from aletheia_nexus.acquire.access.cnki_provider import CNKIProvider
from aletheia_nexus.acquire.access.models import BrowserAccessConfig
from aletheia_nexus.core.models import PaperMetadata

_PROVIDERS: tuple[BaseBrowserProvider, ...] = (CNKIProvider(),)


def registered_browser_providers() -> tuple[BaseBrowserProvider, ...]:
    """Return site-specific browser providers in stable priority order."""

    return tuple(sorted(_PROVIDERS, key=lambda provider: provider.priority))


def applicable_browser_providers(
    *,
    doi: str,
    metadata: PaperMetadata | None,
    expected_title: str | None,
    config: BrowserAccessConfig,
) -> tuple[BaseBrowserProvider, ...]:
    """Return registered providers applicable to one paper."""

    return tuple(
        provider
        for provider in registered_browser_providers()
        if provider.is_applicable(
            doi=doi,
            metadata=metadata,
            expected_title=expected_title,
            config=config,
        )
    )
