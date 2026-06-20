# Coppermind — Servidor MCP de Projeto de PCB com IA

**Documento de Arquitetura e Plano**
Versão 0.1 — rascunho · Junho de 2026
Nome de trabalho: **Coppermind** (placeholder — copper = cobre da PCB + "mind")

---

## 1. Visão

Um servidor MCP que não apenas *executa comandos* no KiCAD, mas *raciocina sobre projeto eletrônico*. A diferença central em relação ao projeto de referência (mixelpixx/KiCAD-MCP-Server) é deslocar o produto de uma **camada fina de tradução** ("traduza esta frase numa chamada de API do pcbnew") para um **copiloto de engenharia** que entende intenção, valida continuamente, conhece boas práticas de EE e mantém o humano no controle de um fluxo iterativo e auditável.

Frase-guia: *"Descreva o que você quer projetar; o sistema propõe, verifica, explica e só então aplica — e tudo é reversível."*

### Os quatro pilares (definidos por você)

1. **Arquitetura limpa** — uma base de código coerente, testável, com documentação que corresponde à realidade. Sem "router fantasma", sem contradições de versão, sem dívida acidental.
2. **Inteligência de design** — conhecimento embarcado de topologias, regras de boas práticas, otimização de layout e sugestão de circuitos, não só CRUD de componentes.
3. **Confiabilidade / verificação** — validação automática antes de cada escrita, DRC/ERC integrados ao loop, e impossibilidade estrutural de gerar estados inválidos sem aviso.
4. **Experiência / colaboração** — feedback visual rico, histórico versionado, undo/redo de verdade e um fluxo humano-IA com previsões e confirmações.

---

## 2. O que aprendemos com o projeto de referência

Análise honesta do mixelpixx/KiCAD-MCP-Server (~1,2k stars). Ele provou a demanda e algumas boas ideias — vamos preservá-las e corrigir o resto.

### 2.1 O que vale herdar

- Backend híbrido com auto-detecção (a ideia certa, mesmo que a execução precise mudar).
- Resources MCP expondo estado do projeto para leitura sem efeitos colaterais.
- Solução engenhosa de manipulação de schematic via injeção de S-expression quando a biblioteca não cria do zero.
- Integrações úteis: JLCPCB (catálogo + preço/estoque), Freerouting, enriquecimento de datasheet.

### 2.2 Falhas a evitar (e o que faremos diferente)

| Falha no projeto de referência | Causa raiz | Nossa decisão |
| --- | --- | --- |
| Documentação contraditória (README diz 122 tools / inventário diz 137; versões divergentes) | Docs escritas à mão, fora de sincronia com o código | **Docs geradas a partir do código** (single source of truth). A contagem e o schema de cada tool saem do registry em build/CI. |
| "Router pattern" anunciado mas inerte (todas as tools sempre visíveis; economia de 70% não acontece) | Plano abandonado pela metade, sem CI que valide a alegação | **Progressive discovery real** com poucas tools sempre visíveis e descoberta sob demanda — medida e testada (ver §6). |
| Ponte TypeScript ↔ Python (subprocesso, serialização, dois runtimes) | Decisão histórica; dobra a superfície de bugs e setup | **Uma única linguagem (Python)**, eliminando a ponte de processos (ver §5). |
| Forte dependência do SWIG/`pcbnew`, com IPC apenas "experimental" | Foi o caminho mais fácil no KiCAD 8/9 | **IPC-first.** O SWIG será **removido no KiCAD 11 (fev/2027)**; construir sobre ele hoje é dívida garantida. |
| Designs gerados por IA sem verificação obrigatória; disclaimer "use por sua conta e risco" | Sem camada de validação no loop | **Verificação não-opcional**: nada é escrito sem passar por validação; DRC/ERC fazem parte do ciclo, não de um passo final manual. |
| Estado implícito, escritas diretas, difícil desfazer | Operações mutam o arquivo direto | **Modelo transacional** com preview, diff e rollback (snapshots automáticos + undo). |
| Confiabilidade aferida por "test results" no README, não por CI público | Falta de harness de testes contra KiCAD real | **CI com KiCAD headless** validando cada tool ponta a ponta. |

> Fato decisivo: o KiCAD 10 saiu em março/2026 (estável 10.0.3) e o **KiCAD 11, previsto para fev/2027, remove as bindings SWIG**. A API IPC (Protobuf, via `kicad-python`/`kipy`) é o futuro suportado. Qualquer projeto novo deve nascer IPC-first.

---

## 3. Princípios de arquitetura

