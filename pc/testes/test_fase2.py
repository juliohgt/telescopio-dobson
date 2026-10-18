"""
Testes da Fase 2 contra o simulador: rastreamento e o fluxo completo
local -> zero -> alinhar 2 estrelas -> ir / seguir.

O "telescopio de verdade" e simulado por uma rotacao conhecida (base
desnivelada 3 graus, zero do azimute a 137 graus do Norte). O criterio de
sucesso e fisico: para onde o tubo realmente aponta vs. onde a estrela esta.
"""

import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arduino import Arduino  # noqa: E402
from astro import PASTA_DADOS  # noqa: E402
from config import Config  # noqa: E402
from montagem import Conversor, angulos, caminho_curto, separacao, vetor  # noqa: E402
from rastreio import CHEGOU, Rastreador, esperar_chegada  # noqa: E402
from simulador import SimuladorArduino  # noqa: E402
from telescopio import App  # noqa: E402
from test_montagem import R_VERDADEIRA  # noqa: E402

TEM_EFEMERIDE = os.path.exists(os.path.join(PASTA_DADOS, "de421.bsp"))
# Instante fixo: 17/10/2026 23:00 UTC (20:00 em Sao Paulo).
INSTANTE = datetime(2026, 10, 17, 23, 0, tzinfo=timezone.utc).timestamp()


class ComSimulador(unittest.TestCase):
    def setUp(self):
        self.sim = SimuladorArduino(porta=0, verboso=False).iniciar()
        self.ard = Arduino(f"socket://127.0.0.1:{self.sim.porta}")

    def tearDown(self):
        self.ard.fechar()
        self.sim.parar()


class TestRastreador(ComSimulador):
    def test_segue_alvo_em_movimento(self):
        self.ard.exigir("SPEED 2000")
        t0 = time.time()

        def alvo(unix, _passos_az):
            dt = unix - t0
            return int(round(1000 + 300 * dt)), int(round(-200 - 100 * dt))

        erros = []
        Rastreador(self.ard, alvo, periodo=0.2, vel_max=2000).rodar(
            duracao=2.5, ao_ciclo=lambda i: erros.append((i["erro_az"], i["erro_alt"])))
        # Comeca 1000 passos atras (satura a velocidade) e alcanca o alvo.
        self.assertGreater(abs(erros[0][0]), 900)
        for erro_az, erro_alt in erros[-3:]:
            self.assertLess(abs(erro_az), 15)
            self.assertLess(abs(erro_alt), 15)
        # Termina parado (STOP no fim)
        p1 = self.ard.posicao()
        time.sleep(0.2)
        self.assertEqual(self.ard.posicao(), p1)

    def test_esperar_chegada(self):
        self.ard.exigir("SPEED 20000")
        self.ard.exigir("ACCEL 100000")
        self.ard.exigir("GOTO AZ 3000")
        self.ard.exigir("GOTO ALT -700")
        self.assertEqual(esperar_chegada(self.ard, (3000, -700), timeout=5), CHEGOU)


