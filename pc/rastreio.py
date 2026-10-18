"""
GoTo e rastreamento.

Apontador: direcao do ceu -> passos-alvo dos motores (modelo de alinhamento +
conversor + caminho mais curto no azimute).

Rastreador: a cada 'periodo' segundos
  1. le a posicao real dos motores (POS?);
  2. calcula onde o objeto vai estar daqui a 'periodo' segundos;
  3. manda RATE = (posicao_futura - posicao_atual) / periodo para cada eixo.
Assim o eixo chega la no fim do ciclo, e qualquer atraso, passo arredondado ou
latencia do Bluetooth vira erro medido no ciclo seguinte e e corrigido
(realimentacao). Em montagem alt-az as duas velocidades mudam o tempo todo,
por isso sao recalculadas a cada ciclo.

Perto do zenite a velocidade de azimute necessaria cresce sem limite (no
zenite exato, o azimute "pula" 180 graus). Ela e limitada a velocidade maxima;
o erro cresce ate o objeto se afastar do zenite.
"""

import time

from montagem import caminho_curto


class Apontador:
    def __init__(self, conversor, modelo):
        self.conv = conversor
        self.modelo = modelo

    def passos_para(self, alt, az, passos_az_atual):
        """(alt, az) do ceu -> (passos_az, passos_alt), pelo caminho mais curto."""
        alt_m, az_m = self.modelo.ceu_para_montagem(alt, az)
        _, az_atual = self.conv.para_graus(passos_az_atual, 0)
        return self.conv.para_passos(alt_m, caminho_curto(az_m, az_atual))

    def angulos_montagem(self, alt, az):
        return self.modelo.ceu_para_montagem(alt, az)

    def apontando_para(self, passos_az, passos_alt):
        """Passos atuais -> (alt, az) do ceu para onde o tubo aponta."""
        alt_m, az_m = self.conv.para_graus(passos_az, passos_alt)
        return self.modelo.montagem_para_ceu(alt_m, az_m % 360.0)


def tempo_estimado(passos, vel_max, accel):
    """Tempo de um GOTO de 'passos' com rampa trapezoidal (segundos)."""
    passos = abs(passos)
    if passos == 0:
        return 0.0
    passos_rampa = vel_max ** 2 / accel          # acelerar + frear
    if passos <= passos_rampa:
        return 2 * (passos / accel) ** 0.5       # perfil triangular
    return passos / vel_max + vel_max / accel


CHEGOU, INTERROMPIDO, TEMPO_ESGOTADO = "chegou", "interrompido", "tempo esgotado"


def esperar_chegada(arduino, alvo, timeout, deve_parar=lambda: False, tolerancia=0):
    """Espera os motores chegarem em alvo=(passos_az, passos_alt).
    Devolve CHEGOU, INTERROMPIDO (deve_parar() ficou True) ou TEMPO_ESGOTADO;
    nos dois ultimos casos manda STOP."""
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        az, alt = arduino.posicao()
        if abs(az - alvo[0]) <= tolerancia and abs(alt - alvo[1]) <= tolerancia:
            return CHEGOU
        if deve_parar():
            arduino.exigir("STOP")
            return INTERROMPIDO
        time.sleep(0.1)
    arduino.exigir("STOP")
    return TEMPO_ESGOTADO


class Rastreador:
    def __init__(self, arduino, alvo_em_passos, periodo=1.0, vel_max=2000.0,
                 relogio=time.time, dormir=time.sleep):
        """alvo_em_passos(instante_unix, passos_az_atual) -> (passos_az, passos_alt)"""
        self.arduino = arduino
        self.alvo_em_passos = alvo_em_passos
        self.periodo = periodo
        self.vel_max = vel_max
        self.relogio = relogio
        self.dormir = dormir

    def _limitar(self, v):
        return max(-self.vel_max, min(self.vel_max, v))

    def ciclo(self):
        agora = self.relogio()
        az, alt = self.arduino.posicao()
        agora_az, agora_alt = self.alvo_em_passos(agora, az)
        futuro_az, futuro_alt = self.alvo_em_passos(agora + self.periodo, az)
        rate_az_ideal = (futuro_az - az) / self.periodo
        rate_alt_ideal = (futuro_alt - alt) / self.periodo
        rate_az = self._limitar(rate_az_ideal)
        rate_alt = self._limitar(rate_alt_ideal)
        self.arduino.exigir(f"RATE AZ {rate_az:.3f}")
        self.arduino.exigir(f"RATE ALT {rate_alt:.3f}")
        return {
            "erro_az": agora_az - az,       # passos que faltam AGORA
            "erro_alt": agora_alt - alt,
            "rate_az": rate_az,
            "rate_alt": rate_alt,
            "saturado": rate_az != rate_az_ideal or rate_alt != rate_alt_ideal,
        }

    def rodar(self, deve_parar=lambda: False, duracao=None, ao_ciclo=None):
        """Rastreia ate deve_parar() ser True ou passar 'duracao' segundos.
        Sempre termina com STOP, inclusive se der erro ou Ctrl+C."""
        inicio = self.relogio()
        proximo = inicio
        try:
            while not deve_parar():
                info = self.ciclo()
                if ao_ciclo:
                    ao_ciclo(info)
                if duracao is not None and self.relogio() - inicio >= duracao:
                    break
                proximo += self.periodo
                # dorme em pedacos curtos para reagir rapido ao pedido de parar
                while not deve_parar():
                    espera = proximo - self.relogio()
                    if espera <= 0:
                        break
                    self.dormir(min(0.05, espera))
                if self.relogio() - proximo > self.periodo:
                    proximo = self.relogio()   # atrasou muito: ressincroniza
        finally:
            self.arduino.exigir("STOP")
