# AGENTS.md

Controlador de telescópio Dobsoniano. O **PC (Python) calcula**; o **Arduino só
executa passos**. Visão geral e uso: [README.md](README.md).

## Regras do projeto

- **Lógica nova vai no `App`** (`pc/telescopio.py`), onde é testável sem janela;
  `pc/tela.py` só a expõe.
- **O firmware é a fonte do protocolo serial.** Ao mudar um comando ou resposta,
  atualize no mesmo passo `firmware/controlador/controlador.ino`, `pc/simulador.py`
  e `pc/testes/test_simulador.py`. Uma linha de resposta por comando, sempre.
- **Conexão se confirma com `PING`.** `READY` só chega pelo USB (reinício do Arduino);
  `READY` no meio da sessão significa posição perdida.
- **`pc/config.json` guarda a localização do usuário:** mantenha-o fora do Git e de
  qualquer saída publicada (já está no `.gitignore`).
- **Testes da tela abrem janelas e puxam o foco** (tiram jogos e vídeos de tela cheia
  do primeiro plano): rode com `TESTAR_TELA=1` só quando o usuário pedir. Para checar
  a tela sem janela, crie `tk.Tk()` e chame `withdraw()` antes de qualquer `update()`.
- **A orientação do radar** (Norte em cima, Leste à direita) é definida só em `Tela._polar()`.
- **Idioma:** identificadores e comentários em português sem acento; textos da
  interface com acento.

## Comandos (Windows)

```powershell
cd pc
py -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -c "import astro; astro.Ceu(0, 0)"   # baixa a efemeride; sem ela, 4 testes pulam
.venv\Scripts\python -m unittest discover -s testes        # OK (skipped=6): 35 testes, sem janela
.venv\Scripts\python simulador.py                          # Arduino falso em socket://127.0.0.1:7777
arduino-cli compile --fqbn arduino:avr:diecimila:cpu=atmega328 firmware/controlador
```

Use `py`, não `python` (pode ser o atalho da Microsoft Store), e `127.0.0.1`, não
`localhost` (IPv6 primeiro, ~2 s de atraso).

## Onde ler antes de mudar

- **protocolo, firmware ou simulador** → [specs/firmware.md](specs/firmware.md)
- **cálculo, alinhamento, GoTo ou rastreamento** → [specs/modelo-matematico.md](specs/modelo-matematico.md)
- **módulos ou threads da tela** → [specs/arquitetura.md](specs/arquitetura.md)
- **interface** → [specs/interface.md](specs/interface.md)
- **ligações e mecânica** → [specs/hardware.md](specs/hardware.md)
- **o que falta** → [specs/pendencias.md](specs/pendencias.md)
