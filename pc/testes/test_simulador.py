"""
Testes do simulador e da comunicacao PC <-> "Arduino" (sem hardware).

Rodar a partir da pasta pc/:
    py -m unittest discover -s testes -v
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serial  # noqa: E402

from simulador import Eixo, SimuladorArduino  # noqa: E402


class TestProtocolo(unittest.TestCase):
    """Respostas devem ser identicas as do firmware (handle() no .ino)."""

    def setUp(self):
        self.sim = SimuladorArduino(verboso=False)   # sem rede, so o protocolo

    def test_ping_sem_diferenciar_maiusculas(self):
        self.assertEqual(self.sim.processar("PING"), ["PONG"])
        self.assertEqual(self.sim.processar("ping"), ["PONG"])

    def test_posicao_inicial(self):
        self.assertEqual(self.sim.processar("POS?"), ["POS AZ=0 ALT=0"])

    def test_erros(self):
        self.assertEqual(self.sim.processar("MOVE AZ"), ["ERR MOVE"])
        self.assertEqual(self.sim.processar("MOVE XX 10"), ["ERR AXIS XX"])
        self.assertEqual(self.sim.processar("FOO"), ["ERR FOO"])
        self.assertEqual(self.sim.processar("FOO AZ 1"), ["ERR FOO"])

    def test_speed_sem_valor_nao_responde(self):
        self.assertEqual(self.sim.processar("SPEED"), [])

    def test_speed_imprime_duas_casas(self):
        self.assertEqual(self.sim.processar("SPEED 1500"), ["OK SPEED 1500.00"])
        self.assertEqual(self.sim.az.max_speed, 1500)

    def test_move_e_relativo_a_posicao_atual(self):
        self.sim.az.pos = 300.0
        self.assertEqual(self.sim.processar("MOVE AZ -100"), ["OK MOVE"])
        self.assertEqual(self.sim.az.alvo, 200)

    def test_goto_e_absoluto(self):
        self.sim.processar("GOTO ALT -500")
        self.assertEqual(self.sim.alt.alvo, -500)

    def test_rate_aceita_fracao_e_sinal(self):
        self.assertEqual(self.sim.processar("RATE AZ -1.75"), ["OK RATE"])
        self.assertTrue(self.sim.az.rate_on)
        self.assertEqual(self.sim.az.rate, -1.75)

    def test_rate_limitado_pela_velocidade_maxima(self):
        self.sim.processar("SPEED 100")
        self.sim.processar("RATE AZ 5000")
        self.sim.az.avancar(0.01, jog_speed=0)
        self.assertEqual(self.sim.az.vel, 100)

    def test_goto_sai_do_modo_rate(self):
        self.sim.processar("RATE ALT 10")
        self.sim.processar("GOTO ALT 50")
        self.assertFalse(self.sim.alt.rate_on)
        self.assertEqual(self.sim.alt.alvo, 50)

    def test_disable_para_e_recusa_movimento(self):
        self.sim.processar("JOG AZ 1")
        self.assertEqual(self.sim.processar("DISABLE"), ["OK DISABLE"])
        self.assertEqual(self.sim.az.jog, 0)
        for cmd in ("MOVE AZ 10", "GOTO AZ 10", "JOG AZ 1", "RATE AZ 1"):
            self.assertEqual(self.sim.processar(cmd), ["ERR DISABLED"], cmd)
        self.assertEqual(self.sim.processar("POS?"), ["POS AZ=0 ALT=0"])  # leitura continua
        self.sim.processar("ENABLE")
        self.assertEqual(self.sim.processar("MOVE AZ 10"), ["OK MOVE"])

    def test_zero_cancela_jog(self):
        self.sim.processar("JOG AZ 1")
        self.sim.processar("ZERO")
        self.assertEqual(self.sim.az.jog, 0)


class TestFisica(unittest.TestCase):
    """A rampa precisa chegar exatamente no alvo, sem passar e sem exceder a velocidade."""

    def test_rampa_chega_no_alvo_sem_ultrapassar(self):
        eixo = Eixo(max_speed=2000, accel=1000)
        eixo.alvo = 1000
        dt, t, v_max = 0.005, 0.0, 0.0
        while eixo.pos != eixo.alvo and t < 10:
            eixo.avancar(dt, jog_speed=0)
            self.assertLessEqual(eixo.pos, 1000)       # nunca passa do alvo
            v_max = max(v_max, abs(eixo.vel))
            t += dt
        self.assertEqual(eixo.posicao, 1000)
        self.assertLessEqual(v_max, 2000)
        # Perfil triangular: t = 2*sqrt(d/a) = 2*sqrt(1000/1000) = 2 s
        self.assertAlmostEqual(t, 2.0, delta=0.2)

    def test_rampa_respeita_velocidade_maxima(self):
        eixo = Eixo(max_speed=500, accel=1000)
        eixo.alvo = 5000
        dt, v_max = 0.005, 0.0
        for _ in range(4000):
            eixo.avancar(dt, jog_speed=0)
            v_max = max(v_max, abs(eixo.vel))
        self.assertLessEqual(v_max, 500)
        self.assertEqual(eixo.posicao, 5000)


class TestPontaAPonta(unittest.TestCase):
    """Conecta pelo pyserial (socket://) exatamente como o controle.py faz."""

    def setUp(self):
        self.sim = SimuladorArduino(porta=0, verboso=False).iniciar()   # porta livre
        self.ser = serial.serial_for_url(f"socket://127.0.0.1:{self.sim.porta}",
                                         baudrate=9600, timeout=0.5)

    def tearDown(self):
        self.ser.close()
        self.sim.parar()

    def ler(self):
        # O READY da conexao pode ou nao chegar (o pyserial limpa a entrada ao
        # abrir; no HC-06 real ele nem e enviado). Nada pode depender dele.
        while True:
            linha = self.ser.readline().decode().strip()
            if linha != "READY":
                return linha

    def cmd(self, texto):
        self.ser.write((texto + "\n").encode())
        return self.ler()

    def posicao(self):
        resposta = self.cmd("POS?")
        _, az, alt = resposta.split()
        return int(az.split("=")[1]), int(alt.split("=")[1])

    def esperar_posicao(self, esperada, limite=5.0):
        fim = time.monotonic() + limite
        while time.monotonic() < fim:
            if self.posicao() == esperada:
                return
            time.sleep(0.05)
        self.fail(f"nao chegou em {esperada}; ficou em {self.posicao()}")

    def test_fluxo_completo(self):
        self.assertEqual(self.cmd("PING"), "PONG")
        self.assertEqual(self.cmd("SPEED 20000"), "OK SPEED 20000.00")
        self.assertEqual(self.cmd("ACCEL 100000"), "OK ACCEL 100000.00")

        self.assertEqual(self.cmd("MOVE AZ 1000"), "OK MOVE")
        self.assertEqual(self.cmd("GOTO ALT -500"), "OK GOTO")
        self.esperar_posicao((1000, -500))

        # JOG continuo anda; STOP para de verdade
        self.assertEqual(self.cmd("JOGSPEED 2000"), "OK JOGSPEED 2000.00")
        self.assertEqual(self.cmd("JOG AZ 1"), "OK JOG")
        time.sleep(0.3)
        self.assertEqual(self.cmd("STOP"), "OK STOP")
        az_parado, _ = self.posicao()
        self.assertGreater(az_parado, 1000)
        time.sleep(0.2)
        self.assertEqual(self.posicao()[0], az_parado)

        self.assertEqual(self.cmd("ZERO"), "OK ZERO")
        self.assertEqual(self.posicao(), (0, 0))

    def test_comandos_com_cr_e_lf(self):
        self.ser.write(b"PING\r\nPOS?\r")
        self.assertEqual(self.ler(), "PONG")
        self.assertEqual(self.ler(), "POS AZ=0 ALT=0")


if __name__ == "__main__":
    unittest.main()
