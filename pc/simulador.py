#!/usr/bin/env python3
"""
Simulador do Arduino (firmware/controlador/controlador.ino) - testa sem hardware
---------------------------------------------------------------------------------
Finge ser o Arduino: responde ao MESMO protocolo de texto do firmware e simula a
posicao dos dois eixos (AZ e ALT) com velocidade maxima e rampa de aceleracao,
imitando o AccelStepper.

Em vez de uma porta COM, ele escuta numa porta TCP local. O pyserial aceita
enderecos "socket://host:porta" no lugar de "COM5", entao o controle.py e o
telescopio.py conversam com o simulador sem mudar o codigo de comunicacao.

Uso:
    py simulador.py                 # escuta em 127.0.0.1:7777
    py simulador.py --porta 8000
    py telescopio.py socket://127.0.0.1:7777   (em outro terminal)

Use 127.0.0.1 e nao "localhost": no Windows, "localhost" tenta IPv6 primeiro
e a conexao demora ~2 s.

Diferenca conhecida em relacao ao hardware: ao conectar ele envia "READY"
(como o Arduino pelo USB, que reinicia ao abrir a porta). Pelo HC-06 o
Arduino nao reinicia e nao envia READY. O PC nao deve depender disso.

Limite: prova que a LOGICA e o PROTOCOLO estao certos. Nao prova nada sobre a
mecanica (torque, Vref, passos perdidos, ligacoes).
"""

import argparse
import math
import re
import socket
import threading
import time

TAXA_FISICA = 200        # atualizacoes por segundo da simulacao de movimento
TAMANHO_BUFFER = 47      # o firmware usa char buf[48]: no maximo 47 caracteres


def _atol(texto):
    """Imita atol() do C: le o inteiro do comeco do texto; 0 se nao houver."""
    m = re.match(r"\s*([+-]?\d+)", texto)
    return int(m.group(1)) if m else 0


def _atof(texto):
    """Imita atof() do C."""
    m = re.match(r"\s*([+-]?(\d+(\.\d*)?|\.\d+))", texto)
    return float(m.group(1)) if m else 0.0


def _f2(valor):
    """Imita Serial.println(float) do Arduino, que imprime 2 casas decimais."""
    return f"{valor:.2f}"


class Eixo:
    """Imita um AccelStepper em modo DRIVER: posicao em passos inteiros."""

    def __init__(self, max_speed, accel):
        self.pos = 0.0       # posicao continua (o que o motor "fez")
        self.alvo = 0        # destino de MOVE/GOTO
        self.vel = 0.0       # passos/s, com sinal
        self.max_speed = max_speed
        self.accel = accel
        self.jog = 0         # -1, 0, +1
        self.rate_on = False
        self.rate = 0.0      # passos/s do comando RATE

    @property
    def posicao(self):
        return int(round(self.pos))

    @property
    def em_velocidade(self):
        return self.jog != 0 or self.rate_on

    def _limitar(self, v):
        """setSpeed() do AccelStepper: constrain(v, -maxSpeed, maxSpeed)."""
        return max(-self.max_speed, min(self.max_speed, v))

    def set_max_speed(self, v):
        self.max_speed = abs(v)          # AccelStepper usa fabs()

    def set_accel(self, a):
        if a == 0:                       # AccelStepper ignora aceleracao 0
            return
        self.accel = abs(a)

    def parar(self):
        """pararEixo() do firmware: sai de JOG/RATE e para na hora."""
        self.jog = 0
        self.rate_on = False
        self.rate = 0.0
        self.pos = float(self.posicao)
        self.alvo = self.posicao
        self.vel = 0.0

    def zerar(self):
        self.parar()
        self.pos = 0.0
        self.alvo = 0

    def avancar(self, dt, jog_speed):
        if self.em_velocidade:
            # runSpeed(): velocidade constante, sem rampa
            self.vel = self._limitar(self.jog * jog_speed if self.jog else self.rate)
            self.pos += self.vel * dt
            return

        falta = self.alvo - self.pos
        if falta == 0:
            self.vel = 0.0
            return
        direcao = 1 if falta > 0 else -1
        # Rampa trapezoidal: a velocidade desejada e a maior que ainda permite
        # frear ate o alvo (v^2 = 2*a*d), limitada pela velocidade maxima.
        v_desejada = direcao * min(self.max_speed, math.sqrt(2 * self.accel * abs(falta)))
        dv = self.accel * dt
        if self.vel < v_desejada:
            self.vel = min(self.vel + dv, v_desejada)
        else:
            self.vel = max(self.vel - dv, v_desejada)
        # garante progresso minimo perto do alvo (o motor real anda passo a passo)
        if self.vel == 0:
            self.vel = direcao * min(self.max_speed, dv)
        novo = self.pos + self.vel * dt
        if (self.alvo - novo) * direcao <= 0:     # chegou ou passou
            self.pos = float(self.alvo)
            self.vel = 0.0
        else:
            self.pos = novo


