# Hardware

## Lista de materiais

| Qtd | Item | Observação |
|---|---|---|
| 1 | Arduino Duemilanove (ATmega328P) | um UNO também serve: mesma pinagem e mesmo chip |
| 1 | Módulo Bluetooth HC-06 | opcional: o cabo USB faz o mesmo papel |
| 2 | Driver DRV8825 (placa padrão, sensor de 0,1 Ω) | um por eixo, com dissipador |
| 2 | Motor de passo NEMA 17 (1,8° = 200 passos/volta) | anote a **corrente por fase** da etiqueta |
| 2 | Capacitor eletrolítico ≥ 100 µF, tensão acima da fonte | um por driver, entre VMOT e GND |
| 1 | Resistor 1 kΩ e 1 resistor 2 kΩ | divisor de tensão do RX do HC-06 |
| 1 | Fonte para os motores (8,2–45 V, ex.: 12 V) | corrente para os dois motores |
| 2 | Transmissão com redução (polia GT2 + correia, ou sem-fim) | ver "Mecânica" |

## Ligações

### Pinos do Arduino

| Função | Pino |
|---|---|
| AZ STEP / DIR / EN | 2 / 3 / 4 |
| ALT STEP / DIR / EN | 5 / 6 / 7 |
| HC-06 TX → Arduino RX | 10 (ligação direta) |
| Arduino TX → HC-06 RX | 11 (**com divisor de tensão**) |

Os pinos 0 e 1 são do USB, por isso o HC-06 fica na `SoftwareSerial` (10 e 11).

### DRV8825 (cada um)

| Pino | Liga em |
|---|---|
| STEP, DIR, EN | pinos do Arduino acima. EN é ativo em nível **baixo** (baixo = habilitado) |
| RST e SLP | **ligados juntos e em nível alto**; soltos, o driver não funciona |
| M0, M1, M2 | microstep. **1/16** (padrão): M2 = alto, M1 = baixo, M0 = baixo |
| VMOT, GND | fonte dos motores + capacitor de 100 µF |
| A1, A2, B1, B2 | bobinas do motor (um par por bobina) |

Tabela de microstep do DRV8825 (M2 M1 M0): 000 = passo inteiro, 001 = 1/2, 010 = 1/4,
011 = 1/8, 100 = 1/16, 101/110/111 = 1/32. Se mudar os jumpers, mude também
`microstep` nas Configurações.

### HC-06: divisor de tensão

O RX do HC-06 tolera 3,3 V, e o Arduino é 5 V:

```
Arduino 11 ──[ 1kΩ ]──┬── HC-06 RX      (5 V × 2k / 3k ≈ 3,3 V)
                      │
                   [ 2kΩ ]
                      │
                     GND
```

HC-06 TX → Arduino 10 pode ir direto: 3,3 V já é lido como nível alto pelo ATmega a 5 V.
HC-06: VCC em 5 V; baud padrão 9600; PIN de pareamento costuma ser `1234` ou `0000`.

### Alimentação: os três erros que queimam peça ou travam o projeto

1. **Sem capacitor no VMOT:** ao ligar o motor, o pico de tensão queima o DRV8825.
2. **Motor alimentado pelo 5 V do Arduino:** não tem corrente; use a fonte dos motores.
3. **Sem GND comum:** GND do Arduino, da fonte dos motores e do HC-06 precisam estar juntos.

## Ajuste da corrente (Vref)

Nas placas DRV8825 comuns (sensor de 0,1 Ω): **corrente limite = Vref × 2**, então
**Vref = corrente ÷ 2**.

1. Pegue a corrente por fase na etiqueta do motor (ex.: 1,5 A).
2. Comece em ~70% dela: 1,05 A → **Vref ≈ 0,52 V**.
3. Com o driver alimentado, meça entre o trimpot e o GND e ajuste.
4. Se o motor perder passos sob carga, suba aos poucos. Use dissipador.

## Mecânica

### Redução
O NEMA 17 ligado direto no eixo não tem torque para uma Dobsoniana nem resolução
para rastrear. A redução multiplica os dois:

`passos por grau = 200 × microstep × redução / 360`

| Redução | Passos/grau (1/16) | 1 passo vale | Para rastrear |
|---|---|---|---|
| 1:1 | 8,9 | 6,75′ | grosso demais |
| 5:1 | 44 | 81″ | só em aumento baixo |
| 50:1 | 444 | 8″ | bom |
| 100:1 | 889 | ~4″ | ótimo |

O movimento sideral máximo é de 15″/s. Com 50:1, o rastreamento manda ~2 passos/s.

### Transmissão sem patinar
O sistema **conta passos** (não há sensor). Se a correia patinar ou houver
embreagem de atrito, a posição calculada se perde sem aviso. Prefira correia dentada
GT2 bem tensionada ou rosca sem-fim.

### Medir a redução real
Marque o eixo e mande o motor dar N voltas: no app `controle.py`, tecle `z` (zera) e
depois `g`, digitando `N × 200 × microstep` no AZ (ex.: 10 voltas com 1/16 = 32000).
Conte quanto o eixo girou: **redução = voltas do motor ÷ voltas do eixo**.
O alinhamento com 2 estrelas **detecta** redução errada (ver
[modelo-matematico.md](modelo-matematico.md)), mas não diz o valor certo.

### Sentido dos motores
Convenção: AZ positivo gira Norte→Leste (horário visto de cima); ALT positivo sobe o
tubo. Se um motor girar ao contrário, ative `inverter_az` ou `inverter_alt`.
