# Coppermind — Development Handoff

> Documento operacional para retomar o desenvolvimento sem depender do histórico da conversa.
>
> **Baseline funcional de referência:** `f8ce6a940b6765e88d72db346a66ee318148e098`  
> **Data do handoff:** 2026-09-13  
> **Estado:** fluxo semântico/incremental de esquemático validado localmente e em CI; próximo foco é orientação automática de componentes e alinhamento por fluxo elétrico.

---

## 1. Objetivo do projeto

O **Coppermind** é um copiloto de engenharia eletrônica para KiCad exposto via MCP.

A regra arquitetural central é:

```text
intenção elétrica
    ↓
Circuit IR
    ↓
placement / routing semântico
    ↓
.kicad_sch real
    ↓
ERC + revisão visual
    ↓
accept / rollback
```

O LLM deve operar com **componentes, pinos, nets e intenção elétrica**, e não com coordenadas arbitrárias de fios.

O caminho principal de esquemático usa símbolos reais do KiCad e gera arquivo `.kicad_sch` real.

---

## 2. Fonte de verdade

Em caso de divergência, considerar nesta ordem:

1. `src/coppermind/` — comportamento implementado;
2. `tests/` — invariantes executáveis;
3. `examples/` — cenários E2E de validação;
4. `README.md`, `docs/` e este handoff — documentação operacional.

Não adaptar o código para manter documentação antiga. Atualizar a documentação quando o comportamento real evoluir.

---

## 3. Estado consolidado da arquitetura

### Circuit IR

O Circuit IR separa intenção elétrica de geometria. Componentes, pinos e nets devem continuar sendo a camada autoritativa da conectividade.

### Símbolos reais

O resolver lê bibliotecas KiCad reais (`.kicad_sym`, `sym-lib-table`, herança, units e pins). Não reintroduzir fallback sintético de símbolo genérico.

### Schematic model

`src/coppermind/schematic/models.py` mantém os objetos de desenho principais:

- `SchSymbol` — referência, valor, posição, rotação e unit;
- `Wire`;
- `NetLabel`;
- `Junction`;
- `Schematic`.

### Composer global

O Semantic Composer continua existindo para composição global determinística.

### Construção incremental

A arquitetura incremental é o caminho preferido para simular uma IA montando o circuito passo a passo:

```text
component_add
    ↓
connect_pins
    ↓
component_place_auto
    ↓
route only impacted nets
    ↓
schematic_checkpoint
```

O objetivo é aproximar o comportamento de um projetista operando no KiCad: adicionar um componente, declarar conexões, posicionar, rotear e validar antes de continuar.

---

## 4. Ferramentas semânticas importantes

### Sempre visíveis / caminho principal

- `project_create`
- `component_add`
- `connect_pins`
- `create_net`
- `inspect_component`
- `find_symbol`
- `design_preview`
- `design_commit`
- `design_rollback`

### Routed / discoverable via `execute_tool`

As tools de menor frequência são descobertas e executadas por `execute_tool`.

No fluxo atual de esquemático, as mais importantes são:

- `component_place_auto`
- `component_place_relative`
- `component_reflow_neighborhood`
- `connect_incremental`
- `schematic_checkpoint`
- `schematic_export_current`
- `schematic_compose`
- `schematic_erc`
- `schematic_export_composed`

Não tornar primitivas cruas de wire/symbol coordenadas o caminho principal do agente.

---

## 5. Regras elétricas e geométricas que NÃO podem regredir

### 5.1 Pin anchors reais

Nunca snapar anchors elétricos para a grade visual.

Símbolos reais do KiCad usam offsets como `1.27 mm` e `3.81 mm`; alterar o anchor para `2.54 mm` pode deixar um fio visualmente próximo, porém eletricamente desconectado no ERC.

### 5.2 Unit 0

Pins de `unit = 0` são compartilhados e devem ser visíveis para a unit exibida. Isso é relevante para símbolos de power, como `PWR_FLAG`.

### 5.3 Foreign pins

Uma net não pode atravessar um pino pertencente a outra net. O roteador deve considerar foreign pins como pontos elétricos protegidos.

### 5.4 Junctions

Junctions pertencentes a outra net também são pontos elétricos protegidos.

### 5.5 Cruzamento seguro entre nets

Em um esquemático, duas nets distintas **podem se cruzar graficamente** sem conexão.

Permitido:

```text
      │
──────┼──────
      │
```

quando o cruzamento é ortogonal, estritamente interior/interior e não existe pin/junction no ponto.

Continuam bloqueados:

- overlap colinear;
- T-junction por endpoint sobre outro wire;
- endpoints coincidentes de nets diferentes;
- cruzamento sobre foreign pin;
- cruzamento sobre junction elétrica existente.