1. **Single source of truth.** Schemas, docs e capacidades derivam do código. Se não está no registry, não existe.
2. **Tudo é reversível e previsível.** Toda mutação tem preview, diff e desfazer. O usuário vê o que vai acontecer antes de acontecer.
3. **Verificação é parte do caminho feliz**, não um opcional. Estados inválidos são barrados na borda.
4. **Conhecimento explícito e auditável.** As "boas práticas de EE" vivem numa base de regras versionada e citável — não escondidas em prompts.
5. **Camadas com fronteiras nítidas.** Protocolo, orquestração, domínio e adaptador de KiCAD são separados e testáveis isoladamente.
6. **Degradação graciosa.** Funciona com KiCAD aberto (IPC) e, quando possível, em modo batch; degrada com mensagens claras em vez de falhar em silêncio.
7. **Privacidade por padrão.** Logs locais, sem telemetria implícita; avisos explícitos sobre o que sai da máquina (datasheets, APIs de fornecedor).

---

## 4. Arquitetura em camadas

```
┌──────────────────────────────────────────────────────────────┐
│  Assistente de IA (Claude / outros clientes MCP)              │
└───────────────────────────┬──────────────────────────────────┘
                            │ MCP (JSON-RPC 2.0, stdio/HTTP)
┌───────────────────────────▼──────────────────────────────────┐
│  L1 · Camada de Protocolo (FastMCP / SDK Python oficial)      │
│  - Registro de tools/resources/prompts                        │
│  - Progressive discovery (poucas visíveis + busca sob demanda)│
│  - Schemas gerados, validação de entrada (pydantic)           │
└───────────────────────────┬──────────────────────────────────┘
┌───────────────────────────▼──────────────────────────────────┐
│  L2 · Orquestração & Transações                               │
│  - Planner: intenção → plano de operações                     │
│  - Transaction manager: begin/preview/commit/rollback         │
│  - Diff engine + snapshots automáticos + undo/redo            │
└──────────────┬───────────────────────────────┬───────────────┘
┌──────────────▼────────────┐   ┌──────────────▼────────────────┐
│  L3 · Núcleo de Domínio    │   │  L4 · Motor de Verificação     │
│  (independente de KiCAD)   │   │  - DRC/ERC no loop             │
│  - Modelo de board/sch     │◄─►│  - Regras de boas práticas EE  │
│  - Knowledge base (regras, │   │  - Checagens pré-escrita       │
│    topologias, heurísticas)│   │  - Relatórios explicáveis      │
└──────────────┬─────────────┘   └────────────────────────────────┘
┌──────────────▼────────────────────────────────────────────────┐
│  L5 · Adaptador de KiCAD (Port/Adapter)                        │
│  - Interface única `KicadBackend`                              │
│  - IPCBackend (kicad-python/kipy) — PRIMÁRIO                   │
│  - BatchBackend (CLI `kicad-cli` / headless) — fallback        │
│  - SwigBackend (legado, só ≤ KiCAD 10) — opcional/depreciado   │
└──────────────┬─────────────────────────────────────────────────┘
┌──────────────▼─────────────────────────────────────────────────┐
│  L6 · Integrações externas (plugáveis, isoladas)               │
│  Fornecedores (JLCPCB/LCSC/Digi-Key), autorouter, datasheets   │
└────────────────────────────────────────────────────────────────┘
```

A regra de ouro: **L3 (domínio) e L4 (verificação) não conhecem o KiCAD.** Eles operam sobre um modelo interno. Isso permite testar inteligência e verificação sem KiCAD rodando, e trocar o backend (IPC hoje, IPC-only amanhã) sem tocar na lógica.

---

## 5. Decisão de stack (recomendação)

Você pediu recomendação. **Python puro, com o SDK MCP oficial (FastMCP).**

Justificativa:

- **Elimina a ponte TS↔Python** do projeto de referência. Aquela ponte existe só porque o ecossistema MCP começou em TS; ela duplica setup, serialização e modos de falha. Um único runtime Python remove uma classe inteira de bugs e simplifica radicalmente a instalação.
- **A integração com KiCAD é Python nativamente.** Tanto `kicad-python` (IPC) quanto o legado `pcbnew` (SWIG) são Python. Ficar em Python coloca o servidor na mesma linguagem do alvo.
- **FastMCP** dá tools/resources/prompts com schema derivado de type hints + `pydantic`, o que sustenta o princípio "schema gerado do código".
- **Trade-off aceito:** perde-se o tooling de tipos do TS, mas `pydantic` + `mypy` cobrem validação e tipagem estáticas o suficiente.

Componentes concretos:

- Protocolo: `mcp` (SDK oficial Python) / FastMCP.
- Validação: `pydantic v2`.
- Backend KiCAD: `kicad-python` (kipy) como primário; `kicad-cli` para exportações batch headless.
- Testes: `pytest` + harness com KiCAD headless em container (CI).
- Empacotamento: `uv`/`pipx` para instalação de um comando; sem `npm install` + `npm build`.

---

