# Coppermind — Arquitetura atual

**Status:** implementação consolidada após as Fases 1–5 do fluxo semântico de
esquemático e introdução dos transports `stdio` + Streamable HTTP.

O objetivo do Coppermind é ser um **copiloto de engenharia eletrônica**, não um
tradutor de linguagem natural para coordenadas CAD. A intenção elétrica vive num
modelo semântico próprio; KiCad é o motor CAD e de verificação/materialização.

---

## 1. Princípios

1. **Intenção antes de geometria.** O agente trabalha com componentes, pinos, nets e
   constraints. Coordenadas são derivadas por algoritmos determinísticos.
2. **Circuit IR é a fonte de verdade elétrica.** O visual pode mudar; conectividade só
   muda por operações semânticas explícitas.
3. **Nada é escrito às cegas.** Preview, verificação, commit e rollback fazem parte do
   fluxo normal.
4. **ERC/DRC entram no gate.** Verificação não é um passo manual opcional no fim.
5. **Símbolos reais.** Não existe fallback genérico de dois pinos para um símbolo que
   não pôde ser resolvido.
6. **IA não executa código arbitrário.** O modelo não recebe um shell ou `exec` livre.
7. **Progressive discovery.** Tools de baixa frequência não ocupam o contexto sempre.
8. **Degradação graciosa.** Núcleo/testes funcionam sem KiCad; integração real entra
   quando `kicad-cli`/IPC estão disponíveis.
9. **Privacidade explícita.** Reviewer multimodal externo é opt-in e possui fronteira
   de dados documentada.
10. **HTTP local por padrão.** Streamable HTTP é loopback-only e single-user por
    processo.

---

## 2. Visão de alto nível

```text
┌──────────────────────────────────────────────────────────────┐
│ ChatGPT / Claude / outro cliente MCP                         │
└───────────────┬───────────────────────────┬──────────────────┘
                │                           │
             stdio                 Streamable HTTP
                │                    via tunnel/gateway
                └──────────────┬────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ server.py / FastMCP                                           │
│ 9 tools de núcleo + 5 tools de descoberta                    │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Circuit IR                                                    │
│ Component · Pin · Net · Constraint                           │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Semantic Composer                                             │
│ placement · net graph · wires · labels · junctions           │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
                    .kicad_sch real + KiCad ERC
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
              SVG/PDF KiCad        feedback elétrico
                    │
                    ▼
             Visual Reviewer
                    │
                    ▼
             Layout Action IR
                    │
              accept / rollback
```

---

## 3. Camadas

| Camada | Código | Responsabilidade |
| --- | --- | --- |
| Protocolo | `server.py` | FastMCP, resources, transports e registro da superfície principal. |
| Tools | `tools/` | núcleo semântico, discovery, registry e long tail roteada. |
| Circuit IR | `circuit/` | modelo elétrico independente de KiCad. |
| Libraries | `libraries/` | resolução de bibliotecas reais e metadados de pinos. |
| Schematic | `schematic/` | modelo desenhável, composer, ERC, reviewer e auto-fix. |
| Serialização | `serialize/` | materialização `.kicad_sch` e `.kicad_pcb`. |
| Transações | `transactions/` | preview/commit/rollback, diff, undo/redo e timeline. |
| Domínio PCB | `domain/` | board, componentes, tracks, vias e operações de PCB. |
| Verificação | `verification/` | checks estruturais independentes de KiCad. |
| Backends | `backends/` | IPC, batch `kicad-cli` e memória. |
| Inteligência | `intelligence/` | knowledge base, critique, blocks e heurísticas. |
| Integrações | `integrations/` | fornecedores, datasheets e Freerouting. |

A regra central continua sendo: **domínio e verificação não dependem da API do
KiCad**. A costura com KiCad fica nos adapters/backends e na materialização do
esquemático.

---

## 4. Transports MCP

O executável `coppermind` suporta duas formas de conexão.

### 4.1 stdio

```bash
coppermind --transport stdio
```

É o default. Um host MCP local inicia o processo e usa stdin/stdout para o protocolo.
É o caminho simples para Claude Desktop/Code e clientes locais.

### 4.2 Streamable HTTP

```bash
coppermind --transport streamable-http --host 127.0.0.1 --port 8765 --path /mcp
```

Endpoint:

```text
http://127.0.0.1:8765/mcp
```

O bind é aceito somente em loopback (`127.0.0.1`, `localhost`, `::1`). Um cliente em
nuvem deve chegar a esse endpoint através de um **túnel/gateway MCP autenticado**.
O Coppermind não desativa as proteções de Host/Origin do SDK MCP.

