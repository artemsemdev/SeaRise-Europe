# Real-local coastal atlas adapter

The real-local coastal atlas is an explicit development and validation mode
for provisioned data. Importing `src/web/scripts/real-local-atlas.mjs` alone
does not inspect local data or start a process.

Call `createRealLocalAtlas()` to validate the disk catalog and place index,
start one loopback Python raster process, and receive the browser catalog,
shared middleware, and an idempotent `close()` function. Reuse the middleware
for development and preview servers, and call `close()` during shutdown. If
middleware initialization fails after the child is ready, the factory closes
the child before rejecting.

Set `SEARISE_ATLAS_ROOT` to the read-only Europe atlas directory when running
from a worktree. Otherwise the factory resolves `local-data/atlas/europe` from
the shared Git checkout. `SEARISE_ATLAS_PYTHON` selects an existing scientific
Python environment; the default is the shared checkout's `.venv/bin/python`.
The adapter never downloads or writes data and does not fall back to synthetic
fixture data.

Node validates file confinement, sizes, and manifest metadata without hashing
raster bodies. The Python service streams each distinct raster once for its
SHA-256 startup check, then serves native-cell inspections and bounded Web
Mercator PNG tiles from read-only files. Public responses omit paths,
checksums, byte sizes, and private receipts. Basemap access is confined to the
`basemap` directory and preserves range requests needed by PMTiles and fonts.
