#!/usr/bin/env python3
"""
Controle manual (slew) do telescopio  -  FASE 1
---------------------------------------------------------------
O PC manda comandos de PASSOS; o Arduino (controlador burro) executa.
Conexao: porta serial do HC-06 (pareado via Bluetooth), do cabo USB, ou o
simulador (simulador.py) em socket://127.0.0.1:7777.

Uso:
  py controle.py                          -> escolhe a porta numa lista
  py controle.py COM5                     -> abre direto a porta COM5
  py controle.py socket://127.0.0.1:7777  -> conecta no simulador

Requisito:  pip install -r requirements.txt   (pyserial)
Setas do teclado: funcionam no Windows (modulo msvcrt).

TECLAS
  setas            -> "nudge": move por 'incremento' passos (MOVE relativo)
                      esquerda/direita = AZ -/+ ; cima/baixo = ALT +/-
  a / d            -> JOG continuo do AZ  (- / +)  ate parar
  w / x            -> JOG continuo da ALT (+ / -)  ate parar
  espaco           -> STOP (para tudo)
  + / -            -> aumenta / diminui o incremento do nudge
  ] / [            -> aumenta / diminui a velocidade (SPEED)
  p                -> pergunta a posicao (POS?)
  z                -> zera a posicao (ZERO) -- usado no alinhamento
  e / r            -> ENABLE / release(DISABLE) dos drivers
  g                -> GOTO: digita a posicao-alvo (passos) de cada eixo
  h                -> mostra esta ajuda
  q / Esc          -> sair (envia STOP antes)
"""

import sys
import time
import threading

import serial

from arduino import abrir, escolher_porta

try:
    import msvcrt  # teclado no Windows
except ImportError:
    msvcrt = None


def leitor(ser, parar):
    """Thread que imprime tudo que o Arduino responde."""
    while not parar.is_set():
        try:
            linha = ser.readline().decode(errors="replace").strip()
            if linha:
                print(f"   << {linha}")
        except Exception:
            break


def ajuda():
    print(__doc__)


def laco_teclado(envia, ajuda=ajuda):
    """Le o teclado e chama envia(comando). Volta com 'q' ou Esc.
    Tambem usado pelo modo manual do telescopio.py."""
    incremento = 200   # passos por nudge
    speed = 2000       # passos/s
    while True:
        ch = msvcrt.getch()

        if ch in (b"\x00", b"\xe0"):          # tecla especial = seta
            ch2 = msvcrt.getch()
            if   ch2 == b"K": envia(f"MOVE AZ -{incremento}")    # esquerda
            elif ch2 == b"M": envia(f"MOVE AZ {incremento}")     # direita
            elif ch2 == b"H": envia(f"MOVE ALT {incremento}")    # cima
            elif ch2 == b"P": envia(f"MOVE ALT -{incremento}")   # baixo
            continue

        if ch == b"\x1b":                       # Esc
            return
        k = ch.decode(errors="ignore").lower()
        if   k == "q":
            return
        elif k == " ":
            envia("STOP")
        elif k == "a": envia("JOG AZ -1")
        elif k == "d": envia("JOG AZ 1")
        elif k == "w": envia("JOG ALT 1")
        elif k == "x": envia("JOG ALT -1")
        elif k == "p": envia("POS?")
        elif k == "z": envia("ZERO")
        elif k == "e": envia("ENABLE")
        elif k == "r": envia("DISABLE")
        elif k == "+":
            incremento += 50; print(f"   incremento = {incremento} passos")
        elif k == "-":
            incremento = max(10, incremento - 50); print(f"   incremento = {incremento} passos")
        elif k == "]":
            speed += 250; envia(f"SPEED {speed}")
        elif k == "[":
            speed = max(100, speed - 250); envia(f"SPEED {speed}")
        elif k == "g":
            a = input("GOTO AZ (passos, vazio=pular): ").strip()
            b = input("GOTO ALT (passos, vazio=pular): ").strip()
            if a: envia(f"GOTO AZ {a}")
            if b: envia(f"GOTO ALT {b}")
        elif k == "h":
            ajuda()


def main():
    endereco = sys.argv[1] if len(sys.argv) > 1 else escolher_porta()
    try:
        ser = abrir(endereco)
    except (serial.SerialException, OSError) as erro:
        print(f"Nao consegui abrir {endereco}: {erro}")
        if endereco.startswith("socket://"):
            print("O simulador esta rodando? (py simulador.py em outro terminal)")
        sys.exit(1)

    parar = threading.Event()
    threading.Thread(target=leitor, args=(ser, parar), daemon=True).start()

    def envia(cmd):
        ser.write((cmd + "\n").encode())
        print(f"   >> {cmd}")

    ajuda()
    envia("PING")

    # Fallback fora do Windows: digita comandos crus.
    if msvcrt is None:
        print("\n(Sem setas neste SO) Digite comandos crus + Enter. 'q' sai.")
        while True:
            c = input().strip()
            if c == "q":
                break
            if c:
                envia(c)
        parar.set(); ser.close(); return

    print("\nPronto. Use as teclas (h = ajuda, q = sair).")
    laco_teclado(envia)

    envia("STOP")
    time.sleep(0.2)
    parar.set()
    ser.close()
    print("Encerrado.")


if __name__ == "__main__":
    main()
