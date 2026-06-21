"""Exemplo: criar uma 'LEDBoard' passo a passo com a API do Coppermind.

Reproduz o fluxo em linguagem natural:
  1. Criar projeto 'LEDBoard' 50x50mm
  2. Colocar um LED em (10,10) e um resistor 330R em (20,10)
  3. Criar a net 'LED1' e rotear de R1 ao LED com 0.3mm
  4. Mostrar preview + conselhos de design
  5. Commit como "primeiro LED" (se não houver violação de erro)

Roda sem KiCAD (MemoryBackend). Execute com:
    python -m examples.led_board      # a partir da raiz do repo
"""

from __future__ import annotations

import json

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.session import Session
from coppermind.tools.core import (
    component_place,
    design_preview,
    net_create,
    net_route,
    project_create,
)


def main() -> None:
    session = Session(backend=MemoryBackend())

    # 1) projeto 50x50
    project_create(session, "LEDBoard", 50, 50)

    # 2) LED (D1) e resistor 330R (R1)
    component_place(session, "D1", "LED_SMD:LED_0603_1608Metric", 10, 10, value="LED")
    component_place(session, "R1", "Resistor_SMD:R_0603_1608Metric", 20, 10, value="330")

    # 3) net 'LED1' + roteamento de R1 (20,10) ao LED (10,10), 0.3mm
    net_create(session, "LED1")
    net_route(session, "LED1", 20, 10, 10, 10, width_mm=0.3)

    # 4) preview: diff + violações + conselhos (citados)
    preview = design_preview(session)
    print("== DIFF ==")
    print(" ", preview["diff"])
    print("== VIOLAÇÕES (bloqueiam o commit se severidade>=erro) ==")
    for v in preview["violations"]:
        print(f"  [{v['severity']}] {v['code']}: {v['message']}")
    print("== CONSELHOS DE DESIGN (advisory, citados) ==")
    for a in preview["advice"]:
        print(f"  - {a['message']}  (regra: {a['rule']})")
    print("would_block:", preview["would_block"])

    # 5) commit como 'primeiro LED' se não houver bloqueio
    doc = session.require_document()
    if not preview["would_block"]:
        result = doc.commit(label="primeiro LED")
        print("\n== COMMIT ==", "ok" if result.committed else "bloqueado")
        print("  resumo:", result.summary())
        print("  timeline:", json.dumps([e.model_dump() for e in doc.timeline()], ensure_ascii=False))
    else:
        print("\nCommit não realizado: há violação de erro. Ajuste e tente de novo.")


if __name__ == "__main__":
    main()
