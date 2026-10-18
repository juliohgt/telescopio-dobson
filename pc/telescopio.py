#!/usr/bin/env python3
"""
Telescopio Dobsoniano  -  FASE 2: GoTo e rastreamento, com o calculo no PC
---------------------------------------------------------------------------
O PC calcula onde o objeto esta (skyfield), converte para passos usando o
alinhamento e manda o Arduino mover. O Arduino continua so executando passos.

Uso:
  py telescopio.py                          -> escolhe a porta numa lista
  py telescopio.py COM5                     -> HC-06 ou USB
  py telescopio.py socket://127.0.0.1:7777  -> simulador (py simulador.py)
"""

import sys
import time

import serial

from arduino import Arduino, ArduinoErro, escolher_porta
from astro import Ceu, ESTRELAS, formatar_dec, formatar_ra, normalizar
from config import ARQUIVO, Config
from montagem import AlinhamentoErro, Conversor, ModeloAlinhamento, separacao
from rastreio import (CHEGOU, INTERROMPIDO, Apontador, Rastreador,
                      esperar_chegada, tempo_estimado)

try:
    import msvcrt  # teclado no Windows
except ImportError:
    msvcrt = None

AJUDA = """
Comandos (digite e Enter):
  local <lat> <lon> [altitude_m]  sua localizacao, graus decimais (sul/oeste NEGATIVOS)
  config                          mostra a configuracao
  config <campo> <valor>          altera (ex.: config reducao_az 50)
  zero                            zera a posicao: faca com o TUBO NA HORIZONTAL
  manual                          teclado: setas/jog para centralizar (Esc volta)
  estrelas                        estrelas de alinhamento visiveis agora
  ver <alvo>                      onde o alvo esta agora (nao move)
  alinhar <alvo>                  registra: "o <alvo> esta centralizado na ocular"
  alinhamento                     pontos de alinhamento e qualidade
  limpar                          apaga o alinhamento
  ir <alvo>                       GoTo
  seguir <alvo>                   GoTo + rastreamento (qualquer tecla para)
  onde                            para onde o telescopio esta apontando
  parar                           para os motores
  ajuda | sair

<alvo>: estrela (sirius, canopus, acrux...), planeta (lua, marte, jupiter...)
        ou coordenadas "RA Dec" J2000, ex.: 06:45:09 -16:42:58

Sequencia de uso:
  1. local ...            (uma vez; fica salvo em config.json)
  2. tubo na horizontal -> zero
  3. manual -> centralize uma estrela brilhante -> Esc -> alinhar <estrela>
  4. repita o passo 3 com outra estrela a 60-120 graus da primeira
  5. ir <objeto>  ou  seguir <objeto>
"""

CAMPOS_MECANICOS = {"passos_por_volta", "microstep", "reducao_az", "reducao_alt",
                    "inverter_az", "inverter_alt"}
CAMPOS_LOCAL = {"latitude", "longitude", "altitude_m", "temperatura_c"}
LIMITE_ALT_MONTAGEM = (-2.0, 92.0)   # curso fisico do eixo de altitude (graus)
TOLERANCIA_ESCALA = 0.02             # 2%: acima disso, a reducao provavelmente esta errada


class ErroUso(Exception):
    pass