@unittest.skipUnless(TEM_EFEMERIDE, "precisa de pc/dados/de421.bsp (baixado no 1o uso do astro.py)")
class TestFluxoCompleto(ComSimulador):
    def setUp(self):
        super().setUp()
        self.saida = []
        self.arquivo_cfg = os.path.join(tempfile.mkdtemp(), "config.json")
        self.cfg = Config(reducao_az=5, reducao_alt=5,      # 44 passos/grau
                          velocidade_max=50000, aceleracao=500000, alt_minima=10)
        self.relogio = lambda: INSTANTE
        self.app = App(self.ard, self.cfg, caminho_config=self.arquivo_cfg,
                       relogio=lambda: self.relogio(), escrever=self.saida.append,
                       tecla_apertada=lambda: False)
        self.conv = Conversor(self.cfg)
        self.cmd("local -23.55 -46.63 760")
        self.cmd("zero")

    def cmd(self, linha):
        self.saida.clear()
        self.app.executar(linha)
        erros = [s for s in self.saida if s.startswith("!")]
        self.assertEqual(erros, [], f"{linha!r} -> {self.saida}")
        return self.saida

    def centralizar(self, nome):
        """Faz o papel do usuario no modo manual: move o tubo ate a estrela."""
        alt, az = self.app.ceu.altaz(self.app.ceu.resolver(nome), self.relogio())
        alt_m, az_m = angulos(R_VERDADEIRA.T @ vetor(alt, az))
        paz_atual, _ = self.ard.posicao()
        _, az_atual = self.conv.para_graus(paz_atual, 0)
        destino = self.conv.para_passos(alt_m, caminho_curto(az_m, az_atual))
        self.ard.exigir(f"GOTO AZ {destino[0]}")
        self.ard.exigir(f"GOTO ALT {destino[1]}")
        self.assertEqual(esperar_chegada(self.ard, destino, timeout=10), CHEGOU)

    def onde_o_tubo_aponta(self):
        """Direcao REAL no ceu, a partir dos passos e da montagem verdadeira."""
        alt_m, az_m = self.conv.para_graus(*self.ard.posicao())
        return angulos(R_VERDADEIRA @ vetor(alt_m, az_m))

    def tres_estrelas(self):
        visiveis = self.app.ceu.estrelas_visiveis(25, INSTANTE)
        escolhidas = []
        for nome, alt, az in visiveis:
            if all(separacao(alt, az, a, z) > 30 for _, a, z in escolhidas):
                escolhidas.append((nome, alt, az))
            if len(escolhidas) == 3:
                return [e[0] for e in escolhidas]
        self.skipTest(f"poucas estrelas separadas visiveis: {visiveis}")

    def test_alinhar_duas_e_ir_para_terceira(self):
        a, b, c = self.tres_estrelas()
        self.centralizar(a)
        self.cmd(f"alinhar {a}")
        self.centralizar(b)
        saida = self.cmd(f"alinhar {b}")
        self.assertTrue(any("medida/real = 1.00" in s for s in saida), saida)

        self.cmd(f"ir {c}")
        alt, az = self.app.ceu.altaz(self.app.ceu.resolver(c), INSTANTE)
        erro = separacao(*self.onde_o_tubo_aponta(), alt, az)
        # 1 passo = 1/44 grau ~ 0,023: o erro deve ficar na ordem de 1-2 passos
        self.assertLess(erro, 0.06, f"errou {c} por {erro:.3f} graus")

        saida = self.cmd("onde")
        self.assertTrue(any(c in s for s in saida), saida)

    def test_seguir_em_tempo_real(self):
        # O RATE e em passos por segundo REAL, entao este teste usa o relogio real.
        # Reducao 500:1 (~4444 passos/grau) para o movimento sideral de poucos
        # segundos virar dezenas de passos.
        for linha in ("config reducao_az 500", "config reducao_alt 500",
                      "config velocidade_max 500000", "config aceleracao 5000000",
                      "config periodo_rastreio 0.5"):
            self.cmd(linha)
        self.conv = Conversor(self.cfg)
        inicio = time.time()
        self.relogio = lambda: INSTANTE + (time.time() - inicio)

        a, b, c = self.tres_estrelas()
        for nome in (a, b):
            self.centralizar(nome)
            self.cmd(f"alinhar {nome}")

        parar_em = time.time() + 3.0
        self.app.tecla_apertada = lambda: time.time() > parar_em
        self.cmd(f"seguir {c}")

        alt, az = self.app.ceu.altaz(self.app.ceu.resolver(c), self.relogio())
        erro = separacao(*self.onde_o_tubo_aponta(), alt, az)
        # Em ~3 s a estrela anda ~0,01 grau. Sem rastreamento o erro seria dessa
        # ordem; rastreando, tem que ficar bem abaixo (poucos passos de 1/4444 grau).
        self.assertLess(erro, 0.004, f"erro ao fim do rastreamento: {erro * 3600:.1f}\"")

    def test_recusa_alvo_abaixo_do_limite(self):
        a, b, _ = self.tres_estrelas()
        for nome in (a, b):
            self.centralizar(nome)
            self.cmd(f"alinhar {nome}")
        self.saida.clear()
        self.app.executar("ir polaris")      # invisivel a 23 graus sul
        self.assertTrue(any("abaixo do limite" in s for s in self.saida), self.saida)

    def test_ir_sem_alinhamento_avisa(self):
        self.saida.clear()
        self.app.executar("ir sirius")
        self.assertTrue(any(s.startswith("!") for s in self.saida), self.saida)


if __name__ == "__main__":
    unittest.main()
