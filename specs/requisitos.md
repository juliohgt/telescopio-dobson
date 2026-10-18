# Requisitos

## Objetivo

Motorizar um telescópio de **montagem Dobsoniana** (alt-azimutal: um eixo gira na
horizontal, o azimute; outro sobe e desce, a altitude) para:

1. apontar à mão pelo computador;
2. ir sozinho até um objeto escolhido (**GoTo**);
3. manter o objeto no campo, compensando a rotação da Terra (**rastreamento**).

## Restrições de partida

Vieram do hardware disponível e de decisões tomadas no início do projeto:

| Restrição | Consequência |
|---|---|
| Placa **Arduino Duemilanove** (ATmega328P, 16 MHz, 2 KB de RAM, lógica 5 V) | o Arduino só executa passos; todo o cálculo fica no PC |
| **HC-06** (Bluetooth clássico, perfil serial) | o PC enxerga uma porta COM; o RX do HC-06 exige divisor de tensão 5 V→3,3 V |
| 2× **DRV8825** + 2× **NEMA 17** | um driver e um motor por eixo |
| Controle **pelo computador**, não pelo celular | app para Windows |
| Software do PC em **Python** | por causa do `skyfield` (ver abaixo) |
| Projeto **"faça você mesmo"** | descartado o firmware pronto **OnStep**, que exige placa mais forte (ESP32, Teensy, STM32) e trocaria a programação por configuração |

### Por que Python
O ponto difícil é o cálculo astronômico (posição de objetos, RA/Dec → altitude/azimute
no seu local, hora sideral, refração). Em Python há o `skyfield`, biblioteca de
referência da área. Em C#/.NET seria possível (há o *Astronomy Engine*), mas com
ecossistema bem menor. A serial é trivial nas duas.

## Requisitos funcionais

| Id | Requisito | Onde está |
|---|---|---|
| RF1 | Mover cada eixo à mão, segurando um botão ou uma seta do teclado, e parar ao soltar | `tela.py`, firmware `JOG` |
| RF2 | Parar tudo imediatamente (botão, Esc ou espaço) | firmware `STOP` |
| RF3 | Definir o local de observação, digitado ou pelo serviço de localização do Windows | `config.py`, `localizacao.py` |
| RF4 | Alinhar a montagem centralizando 1 ou mais estrelas conhecidas | `montagem.py` |
| RF5 | Apontar (GoTo) para estrela da lista, Lua, planeta ou coordenada RA/Dec J2000 | `rastreio.py`, `astro.py` |
| RF6 | Rastrear o objeto continuamente | `rastreio.py`, firmware `RATE` |
| RF7 | Mostrar para onde o tubo aponta: altitude, azimute, RA/Dec e mapa do céu | `tela.py` |
| RF8 | Recusar alvos abaixo da altura mínima ou fora do curso do eixo de altitude | `telescopio.py` |
| RF9 | Detectar que o Arduino reiniciou e invalidar o alinhamento | `arduino.py`, `telescopio.py` |
| RF10 | Funcionar sem hardware, contra um simulador, para desenvolvimento e testes | `simulador.py` |

## Requisitos não funcionais

| Id | Requisito |
|---|---|
| RNF1 | A tela nunca congela: comunicação e operações longas rodam fora da thread da interface |
| RNF2 | Modo noturno só em vermelho, para preservar a adaptação do olho ao escuro |
| RNF3 | Funciona offline no campo, depois do primeiro download da efeméride (~17 MB) |
| RNF4 | O firmware cabe com folga na Duemilanove com ATmega328P (42% da flash, 34% da RAM); no ATmega168 cabe, mas apertado |
| RNF5 | Nenhum dado pessoal (localização) vai para o repositório: `pc/config.json` é ignorado pelo Git |

## Fora de escopo

- **Encoders nos eixos** (malha fechada): o sistema conta passos. Ver [pendencias.md](pendencias.md).
- **Fotografia de longa exposição:** a montagem alt-az gira o campo durante o rastreamento.
- **Controle pelo celular.**
- **Integração ASCOM / Stellarium:** possível no futuro (ver [pendencias.md](pendencias.md)).

## Premissas

Se alguma delas falhar, o GoTo e o rastreamento erram:

1. A transmissão (polia/correia ou engrenagem) **não patina**.
2. O motor **não perde passos** (torque e Vref adequados, velocidade não exagerada).
3. O **Zerar** é feito com o tubo na horizontal.
4. O **relógio do Windows** está sincronizado.
5. A **redução e o microstep configurados** são os reais.
