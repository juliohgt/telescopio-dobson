# Arquitetura do software do PC

```
 tela.py ──────┐            (janela tkinter)
               ├──> telescopio.App ──> rastreio ──> montagem ──> arduino.Arduino ──> serial/BT
 telescopio.py ┘    (comandos)         (GoTo,       (passos ↔    (pergunta e        │
                                        rastreio)    graus,       resposta)          ▼
                         │                           alinhamento)            Arduino ou
                         └──> astro.Ceu (skyfield: onde o objeto está)       simulador.py
```

## Módulos (`pc/`)

| Módulo | Responsabilidade |
|---|---|
| `arduino.py` | abre a porta (COM ou `socket://`) e faz pergunta e resposta síncronas; detecta `READY` espontâneo |
| `astro.py` | `Ceu`: alt/az aparente de um objeto no seu local e hora (skyfield + efeméride de421); catálogo de estrelas; RA/Dec do ponto apontado |
| `config.py` | `Config` salva em `pc/config.json` (local, mecânica, limites) |
| `montagem.py` | `Conversor` (passos ↔ ângulos da montagem) e `ModeloAlinhamento` (1 estrela = deslocamento; 2+ = rotação de Kabsch) |
| `rastreio.py` | `Apontador` (céu → passos-alvo), `esperar_chegada`, `Rastreador` (laço de velocidade) |
| `telescopio.py` | `App`: todos os comandos (`local`, `zero`, `alinhar`, `ir`, `seguir`...) e o app de texto |
| `tela.py` | janela tkinter que chama os comandos do `App` |
| `localizacao.py` | pede a posição ao serviço de localização do Windows |
| `controle.py` | app só de movimento manual, útil para testar motores |
| `simulador.py` | finge ser o Arduino, para desenvolver e testar sem hardware |

**Regra de dependência:** a tela não tem lógica própria de astronomia nem de
alinhamento; ela chama o `App`. Lógica nova vai no `App` (testável sem janela) e a
tela só a expõe.

## Fluxo do GoTo (`App._ir`)

1. `Ceu.altaz(alvo, agora)` → onde o objeto está.
2. Confere os limites: altura mínima e curso do eixo de altitude.
3. `Apontador.passos_para()`: modelo de alinhamento → ângulos da montagem → passos,
   pelo caminho mais curto no azimute.
4. `GOTO AZ` e `GOTO ALT`; espera chegar (`esperar_chegada`).
5. **Segunda passada:** recalcula e corrige o quanto o céu girou durante a primeira.

## Fluxo do rastreamento (`Rastreador`)

A cada `periodo_rastreio` (1 s): `POS?` → onde o objeto estará em `t + período` →
`RATE = (futuro − atual) / período` em cada eixo. Detalhes em
[modelo-matematico.md](modelo-matematico.md). Sempre termina com `STOP`, inclusive em erro.

## Concorrência na tela

O tkinter roda num laço de eventos de **uma** thread. Se ela esperasse o Bluetooth ou
um GoTo de 30 s, a janela congelaria, e o botão Parar junto.

| Thread | Faz |
|---|---|
| principal (tkinter) | desenha e reage a cliques; lê a fila de mensagens a cada 100 ms (`root.after`) |
| trabalho (uma por operação) | `App.executar("ir ...")`, `seguir`, `alinhar`, `zero` |
| comandos curtos | fila FIFO de `JOG`/`JOGSPEED`, na ordem em que foram clicados |
| posição | a cada 0,5 s: `POS?`, alt/az, RA/Dec, alvo; estrelas a cada 30 s |

- As threads não tocam em widgets: mandam `(tipo, dado)` para uma fila, e a thread
  principal chama `_ao_<tipo>`.
- **PARAR** não entra na fila: manda `STOP` numa thread própria e liga o evento que faz
  a operação em curso encerrar.
- O `Arduino` serializa os comandos com um lock, então várias threads podem usá-lo.

## Dados e arquivos locais

| Arquivo | O que é | No Git? |
|---|---|---|
| `pc/config.json` | configuração **com a sua localização** | **não** (`.gitignore`) |
| `pc/dados/de421.bsp` | efeméride NASA/JPL, ~17 MB, baixada no primeiro uso | não |
| `pc/.venv/` | ambiente virtual Python | não |

## Particularidades do Windows

- Use `py` (lançador do Python); `python` pode ser só o atalho da Microsoft Store.
- Use `127.0.0.1`, não `localhost`, para o simulador: `localhost` tenta IPv6 primeiro
  e a conexão demora ~2 s.
- `tela.py` chama `SetProcessDpiAwareness(1)`; sem isso, com escala de 125% ou 150%
  o Windows amplia a janela como imagem e o texto fica borrado.
- `localizacao.py` chama o PowerShell com `CREATE_NO_WINDOW`, para não piscar uma
  janela de console.
