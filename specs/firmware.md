# Firmware e protocolo serial

Arquivo: `firmware/controlador/controlador.ino`. Biblioteca: **AccelStepper**.

## Papel

O Arduino é um **controlador "burro"**: executa movimentos em **passos** e informa a
posição. Ele nunca vê coordenadas celestes. Quem converte ângulo ↔ passos (usando
redução e microstep) é o PC. Essa divisão é o que permite usar a Duemilanove: o
cálculo astronômico pesado roda no PC.

## Modos de cada eixo

| Modo | Comando que entra | Como anda | Função do AccelStepper |
|---|---|---|---|
| Posicionamento | `MOVE`, `GOTO` | rampa trapezoidal até o alvo | `run()` |
| JOG | `JOG <1\|-1>` | velocidade fixa (`JOGSPEED`) até `JOG 0`/`STOP` | `runSpeed()` |
| RATE | `RATE <sps>` | velocidade definida pelo PC (rastreamento) | `runSpeed()` |

Ao sair de JOG/RATE para MOVE/GOTO, o eixo para com `setCurrentPosition(currentPosition())`,
que zera a velocidade e o estado interno da rampa. Sem isso, o `run()` poderia partir
com uma velocidade velha. `setSpeed()` é limitado por `SPEED` (o AccelStepper
aplica `constrain`), então `SPEED` também limita JOG e RATE.

## Canais

O firmware aceita comandos por **dois canais ao mesmo tempo**, a 9600 bps cada:

| Canal | Pinos | Uso |
|---|---|---|
| HC-06 (Bluetooth), `SoftwareSerial` | 10 (RX) e 11 (TX) | uso normal, sem fio |
| USB (`Serial`) | 0 e 1, via chip FTDI | bancada, e alternativa ao Bluetooth |

Cada canal tem seu buffer de linha, e **a resposta sai pelo canal de onde veio o
comando**. O `READY` do `setup()` sai pelos dois. A gravação do firmware usa o USB
(pinos 0/1) e não conflita com o HC-06.

## Protocolo

- Texto, 9600 bps, linhas terminadas por `\n` ou `\r`; no máximo 47 caracteres por linha.
- **Uma linha de resposta por comando**, na ordem. O PC depende disso para casar
  pergunta e resposta.
- Comandos e eixos sem diferenciar maiúsculas (`strcasecmp`).

| Comando | Resposta | Efeito |
|---|---|---|
| `PING` | `PONG` | teste de conexão |
| `POS?` | `POS AZ=<n> ALT=<n>` | posição em passos |
| `MOVE AZ\|ALT <delta>` | `OK MOVE` | relativo à posição atual, com rampa |
| `GOTO AZ\|ALT <pos>` | `OK GOTO` | absoluto, com rampa |
| `JOG AZ\|ALT <1\|-1\|0>` | `OK JOG` | contínuo até `0` ou `STOP` |
| `RATE AZ\|ALT <sps>` | `OK RATE` | velocidade constante, com sinal e fração |
| `SPEED <sps>` | `OK SPEED <v com 2 casas>` | velocidade máxima; sem valor, não responde |
| `ACCEL <sps2>` | `OK ACCEL <v>` | aceleração; 0 é ignorado pelo AccelStepper |
| `JOGSPEED <sps>` | `OK JOGSPEED <v>` | velocidade do JOG |
| `STOP` | `OK STOP` | para os dois eixos na hora |
| `ZERO` | `OK ZERO` | para e zera a posição dos dois eixos |
| `ENABLE` | `OK ENABLE` | liga os drivers |
| `DISABLE` | `OK DISABLE` | para e desliga os drivers |

Erros: `ERR <comando>` (comando desconhecido ou sem argumentos), `ERR AXIS <eixo>`,
`ERR DISABLED` (movimento com drivers desligados).

### Regras que protegem a contagem de passos

- **`DISABLE` recusa movimento:** com o motor solto, o AccelStepper continuaria
  "contando" passos que o motor não dá, e a posição ficaria errada sem aviso.
- **`READY` espontâneo:** o firmware imprime `READY` no `setup()`. Se ele aparecer no
  meio da sessão, o Arduino reiniciou e a posição voltou a 0. O PC apaga o alinhamento.
  Pelo USB o Arduino reinicia ao abrir a porta (sinal DTR) e manda `READY`; pelo HC-06
  não reinicia e não manda. Por isso **a conexão é confirmada com `PING`, nunca com `READY`**.
  Atenção: abrir a porta USB **reinicia o Arduino e zera a posição**, inclusive se outro
  programa estiver usando o Bluetooth naquele momento.

## Simulador

`pc/simulador.py` espelha este protocolo (mesmas respostas, mesmos erros, mesma
limitação de velocidade e rampa trapezoidal) e escuta em `socket://127.0.0.1:7777`.
**Ao mudar o firmware, mude o simulador junto** e cubra a mudança em
`pc/testes/test_simulador.py`. Diferença conhecida: o simulador manda `READY` a cada
conexão, como o Arduino pelo USB.

## Recursos

| Chip da Duemilanove | Flash | RAM | Sobra para a pilha |
|---|---|---|---|
| ATmega328P (`cpu=atmega328`) | 13.092 bytes (42%) | 708 bytes (34%) | 1.340 bytes |
| ATmega168 (`cpu=atmega168`) | 13.092 bytes (91%) | 708 bytes (69%) | 316 bytes: apertado |

Boa parte da RAM são os buffers das duas seriais (`Serial` e `SoftwareSerial`).

```bash
arduino-cli core install arduino:avr
arduino-cli lib install AccelStepper
arduino-cli compile --fqbn arduino:avr:diecimila:cpu=atmega328 firmware/controlador
```
