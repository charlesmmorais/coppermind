<div align="center">

# 🔶 Coppermind

### Copiloto de engenharia eletrônica para KiCad — MCP semântico, transacional e verificado

[![CI](https://github.com/charlesmmorais/coppermind/actions/workflows/ci.yml/badge.svg)](https://github.com/charlesmmorais/coppermind/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](https://www.python.org/)
[![KiCad 10/11](https://img.shields.io/badge/KiCad-10%20%7C%2011-green.svg)](https://www.kicad.org/)
[![MCP](https://img.shields.io/badge/protocol-MCP-orange.svg)](https://modelcontextprotocol.io/)

**🇧🇷 Português** · [🇺🇸 English](README.en.md)

</div>

---

> **Descreva o circuito, não as coordenadas.** O Coppermind resolve símbolos reais,
> cria o Circuit IR, compõe o esquemático, roda ERC, revisa a organização visual e
> só confirma mudanças depois dos gates de segurança.

O **Coppermind** é um servidor MCP em Python para trabalhar com projetos eletrônicos
no **KiCad**. O caminho principal de esquemático é semântico: o agente opera com
`Component / Pin / Net / Constraint`, enquanto o Coppermind transforma essa intenção
em `.kicad_sch` real, usando símbolos das bibliotecas instaladas do KiCad.

Ele pode ser executado com **dois transports MCP**:

- **stdio** — cliente local inicia o Coppermind como subprocesso;
- **Streamable HTTP** — endpoint local em `/mcp`, adequado para um túnel/gateway MCP
  confiável quando o cliente está fora da máquina.

O HTTP é **loopback-only por projeto**. O Coppermind não deve ser publicado diretamente
na Internet: ele ainda mantém uma sessão de design por processo e não implementa
autenticação multiusuário.

![Arquitetura do Coppermind](docs/architecture.svg)

---

## Estado atual

O fluxo de esquemático implementa as cinco fases da arquitetura semântica:

| Fase | Entrega |
| --- | --- |
| **1 — Circuit IR + símbolos reais** | `Component`, `Pin`, `Net`, `Constraint`; resolução de `.kicad_sym`/`.kicad_symdir`; sem fallback genérico de dois pinos. |
| **2 — Tools semânticas** | `find_symbol`, `component_add`, `create_net`, `connect_pins`, `inspect_component`; o LLM não desenha wires por coordenadas. |
| **3 — Semantic Composer** | Circuit IR → placement → net graph → wires/labels/junctions → `.kicad_sch` → ERC real via `kicad-cli`. |
| **4 — Visual Reviewer** | score visual, SVG/PDF real do KiCad, reflow determinístico e reviewer multimodal opcional. |
| **5 — Visual Auto-Fix** | Layout Action IR tipado, copy-on-write, safety gates, ERC antes/depois e rollback quando o candidato piora. |

O resultado é um ciclo como este:

```text
ChatGPT / Claude / outro cliente MCP
              │
       stdio ou Streamable HTTP
              │
              ▼
          Coppermind
              │
              ▼
          Circuit IR
              │
              ▼
      Semantic Composer
              │
              ▼
      .kicad_sch real
              │
      ┌───────┴────────┐
      ▼                ▼
  KiCad ERC       SVG / PDF
      │                │
      └───────┬────────┘
              ▼
      Visual Reviewer
              │
      Layout Action IR
              │
        accept / rollback
```

---

## Instalação

### Requisitos

- Python **3.11+**;
- KiCad **10+** para uso real;
- `kicad-cli` disponível no `PATH` para ERC/render headless;
- para IPC ao vivo: extra Python `kicad-python` e API IPC habilitada no KiCad.

O projeto permanece na linha **MCP Python SDK 1.x** enquanto usa a API `FastMCP`:
`mcp>=1.30,<2`. Isso evita uma migração implícita para a API v2.

### Linux/macOS

```bash
git clone https://github.com/charlesmmorais/coppermind.git
cd coppermind
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[ipc]"
```

### Windows / PowerShell

```powershell
git clone https://github.com/charlesmmorais/coppermind.git
cd coppermind
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[ipc]"
```

Para desenvolvimento:

```bash
pip install -e ".[dev,ipc]"
pytest
```

No KiCad, habilite a API IPC quando quiser operar uma instância aberta:

**Preferences → Plugins → Enable IPC API Server**

---

## Executando o servidor MCP

### Opção A — stdio

É o padrão e o melhor caminho para clientes MCP locais:

```bash
coppermind
```

ou explicitamente:

```bash
coppermind --transport stdio
```

### Opção B — Streamable HTTP

```bash
coppermind \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8765 \
  --path /mcp
```

Endpoint:

```text
http://127.0.0.1:8765/mcp
```

Também pode ser configurado por variáveis de ambiente:

```bash
COPPERMIND_TRANSPORT=streamable-http
COPPERMIND_HTTP_HOST=127.0.0.1
COPPERMIND_HTTP_PORT=8765
COPPERMIND_HTTP_PATH=/mcp
COPPERMIND_BACKEND=auto
coppermind
```

No PowerShell:

```powershell
$env:COPPERMIND_TRANSPORT="streamable-http"
$env:COPPERMIND_HTTP_HOST="127.0.0.1"
$env:COPPERMIND_HTTP_PORT="8765"
$env:COPPERMIND_HTTP_PATH="/mcp"
$env:COPPERMIND_BACKEND="auto"
coppermind
```

> **Segurança:** o processo recusa bind em `0.0.0.0`, IP de LAN ou hostname não
> loopback. Para ChatGPT ou outro cliente remoto, mantenha o Coppermind em
> `127.0.0.1` e coloque um **túnel/gateway MCP autenticado** na frente. Veja
> [`docs/TRANSPORTES.md`](docs/TRANSPORTES.md).

---

## Conectando clientes MCP

### Claude Desktop / clientes locais

Exemplo `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "coppermind": {
      "command": "coppermind",
      "args": ["--transport", "stdio"],
      "env": {
        "COPPERMIND_BACKEND": "auto",
        "LOG_LEVEL": "INFO"
      }
    }
  }
}
```

Se `coppermind` não estiver no `PATH`, use o caminho absoluto do executável da
virtualenv.

### ChatGPT / cliente MCP remoto

O Coppermind agora fornece Streamable HTTP, mas `127.0.0.1` só existe na sua máquina.
Para um cliente em nuvem:

```text
ChatGPT
   │
   │ MCP Streamable HTTP
   ▼
túnel/gateway MCP autenticado
   │
   ▼
127.0.0.1:8765/mcp
   │
   ▼
Coppermind → KiCad
```

O cliente/workspace precisa aceitar **servidores MCP personalizados e tools de
escrita** para poder criar/modificar o esquemático. O transporte HTTP, sozinho, não
concede essas permissões.

---

## Seleção do backend KiCad

```bash
COPPERMIND_BACKEND=auto    # IPC se estiver acessível; senão MemoryBackend
COPPERMIND_BACKEND=ipc     # exige uma sessão KiCad IPC acessível
COPPERMIND_BACKEND=memory  # desenvolvimento/offline
```

| Backend | Uso principal |
| --- | --- |
| `MemoryBackend` | domínio/testes e trabalho offline |
| `IPCBackend` | interação com uma instância KiCad via `kicad-python`/kipy |
| `BatchBackend` | DRC/render/export headless com `kicad-cli` |

No KiCad 10, o caminho de esquemático é deliberadamente híbrido: o Circuit IR e o
composer geram o arquivo `.kicad_sch`; `kicad-cli` executa ERC e renderizações reais.
A evolução do IPC de esquemático no KiCad 11 poderá substituir partes dessa camada
sem mudar as tools semânticas.

---

## Fluxo recomendado do agente

As **9 tools de núcleo** são orientadas à intenção elétrica:

```text
project_create
find_symbol
component_add
create_net
connect_pins
inspect_component
design_preview
design_commit
design_rollback
```

Há ainda **5 tools de descoberta progressiva** para acessar a cauda longa sem poluir
o contexto do modelo:

```text
list_tool_categories
get_category_tools
search_tools
get_tool_schema
execute_tool
```

Exemplo de autoria semântica:

```text
find_symbol("resistor")
component_add(reference="R1", symbol="Device:R", value="10k")
component_add(reference="C1", symbol="Device:C", value="100nF")
create_net(name="SENSE")
connect_pins(net="SENSE", pins=["R1.2", "C1.1"])
design_preview()
design_commit()
```

As primitivas cruas de esquemático como `symbol_add` e `wire_add` ficam internas e
não são oferecidas ao agente. As operações PCB por coordenadas permanecem como
compatibilidade roteada, não como caminho principal.

---

## Composer, ERC e revisão visual

`design_preview` e `design_commit` executam automaticamente o pipeline seguro de
esquemático:

```text
Circuit IR
 → compose
 → visual review/reflow
 → serialização .kicad_sch
 → KiCad ERC
 → gate
```

Tools adicionais são descobertas sob demanda:

```text
schematic_compose
schematic_erc
schematic_export_composed
schematic_visual_review
schematic_visual_optimize
schematic_visual_plan
schematic_visual_apply
schematic_visual_autofix
```

O auto-fix visual **não altera a intenção elétrica**. Só executa ações geométricas
tipadas e limitadas (`move_near`, `align`, `compact_block` etc.) sobre uma cópia do
esquemático. Se o score piorar, surgir nova violação ERC ou o Circuit IR mudar, o
candidato é descartado.

Documentação detalhada:

- [`docs/MULTIMODAL_VISUAL_REVIEW.md`](docs/MULTIMODAL_VISUAL_REVIEW.md)
- [`docs/VISUAL_AUTOFIX.md`](docs/VISUAL_AUTOFIX.md)

---

## Reviewer multimodal opcional

A revisão determinística funciona sem serviço externo. Para acrescentar um crítico
multimodal, configure um provider compatível:

```bash
COPPERMIND_VISUAL_PROVIDER=openai
OPENAI_API_KEY=...
COPPERMIND_VISUAL_MODEL=<modelo-multimodal>
```

Quando habilitado, o PDF real exportado pelo KiCad e um contexto limitado do Circuit
IR são enviados ao provider. Não habilite essa opção para designs sensíveis sem
avaliar a política de dados aplicável.

---

## PCB, autorroteamento e integrações

O núcleo histórico de PCB continua disponível: modelo transacional, DRC, undo/redo,
variantes, fornecedores, datasheets, exportação `.kicad_pcb` e Freerouting.

Para autorroteamento:

[`docs/AUTORROTEAMENTO.md`](docs/AUTORROTEAMENTO.md)

Fluxo resumido:

```text
KiCad → Specctra DSN → Freerouting → SES → Coppermind
                                      ↓
                              preview / DRC
                                      ↓
                              commit / rollback
```

---

## Garantias de segurança da arquitetura

O Coppermind foi desenhado para impedir que o LLM vire um executor irrestrito:

- não executa Python arbitrário gerado pelo modelo;
- símbolos são resolvidos em bibliotecas reais do KiCad;
- símbolo inexistente falha explicitamente;
- Circuit IR é a fonte de verdade elétrica;
- alterações passam por preview/commit/rollback;
- ERC/DRC entram no gate;
- visual auto-fix opera copy-on-write e só em geometria;
- paths de arquivos usados por tools são validados;
- Streamable HTTP fica restrito a loopback;
- provider multimodal é opcional e possui fronteira de dados documentada.

---

## Testes e CI

O workflow de CI executa:

- Python 3.11 e 3.12;
- Ruff;
- pytest + cobertura;
- mypy;
- job de integração **bloqueante** com KiCad 10 real;
- serialização de esquemático, ERC, SVG/PDF e Visual Auto-Fix contra KiCad.

O objetivo é que afirmações críticas da arquitetura sejam verificadas pelo CI, não
apenas descritas no README.

---

## Limitações atuais

- Streamable HTTP é **single-user por processo**; não é um servidor multi-tenant.
- Não há autenticação embutida no endpoint HTTP; use túnel/gateway confiável.
- A criação de esquemático no KiCad 10 usa arquivo `.kicad_sch` + `kicad-cli`; live
  schematic IPC será adotado quando a API adequada estiver estável.
- O Visual Reviewer multimodal é probabilístico e opcional; os gates determinísticos
  continuam sendo a autoridade de segurança.
- O caminho de PCB ainda possui mais operações legadas baseadas em geometria do que
  o caminho de esquemático semântico.
- Revisão de engenharia continua necessária antes da fabricação de hardware.

---

## Documentação

Veja o índice em [`docs/README.md`](docs/README.md):

- [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) — arquitetura atual e decisões;
- [`docs/TRANSPORTES.md`](docs/TRANSPORTES.md) — stdio, Streamable HTTP e túnel;
- [`docs/TRANSPORTS.md`](docs/TRANSPORTS.md) — transport guide in English;
- [`docs/MULTIMODAL_VISUAL_REVIEW.md`](docs/MULTIMODAL_VISUAL_REVIEW.md);
- [`docs/VISUAL_AUTOFIX.md`](docs/VISUAL_AUTOFIX.md);
- [`docs/AUTORROTEAMENTO.md`](docs/AUTORROTEAMENTO.md).

---

## Contribuindo

Antes de abrir um PR:

```bash
pip install -e ".[dev,ipc]"
ruff check src tests
pytest
mypy src
```

Mantenha as invariantes centrais: intenção elétrica no Circuit IR, geometria derivada,
progressive discovery, mudanças reversíveis e nenhuma execução arbitrária de código
produzido por modelo.

## Licença

MIT. Consulte [`LICENSE`](LICENSE).

O Coppermind é uma ferramenta de assistência. ERC/DRC, regras e IA reduzem risco,
mas não substituem validação elétrica, térmica, mecânica, regulatória e de segurança
antes da fabricação.
