"""
Calculo astronomico com skyfield: onde um objeto esta no SEU ceu agora.

Cadeia: objeto (RA/Dec J2000, ou efemeride de planeta) + sua latitude/longitude
+ hora UTC do relogio do PC  ->  altitude/azimute aparentes (com precessao,
nutacao, aberracao e refracao atmosferica).

Convencao de azimute (a do skyfield): 0 = Norte, 90 = Leste, 180 = Sul, 270 = Oeste.

Dados: na primeira vez o skyfield baixa a efemeride de421.bsp (~17 MB, NASA/JPL)
para a pasta pc/dados/. Ela da a posicao da Terra (necessaria ate para estrelas,
por causa da aberracao) e de Sol, Lua e planetas. Depois funciona offline.

A hora vem do relogio do Windows: se ele estiver 1 minuto errado, o ceu
calculado fica girado ~0,25 grau. Mantenha a sincronizacao de hora ligada.
"""

import math
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

from skyfield.api import Loader, Star, wgs84
from skyfield.earthlib import refraction

PASTA_DADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados")

# Estrelas brilhantes para alinhamento e GoTo. Coordenadas ICRS/J2000 (RA em
# horas, Dec em graus) dos catalogos baseados no Hipparcos, digitadas a mao;
# confira no Stellarium se alguma parecer errada. O movimento proprio foi
# ignorado: para estas estrelas o desvio desde 2000 e de segundos de arco
# (no pior caso, Alfa Centauri, ~1,6 minuto de arco), bem abaixo da resolucao
# da montagem.
ESTRELAS = {
    "sirius":          ("06 45 08.92", "-16 42 58.0"),
    "canopus":         ("06 23 57.11", "-52 41 44.4"),
    "alfa centauri":   ("14 39 36.49", "-60 50 02.4"),
    "arcturus":        ("14 15 39.67", "+19 10 56.7"),
    "vega":            ("18 36 56.34", "+38 47 01.3"),
    "capella":         ("05 16 41.36", "+45 59 52.8"),
    "rigel":           ("05 14 32.27", "-08 12 05.9"),
    "procyon":         ("07 39 18.12", "+05 13 30.0"),
    "achernar":        ("01 37 42.85", "-57 14 12.3"),
    "betelgeuse":      ("05 55 10.31", "+07 24 25.4"),
    "hadar":           ("14 03 49.41", "-60 22 22.9"),
    "altair":          ("19 50 47.00", "+08 52 06.0"),
    "acrux":           ("12 26 35.90", "-63 05 56.7"),
    "aldebaran":       ("04 35 55.24", "+16 30 33.5"),
    "antares":         ("16 29 24.46", "-26 25 55.2"),
    "spica":           ("13 25 11.58", "-11 09 40.8"),
    "pollux":          ("07 45 18.95", "+28 01 34.3"),
    "fomalhaut":       ("22 57 39.05", "-29 37 20.1"),
    "deneb":           ("20 41 25.92", "+45 16 49.2"),
    "mimosa":          ("12 47 43.27", "-59 41 19.6"),
    "regulus":         ("10 08 22.31", "+11 58 02.0"),
    "adhara":          ("06 58 37.55", "-28 58 19.5"),
    "shaula":          ("17 33 36.52", "-37 06 13.8"),
    "castor":          ("07 34 35.87", "+31 53 17.8"),
    "gacrux":          ("12 31 09.96", "-57 06 47.6"),
    "bellatrix":       ("05 25 07.86", "+06 20 58.9"),
    "peacock":         ("20 25 38.86", "-56 44 06.3"),
    "alnair":          ("22 08 13.98", "-46 57 39.5"),
    "alphard":         ("09 27 35.24", "-08 39 31.0"),
    "nunki":           ("18 55 15.93", "-26 17 48.2"),
    "kaus australis":  ("18 24 10.32", "-34 23 04.6"),
    "polaris":         ("02 31 49.09", "+89 15 50.8"),
}

APELIDOS = {
    "rigil kentaurus": "alfa centauri",
    "alpha centauri": "alfa centauri",
    "estrela polar": "polaris",
    "polar": "polaris",
}

# Nomes no arquivo de421. Planetas externos so existem como baricentro do
# sistema (planeta + luas); a diferenca para o planeta e desprezivel aqui.
PLANETAS = {
    "lua": "moon",
    "mercurio": "mercury",
    "venus": "venus",
    "marte": "mars barycenter",
    "jupiter": "jupiter barycenter",
    "saturno": "saturn barycenter",
    "urano": "uranus barycenter",
    "netuno": "neptune barycenter",
}