def cardinal(az):
    return ["N", "NE", "L", "SE", "S", "SO", "O", "NO"][int((az + 22.5) // 45) % 8]


def _numero(texto):
    """Aceita virgula decimal: '-23,55' -> -23.55."""
    return float(texto.replace(",", "."))


def _tecla_apertada():
    if msvcrt and msvcrt.kbhit():
        while msvcrt.kbhit():
            msvcrt.getch()
        return True
    return False


class App:
    def __init__(self, arduino, cfg, caminho_config=ARQUIVO, relogio=time.time,
                 escrever=print, tecla_apertada=_tecla_apertada):
        self.ard = arduino
        self.cfg = cfg
        self.caminho_config = caminho_config
        self.relogio = relogio
        self.escrever = escrever
        self.tecla_apertada = tecla_apertada
        self.dica_parar = "Qualquer tecla interrompe."   # a tela troca por "Clique PARAR"
        self.modelo = ModeloAlinhamento()
        self._ceu = None
        self.ard.exigir(f"SPEED {cfg.velocidade_max}")
        self.ard.exigir(f"ACCEL {cfg.aceleracao}")

    # ---------- apoio ----------
    @property
    def ceu(self):
        if not self.cfg.local_definido:
            raise ErroUso("defina sua localizacao primeiro: local <lat> <lon> [altitude_m]")
        if self._ceu is None:
            self._ceu = Ceu(self.cfg.latitude, self.cfg.longitude,
                            self.cfg.altitude_m, self.cfg.temperatura_c)
        return self._ceu

    @property
    def conv(self):
        return Conversor(self.cfg)

    @property
    def apontador(self):
        return Apontador(self.conv, self.modelo)

    def _perder_alinhamento(self, motivo):
        if self.modelo.pronto:
            self.escrever(f"! Alinhamento apagado: {motivo}. Refaca o alinhamento.")
        self.modelo.limpar()

    def _status(self, texto):
        if self.escrever is print:
            print("\r" + texto.ljust(90), end="", flush=True)
        else:
            self.escrever(texto)

    def avisos(self):
        if not self.cfg.local_definido:
            self.escrever("! Localizacao nao definida: use  local <lat> <lon> [altitude_m]")
        for eixo, ppg, reducao in (("AZ", self.cfg.passos_por_grau_az, self.cfg.reducao_az),
                                   ("ALT", self.cfg.passos_por_grau_alt, self.cfg.reducao_alt)):
            resolucao = 3600.0 / ppg
            self.escrever(f"  Eixo {eixo}: {ppg:.1f} passos/grau = {resolucao:.1f}\" por passo "
                          f"(reducao {reducao:g}:1)")
            if reducao == 1.0:
                self.escrever(f"! Reducao do {eixo} = 1:1 (padrao). Se ha polia/engrenagem, configure: "
                              f"config reducao_{eixo.lower()} <valor>")

    # ---------- laco de comandos ----------
    def executar(self, linha):
        """Executa uma linha de comando. Devolve False para sair."""
        if self.ard.reiniciou:
            self.ard.reiniciou = False
            self._perder_alinhamento("o Arduino reiniciou e a contagem de passos voltou a zero")
        partes = linha.strip().split(maxsplit=1)
        if not partes:
            return True
        cmd = normalizar(partes[0])
        resto = partes[1].strip() if len(partes) > 1 else ""
        if cmd in ("sair", "q", "exit"):
            return False
        metodo = getattr(self, f"cmd_{cmd}", None)
        if metodo is None:
            self.escrever(f"! comando desconhecido: {partes[0]} (digite 'ajuda')")
            return True
        try:
            metodo(resto)
        except (ErroUso, AlinhamentoErro, ValueError) as erro:
            self.escrever(f"! {erro}")
        except ArduinoErro as erro:
            self.escrever(f"! Arduino: {erro}")
        except KeyboardInterrupt:
            self.ard.exigir("STOP")
            self.escrever("\nInterrompido (motores parados).")
        return True

    # ---------- comandos ----------
    def cmd_ajuda(self, _):
        self.escrever(AJUDA)

    def cmd_local(self, resto):
        t = resto.split()
        if len(t) not in (2, 3):
            raise ErroUso("uso: local <lat> <lon> [altitude_m]   (ex.: local -23.55 -46.63 760)")
        lat, lon = _numero(t[0]), _numero(t[1])
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ErroUso("latitude deve estar em -90..90 e longitude em -180..180")
        self.cfg.latitude, self.cfg.longitude = lat, lon
        if len(t) == 3:
            self.cfg.altitude_m = _numero(t[2])
        self.cfg.salvar(self.caminho_config)
        self._ceu = None
        self._perder_alinhamento("a localizacao mudou")
        self.escrever(f"Local: lat {lat:.4f}, lon {lon:.4f}, altitude {self.cfg.altitude_m:.0f} m (salvo).")

    def cmd_config(self, resto):
        if not resto:
            for campo, valor in vars(self.cfg).items():
                self.escrever(f"  {campo:18s} = {valor}")
            self.avisos()
            return
        partes = resto.split(maxsplit=1)
        if len(partes) != 2:
            raise ErroUso("uso: config <campo> <valor>")
        campo, texto = partes
        try:
            valor = self.cfg.alterar(campo, texto.replace(",", "."))
        except KeyError:
            raise ErroUso(f"campo desconhecido: {campo} (veja 'config')") from None
        self.cfg.salvar(self.caminho_config)
        self.escrever(f"  {campo} = {valor} (salvo)")
        if campo in CAMPOS_MECANICOS:
            self._perder_alinhamento("a conversao passos/graus mudou")
        if campo in CAMPOS_LOCAL:
            self._ceu = None
            if campo in ("latitude", "longitude"):
                self._perder_alinhamento("a localizacao mudou")
        if campo == "velocidade_max":
            self.ard.exigir(f"SPEED {valor}")
        if campo == "aceleracao":
            self.ard.exigir(f"ACCEL {valor}")

    def cmd_zero(self, _):
        self.ard.exigir("ZERO")
        self._perder_alinhamento("a posicao foi zerada")
        self.escrever("Zero feito. A altitude da montagem passa a contar a partir daqui:\n"
                      "o tubo precisa estar na HORIZONTAL (use um nivel de bolha). Se ele tambem\n"
                      "apontava para o Norte, a posicao fica estimada mesmo antes do alinhamento.")

    def cmd_manual(self, _):
        if msvcrt is None:
            raise ErroUso("o modo manual por teclado so funciona no Windows")
        from controle import __doc__ as teclas, laco_teclado

        def envia(comando):
            if comando == "ZERO":
                self.cmd_zero("")
                return
            self.escrever(f"   {comando} -> {self.ard.enviar(comando)}")

        self.escrever("Modo manual: setas = passo a passo, a/d w/x = continuo, espaco = parar, "
                      "h = ajuda, Esc = voltar")
        try:
            laco_teclado(envia, ajuda=lambda: self.escrever(teclas))
        finally:
            self.ard.exigir("STOP")
        self.escrever("Fim do modo manual.")

    def cmd_estrelas(self, _):
        agora = self.relogio()
        visiveis = self.ceu.estrelas_visiveis(self.cfg.alt_minima, agora)
        if not visiveis:
            self.escrever("Nenhuma estrela da lista acima do limite agora.")
            return
        self.escrever(f"Estrelas acima de {self.cfg.alt_minima:g} graus agora:")
        for nome, alt, az in visiveis:
            self.escrever(f"  {nome:15s} alt {alt:5.1f}   az {az:5.1f} ({cardinal(az)})")

    def cmd_ver(self, resto):
        alvo = self._resolver(resto)
        alt, az = self.ceu.altaz(alvo, self.relogio())
        situacao = "visivel" if alt >= self.cfg.alt_minima else "abaixo do limite"
        self.escrever(f"{alvo.nome}: alt {alt:.2f}  az {az:.2f} ({cardinal(az)})  [{situacao}]")

    def cmd_alinhar(self, resto):
        alvo = self._resolver(resto)
        alt, az = self.ceu.altaz(alvo, self.relogio())
        if alt < 0:
            raise ErroUso(f"{alvo.nome} esta abaixo do horizonte ({alt:.1f} graus): estrela errada?")
        alt_m, az_m = self.conv.para_graus(*self.ard.posicao())
        self.modelo.adicionar(alvo.nome, alt, az, alt_m, az_m)
        n = len(self.modelo.pontos)
        self.escrever(f"Ponto {n} registrado: {alvo.nome} (alt {alt:.2f}, az {az:.2f}).")
        if n == 1:
            self.escrever("Com 1 estrela o modelo so desloca os eixos e supoe a base nivelada.\n"
                          "Alinhe uma 2a estrela a 60-120 graus desta para corrigir desnivel.")
        else:
            self._qualidade()

    def cmd_alinhamento(self, _):
        if not self.modelo.pronto:
            self.escrever("Sem alinhamento.")
            return
        for nome, alt, az, alt_m, az_m in self.modelo.pontos:
            self.escrever(f"  {nome:15s} ceu alt {alt:6.2f} az {az:6.2f} | "
                          f"montagem alt {alt_m:7.2f} az {az_m:7.2f}")
        self._qualidade()

    def _qualidade(self):
        if len(self.modelo.pontos) < 2:
            return
        for nome, erro in self.modelo.residuos():
            self.escrever(f"  residuo {nome:15s} {erro * 60:6.1f}'")
        for a, b, razao in self.modelo.erro_de_escala():
            self.escrever(f"  separacao {a}-{b}: medida/real = {razao:.4f}")
            if abs(razao - 1) > TOLERANCIA_ESCALA:
                self.escrever(
                    f"! A montagem mediu {abs(razao - 1) * 100:.1f}% {'a mais' if razao > 1 else 'a menos'} "
                    f"que a separacao real. Causas provaveis: reducao/microstep configurados "
                    f"errados ({'menores' if razao > 1 else 'maiores'} que os reais), estrela "
                    f"errada, ou passos perdidos. Meca a reducao no eixo (ver README).")

    def cmd_limpar(self, _):
        self.modelo.limpar()
        self.escrever("Alinhamento apagado.")

    def _resolver(self, texto):
        if not texto:
            raise ErroUso("informe o alvo (ex.: sirius, jupiter, 06:45:09 -16:42:58)")
        return self.ceu.resolver(texto)

    def _checar_limites(self, alvo, alt, az):
        if alt < self.cfg.alt_minima:
            raise ErroUso(f"{alvo.nome} esta a {alt:.1f} graus de altura, abaixo do limite de "
                          f"{self.cfg.alt_minima:g} graus (config alt_minima)")
        alt_m, _ = self.apontador.angulos_montagem(alt, az)
        if not LIMITE_ALT_MONTAGEM[0] <= alt_m <= LIMITE_ALT_MONTAGEM[1]:
            raise ErroUso(f"fora do curso do eixo de altitude: seriam {alt_m:.1f} graus na montagem")

    def _ir(self, alvo):
        """GoTo em duas passadas: a 2a corrige o quanto o ceu girou durante a 1a."""
        if not self.modelo.pronto:
            raise ErroUso("sem alinhamento: centralize uma estrela e use 'alinhar <estrela>'")
        for passada in (1, 2):
            alt, az = self.ceu.altaz(alvo, self.relogio())
            self._checar_limites(alvo, alt, az)
            atual = self.ard.posicao()
            destino = self.apontador.passos_para(alt, az, atual[0])
            distancia = max(abs(destino[0] - atual[0]), abs(destino[1] - atual[1]))
            if distancia == 0:
                break
            t = tempo_estimado(distancia, self.cfg.velocidade_max, self.cfg.aceleracao)
            if passada == 1:
                self.escrever(f"Indo para {alvo.nome}: alt {alt:.2f} az {az:.2f} ({cardinal(az)}), "
                              f"{distancia} passos, ~{t:.0f} s. {self.dica_parar}")
            self.ard.exigir(f"GOTO AZ {destino[0]}")
            self.ard.exigir(f"GOTO ALT {destino[1]}")
            resultado = esperar_chegada(self.ard, destino, timeout=2 * t + 5,
                                        deve_parar=self.tecla_apertada)
            if resultado == INTERROMPIDO:
                raise ErroUso("movimento interrompido")
            if resultado != CHEGOU:
                raise ErroUso("os motores nao chegaram no tempo esperado: motor travado, "
                              "passos perdidos ou velocidade/aceleracao configuradas erradas")
        self.escrever(f"No alvo: {alvo.nome}.")

    def cmd_ir(self, resto):
        self._ir(self._resolver(resto))

    def cmd_seguir(self, resto):
        alvo = self._resolver(resto)
        self._ir(alvo)
        apontador, ceu, cfg = self.apontador, self.ceu, self.cfg
        alt_atual = [0.0]

        def alvo_em_passos(unix, passos_az):
            alt, az = ceu.altaz(alvo, unix)
            if alt < cfg.alt_minima:
                raise ErroUso(f"{alvo.nome} desceu abaixo de {cfg.alt_minima:g} graus: rastreamento parado")
            alt_atual[0] = alt
            return apontador.passos_para(alt, az, passos_az)

        def mostrar(info):
            erro = max(abs(info["erro_az"]) / cfg.passos_por_grau_az,
                       abs(info["erro_alt"]) / cfg.passos_por_grau_alt) * 3600
            extra = "  ! velocidade no limite" if info["saturado"] else ""
            if alt_atual[0] > 85:
                extra += "  ! perto do zenite"
            self._status(f"Rastreando {alvo.nome}: alt {alt_atual[0]:5.1f}  erro {erro:5.0f}\"  "
                         f"vel AZ {info['rate_az']:7.2f} ALT {info['rate_alt']:7.2f} passos/s{extra}")

        self.escrever(f"Rastreando. {self.dica_parar}")
        Rastreador(self.ard, alvo_em_passos, periodo=cfg.periodo_rastreio,
                   vel_max=cfg.velocidade_max, relogio=self.relogio).rodar(
            deve_parar=self.tecla_apertada, ao_ciclo=mostrar)
        self.escrever("\nRastreamento parado.")

    def cmd_onde(self, _):
        paz, palt = self.ard.posicao()
        alt_m, az_m = self.conv.para_graus(paz, palt)
        self.escrever(f"Passos AZ {paz}  ALT {palt}  |  montagem alt {alt_m:.2f} az {az_m % 360:.2f}")
        if not self.modelo.pronto:
            self.escrever("(sem alinhamento: nao sei para onde isso aponta no ceu)")
            return
        agora = self.relogio()
        alt, az = self.apontador.apontando_para(paz, palt)
        ra, dec = self.ceu.radec(alt, az, agora)
        self.escrever(f"Apontando: alt {alt:.2f} az {az:.2f} ({cardinal(az)})  |  "
                      f"RA {formatar_ra(ra)}  Dec {formatar_dec(dec)}")
        perto = min(((separacao(alt, az, *self.ceu.altaz(self.ceu.resolver(n), agora)), n)
                     for n in ESTRELAS))
        if perto[0] < 5:
            self.escrever(f"Estrela da lista mais proxima: {perto[1]} ({perto[0]:.2f} graus)")

    def cmd_parar(self, _):
        self.ard.exigir("STOP")
        self.escrever("Parado.")


def main():
    endereco = sys.argv[1] if len(sys.argv) > 1 else escolher_porta()
    cfg = Config.carregar()
    try:
        ard = Arduino(endereco)
    except (ArduinoErro, serial.SerialException, OSError) as erro:
        print(f"Nao consegui conectar em {endereco}: {erro}")
        if endereco.startswith("socket://"):
            print("O simulador esta rodando? (py simulador.py em outro terminal)")
        sys.exit(1)

    app = App(ard, cfg)
    print("Conectado. Digite 'ajuda' para os comandos.")
    app.avisos()
    try:
        while True:
            try:
                linha = input("\ntelescopio> ")
            except EOFError:
                break
            if not app.executar(linha):
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            ard.exigir("STOP")
        except ArduinoErro:
            pass
        ard.fechar()
        print("\nEncerrado.")


if __name__ == "__main__":
    main()
