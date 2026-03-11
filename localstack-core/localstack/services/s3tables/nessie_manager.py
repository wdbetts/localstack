import logging
import time

import requests

from localstack import config
from localstack.utils.container_utils.container_client import (
    ContainerClient,
    DockerContainerStatus,
    PortMappings,
)
from localstack.utils.docker_utils import DOCKER_CLIENT
from localstack.utils.net import get_free_tcp_port

LOG = logging.getLogger(__name__)

NESSIE_IMAGE = "ghcr.io/projectnessie/nessie:latest"
NESSIE_CONTAINER_NAME = "localstack-s3tables-nessie"
NESSIE_INTERNAL_PORT = 19120
HEALTH_CHECK_TIMEOUT = 60
HEALTH_CHECK_INTERVAL = 2


class NessieManager:
    """Manages a singleton Nessie container that serves as the Iceberg REST catalog
    backend for the S3 Tables provider."""

    def __init__(self, docker_client: ContainerClient | None = None):
        self._docker_client = docker_client or DOCKER_CLIENT
        self._host_port: int | None = None
        self._started = False

    @property
    def endpoint(self) -> str | None:
        if not self._started:
            return None
        host, port = self._resolve_nessie_address()
        return f"http://{host}:{port}/iceberg/"

    def _resolve_nessie_address(self) -> tuple[str, int]:
        """Return (host, port) to reach Nessie.
        Inside Docker: use container IP + internal port (19120).
        On host: use localhost + mapped host port."""
        if config.is_in_docker:
            try:
                ip = self._docker_client.get_container_ip(NESSIE_CONTAINER_NAME)
                if ip:
                    return ip, NESSIE_INTERNAL_PORT
            except Exception:
                LOG.debug("Could not get Nessie container IP, falling back to localhost")
        return "localhost", self._host_port or NESSIE_INTERNAL_PORT

    def start(self, localstack_s3_endpoint: str = "http://host.docker.internal:4566") -> str:
        """Start the Nessie container if not already running. Returns the Iceberg REST endpoint URL."""
        if self._started and self._is_running():
            return self.endpoint

        LOG.info("Starting Nessie Iceberg catalog container...")

        # Check if container already exists from a previous run
        status = self._docker_client.get_container_status(NESSIE_CONTAINER_NAME)
        if status == DockerContainerStatus.UP:
            LOG.info("Nessie container already running, reusing.")
            self._started = True
            return self.endpoint

        # Clean up stopped container if it exists
        if status != DockerContainerStatus.NON_EXISTENT:
            self._docker_client.remove_container(NESSIE_CONTAINER_NAME, force=True)

        self._host_port = get_free_tcp_port()
        port_mappings = PortMappings()
        port_mappings.add(self._host_port, NESSIE_INTERNAL_PORT)

        env_vars = {
            "nessie.catalog.default-warehouse": "warehouse",
            "nessie.catalog.warehouses.warehouse.location": "s3://s3tables-data/",
            "nessie.catalog.service.s3.default-options.region": "us-east-1",
            "nessie.catalog.service.s3.default-options.path-style-access": "true",
            "nessie.catalog.service.s3.default-options.access-key": (
                "urn:nessie-secret:quarkus:nessie.catalog.secrets.access-key"
            ),
            "nessie.catalog.secrets.access-key.name": "test",
            "nessie.catalog.secrets.access-key.secret": "test",
            "nessie.catalog.service.s3.default-options.endpoint": localstack_s3_endpoint,
            "nessie.catalog.service.s3.default-options.external-endpoint": (
                "http://localhost:4566/"
            ),
        }

        self._docker_client.run_container(
            image_name=NESSIE_IMAGE,
            name=NESSIE_CONTAINER_NAME,
            detach=True,
            ports=port_mappings,
            env_vars=env_vars,
        )

        self._wait_for_healthy()
        self._started = True
        LOG.info("Nessie Iceberg catalog running at %s", self.endpoint)
        return self.endpoint

    def stop(self):
        """Stop and remove the Nessie container."""
        if not self._started:
            return

        LOG.info("Stopping Nessie Iceberg catalog container...")
        try:
            self._docker_client.stop_container(NESSIE_CONTAINER_NAME, timeout=10)
        except Exception:
            LOG.debug("Error stopping Nessie container", exc_info=True)
        try:
            self._docker_client.remove_container(NESSIE_CONTAINER_NAME, force=True)
        except Exception:
            LOG.debug("Error removing Nessie container", exc_info=True)

        self._started = False
        self._host_port = None

    def _is_running(self) -> bool:
        try:
            return (
                self._docker_client.get_container_status(NESSIE_CONTAINER_NAME)
                == DockerContainerStatus.UP
            )
        except Exception:
            return False

    def _wait_for_healthy(self):
        """Poll Nessie's config endpoint until it responds."""
        host, port = self._resolve_nessie_address()
        url = f"http://{host}:{port}/iceberg/v1/config"
        deadline = time.time() + HEALTH_CHECK_TIMEOUT
        while time.time() < deadline:
            try:
                resp = requests.get(url, timeout=2)
                if resp.status_code == 200:
                    return
            except requests.ConnectionError:
                pass
            time.sleep(HEALTH_CHECK_INTERVAL)
        raise TimeoutError(
            f"Nessie container did not become healthy within {HEALTH_CHECK_TIMEOUT}s"
        )


# --- Singleton ---

_nessie_manager: NessieManager | None = None


def nessie_manager() -> NessieManager:
    global _nessie_manager
    if _nessie_manager is None:
        _nessie_manager = NessieManager()
    return _nessie_manager