def normalizar(nome):
    """'Júpiter ' -> 'jupiter' (sem acento, minusculo, espacos simples)."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def sexagesimal(texto):
    """'06:45:08.9', '06 45 08.9', '6h45m08.9s', '-16d42m58s' ou '6.75' -> float."""
    t = texto.strip()
    sinal = -1.0 if t.startswith("-") else 1.0
    numeros = re.findall(r"\d+(?:\.\d+)?", t)
    if not numeros or len(numeros) > 3:
        raise ValueError(f"coordenada invalida: {texto!r}")
    valor = 0.0
    for i, n in enumerate(numeros):
        valor += float(n) / (60 ** i)
    return sinal * valor


def _estrela(ra_texto, dec_texto):
    ra, dec = sexagesimal(ra_texto), sexagesimal(dec_texto)
    if not 0 <= ra < 24:
        raise ValueError(f"RA fora de 0..24 h: {ra}")
    if not -90 <= dec <= 90:
        raise ValueError(f"Dec fora de -90..+90: {dec}")
    return Star(ra_hours=ra, dec_degrees=dec)


@dataclass
class Alvo:
    nome: str
    corpo: object     # Star do skyfield ou corpo da efemeride


class Ceu:
    def __init__(self, latitude, longitude, altitude_m=0.0, temperatura_c=15.0,
                 pasta=PASTA_DADOS):
        os.makedirs(pasta, exist_ok=True)
        carregar = Loader(pasta)
        self.ts = carregar.timescale()            # dados de tempo embutidos no skyfield
        self.efemerides = carregar("de421.bsp")   # baixa na primeira vez (~17 MB)
        self.terra = self.efemerides["earth"]
        self.local = wgs84.latlon(latitude, longitude, elevation_m=altitude_m)
        self.observador = self.terra + self.local
        self.temperatura_c = temperatura_c
        # mesma pressao "padrao" que o skyfield usa com pressure_mbar="standard"
        self._pressao_mbar = 1010.0 * math.exp(-altitude_m / 9.1e3)

    def tempo(self, unix=None):
        """Tempo do skyfield a partir de um instante Unix (padrao: agora)."""
        if unix is None:
            return self.ts.now()
        return self.ts.from_datetime(datetime.fromtimestamp(unix, tz=timezone.utc))

    def resolver(self, texto):
        """Nome de estrela, de planeta, ou coordenadas 'RA Dec'."""
        nome = normalizar(texto)
        nome = APELIDOS.get(nome, nome)
        if nome in ESTRELAS:
            return Alvo(nome, _estrela(*ESTRELAS[nome]))
        if nome in PLANETAS:
            return Alvo(nome, self.efemerides[PLANETAS[nome]])
        partes = texto.split()
        if len(partes) == 2:
            try:
                return Alvo(f"RA {partes[0]} Dec {partes[1]}", _estrela(*partes))
            except ValueError as erro:
                raise ValueError(str(erro)) from None
        raise ValueError(
            f"nao conheco {texto!r}. Use uma estrela ({', '.join(sorted(ESTRELAS))}), "
            f"um planeta ({', '.join(PLANETAS)}) ou coordenadas 'RA Dec' "
            f"(ex.: 06:45:09 -16:42:58)."
        )

    def altaz(self, alvo, unix=None, refracao=True):
        """(altitude, azimute) aparentes em graus."""
        t = self.tempo(unix)
        aparente = self.observador.at(t).observe(alvo.corpo).apparent()
        if refracao:
            alt, az, _ = aparente.altaz(temperature_C=self.temperatura_c,
                                        pressure_mbar="standard")
        else:
            alt, az, _ = aparente.altaz()
        return alt.degrees, az.degrees

    def radec(self, alt, az, unix=None, refracao=True):
        """Direcao aparente (alt, az) -> (RA em horas, Dec em graus), J2000."""
        if refracao:
            # refraction() recebe a altitude APARENTE (e assim que o refract()
            # do skyfield a usa), entao desfazer e uma subtracao direta.
            alt = alt - refraction(alt, self.temperatura_c, self._pressao_mbar)
        posicao = self.observador.at(self.tempo(unix)).from_altaz(alt_degrees=alt,
                                                                  az_degrees=az)
        ra, dec, _ = posicao.radec()
        return ra.hours, dec.degrees

    def estrelas_visiveis(self, alt_minima, unix=None):
        """[(nome, alt, az)] das estrelas da lista acima de alt_minima, mais altas primeiro."""
        visiveis = []
        for nome in ESTRELAS:
            alt, az = self.altaz(self.resolver(nome), unix)
            if alt >= alt_minima:
                visiveis.append((nome, alt, az))
        return sorted(visiveis, key=lambda v: -v[1])


def formatar_ra(horas):
    h = int(horas)
    m = int((horas - h) * 60)
    s = ((horas - h) * 60 - m) * 60
    return f"{h:02d}h{m:02d}m{s:04.1f}s"


def formatar_dec(graus):
    sinal = "-" if graus < 0 else "+"
    g = abs(graus)
    d = int(g)
    m = int((g - d) * 60)
    s = ((g - d) * 60 - m) * 60
    return f"{sinal}{d:02d}°{m:02d}'{s:02.0f}\""
