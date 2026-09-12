"""Session state: one open project document at a time.

The session ties together board backends, suppliers and the KiCad symbol
resolver. Schematic tools resolve real library symbols at mutation time so an
invalid ``Library:Symbol`` fails immediately rather than during export.
"""

from __future__ import annotations

from coppermind.backends.base import KicadBackend
from coppermind.backends.factory import create_backend
from coppermind.integrations.suppliers.base import SupplierProvider
from coppermind.integrations.suppliers.offline import OfflineCatalogProvider
from coppermind.libraries import SymbolResolver
from coppermind.schematic.models import Schematic
from coppermind.transactions.manager import Document


class Session:
    def __init__(
        self,
        backend: KicadBackend | None = None,
        supplier: SupplierProvider | None = None,
        symbol_resolver: SymbolResolver | None = None,
    ) -> None:
        self.backend: KicadBackend = backend or create_backend()
        self.supplier: SupplierProvider = supplier or OfflineCatalogProvider()
        self.symbol_resolver: SymbolResolver = symbol_resolver or SymbolResolver()
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
