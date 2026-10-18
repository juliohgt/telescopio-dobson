"""
Testes da tela (tkinter) contra o simulador. Abre a janela de verdade e
simula cliques; confere o efeito no "Arduino" simulado.

OPCIONAIS: abrem janelas e um deles puxa o foco do teclado, o que tira do
primeiro plano o que estiver em tela cheia (um jogo, um video). Por isso so
rodam com a variavel de ambiente TESTAR_TELA=1:

    $env:TESTAR_TELA = "1"; .venv\\Scripts\\python -m unittest testes.test_tela -v
"""

import os
import sys
import tempfile
import time
import tkinter as tk
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from astro import PASTA_DADOS  # noqa: E402
from config import Config  # noqa: E402
from simulador import SimuladorArduino  # noqa: E402
from tela import Tela  # noqa: E402

TEM_EFEMERIDE = os.path.exists(os.path.join(PASTA_DADOS, "de421.bsp"))


@unittest.skipUnless(os.environ.get("TESTAR_TELA") == "1",
                     "abre janelas e puxa o foco; rode com TESTAR_TELA=1")
class TestTela(unittest.TestCase):
    def setUp(self):
        self.sim = SimuladorArduino(porta=0, verboso=False).iniciar()
        self.root = tk.Tk()
        self.caminho = os.path.join(tempfile.mkdtemp(), "config.json")
        cfg = Config(velocidade_max=20000, aceleracao=100000, alt_minima=5)
        self.tela = Tela(self.root, f"socket://127.0.0.1:{self.sim.porta}", cfg=cfg,
                         caminho_config=self.caminho)
        self.esperar(lambda: self.tela.app is not None, "conectar")

    def tearDown(self):
        self.tela._fechar()
        self.sim.parar()

    def esperar(self, condicao, oque, limite=8.0):
        fim = time.monotonic() + limite
        while time.monotonic() < fim:
            self.root.update()
            if condicao():
                return
            time.sleep(0.02)
        self.fail(f"tempo esgotado esperando: {oque}")

    def girar(self, segundos):
        fim = time.monotonic() + segundos
        while time.monotonic() < fim:
            self.root.update()
            time.sleep(0.02)

    def log(self):
        return self.tela.txt_log.get("1.0", "end")

    def test_conecta_e_mostra_avisos(self):
        self.assertIn("Conectado", self.tela.lb_conexao.cget("text"))
        self.esperar(lambda: "Reducao do AZ = 1:1" in self.log(), "aviso de reducao")
        self.assertEqual(str(self.tela.bt_ir.cget("state")), "normal")

    def test_segurar_e_soltar_botao_move_e_para(self):
        direita = self.tela.botoes_mover[2]          # ▶ = AZ +
        self.root.update()
        direita.event_generate("<ButtonPress-1>")
        self.esperar(lambda: self.sim.az.posicao > 50, "AZ andar")
        direita.event_generate("<ButtonRelease-1>")
        self.girar(0.4)
        parado = self.sim.az.posicao
        self.girar(0.3)
        self.assertEqual(self.sim.az.posicao, parado, "continuou andando depois de soltar")
        self.assertEqual(self.sim.alt.posicao, 0)

    def test_tecla_seta_com_repeticao_nao_engasga(self):
        # Simula a repeticao automatica no formato de pares Release+Press.
        self.root.focus_force()
        self.root.update()
        for _ in range(5):
            self.root.event_generate("<KeyPress-Up>")
            self.girar(0.03)
            self.root.event_generate("<KeyRelease-Up>")
            self.girar(0.01)
        self.root.event_generate("<KeyPress-Up>")
        self.girar(0.2)
        self.assertEqual(self.tela._jog["ALT"], 1)
        self.assertEqual(self.sim.alt.jog, 1, "o motor deveria seguir em JOG sem parar")
        self.root.event_generate("<KeyRelease-Up>")
        self.esperar(lambda: self.sim.alt.jog == 0, "parar ao soltar a tecla")

    def test_parar_sem_operacao(self):
        self.tela.botoes_mover[0].event_generate("<ButtonPress-1>")
        self.esperar(lambda: self.sim.alt.posicao > 20, "ALT andar")
        self.tela.parar()
        self.esperar(lambda: self.sim.alt.jog == 0, "STOP")
        self.assertEqual(self.tela.lb_estado.cget("text"), "Parado")

    def test_tema_noturno_alterna(self):
        self.tela.alternar_tema()
        self.root.update()
        self.assertEqual(self.tela.root.cget("bg"), "#000000")
        self.tela.alternar_tema()
        self.root.update()
        self.assertNotEqual(self.tela.root.cget("bg"), "#000000")

    @unittest.skipUnless(TEM_EFEMERIDE, "precisa de pc/dados/de421.bsp")
    def test_alinhar_ir_seguir_parar(self):
        self.tela._aplicar("local -23.55 -46.63 760")
        self.tela._em_fundo("zero", "Zerando...")
        self.esperar(lambda: not self.tela._ocupado, "zerar")

        self.tela.atualizar_visiveis()
        self.esperar(lambda: self.tela.var_estrela.get(), "lista de estrelas visiveis")

        # Faz o papel do usuario: leva o tubo ate a estrela ANTES de alinhar.
        # (O simulador e uma montagem ideal: nivelada, azimute zero no Norte.)
        app = self.tela.app
        alt, az = app.ceu.altaz(app.ceu.resolver(self.tela.var_estrela.get()))
        destino = app.conv.para_passos(alt, az)
        app.ard.exigir(f"GOTO AZ {destino[0]}")
        app.ard.exigir(f"GOTO ALT {destino[1]}")
        self.esperar(lambda: (self.sim.az.posicao, self.sim.alt.posicao) == destino, "centralizar")
        self.tela.alinhar()
        self.esperar(lambda: not self.tela._ocupado and "1 ponto" in
                     self.tela.lb_alinhamento.cget("text"), "alinhar")

        # Alvo: outra estrela visivel (ja alinhada a 1 estrela, o GoTo e coerente)
        visiveis = list(self.tela.cb_estrela["values"])
        self.tela.var_alvo.set(visiveis[1])
        self.tela._operacao("ir")
        self.assertTrue(self.tela._ocupado)
        self.esperar(lambda: not self.tela._ocupado, "GoTo terminar", limite=15)
        self.assertIn("No alvo", self.log())
        self.esperar(lambda: self.tela.lb_alt.cget("text").strip().endswith("°"),
                     "leitura de altitude")

        self.tela._operacao("seguir")
        self.esperar(lambda: "Rastreando" in self.tela.lb_estado.cget("text"), "rastrear", limite=15)
        self.tela.parar()
        self.esperar(lambda: not self.tela._ocupado, "parar o rastreamento")
        self.assertEqual(self.tela.lb_estado.cget("text"), "Parado")
        self.assertFalse(self.sim.az.rate_on)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(PASTA_DADOS), "config.json")),
                         "o teste nao pode gravar o config.json real")


if __name__ == "__main__":
    unittest.main()