### 4.3 Por que não publicar diretamente

`build_server()` cria uma única `Session` e a vincula às tools. Isso é apropriado ao
modelo atual de um usuário/projeto por processo, mas não a um serviço multi-tenant.
Além disso, não há autenticação de aplicação embutida.

Logo, a fronteira suportada hoje é:

```text
1 processo Coppermind = 1 contexto de design confiável
```

Um serviço multiusuário futuro precisará isolar `Session`, workspace e permissões por
identidade.

Detalhes: [TRANSPORTES.md](TRANSPORTES.md).

---

## 5. Superfície MCP

### 5.1 Tools sempre visíveis

O caminho principal tem **9 tools de núcleo**:

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

Mais **5 tools de descoberta progressiva**:

```text
list_tool_categories
get_category_tools
search_tools
get_tool_schema
execute_tool
```

Isso mantém a superfície default pequena sem remover capacidade.

### 5.2 Tools roteadas

A cauda longa inclui categorias como:

- esquemático (`schematic_compose`, `schematic_erc`, `schematic_visual_*`);
- PCB e edição legada;
- design intelligence;
- fornecedores/datasheets;
- autorroteamento;
- variantes;
- persistência/exportações.

`symbol_add` e `wire_add` são deliberadamente escondidas do agente. Elas podem existir
internamente para compatibilidade/serialização, mas o LLM não deve regredir para
desenhar um esquemático por coordenadas.

---

## 6. Circuit IR

A intenção elétrica é representada antes do desenho.

```text
Circuit
 ├─ components: Component
 │    └─ pins: Pin
 ├─ nets: Net
 │    └─ nodes: PinRef
 └─ constraints: Constraint
```

Exemplo conceitual:

```text
Component U1 = ESP32-S3
Component C1 = 100 nF
Net +3V3 = [U1.VDD, C1.1]
Net GND  = [U1.GND, C1.2]
Constraint = decoupling C1 near U1
```

O Circuit IR não carrega a obrigação de decidir onde desenhar um wire. Essa decisão
pertence ao composer/layout.

---

## 7. Símbolos reais do KiCad

O resolver trabalha com bibliotecas instaladas/configuradas:

- bibliotecas empacotadas `*.kicad_sym`;
- formato unpacked `*.kicad_symdir/<Symbol>.kicad_sym`;
- `sym-lib-table` de projeto;
- diretórios configurados por ambiente.

O resolver extrai pinos reais, incluindo número, nome, tipo elétrico, unidade e
herança (`extends`). A definição real do símbolo pode ser embutida no `.kicad_sch`.

**Invariante:** símbolo não encontrado gera erro explícito. Não existe caixa genérica
de dois pinos para “continuar mesmo assim”.

---

## 8. Fases semânticas do esquemático

### Fase 1 — Circuit IR + símbolos reais

Separou intenção elétrica de geometria e eliminou o fallback sintético.

### Fase 2 — Tools semânticas

O agente passou a operar com:

```text
find_symbol → component_add → create_net → connect_pins → inspect_component
```

### Fase 3 — Semantic Composer

O lowering passou a ser automático:

```text
Circuit IR
 → placement determinístico
 → pontos reais dos pinos
 → net graph
 → roteamento ortogonal
 → wires/labels/junctions
 → .kicad_sch
 → kicad-cli sch erc
```

Correções automáticas dessa fase são restritas a geometria segura, como duplicatas e
segmentos degenerados. O sistema não inventa conexão elétrica para “zerar o ERC”.

### Fase 4 — Visual Reviewer

O fluxo exporta SVG/PDF reais do KiCad e calcula métricas de legibilidade:

- overlap e espaçamento;
- crossings;
- comprimento excessivo;
- fluxo esquerda→direita quando inferível;
- densidade/aspect ratio;
- agrupamento visual via crítico multimodal opcional.

O reviewer externo é **critic**, não executor direto.

### Fase 5 — Visual Auto-Fix

Findings seguros são convertidos para um Layout Action IR restrito:

```text
move_near
move_group
align
distribute
compact_block
separate_blocks
```

Aplicação é copy-on-write. Um candidato só é aceito se:

- Circuit IR permanecer invariável;
- nenhum pino ficar sem geometria;
- não surgir nova violação ERC;
- score determinístico não regredir;
- score final melhorar.

Caso contrário, a cópia é descartada.

Detalhes: [VISUAL_AUTOFIX.md](VISUAL_AUTOFIX.md).

---

## 9. Modelo transacional

PCB e estado semântico participam do mesmo conceito de revisão:

```text
working state
   ↓
design_preview
   ↓
checks + ERC/DRC + render + visual review
   ↓
┌───────────────┬────────────────┐
│ design_commit │ design_rollback│
└───────────────┴────────────────┘
```

`design_commit` não deve publicar estado semanticamente bloqueante. O histórico de
board mantém undo/redo e timeline; o estado semântico possui snapshots de commit e
rollback correspondentes.

---

## 10. Backends KiCad

### MemoryBackend

Usado para domínio, testes e desenvolvimento offline.

### IPCBackend

Usa `kicad-python`/kipy para interagir com KiCad quando uma sessão IPC está realmente
acessível. A detecção testa conexão real em vez de apenas construir um cliente lazy.

### BatchBackend / kicad-cli

Usado para tarefas headless de arquivo, DRC, ERC e renderizações.

No KiCad 10, o caminho de esquemático é híbrido: **arquivo real + CLI**. A API de
esquemático do KiCad 11 poderá assumir materialização live progressivamente, sem
mudar Circuit IR nem as tools semânticas.

---

## 11. Segurança e confiança

### 11.1 Sem `exec` arbitrário

A arquitetura não expõe um executor Python geral ao LLM. Ações são tools tipadas.

### 11.2 Geometria não pode alterar conectividade silenciosamente

Visual Reviewer e Auto-Fix só atuam em `x/y` e geometria derivada. O Circuit IR é
comparado antes/depois.

### 11.3 Paths validados

Tools que leem/escrevem artefatos restringem extensões e normalizam caminhos através
da camada `safety.py`.

### 11.4 Provider multimodal opt-in

Sem `COPPERMIND_VISUAL_PROVIDER`, nenhuma chamada de IA visual externa é realizada.
Quando ativado, PDF + contexto limitado saem da máquina; a fronteira é descrita em
[MULTIMODAL_VISUAL_REVIEW.md](MULTIMODAL_VISUAL_REVIEW.md).

### 11.5 HTTP local

Streamable HTTP é loopback-only e o processo deve ser acessado externamente apenas
através de uma camada confiável de tunnel/gateway.

---

## 12. CI e invariantes executáveis

O workflow de CI verifica:

- Python 3.11 e 3.12;
- Ruff;
- pytest + cobertura;
- mypy;
- integração bloqueante com KiCad 10;
- `.kicad_sch` real;
- ERC real;
- SVG/PDF reais;
- Visual Auto-Fix com Circuit IR invariável.

O job de integração não é mais `continue-on-error`: regressão contra KiCad deve
quebrar o CI.

---

## 13. Limitações atuais

1. **Sessão HTTP única por processo.** Não existe isolamento multi-tenant.
2. **Sem auth HTTP embutida.** O endpoint local depende do túnel/gateway para uma
   fronteira remota segura.
3. **KiCad 10 schematic live IPC incompleto para este caso.** Materialização por
   `.kicad_sch` + CLI continua sendo o caminho confiável.
4. **PCB ainda é menos semântico.** Há operações legadas por coordenadas atrás do
   registry; a evolução futura deve aplicar ao PCB o mesmo padrão do Circuit IR.
5. **Reviewer multimodal é probabilístico.** Gates determinísticos continuam sendo a
   autoridade.
6. **Fabricação exige revisão humana.** ERC/DRC e IA não substituem análise elétrica,
   térmica, mecânica, EMC, segurança ou conformidade.

---

## 14. Próximos passos

Prioridade recomendada:

1. benchmark real ponta a ponta de circuitos representativos;
2. melhorar blocos funcionais e constraints semânticos;
3. evoluir o PCB para `Placement/Routing IR` de nível mais alto;
4. adotar live schematic IPC do KiCad 11 quando a API estiver estável;
5. tornar docs/tool inventory parcialmente gerados pelo registry;
6. se houver necessidade de serviço compartilhado, introduzir autenticação e uma
   `Session` isolada por identidade/conexão antes de permitir bind de rede.

---

## 15. Decisões-chave

- **Python + MCP SDK/FastMCP v1.x** no momento; dependência explicitamente limitada a
  `<2` para impedir migração quebradora silenciosa.
- **Dois transports** com um mesmo servidor: stdio e Streamable HTTP.
- **Streamable HTTP loopback-only**; exposição remota pertence a tunnel/gateway.
- **Circuit IR** como fonte de verdade elétrica.
- **KiCad como motor CAD/verificação**, não como modelo mental do agente.
- **Geometria derivada e reversível**.
- **Tools semânticas no caminho principal; primitives cruas escondidas**.
- **ERC/DRC e CI real como gates**, não marketing.