## 6. Design das tools (resolvendo o "tool overload" de verdade)

O problema real, confirmado pelas boas práticas atuais de MCP: cada definição de tool consome contexto antes mesmo de o modelo ler a pergunta; muitas tools degradam a seleção do modelo. O projeto de referência tem ~137 tools sempre visíveis e *afirma* economizar contexto sem fazê-lo.

Nossa abordagem:

- **Núcleo enxuto sempre visível (~15–20 tools)** para o fluxo de 80% dos casos: criar/abrir projeto, colocar componente, rotear, validar, exportar, e as tools de descoberta.
- **Progressive discovery real**: `search_tools` / `get_tool_schema` carregam definições sob demanda, *anexando após o breakpoint de cache* para não invalidar o cache do prompt (boa prática de 2026).
- **Granularidade correta**: nada de uma mega-tool que ramifica em 15 ações por string; nada de exigir 3 chamadas sequenciais para uma operação óbvia (essas viram tools compostas, ex. `place_and_route_decoupling`).
- **Nomenclatura consistente** `recurso_ação` (ex. `board_add_outline`, `component_place`, `net_route`) para busca e filtragem previsíveis.
- **Verificável por CI**: um teste mede quantos tokens o conjunto visível consome e falha se ultrapassar o orçamento — a "economia de contexto" deixa de ser slogan e vira invariante testada.

---

## 7. Inteligência de design (o grande diferencial)

Aqui está o que transforma "executor de comandos" em "copiloto". Implementado em L3, independente do KiCAD.

### 7.1 Base de conhecimento de EE (explícita e versionada)

Em vez de embutir conhecimento em prompts opacos, manter uma **knowledge base** de regras e padrões, versionada e citável:

- **Regras de boas práticas**: capacitor de desacoplamento por pino de alimentação de CI; largura de trilha por corrente (tabelas IPC-2221); retorno de terra; isolamento para alta tensão; comprimento casado para pares diferenciais; antiilhas térmicas em planos.
- **Padrões/topologias reutilizáveis ("design blocks")**: reguladores LDO/buck típicos, front-ends de USB, cristais com cargas, divisores, RC de reset, etc. — parametrizáveis.
- **Heurísticas de placement/roteamento**: agrupar por função, posicionar desacoplamento junto ao pino, minimizar laços de corrente.

Cada sugestão da IA **cita a regra** que a fundamenta ("largura 0,4 mm para 1 A em 1 oz, ΔT 10 °C — IPC-2221"). Isso é auditável e ensina o usuário.

### 7.2 Como a inteligência opera

- **Da intenção ao plano**: "faça um regulador 3,3 V" → o planner instancia um design block, escolhe valores, posiciona, e apresenta plano + justificativa *antes* de aplicar.
- **Crítica proativa**: ao detectar um CI sem desacoplamento, ou trilha subdimensionada, sugere correção com a regra citada.
- **Otimização de layout** como serviço de domínio (placement por função, sugestão de reorganização), separada da execução.

> Importante manter a honestidade do projeto original quanto a limites: sugestões de IA **não substituem revisão de engenharia**. A diferença é que aqui a verificação é estrutural e as recomendações são rastreáveis — reduzindo, não eliminando, o risco.

---

## 8. Confiabilidade e verificação

### 8.1 Modelo transacional (nada de escrita cega)

Toda mutação segue: **`begin` → aplicar no modelo → `preview` (diff + render) → validação → `commit` ou `rollback`.**

- O usuário (ou a IA) vê um **diff** estruturado e um **render** do antes/depois antes de confirmar.
- **Snapshots automáticos** antes de cada commit; **undo/redo** reais.
- Falha de validação ⇒ rollback automático com explicação.

### 8.2 Verificação no loop, não no fim

- **Pré-escrita**: checagens baratas (colisão de footprint, pino inexistente, net duplicada, fora dos limites da placa) barram operações inválidas na borda — o sistema é *estruturalmente* incapaz de aplicar muitos estados ruins.
- **DRC/ERC integrados**: rodam automaticamente após mutações relevantes; violações voltam como dados estruturados e explicáveis, não texto solto.
- **Relatórios explicáveis**: cada violação traz causa, regra e correção sugerida.

### 8.3 Garantia de qualidade do próprio servidor

- **CI com KiCAD headless** (container) executa cada tool ponta a ponta contra um KiCAD real.
- **Testes de propriedade**: gerar boards aleatórios válidos e garantir invariantes (ex.: todo commit que passa na validação abre no KiCAD sem erro).
- **Testes de regressão** ancorados em projetos de exemplo (LED board, regulador, adaptador FFC).

---

## 9. Experiência e colaboração

