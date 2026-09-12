"""Session state: board document plus semantic schematic state.

The session ties together board backends, suppliers, the semantic Circuit IR,
the drawable schematic and the KiCad symbol resolver. Circuit/schematic edits
follow the same preview/commit/rollback lifecycle as PCB-domain edits.
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
        self._committed_schematic: Schematic | None = None
        self._committed_circuit: Circuit | None = None

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

    def commit_semantic_state(self) -> None:
        """Snapshot Circuit IR and drawable schematic as the committed semantic state."""
        if self.circuit is not None:
            self._committed_circuit = self.circuit.model_copy(deep=True)
        if self.schematic is not None:
            self._committed_schematic = self.schematic.model_copy(deep=True)

    def rollback_semantic_state(self) -> None:
        """Restore Circuit IR and schematic to the last semantic commit."""
        if self._committed_circuit is not None:
            self.circuit = self._committed_circuit.model_copy(deep=True)
        if self._committed_schematic is not None:
            self.schematic = self._committed_schematic.model_copy(deep=True)

    def semantic_dirty(self) -> bool:
        """Return whether Circuit IR or schematic differs from the committed snapshot."""
        if self.circuit is not None:
            if self._committed_circuit is None or self.circuit != self._committed_circuit:
                return True
        if self.schematic is not None:
            if self._committed_schematic is None or self.schematic != self._committed_schematic:
                return True
        return False
