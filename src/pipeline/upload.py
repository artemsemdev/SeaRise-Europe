"""Step 6: Upload COGs to Azure Blob Storage (S03-06).

Blob path convention (architecture doc section 9):
  layers/{methodology_version}/{scenario_id}/{horizon_year}.tif

Container: ``geospatial`` (private).

During local development the target is Azurite (Azure Blob emulator).
The same path structure is used in production Azure Blob Storage.
"""

import logging
from pathlib import Path

from azure.storage.blob import BlobServiceClient, ContentSettings

from .config import BLOB_CONTAINER

logger = logging.getLogger(__name__)


def _ensure_container(client: BlobServiceClient) -> None:
    """Create the blob container if it does not exist (idempotent)."""
    container = client.get_container_client(BLOB_CONTAINER)
    if not container.exists():
        container.create_container()
        logger.info("Created container '%s'", BLOB_CONTAINER)


def upload_cog(
    cog_path: Path,
    scenario: str,
    horizon: int,
    methodology_version: str,
    connection_string: str,
) -> str:
    """Upload a COG file to Azure Blob Storage.

    Returns:
        The blob path (relative within the container) for database registration.
    """
    blob_path = f"layers/{methodology_version}/{scenario}/{horizon}.tif"

    client = BlobServiceClient.from_connection_string(connection_string)
    _ensure_container(client)
    blob = client.get_blob_client(container=BLOB_CONTAINER, blob=blob_path)

    content_settings = ContentSettings(
        content_type="image/tiff",
        cache_control="max-age=86400, public",
    )

    file_size = cog_path.stat().st_size
    with open(cog_path, "rb") as data:
        blob.upload_blob(
            data,
            overwrite=True,
            content_settings=content_settings,
        )

    logger.info(
        "Uploaded %s (%d bytes) -> %s/%s",
        cog_path.name, file_size, BLOB_CONTAINER, blob_path,
    )

    return blob_path