- **Feedback visual rico**: renders PNG/SVG do board e do schematic expostos como resources, atualizados a cada transação, com realce de diffs.
- **Sessões versionadas**: histórico de operações como linha do tempo navegável; cada passo é um snapshot rotulado (evolução do `snapshot_project` do original, porém automático e estruturado).
- **Confirmar/editar planos**: a IA propõe um plano com justificativa; o usuário aprova, ajusta ou rejeita parte dele antes da execução.
- **Modo "explique"**: para qualquer estado ou sugestão, o servidor explica o porquê citando a knowledge base.
- **Tempo real com a UI**: via IPC, mudanças aparecem imediatamente no KiCAD aberto, sem reload manual — agora como caminho primário, não experimental.

---

## 10. Integrações (plugáveis e isoladas em L6)

Mantidas atrás de interfaces, sem contaminar o domínio:

- **Fornecedores**: JLCPCB/LCSC, com arquitetura aberta para Digi-Key/Mouser. Preço, estoque, Básico vs. Estendido, sugestão de alternativas e otimização de custo de montagem.
- **Autorouter**: Freerouting (Java/Docker/Podman) atrás de uma interface `AutoRouter`, permitindo trocar de motor.
- **Datasheets**: enriquecimento via LCSC e outras fontes, com avisos de privacidade sobre o que é consultado online.

---

## 11. Roadmap incremental

**Fase 0 — Fundação (prova de arquitetura)**
SDK MCP em Python, `KicadBackend` (interface) + `IPCBackend`, modelo de domínio mínimo, transação begin/preview/commit/rollback, 5–6 tools núcleo, CI com KiCAD headless. *Critério de saída: criar projeto, colocar componente e rotear, tudo reversível e testado em CI.*

**Fase 1 — Verificação no loop**
DRC/ERC integrados, checagens pré-escrita, relatórios explicáveis, diffs e renders nos previews. *Critério: impossível aplicar estados inválidos comuns sem aviso.*

**Fase 2 — Progressive discovery + paridade de tools**
Núcleo enxuto + descoberta sob demanda com orçamento de contexto testado; cobrir board/component/routing/schematic/export com nomenclatura consistente.

**Fase 3 — Inteligência de design**
Knowledge base de EE versionada, design blocks parametrizáveis, crítica proativa com citação de regras, sugestões de placement.

**Fase 4 — Colaboração e integrações**
Linha do tempo versionada, modo "explique", fornecedores, autorouter, datasheets.

**Fase 5 — Maturidade**
Schematics hierárquicos, otimização de layout avançada, suporte a variantes (recurso novo do KiCAD 10), preparação para o mundo IPC-only do KiCAD 11.

---

## 12. Riscos e mitigações

| Risco | Mitigação |
| --- | --- |
| IPC exige KiCAD rodando (não abre arquivos headless puros) | `BatchBackend` via `kicad-cli` para exportação/validação headless; gerenciamento de ciclo de vida da instância KiCAD. |
| Remoção do SWIG no KiCAD 11 quebra o legado | IPC-first desde o dia 1; SWIG isolado atrás da interface e marcado depreciado. |
| API IPC ainda evoluindo entre 10.x e 11 | Adaptador fino + testes de contrato contra cada versão no CI. |
| Inteligência de IA gerar designs sutilmente errados | Verificação estrutural + citação de regras + revisão humana obrigatória declarada; nunca prometer correção garantida. |
| Escopo ambicioso (4 pilares de uma vez) | Roadmap incremental com critérios de saída; cada fase entrega valor isolado. |
| Manutenção da knowledge base de EE | Regras versionadas, com fonte citada (IPC etc.) e testes; contribuição comunitária estruturada. |

---

## 13. Resumo das decisões-chave

1. **Python puro + FastMCP** — elimina a ponte TS↔Python.
2. **IPC-first** — alinhado ao KiCAD 11 (SWIG removido em fev/2027); SWIG só como legado isolado.
3. **Domínio e verificação independentes do KiCAD** — testáveis sem o KiCAD, backend trocável.
4. **Modelo transacional com preview/diff/rollback** — nada de escrita cega; tudo reversível.
5. **Verificação no caminho feliz** — DRC/ERC e checagens pré-escrita no loop, não opcionais.
6. **Progressive discovery medido por CI** — a economia de contexto vira invariante testada, não slogan.
7. **Conhecimento de EE explícito, versionado e citável** — inteligência auditável, não prompt mágico.
8. **Docs e schemas gerados do código** — fim das contradições de versão/contagem.
9. **CI com KiCAD headless** — confiabilidade comprovada, não declarada.

---

*Documento de planejamento. Próximos passos sugeridos: (a) validar nome e escopo da Fase 0; (b) prototipar o `KicadBackend` + uma transação ponta a ponta contra KiCAD 10 via IPC; (c) montar o esqueleto do repositório e o CI headless.*
