# Testes

## Testes automatizados (sem hardware)

```bash
cd pc
.venv\Scripts\python -m unittest discover -s testes -v
```

| Arquivo | Cobre |
|---|---|
| `test_simulador.py` | respostas do protocolo iguais às do firmware, `RATE`, `DISABLE`, rampa chegando no alvo sem ultrapassar nem exceder a velocidade, comunicação pelo pyserial |
| `test_montagem.py` | geometria, conversão passos↔graus, inversão de sentido, caminho curto, alinhamento com montagem sintética desnivelada (3°) e Norte desconhecido, mínimos quadrados com ruído, detecção de redução errada |
| `test_fase2.py` | fluxo completo contra o simulador: alinhar 2 estrelas → GoTo na 3ª (erro < 0,06°) → rastrear em tempo real (erro < 0,004°) |
| `test_tela.py` | tela: segurar e soltar, repetição de tecla, parar, tema, alinhar/apontar/seguir. **Opcional** (ver abaixo) |

Resultado atual: 41 testes; 35 rodam por padrão e passam; os 6 da tela são opcionais.

**O teste de rastreamento foi conferido pelo avesso:** com o rastreamento desligado de
propósito (velocidades forçadas a zero), ele falha com erro de 42″, que é o quanto a
estrela andou. Um teste que passa só vale se falhar com o código errado.

### Testes da tela são opcionais
Eles abrem janelas, e um deles puxa o foco do teclado, o que tira do primeiro plano o
que estiver em tela cheia (um jogo, um vídeo). Rode só quando não atrapalhar:

```powershell
$env:TESTAR_TELA = "1"; .venv\Scripts\python -m unittest testes.test_tela -v
```

### O que o simulador não prova
Lógica e protocolo, sim. Ligações, Vref, torque, passos perdidos e escorregamento
mecânico, não, e são esses pontos que decidem se GoTo e rastreamento funcionam.

### Firmware
Compila sem a placa (ver [firmware.md](firmware.md)). Sem avisos no código do projeto.

## Roteiro do primeiro teste no hardware

Siga na ordem: cada etapa depende da anterior. Anote os resultados no fim.

### A. Bancada, sem motores
1. **Gravar o firmware** pelo USB, com o HC-06 **desligado** (ele divide a serial
   com o USB). Arduino IDE → biblioteca AccelStepper → placa Duemilanove (ATmega328P).
2. **Conversar pelo USB:** `py controle.py`, escolha a COM do USB. Deve aparecer
   `<< READY` e, a qualquer tecla, `<< PONG`.
3. **Conversar pelo Bluetooth:** monte o divisor de tensão, ligue o HC-06, pareie no
   Windows e abra a COM do Bluetooth. Deve responder `PONG`. **Não** aparece `READY`
   (abrir a porta pelo Bluetooth não reinicia o Arduino); isso é normal.

### B. Drivers e motores, fora do telescópio
4. **Antes de energizar:** capacitor de 100 µF no VMOT de cada driver, RST+SLP em
   nível alto, GND comum. **Nunca conecte ou desconecte um motor com o driver
   energizado:** o pico de tensão pode queimar o DRV8825.
5. **Ajustar o Vref** de cada driver (ver [hardware.md](hardware.md)).
6. **Primeiro movimento**, velocidade baixa (`[` no `controle.py`): setas e JOG.
   Se o motor só vibra: bobinas trocadas, Vref baixo ou RST/SLP soltos.
7. **Sentido:** no eixo AZ, a seta direita deve girar no sentido horário visto de cima;
   no ALT, a seta para cima deve subir o tubo. Se não, `config inverter_az sim` /
   `config inverter_alt sim`.
8. **Passos perdidos, sem carga:** faça uma marca no eixo do motor, tecle `z`, `g` →
   AZ 32000 (10 voltas com 1/16), depois `g` → AZ 0. A marca deve voltar exatamente
   ao lugar. Repita no ALT.

### C. Acoplado ao telescópio
9. **Medir a redução real** de cada eixo (ver [hardware.md](hardware.md)) e configurar
   `reducao_az` / `reducao_alt`.
10. **Torque:** repita o teste 8 com o tubo acoplado, na velocidade e aceleração
    configuradas. Se a marca não voltar ao lugar, há passos perdidos: reduza
    `velocidade_max`/`aceleracao` ou suba o Vref.
11. **Escorregamento:** marque a posição do tubo, rode 20 GoTo de ida e volta grandes e
    confira se volta à marca. Se não voltar e o teste 10 passou, a transmissão patina.
12. **Temperatura:** depois de 10 minutos movendo, toque o dissipador. Muito quente
    para segurar = Vref alto demais ou falta de ventilação.

### D. No céu
13. **Preparar:** `local` (ou Usar minha localização), relógio do Windows sincronizado,
    **Zerar** com o tubo na horizontal e apontando para o Norte.
14. **Alinhar 2 estrelas** a 60–120° uma da outra, centralizadas numa ocular de aumento
    médio. Confira no painel: **"escala ok"**. Se der "escala fora", volte ao passo 9.
15. **GoTo:** aponte para uma 3ª estrela. Ela deve aparecer no campo de uma ocular de
    **baixo** aumento. Anote quanto ficou fora do centro.
16. **Rastrear:** `Seguir` um objeto em aumento médio. Ele deve continuar no campo por
    10 minutos ou mais. Acompanhe o erro em **ESTADO**.
17. **Perto do zênite** (opcional): observe o aviso de velocidade no limite. É esperado.

### Registro

| Etapa | Resultado | Observação |
|---|---|---|
| 2–3 comunicação | | |
| 7 sentido dos eixos | | |
| 8 passos perdidos sem carga | | |
| 9 redução medida (AZ / ALT) | | |
| 10–11 passos perdidos / escorregamento com carga | | |
| 14 escala no alinhamento | | |
| 15 erro do GoTo | | |
| 16 tempo no campo rastreando | | |
