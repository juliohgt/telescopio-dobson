"""
Configuracao do telescopio, salva em config.json (ao lado deste arquivo).

Os valores mecanicos (reducao, microstep, sentido dos motores) definem a
conversao angulo <-> passos. Se estiverem errados, o GoTo erra proporcionalmente
a distancia percorrida, e o alinhamento com 2 estrelas denuncia (ver
montagem.ModeloAlinhamento.erro_de_escala).
"""

import json
import os
from dataclasses import asdict, dataclass, fields

ARQUIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


@dataclass
class Config:
    # Local de observacao (graus decimais: sul e oeste NEGATIVOS).
    latitude: float = None
    longitude: float = None
    altitude_m: float = 0.0
    temperatura_c: float = 15.0      # usada no calculo da refracao atmosferica

    # Mecanica de cada eixo
    passos_por_volta: int = 200      # NEMA 17 de 1,8 graus
    microstep: int = 16              # jumpers M0/M1/M2 do DRV8825
    reducao_az: float = 1.0          # voltas do motor por volta do eixo (ex.: 20T->60T = 3.0)
    reducao_alt: float = 1.0
    # Convencao: AZ positivo gira no sentido Norte->Leste (horario visto de cima)
    # e ALT positivo sobe o tubo. Se um motor gira ao contrario, inverta aqui.
    inverter_az: bool = False
    inverter_alt: bool = False

    # Limites e rastreamento
    alt_minima: float = 5.0          # nao aponta abaixo disso (horizonte, obstaculos)
    velocidade_max: float = 2000.0   # passos/s (enviada como SPEED ao conectar)
    aceleracao: float = 1000.0       # passos/s^2 (enviada como ACCEL ao conectar)
    periodo_rastreio: float = 1.0    # segundos entre correcoes do rastreamento

    @property
    def local_definido(self):
        return self.latitude is not None and self.longitude is not None

    @property
    def passos_por_grau_az(self):
        return self.passos_por_volta * self.microstep * self.reducao_az / 360.0

    @property
    def passos_por_grau_alt(self):
        return self.passos_por_volta * self.microstep * self.reducao_alt / 360.0

    @classmethod
    def carregar(cls, caminho=ARQUIVO):
        if not os.path.exists(caminho):
            return cls()
        with open(caminho, encoding="utf-8") as f:
            dados = json.load(f)
        conhecidos = {c.name for c in fields(cls)}
        return cls(**{k: v for k, v in dados.items() if k in conhecidos})

    def salvar(self, caminho=ARQUIVO):
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    def alterar(self, campo, texto):
        """Altera um campo a partir de texto, convertendo para o tipo certo."""
        tipos = {c.name: c.type for c in fields(self)}
        if campo not in tipos:
            raise KeyError(campo)
        atual = getattr(self, campo)
        if isinstance(atual, bool) or tipos[campo] is bool:
            valor = texto.strip().lower() in ("1", "sim", "s", "true", "verdadeiro", "yes")
        elif tipos[campo] is int:
            valor = int(texto)
        else:
            valor = float(texto)
        setattr(self, campo, valor)
        return valor
