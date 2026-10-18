"""
Modelo da montagem: passos dos motores <-> direcao no ceu.

Dois referenciais:
- CEU: altitude/azimute verdadeiros (do skyfield), azimute 0 = Norte, 90 = Leste.
- MONTAGEM: os angulos que os eixos do telescopio realmente giraram, contados
  a partir do ZERO (feito com o tubo na horizontal). O zero do azimute e
  arbitrario: a montagem nao sabe onde fica o Norte.

O alinhamento descobre a relacao entre os dois. Ela e FIXA no tempo (a
montagem nao se move em relacao ao chao), entao estrelas medidas em
instantes diferentes podem ser combinadas.

- 1 estrela: so desloca altitude e azimute (supoe base nivelada).
- 2 ou mais: calcula a ROTACAO 3D que leva a montagem ao ceu, por minimos
  quadrados (algoritmo de Kabsch, via SVD). Isso absorve o Norte desconhecido
  e a base desnivelada. Nao corrige erros de escala (reducao errada) nem eixos
  nao perpendiculares; o erro de escala e medido e reportado.
"""

import numpy as np

SEPARACAO_MINIMA = 15.0   # graus entre estrelas de alinhamento


def vetor(alt, az):
    """(alt, az) em graus -> vetor unitario (Norte, Leste, Cima)."""
    a, z = np.radians(alt), np.radians(az)
    return np.array([np.cos(a) * np.cos(z), np.cos(a) * np.sin(z), np.sin(a)])


def angulos(v):
    """Vetor -> (alt, az) em graus, az em [0, 360)."""
    v = np.asarray(v, dtype=float)
    v = v / np.linalg.norm(v)
    alt = np.degrees(np.arcsin(np.clip(v[2], -1.0, 1.0)))
    az = np.degrees(np.arctan2(v[1], v[0])) % 360.0
    return float(alt), float(az)


def separacao(alt1, az1, alt2, az2):
    """Angulo entre duas direcoes, em graus."""
    c = float(np.dot(vetor(alt1, az1), vetor(alt2, az2)))
    return float(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))


def caminho_curto(az_alvo, az_atual):
    """Azimute 'acumulado' mais proximo de az_atual equivalente a az_alvo.
    Ex.: atual 350, alvo 10 -> 370 (anda +20, nao -340)."""
    delta = ((az_alvo - az_atual + 180.0) % 360.0) - 180.0
    return az_atual + delta


class Conversor:
    """Passos <-> angulos da montagem, a partir da Config."""

    def __init__(self, cfg):
        self.ppg_az = cfg.passos_por_grau_az
        self.ppg_alt = cfg.passos_por_grau_alt
        self.sinal_az = -1 if cfg.inverter_az else 1
        self.sinal_alt = -1 if cfg.inverter_alt else 1

    def para_graus(self, passos_az, passos_alt):
        """-> (alt_m, az_m). az_m e acumulado (pode passar de 360 ou ser negativo)."""
        return (self.sinal_alt * passos_alt / self.ppg_alt,
                self.sinal_az * passos_az / self.ppg_az)

    def para_passos(self, alt_m, az_m):
        """-> (passos_az, passos_alt) inteiros."""
        return (int(round(self.sinal_az * az_m * self.ppg_az)),
                int(round(self.sinal_alt * alt_m * self.ppg_alt)))


class AlinhamentoErro(Exception):
    pass


class ModeloAlinhamento:
    def __init__(self):
        self.pontos = []        # (nome, alt_ceu, az_ceu, alt_m, az_m)
        self._R = None          # rotacao montagem -> ceu (>= 2 pontos)
        self._desloc = None     # (d_alt, d_az) montagem - ceu (1 ponto)

    @property
    def pronto(self):
        return bool(self.pontos)

    def limpar(self):
        self.__init__()

    def adicionar(self, nome, alt_ceu, az_ceu, alt_m, az_m):
        for outro in self.pontos:
            sep = separacao(alt_ceu, az_ceu, outro[1], outro[2])
            if sep < SEPARACAO_MINIMA:
                raise AlinhamentoErro(
                    f"{nome} esta a {sep:.1f} graus de {outro[0]}: use estrelas a "
                    f"pelo menos {SEPARACAO_MINIMA:.0f} graus uma da outra "
                    f"(de preferencia 60-120), senao a rotacao fica mal definida.")
        self.pontos.append((nome, alt_ceu, az_ceu, alt_m, az_m % 360.0))
        self._ajustar()

    def _ajustar(self):
        if len(self.pontos) == 1:
            _, alt_c, az_c, alt_m, az_m = self.pontos[0]
            self._desloc = (alt_m - alt_c, az_m - az_c)
            self._R = None
            return
        # Kabsch: R que minimiza soma |R*m_i - s_i|^2 (m = montagem, s = ceu)
        M = np.array([vetor(p[3], p[4]) for p in self.pontos])
        S = np.array([vetor(p[1], p[2]) for p in self.pontos])
        U, _, Vt = np.linalg.svd(M.T @ S)
        d = np.sign(np.linalg.det(Vt.T @ U.T))
        self._R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
        self._desloc = None

    def ceu_para_montagem(self, alt, az):
        """Direcao no ceu -> (alt_m, az_m em [0,360)) que os eixos devem ter."""
        if not self.pronto:
            raise AlinhamentoErro("sem alinhamento: use 'alinhar <estrela>'")
        if self._R is None:
            d_alt, d_az = self._desloc
            return alt + d_alt, (az + d_az) % 360.0
        return angulos(self._R.T @ vetor(alt, az))

    def montagem_para_ceu(self, alt_m, az_m):
        if not self.pronto:
            raise AlinhamentoErro("sem alinhamento")
        if self._R is None:
            d_alt, d_az = self._desloc
            return alt_m - d_alt, (az_m - d_az) % 360.0
        return angulos(self._R @ vetor(alt_m, az_m))

    def residuos(self):
        """Erro (graus) de cada ponto de alinhamento depois do ajuste."""
        erros = []
        for nome, alt_c, az_c, alt_m, az_m in self.pontos:
            alt_p, az_p = self.montagem_para_ceu(alt_m, az_m)
            erros.append((nome, separacao(alt_c, az_c, alt_p, az_p)))
        return erros

    def erro_de_escala(self):
        """Para cada par de pontos: separacao medida pela montagem / separacao real.
        Rotacao preserva angulos; se a razao foge de 1 (alem do erro de centragem),
        a conversao passos->graus (reducao, microstep) esta errada: > 1 = reducao
        configurada MENOR que a real; < 1 = MAIOR.

        Serve para DETECTAR, nao para calcular o valor certo: em geometria
        esferica, errar a escala dos eixos por um fator k nao multiplica a
        separacao por k (nos testes, k = 2 deu razao 1,39). Para corrigir, meca
        a reducao no proprio eixo: marque o eixo, mande o motor dar N voltas
        (N * passos_por_volta * microstep passos) e conte quanto o eixo girou."""
        razoes = []
        for i in range(len(self.pontos)):
            for j in range(i + 1, len(self.pontos)):
                a, b = self.pontos[i], self.pontos[j]
                real = separacao(a[1], a[2], b[1], b[2])
                medida = separacao(a[3], a[4], b[3], b[4])
                razoes.append((a[0], b[0], medida / real))
        return razoes