A política atual vive em `src/coppermind/schematic/incremental.py`, enquanto helpers históricos ficam em `incremental_core.py`.

### 5.6 Sem reflow global inesperado

No modo incremental, mudanças locais não devem reposicionar o circuito inteiro.

O princípio é:

```text
move the minimum semantic neighborhood necessary
```

---

## 6. Auto-placement atual

Arquivo principal:

```text
src/coppermind/tools/auto_placement.py
```

O `component_place_auto` avalia posições candidatas em snapshots isolados e só aceita uma posição legal.

Hoje ele considera:

- anchors semânticos;
- múltiplas direções;
- múltiplos gaps;
- busca de espaço livre dentro da folha;
- comprimento/score das rotas;
- expansão da área ocupada;
- proximidade de componentes;
- clearance de borda;
- reroteamento apenas das nets impactadas.

A área útil da folha é limitada por margem interna. Não aceitar candidato fora da folha apenas porque o centro do símbolo ainda está dentro.

---

## 7. Neighborhood reflow atual

A tool:

```text
component_reflow_neighborhood
```

é o segundo estágio depois do auto-placement.

O cenário que motivou sua criação foi um componente tardio (`R9`) conectado a `VIN` e `SENSE` que ficava eletricamente válido, mas visualmente distante.

A estratégia atual é **target-first / lexicographic-target-bridge**:

1. escolher um bounded semantic neighborhood;
2. manter todos os componentes, exceto o target, congelados;
3. permitir reroute das nets do neighborhood;
4. minimizar primeiro o comprimento das focus nets do target;
5. depois minimizar comprimento total, bends, movimento e score agregado.

Arquivo atual:

```text
src/coppermind/tools/neighborhood_reflow_v3.py
```

---

## 8. Cenários E2E que devem continuar funcionando

### Divisor simples

Arquivo:

```text
examples/incremental_divider_mcp.py
```

Validou anchors reais, power markers, labels e conectividade elétrica.

### Auto-placement simples

Arquivo:

```text
examples/auto_placement_mcp.py
```

Valida que a IA possa declarar conexões antes de escolher posição.

### Circuito denso incremental

Arquivo:

```text
examples/dense_incremental_mcp.py
```

Stress case com `VIN`, `VOUT`, `FB`, `SENSE`, `GND` e resistores paralelos.

### Circuito denso com auto-placement

Arquivo:

```text
examples/dense_auto_placement_mcp.py
```

Compara placement automático com o baseline manual.

### Circuito denso com neighborhood reflow

Arquivo:

```text
examples/dense_neighborhood_reflow_mcp.py
```

É o principal cenário visual atual.

Esse teste deve terminar com:

```text
Final validated: True
```

sem invocar o global composer.

---

## 9. Ambiente local de desenvolvimento usado na validação

### Windows

Diretório de trabalho usado:

```text
C:\Users\xales\coppermind
```

KiCad:

```text
C:\Program Files\KiCad\10.0\bin\kicad-cli.exe
```

Adicionar KiCad ao PATH temporário:

```powershell
$env:Path = "C:\Program Files\KiCad\10.0\bin;$env:Path"
```

Usar sempre a virtualenv do projeto para testes:

```powershell
& .\.venv\Scripts\python.exe -m pytest
```

Evitar `pytest` global, porque pode usar outra instalação do Python.

---

## 10. Subindo o MCP local

Para testes de esquemático, usar o backend em memória:

```powershell
$env:COPPERMIND_BACKEND = "memory"

& .\.venv\Scripts\coppermind.exe `
  --transport streamable-http `
  --host 127.0.0.1 `
  --port 8765 `
  --path /mcp
```

Endpoint:

```text
http://127.0.0.1:8765/mcp
```

O servidor HTTP deve permanecer loopback-only.

---

## 11. Backend e KiCad ao vivo

Não assumir que o MCP já manipula o Eeschema aberto em tempo real.

O caminho estável atual para esquemático é:

```text
semantic state
    ↓
file backend
    ↓
.kicad_sch
    ↓
open/render/ERC with KiCad
```

O IPC atual é mais adequado ao lado PCB/live-board. Não forçar IPC para Eeschema enquanto não existir uma implementação real e validada de edição live-schematic.

---

## 12. CI mínima antes de merge

Todo PR de esquemático deve, no mínimo, fechar verde em:

- Core Python 3.11;
- Core Python 3.12;
- Integration headless KiCad 10.

Além da CI, mudanças de placement/layout devem ter **validação visual local no KiCad**.

Um `pytest` verde sozinho não é suficiente para aceitar uma regressão visual clara.

---

