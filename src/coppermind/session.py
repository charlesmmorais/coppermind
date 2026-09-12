"""Session state: one open project document at a time.

The session ties together board backends, suppliers, the semantic Circuit IR,
the drawable schematic and the KiCad symbol resolver. Agent-facing schematic
tools mutate the Circuit IR first; geometry is kept as an implementation detail.
"""

from __future__ import annotations

from coppermind.backends.base import KicadBackend
from coppermind.backends.factory import create_backend
from coppermind.circuit import Circuit
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
        self.circuit: Circuit | None = None

    def require_document(self) -> Document:
        if self.document is None:
            raise RuntimeError("No project open. Call project_create first.")
        return self.document

    def require_schematic(self) -> Schematic:
        if self.schematic is None:
            raise RuntimeError("No schematic open. Call project_create first.")
        return self.schematic

    def require_circuit(self) -> Circuit:
        if self.circuit is None:
            raise RuntimeError("No Circuit IR open. Call project_create first.")
        return self.circuit