class SimuladorArduino:
    def __init__(self, porta=7777, verboso=True):
        self.porta = porta
        self.verboso = verboso
        # mesmos padroes do firmware
        self.max_speed = 2000.0
        self.accel = 1000.0
        self.jog_speed = 600.0
        self.az = Eixo(self.max_speed, self.accel)
        self.alt = Eixo(self.max_speed, self.accel)
        self.drivers_ligados = True
        self._lock = threading.Lock()
        self._rodando = threading.Event()
        self._servidor = None

    # ---------- protocolo (espelho de handle() no firmware) ----------
    def processar(self, linha):
        """Recebe uma linha de comando e devolve a lista de respostas."""
        with self._lock:
            return self._processar(linha[:TAMANHO_BUFFER])

    def _processar(self, linha):
        tokens = linha.split()            # strtok(" ") ignora espacos repetidos
        if not tokens:
            return []
        cmd = tokens[0]
        c = cmd.upper()                    # strcasecmp: sem diferenciar maiusculas

        if c == "PING":
            return ["PONG"]
        if c == "POS?":
            return [f"POS AZ={self.az.posicao} ALT={self.alt.posicao}"]
        if c == "STOP":
            self.az.parar()
            self.alt.parar()
            return ["OK STOP"]
        if c == "ZERO":
            self.az.zerar()
            self.alt.zerar()
            return ["OK ZERO"]
        if c == "ENABLE":
            self.drivers_ligados = True
            return ["OK ENABLE"]
        if c == "DISABLE":
            self.az.parar()
            self.alt.parar()
            self.drivers_ligados = False
            return ["OK DISABLE"]
        if c == "SPEED":
            if len(tokens) < 2:
                return []                  # o firmware nao responde nada
            self.max_speed = _atof(tokens[1])
            self.az.set_max_speed(self.max_speed)
            self.alt.set_max_speed(self.max_speed)
            return [f"OK SPEED {_f2(self.max_speed)}"]
        if c == "ACCEL":
            if len(tokens) < 2:
                return []
            self.accel = _atof(tokens[1])
            self.az.set_accel(self.accel)
            self.alt.set_accel(self.accel)
            return [f"OK ACCEL {_f2(self.accel)}"]
        if c == "JOGSPEED":
            if len(tokens) < 2:
                return []
            self.jog_speed = _atof(tokens[1])
            return [f"OK JOGSPEED {_f2(self.jog_speed)}"]

        # MOVE / GOTO / JOG / RATE <AZ|ALT> <n>
        if len(tokens) < 3:
            return [f"ERR {cmd}"]
        eixo_nome, valor = tokens[1], tokens[2]
        if eixo_nome.upper() == "AZ":
            eixo = self.az
        elif eixo_nome.upper() == "ALT":
            eixo = self.alt
        else:
            return [f"ERR AXIS {eixo_nome}"]

        if c in ("MOVE", "GOTO", "JOG", "RATE") and not self.drivers_ligados:
            return ["ERR DISABLED"]

        if c == "MOVE":
            if eixo.em_velocidade:
                eixo.parar()
            eixo.alvo = eixo.posicao + _atol(valor)   # move(): relativo a posicao atual
            return ["OK MOVE"]
        if c == "GOTO":
            if eixo.em_velocidade:
                eixo.parar()
            eixo.alvo = _atol(valor)
            return ["OK GOTO"]
        if c == "JOG":
            d = _atol(valor)
            eixo.parar()
            eixo.jog = 1 if d > 0 else (-1 if d < 0 else 0)
            return ["OK JOG"]
        if c == "RATE":
            if not eixo.rate_on:
                eixo.parar()
            eixo.rate_on = True
            eixo.rate = _atof(valor)
            return ["OK RATE"]
        return [f"ERR {cmd}"]

    # ---------- simulacao do movimento ----------
    def _laco_fisica(self):
        dt = 1.0 / TAXA_FISICA
        ultimo_log = 0.0
        ultima_pos = None
        while self._rodando.is_set():
            with self._lock:
                self.az.avancar(dt, self.jog_speed)
                self.alt.avancar(dt, self.jog_speed)
                pos = (self.az.posicao, self.alt.posicao)
            agora = time.monotonic()
            if self.verboso and pos != ultima_pos and agora - ultimo_log > 0.25:
                print(f"   [sim] AZ={pos[0]:>8}  ALT={pos[1]:>8}")
                ultimo_log, ultima_pos = agora, pos
            time.sleep(dt)

    # ---------- servidor TCP (faz o papel da porta serial) ----------
    def _atender(self, conexao):
        with conexao:
            conexao.sendall(b"READY\r\n")      # o firmware imprime READY no setup()
            pendente = ""
            while self._rodando.is_set():
                try:
                    dados = conexao.recv(1024)
                except (socket.timeout, TimeoutError):
                    continue
                except OSError:
                    break
                if not dados:
                    break
                pendente += dados.decode(errors="replace")
                # o firmware aceita '\n' ou '\r' como fim de linha
                partes = re.split(r"[\r\n]", pendente)
                pendente = partes.pop()
                for linha in partes:
                    if not linha:
                        continue
                    for resposta in self.processar(linha):
                        conexao.sendall((resposta + "\r\n").encode())

    def _laco_servidor(self):
        while self._rodando.is_set():
            try:
                conexao, endereco = self._servidor.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break
            conexao.settimeout(0.2)
            if self.verboso:
                print(f"   [sim] cliente conectado: {endereco}")
            self._atender(conexao)
            if self.verboso:
                print("   [sim] cliente desconectado")

    def iniciar(self):
        self._servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._servidor.bind(("127.0.0.1", self.porta))
        self._servidor.listen(1)
        self._servidor.settimeout(0.2)
        self.porta = self._servidor.getsockname()[1]   # util com porta=0 nos testes
        self._rodando.set()
        threading.Thread(target=self._laco_fisica, daemon=True).start()
        threading.Thread(target=self._laco_servidor, daemon=True).start()
        return self

    def parar(self):
        self._rodando.clear()
        if self._servidor:
            self._servidor.close()


def main():
    ap = argparse.ArgumentParser(description="Simulador do Arduino do telescopio")
    ap.add_argument("--porta", type=int, default=7777)
    ap.add_argument("--quieto", action="store_true", help="nao imprime as posicoes")
    args = ap.parse_args()

    sim = SimuladorArduino(args.porta, verboso=not args.quieto).iniciar()
    print(f"Simulador ouvindo em socket://127.0.0.1:{sim.porta}  (Ctrl+C para sair)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sim.parar()
        print("\nSimulador encerrado.")


if __name__ == "__main__":
    main()
