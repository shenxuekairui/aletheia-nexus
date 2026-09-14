from aletheia_nexus.acquire.discovery.hosts import refine_host_type
from aletheia_nexus.acquire.discovery.models import HostType


def test_doi_and_handle_routes_are_resolvers():
    assert (
        refine_host_type("https://doi.org/10.1000/test", HostType.PUBLISHER)
        == HostType.RESOLVER
    )
    assert (
        refine_host_type("https://hdl.handle.net/10379/15835", HostType.REPOSITORY)
        == HostType.RESOLVER
    )


def test_bibliographic_indexes_are_distinct_from_repositories():
    assert (
        refine_host_type(
            "https://pubmed.ncbi.nlm.nih.gov/18669820",
            HostType.REPOSITORY,
        )
        == HostType.INDEX
    )
    assert (
        refine_host_type(
            "https://doaj.org/article/example",
            HostType.REPOSITORY,
        )
        == HostType.INDEX
    )


def test_pmc_routes_are_repositories():
    assert (
        refine_host_type(
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC11192878/",
            HostType.UNKNOWN,
        )
        == HostType.REPOSITORY
    )
    assert (
        refine_host_type(
            "https://www.ncbi.nlm.nih.gov/pmc/articles/11192878",
            HostType.UNKNOWN,
        )
        == HostType.REPOSITORY
    )


def test_unknown_hosts_preserve_provider_reported_type():
    assert (
        refine_host_type("https://repo.example.org/item/1", HostType.REPOSITORY)
        == HostType.REPOSITORY
    )
    assert (
        refine_host_type("https://publisher.example.org/article", HostType.PUBLISHER)
        == HostType.PUBLISHER
    )
