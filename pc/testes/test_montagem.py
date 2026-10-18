"""
Testes do modelo de montagem com dados sinteticos: inventamos uma montagem
desnivelada e com o Norte desconhecido, geramos as leituras que ela daria, e
conferimos se o alinhamento recupera a relacao verdadeira.
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # noqa: E402
from montagem import (AlinhamentoErro, Conversor, ModeloAlinhamento,  # noqa: E402
                      angulos, caminho_curto, separacao, vetor)


def rotacao(eixo, graus):
    """Matriz de rotacao (Rodrigues) em torno de 'eixo'."""
    k = np.asarray(eixo, float) / np.linalg.norm(eixo)
    t = np.radians(graus)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(t) * K + (1 - np.cos(t)) * K @ K


# Montagem "verdadeira": base inclinada 3 graus, zero do azimute a 137 graus do Norte.
R_VERDADEIRA = rotacao([1, 0.4, 0], 3.0) @ rotacao([0, 0, 1], 137.0)


def leitura_da_montagem(alt, az):
    """Angulos que os eixos marcariam apontando para (alt, az) do ceu."""
    return angulos(R_VERDADEIRA.T @ vetor(alt, az))


class TestGeometria(unittest.TestCase):
    def test_vetor_e_angulos_ida_e_volta(self):
        for alt, az in [(0, 0), (45, 90), (-10, 359.5), (89, 200)]:
            a, z = angulos(vetor(alt, az))
            self.assertAlmostEqual(a, alt, places=9)
            self.assertAlmostEqual(z, az, places=9)

    def test_separacao_conhecida(self):
        self.assertAlmostEqual(separacao(0, 0, 0, 90), 90)
        self.assertAlmostEqual(separacao(0, 10, 90, 250), 90)   # zenite

    def test_caminho_curto_atravessa_o_norte(self):
        self.assertAlmostEqual(caminho_curto(10, 350), 370)
        self.assertAlmostEqual(caminho_curto(350, 10), -10)
        self.assertAlmostEqual(caminho_curto(10, 730), 730)   # 730 = 2 voltas + 10: ja esta la
        self.assertAlmostEqual(caminho_curto(20, 715), 740)   # 715 = 2 voltas - 5: anda +25
        self.assertAlmostEqual(caminho_curto(180, 0), -180)   # empate: qualquer lado serve


class TestConversor(unittest.TestCase):
    def test_passos_por_grau(self):
        cfg = Config(reducao_az=50, reducao_alt=40)
        self.assertAlmostEqual(cfg.passos_por_grau_az, 200 * 16 * 50 / 360)
        self.assertAlmostEqual(cfg.passos_por_grau_alt, 200 * 16 * 40 / 360)

    def test_ida_e_volta_e_inversao(self):
        for inverter in (False, True):
            conv = Conversor(Config(reducao_az=50, reducao_alt=40,
                                    inverter_az=inverter, inverter_alt=inverter))
            paz, palt = conv.para_passos(30.0, -12.5)
            self.assertEqual((paz < 0), not inverter)
            alt, az = conv.para_graus(paz, palt)
            self.assertAlmostEqual(alt, 30.0, delta=1 / conv.ppg_alt)
            self.assertAlmostEqual(az, -12.5, delta=1 / conv.ppg_az)


class TestAlinhamento(unittest.TestCase):
    def test_uma_estrela_base_nivelada_e_exata(self):
        R = rotacao([0, 0, 1], 137.0)          # so o Norte desconhecido
        m = ModeloAlinhamento()
        alt_m, az_m = angulos(R.T @ vetor(40, 100))
        m.adicionar("a", 40, 100, alt_m, az_m)
        for alt, az in [(20, 200), (70, 10)]:
            esperado = angulos(R.T @ vetor(alt, az))
            obtido = m.ceu_para_montagem(alt, az)
            self.assertAlmostEqual(obtido[0], esperado[0], places=6)
            self.assertAlmostEqual(obtido[1], esperado[1], places=6)

    def test_duas_estrelas_recuperam_base_inclinada(self):
        m = ModeloAlinhamento()
        for nome, alt, az in [("a", 35, 80), ("b", 50, 190)]:
            m.adicionar(nome, alt, az, *leitura_da_montagem(alt, az))
        # testa em direcoes que NAO foram usadas no alinhamento
        for alt, az in [(15, 300), (80, 45), (25, 140)]:
            alt_m, az_m = m.ceu_para_montagem(alt, az)
            esperado = leitura_da_montagem(alt, az)
            self.assertLess(separacao(alt_m, az_m, *esperado), 1e-6)
            # e o caminho inverso
            alt_c, az_c = m.montagem_para_ceu(*esperado)
            self.assertLess(separacao(alt_c, az_c, alt, az), 1e-6)
        for _, erro in m.residuos():
            self.assertLess(erro, 1e-6)

    def test_uma_estrela_com_base_inclinada_erra_e_duas_corrigem(self):
        # Mostra por que vale fazer 2 estrelas: com base desnivelada, 1 estrela
        # deixa erro longe do ponto de alinhamento.
        um = ModeloAlinhamento()
        um.adicionar("a", 35, 80, *leitura_da_montagem(35, 80))
        erro_um = separacao(*um.ceu_para_montagem(20, 260), *leitura_da_montagem(20, 260))
        self.assertGreater(erro_um, 1.0)

    def test_tres_estrelas_com_ruido_minimos_quadrados(self):
        rng = np.random.default_rng(42)
        m = ModeloAlinhamento()
        for nome, alt, az in [("a", 30, 20), ("b", 60, 140), ("c", 25, 250)]:
            alt_m, az_m = leitura_da_montagem(alt, az)
            ruido = rng.normal(0, 0.05, 2)   # erro de centragem ~3 minutos de arco
            m.adicionar(nome, alt, az, alt_m + ruido[0], az_m + ruido[1])
        alt_m, az_m = m.ceu_para_montagem(45, 330)
        self.assertLess(separacao(alt_m, az_m, *leitura_da_montagem(45, 330)), 0.15)

    def test_estrelas_proximas_sao_recusadas(self):
        m = ModeloAlinhamento()
        m.adicionar("a", 40, 100, *leitura_da_montagem(40, 100))
        with self.assertRaises(AlinhamentoErro):
            m.adicionar("b", 45, 105, *leitura_da_montagem(45, 105))

    def test_erro_de_escala_denuncia_reducao_errada(self):
        # A montagem real gira o dobro do que o programa acha (reducao
        # configurada pela metade): os angulos lidos saem multiplicados por 2.
        def leitura_errada(alt, az):
            alt_m, az_m = leitura_da_montagem(alt, az)
            return alt_m * 2, az_m * 2
        m = ModeloAlinhamento()
        m.adicionar("a", 20, 30, *leitura_errada(20, 30))
        m.adicionar("b", 30, 80, *leitura_errada(30, 80))
        (_, _, razao), = m.erro_de_escala()
        # Detecta (bem acima de 1), mas nao vale 2: ver docstring de erro_de_escala.
        self.assertGreater(razao, 1.2)

    def test_erro_de_escala_e_um_com_reducao_certa(self):
        m = ModeloAlinhamento()
        m.adicionar("a", 20, 30, *leitura_da_montagem(20, 30))
        m.adicionar("b", 30, 80, *leitura_da_montagem(30, 80))
        (_, _, razao), = m.erro_de_escala()
        self.assertAlmostEqual(razao, 1.0, places=9)

    def test_sem_alinhamento_avisa(self):
        with self.assertRaises(AlinhamentoErro):
            ModeloAlinhamento().ceu_para_montagem(10, 10)


if __name__ == "__main__":
    unittest.main()
