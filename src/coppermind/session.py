"""Session state: one open project document at a time (Phase 0).

The session ties together a backend, the active Document, and the external
providers (supplier catalog). Tools operate on the session; the MCP server is a
thin wrapper over these calls.
"""

from __future__ import annotations

from coppermind.backends.base import KicadBackend
from coppermind.backends.factory import create_backend
from coppermind.integrations.suppliers.base import SupplierProvider
from coppermind.integrations.suppliers.offline import OfflineCatalogProvider
from coppermind.schematic.models import Schematic
from coppermind.transactions.manager import Document


class Session:
    def __init__(
        self,
        backend: KicadBackend | None = None,
        supplier: SupplierProvider | None = None,
    ) -> None:
        self.backend: KicadBackend = backend or create_backend()
        self.supplier: SupplierProvider = supplier or OfflineCatalogProvider()
        self.document: Document | None = None
        self.schematic: Schematic | None = None

    def require_document(self) -> Document:
        if self.document is None:
            raise RuntimeError("No project open. Call project_create first.")
        return self.document

    def require_schematic(self) -> Schematic:
        if self.schematic is None:
            raise RuntimeError("No schematic open. Call schematic_create first.")
        return self.schematic
