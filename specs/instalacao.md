# Instalação passo a passo

Para quem vai rodar o projeto do zero, num PC com Windows 10 ou 11.

## 1. O que você precisa

- PC com **Windows 10 ou 11** e **internet na primeira vez** (para baixar dependências e a efeméride).
- **Python 3.11 ou mais novo.**
- **Arduino IDE 2.x**, só para gravar o firmware.
- Cabo USB do Arduino (Duemilanove usa o conector USB tipo B, o "quadrado").

## 2. Baixar o projeto

No GitHub, botão **Code → Download ZIP**, e extraia numa pasta (ex.: `C:\telescopio-dobson`).
Quem usa Git pode fazer `git clone https://github.com/juliohgt/telescopio-dobson.git`.

## 3. Instalar o Python

1. Baixe em [python.org/downloads](https://www.python.org/downloads/).
2. No instalador, marque **"Add python.exe to PATH"**. Mantenha marcados **py launcher**
   e **tcl/tk and IDLE** (a tela de controle usa o tkinter, que vem nesse item).
3. Confira no PowerShell:
   ```powershell
   py --version
   ```
   Deve mostrar `Python 3.11` ou mais novo. Se aparecer "Python não foi encontrado",
   o comando `python` está caindo no atalho da Microsoft Store: use sempre `py`.

## 4. Preparar o software

Abra o PowerShell **na pasta `pc` do projeto** (no Explorador de Arquivos: abra a pasta
`pc`, clique na barra de endereço, digite `powershell` e Enter) e rode:

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

O primeiro comando cria um ambiente isolado (`.venv`); o segundo instala `pyserial` e
`skyfield`. Os comandos usam `.venv\Scripts\python` direto, sem o `activate`: num
Windows com a configuração padrão, o PowerShell bloqueia scripts e o `activate`
falharia com "a execução de scripts foi desabilitada neste sistema".

## 5. Primeiro uso: baixar a efeméride

O cálculo do céu precisa da efeméride `de421.bsp` (~17 MB, NASA/JPL). Ela é baixada
sozinha na primeira vez que o programa calcula o céu. Para baixar já:

```powershell
.venv\Scripts\python -c "import astro; astro.Ceu(0, 0)"
```

Ela fica em `pc\dados\`; depois disso o programa funciona sem internet.

## 6. Testar sem hardware (opcional)

```powershell
.venv\Scripts\python -m unittest discover -s testes
```

Deve terminar em `OK (skipped=6)`: 35 testes passam e os 6 da tela são pulados de
propósito (abrem janelas). Sem a efeméride, mais 4 são pulados.

Para ver a tela funcionando com um Arduino simulado, abra **dois** PowerShell na pasta `pc`:

```powershell
.venv\Scripts\python simulador.py
```
```powershell
.venv\Scripts\python tela.py socket://127.0.0.1:7777
```

## 7. Gravar o firmware no Arduino

1. Instale a **Arduino IDE 2.x** ([arduino.cc/en/software](https://www.arduino.cc/en/software)).
2. **Ferramentas → Gerenciar bibliotecas**: procure e instale **AccelStepper**.
3. Abra `firmware\controlador\controlador.ino`.
4. **Ferramentas → Placa → Arduino AVR Boards → "Arduino Duemilanove or Diecimila"**.
5. **Ferramentas → Processador**: leia o chip grande da placa.
   - `ATMEGA328P` → **ATmega328P**
   - `ATMEGA168` → **ATmega168** (Duemilanove antigas; ver o aviso em [pendencias.md](pendencias.md))
6. Ligue o cabo USB. **Ferramentas → Porta**: a COM que aparecer (a Duemilanove usa um
   chip FTDI; o Windows instala o driver sozinho; se não, baixe o "VCP driver" no site da FTDI).
7. **Carregar** (seta →). O HC-06 pode ficar ligado: ele usa os pinos 10/11, e a
   gravação usa os pinos 0/1.

Monte a parte elétrica antes de energizar os motores: [hardware.md](hardware.md).

## 8. Conectar o PC ao Arduino

O firmware atende **pelo USB e pelo Bluetooth**; use o que for mais prático.

- **USB:** a porta é a mesma COM usada para gravar (aparece como "USB Serial Port").
- **Bluetooth (HC-06):** Configurações → Bluetooth e dispositivos → Adicionar dispositivo
  → Bluetooth → HC-06 (PIN `1234` ou `0000`). O Windows cria **duas** portas COM para
  ele; a certa é a de **saída** ("Saída"/"Outgoing"). Para ver qual é: Configurações →
  Bluetooth e dispositivos → Dispositivos → **Mais configurações de Bluetooth** → aba **Portas COM**.

## 9. Rodar

```powershell
.venv\Scripts\python tela.py
```

Escolha a porta no topo da janela e clique em **Conectar**. Siga "Uma noite de
observação" no [README](../README.md). Para o primeiro teste com motores, siga o
[roteiro em testes.md](testes.md#roteiro-do-primeiro-teste-no-hardware).

## Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| "Python não foi encontrado" | `python` aponta para o atalho da Microsoft Store | use `py`, ou desative o atalho em Configurações → Aplicativos → Aliases de execução |
| "execução de scripts foi desabilitada" | política padrão do PowerShell | não use `activate`; use `.venv\Scripts\python ...` |
| `No module named 'tkinter'` | Python instalado sem tcl/tk | rode o instalador de novo → Modify → marque tcl/tk |
| A porta não aparece na lista | cabo só de energia, driver FTDI ou HC-06 não pareado | outro cabo; driver FTDI; parear de novo |
| Conecta mas não responde | porta COM de **entrada** do Bluetooth, ou baud diferente de 9600 | use a COM de **saída**; o HC-06 vem de fábrica em 9600 |
| "Não foi possível conectar" no simulador | simulador fechado ou `localhost` | deixe o `simulador.py` aberto; use `127.0.0.1` |
| Letras diferentes na tela (Windows 10) | fontes Bahnschrift/Cascadia ausentes | só visual; instale a fonte Cascadia (vem com o Windows Terminal) |
| Arduino reinicia sozinho (aparece `READY` e o alinhamento some) | fonte fraca ou ruído, ou RAM no limite do ATmega168 | fonte dos motores separada e GND comum; no ATmega168, ver [pendencias.md](pendencias.md) |