## 13. Próximo milestone: orientação automática + alinhamento por fluxo elétrico

### Problema atual

O CopperMind já escolhe posições razoáveis, mas ainda trata `rotation` principalmente como estado do símbolo, sem uma heurística forte baseada no fluxo elétrico.

Em circuitos densos isso produz:

- resistores orientados de forma inconsistente;
- topologias que não deixam claro o fluxo `source → processing → sink`;
- branches visualmente válidos, porém menos naturais para leitura humana;
- necessidade de wires maiores do que o necessário.

### Objetivo

Adicionar uma etapa de **orientation candidate search** ao placement incremental.

Para cada candidato de posição, avaliar também rotações permitidas do símbolo, por exemplo:

```text
0° / 90° / 180° / 270°
```

A seleção deve considerar a posição real dos pins depois da rotação.

### Heurística de fluxo elétrico

Para componentes de dois pinos, preferir a orientação que alinha seus pins com o vetor aproximado entre os seus vizinhos semânticos.

Exemplo:

```text
VIN ── R ── VOUT
```

preferir resistor horizontal.

Exemplo:

```text
VOUT
  │
  R
  │
 GND
```

preferir resistor vertical.

### Não depender apenas do nome da net

Nomes como `VIN`, `VOUT`, `GND`, `FB`, `SENSE` podem ajudar como sinal fraco, mas a decisão principal deve vir da topologia do Circuit IR:

- componentes conectados;
- posição dos vizinhos;
- quantidade/direção dos pins;
- comprimento estimado das rotas;
- bends;
- congestionamento;
- hierarquia source/sink quando conhecida.

### Suggested score

A escolha de posição + rotação deve minimizar algo na linha de:

```text
route_length
+ bends_penalty
+ envelope_expansion
+ edge_penalty
+ symbol_proximity_penalty
+ flow_misalignment_penalty
+ field_collision_penalty
```

Não transformar isso em um otimizador global. Continuar bounded/local.

### Acceptance criteria do próximo PR

1. `SchSymbol.rotation` passa a ser parte dos candidatos de `component_place_auto`.
2. Rotacionar um componente recalcula anchors reais dos pins antes do routing.
3. Em cadeia simples horizontal, componente de dois pinos prefere orientação horizontal.
4. Em divider vertical, componente de dois pinos prefere orientação vertical.
5. O circuito denso mantém `Final validated: True`.
6. Nenhuma regressão em safe crossings, foreign pins ou junction protection.
7. Nenhum componente sai da folha.
8. Componentes fora do semantic neighborhood permanecem congelados.
9. O layout final deve ser visualmente comparado no KiCad antes do merge.

### Arquivos prováveis

```text
src/coppermind/tools/auto_placement.py
src/coppermind/schematic/composer.py
src/coppermind/schematic/models.py
src/coppermind/schematic/incremental.py
src/coppermind/serialize/kicad_sch.py
```

Criar testes específicos em `tests/` e um exemplo E2E dedicado, por exemplo:

```text
examples/auto_orientation_flow_mcp.py
```

---

## 14. Regras para novos PRs

- uma mudança de arquitetura por PR quando possível;
- manter PR em Draft até CI + screenshot local quando houver impacto visual;
- não aceitar uma solução apenas porque é eletricamente válida se o layout ficar obviamente pior;
- não aumentar escopo com reflow global para resolver um problema local;
- preservar Circuit IR como autoridade elétrica;
- manter mudanças visuais separadas de mudanças de conectividade sempre que possível;
- preferir ferramentas tipadas e restritas a execução arbitrária de código pelo LLM.

---

## 15. Comando de retomada rápida

```powershell
cd C:\Users\xales\coppermind

git switch main
git pull origin main

$env:Path = "C:\Program Files\KiCad\10.0\bin;$env:Path"
$env:COPPERMIND_BACKEND = "memory"

& .\.venv\Scripts\python.exe -m pytest
```

Depois iniciar o MCP e executar o cenário denso:

```powershell
& .\.venv\Scripts\python.exe `
  .\examples\dense_neighborhood_reflow_mcp.py

Invoke-Item .\dense_neighborhood_reflow.kicad_sch
```

Se isso passar e o esquemático abrir corretamente, o ambiente está pronto para o próximo milestone.

---

## 16. Último resultado visual aceito

O último baseline aceito mostrou:

- `R9` movido para próximo de `VIN/SENSE`;
- `VIN` e `SENSE` significativamente mais compactos do que nas iterações anteriores;
- `VOUT`, `FB` e `GND` preservados;
- safe wire crossings habilitados;
- sem junction indevida;
- circuito eletricamente válido.

Esse é o ponto de partida para **orientação automática de componentes + alinhamento por fluxo elétrico**.
