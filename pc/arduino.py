"""
Conexao com o Arduino (ou com o simulador) pela serial.

- abrir(): abre porta COM (HC-06 ou USB) ou endereco do pyserial
  (ex.: socket://127.0.0.1:7777 para o simulador).
- Arduino: pergunta e resposta sincronas. O firmware responde exatamente
  uma linha por comando, na ordem, entao cada enviar() espera a sua resposta.
"""

import queue
import threading
import time

import serial
import serial.tools.list_ports

BAUD = 9600
# 127.0.0.1 e nao "localhost": no Windows, "localhost" tenta IPv6 (::1) primeiro
# e a recusa demora ~2 s antes de cair para o IPv4 onde o simulador escuta.
SIMULADOR = "socket://127.0.0.1:7777"


def escolher_porta():
    portas = list(serial.tools.list_ports.comports())
    print("Portas disponiveis:")
    for i, p in enumerate(portas):
        print(f"  [{i}] {p.device}   {p.description}")
    if not portas:
        print("  (nenhuma porta serial: pareie o HC-06 ou conecte o USB)")
    print(f"  [s] simulador ({SIMULADOR})")
    while True:
        s = input("Escolha: ").strip().lower()
        if s == "s":
            return SIMULADOR
        if s.isdigit() and 0 <= int(s) < len(portas):
            return portas[int(s)].device
        print("Opcao invalida.")


def abrir(endereco, timeout=0.2):
    """Abre porta COM ou endereco do pyserial (ex.: socket://127.0.0.1:7777)."""
    ser = serial.serial_for_url(endereco, baudrate=BAUD, timeout=timeout)
    if not endereco.startswith("socket://"):
        # Pelo USB o Arduino reinicia ao abrir a porta (sinal DTR) e leva ~2 s
        # para o bootloader liberar. Pelo HC-06 nao ha reinicio, mas esperar
        # nao atrapalha.
        time.sleep(2)
    return ser


class ArduinoErro(Exception):
    pass


class Arduino:
    def __init__(self, endereco, timeout=2.0):
        self.endereco = endereco
        self.timeout = timeout
        self.ser = abrir(endereco)
        self._fila = queue.Queue()
        self._lock = threading.Lock()
        self._rodando = True
        # True se o Arduino imprimir READY no meio da sessao: ele reiniciou
        # (queda de energia, reset) e a contagem de passos voltou a zero.
        self.reiniciou = False
        self._leitor = threading.Thread(target=self._ler, daemon=True)
        self._leitor.start()

        # O READY inicial pode ou nao chegar (pelo HC-06 nem existe), entao
        # a conexao e confirmada com PING, nao com READY.
        time.sleep(0.3)
        self._descartar()
        resposta = self.enviar("PING")
        if resposta != "PONG":
            raise ArduinoErro(f"resposta inesperada ao PING: {resposta!r}")
        self.reiniciou = False

    def _ler(self):
        while self._rodando:
            try:
                linha = self.ser.readline().decode(errors="replace").strip()
            except Exception:
                break
            if not linha:
                continue
            if linha == "READY":
                self.reiniciou = True
                continue
            self._fila.put(linha)

    def _descartar(self):
        while not self._fila.empty():
            self._fila.get_nowait()

    def enviar(self, comando):
        """Manda um comando e devolve a linha de resposta."""
        with self._lock:
            self._descartar()
            self.ser.write((comando + "\n").encode())
            try:
                return self._fila.get(timeout=self.timeout)
            except queue.Empty:
                raise ArduinoErro(f"sem resposta para {comando!r} em {self.timeout} s") from None

    def exigir(self, comando, esperado_prefixo="OK"):
        resposta = self.enviar(comando)
        if not resposta.startswith(esperado_prefixo):
            raise ArduinoErro(f"{comando!r} -> {resposta!r}")
        return resposta

    def posicao(self):
        """Devolve (passos_az, passos_alt)."""
        resposta = self.enviar("POS?")
        try:
            _, az, alt = resposta.split()
            return int(az.split("=")[1]), int(alt.split("=")[1])
        except (ValueError, IndexError):
            raise ArduinoErro(f"POS? -> {resposta!r}") from None

    def fechar(self):
        self._rodando = False
        try:
            self.ser.close()
        except OSError:
            pass
