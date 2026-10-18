#!/usr/bin/env python3
"""
Tela de controle do telescopio (janela do Windows, feita com tkinter).

A tela nao tem logica propria de astronomia ou alinhamento: ela chama os mesmos
comandos do telescopio.py (App.executar), que ja tem testes.

Uso:
  py tela.py                          -> escolhe a porta na propria janela
  py tela.py COM5                     -> conecta direto
  py tela.py socket://127.0.0.1:7777  -> simulador (py simulador.py)

Concorrencia: o tkinter roda num laco de eventos de UMA thread. Se ela
esperasse o Bluetooth ou um GoTo de 30 s, a janela congelaria (e o botao Parar
junto). Por isso:
  - operacoes longas (ir, seguir, alinhar) rodam numa thread de trabalho;
  - comandos curtos (mover, velocidade) vao para uma fila com thread propria;
  - a posicao e lida por outra thread a cada 0,5 s;
  - tudo volta para a janela por uma fila lida a cada 100 ms (root.after);
  - PARAR nao entra em fila: manda STOP na hora e avisa a operacao em curso.

Desenho: o centro e um radar do ceu (voce no centro, que e o zenite; horizonte
na borda; Norte em cima e Leste a DIREITA, como uma bussola vista de cima)
cercado por um anel graduado em latao, como os circulos graduados das
montagens. Mapas celestes impressos poem o Leste a esquerda porque sao feitos
para segurar acima da cabeca; aqui a escolha foi a vista de bussola. Cor com significado: latao = o instrumento (reticula, acoes);
azul = o ceu (alvo, estrelas); vermelho = so o PARAR.
"""

import math
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import serial
import serial.tools.list_ports

import localizacao
from arduino import SIMULADOR, Arduino, ArduinoErro
from astro import ESTRELAS, formatar_dec, formatar_ra
from config import ARQUIVO, Config
from montagem import angulos, vetor
from telescopio import App, cardinal

PLANETAS_TELA = ["Lua", "Mercúrio", "Vênus", "Marte", "Júpiter", "Saturno", "Urano", "Netuno"]
ESTRELAS_TELA = sorted(n.title() for n in ESTRELAS)

PALETAS = {
    "padrao": dict(
        tinta="#0E1420", painel="#141B29", linha="#26324A", texto="#DCE1EA", fraco="#7D889D",
        latao="#C9A45C", latao_hover="#D9B873", latao_texto="#1A1408", reticula="#D9B873",
        rigel="#8DB6F5", sinal="#E0574F", sinal_hover="#EC6D66", sinal_texto="#FFFFFF",
        botao="#1D2537", botao_hover="#283350", ok="#6CC08B", aviso="#E8A33D",
        ceu="#0A0F18", grade="#1C2638", entrada="#0B1019"),
    # Noturno: so vermelho e com pouco brilho. A visao adaptada ao escuro
    # (bastonetes da retina) e pouco sensivel ao vermelho; luz branca ou azul a
    # desfaz e ela leva de 20 a 30 minutos para voltar.
    "noturno": dict(
        tinta="#000000", painel="#070101", linha="#2A0707", texto="#C2332B", fraco="#6E1A15",
        latao="#3A0B08", latao_hover="#4A0F0A", latao_texto="#D2392E", reticula="#C2332B",
        rigel="#8E241B", sinal="#6A100B", sinal_hover="#7E140E", sinal_texto="#FF5246",
        botao="#140202", botao_hover="#220404", ok="#9A2A20", aviso="#B83024",
        ceu="#030000", grade="#1C0404", entrada="#030000"),
}

# Bahnschrift (estilo DIN, de placa de instrumento) nos rotulos; Segoe UI no
# texto; Cascadia Mono nas leituras, para os digitos nao "dancarem" ao mudar.
F_MARCA = ("Bahnschrift SemiBold", 15)
F_ROTULO = ("Bahnschrift SemiBold SemiCondensed", 10)
F_TEXTO = ("Segoe UI Variable Text", 10)
F_TEXTO_FORTE = ("Segoe UI Variable Text Semibold", 11)
F_BOTAO = ("Bahnschrift SemiBold", 11)
F_SETA = ("Segoe UI Symbol", 15)
F_LEITURA = ("Cascadia Mono", 18)
F_LEITURA_M = ("Cascadia Mono", 13)
F_DADO = ("Cascadia Mono", 9)
F_CANVAS = ("Bahnschrift SemiCondensed", 8)
F_CARDINAL = ("Bahnschrift SemiBold", 13)

SECOES_CONFIG = [
    ("LOCAL", [
        ("latitude", "Latitude", float, "graus; sul é negativo"),
        ("longitude", "Longitude", float, "graus; oeste é negativo"),
        ("altitude_m", "Altitude", float, "metros"),
        ("temperatura_c", "Temperatura", float, "°C, usada na refração"),
    ]),
    ("MECÂNICA", [
        ("reducao_az", "Redução do azimute", float, "voltas do motor por volta do eixo"),
        ("reducao_alt", "Redução da altitude", float, "voltas do motor por volta do eixo"),
        ("microstep", "Microstep", int, "jumpers do DRV8825 (16 = 1/16)"),
        ("passos_por_volta", "Passos por volta", int, "200 = motor de 1,8°"),
        ("inverter_az", "Inverter azimute", bool, "se o ▶ gira para o lado errado"),
        ("inverter_alt", "Inverter altitude", bool, "se o ▲ desce o tubo"),
    ]),
    ("LIMITES E VELOCIDADE", [
        ("alt_minima", "Altura mínima", float, "graus acima do horizonte"),
        ("velocidade_max", "Velocidade máxima", float, "passos/s"),
        ("aceleracao", "Aceleração", float, "passos/s²"),
        ("periodo_rastreio", "Ciclo do rastreamento", float, "segundos"),
    ]),
]

CAMPOS_TEXTO = (tk.Entry, ttk.Entry, ttk.Combobox, tk.Text)
SEM_ALINHAMENTO = "Sem alinhamento. Centralize uma estrela na ocular, escolha o nome e clique em Alinhar."


class Tela:
    def __init__(self, root, endereco_inicial=None, cfg=None, caminho_config=ARQUIVO):
        self.root = root
        self.caminho_config = caminho_config
        self.cfg = cfg if cfg is not None else Config.carregar(caminho_config)
        self.ard = None
        self.app = None
        self.tema = "padrao"
        self.P = PALETAS[self.tema]
        self._pinturas = []                # (widget, {opcao: chave da paleta})
        self._combos = []
        self._fila = queue.Queue()         # threads -> janela
        self._cmds = queue.Queue()         # comandos curtos -> Arduino
        self._parar = threading.Event()    # pedido de parada da operacao longa
        self._ocupado = False
        self._jog = {"AZ": 0, "ALT": 0}
        self._soltura = {"AZ": None, "ALT": None}   # "soltou a tecla" agendado (ver _tecla)
        self._alvo_texto = ""              # copia do campo Alvo, legivel por outras threads
        self._fechando = False
        # o que o planisferio desenha
        self._estrelas_ceu = []            # [(nome, alt, az)]
        self._alinhadas = []               # [(nome, alt, az)]
        self._telescopio = None            # (alt, az) pelo alinhamento: preciso
        self._estimado = None              # (alt, az) sem alinhamento: supoe zero apontando ao Norte
        self._marca_alvo = None            # (nome, alt, az)

        root.title("Telescópio Dobsoniano")
        escala = root.winfo_fpixels("1i") / 96.0      # 1,0 em 100%; 1,5 em 150%
        # nunca maior que a tela (em 150%, 800 px viram 1200 e passam de um Full HD)
        largura = min(int(1180 * escala), root.winfo_screenwidth() - 40)
        altura = min(int(800 * escala), root.winfo_screenheight() - 80)
        root.geometry(f"{largura}x{altura}+20+10")
        root.minsize(min(int(1040 * escala), largura), min(int(680 * escala), altura))
        self._estilo = ttk.Style(root)
        self._estilo.theme_use("clam")     # o tema padrao do Windows ignora cores
        self._montar()
        self._aplicar_tema()

        threading.Thread(target=self._laco_comandos, daemon=True).start()
        threading.Thread(target=self._laco_posicao, daemon=True).start()
        self._agendado = root.after(100, self._processar_fila)
        root.protocol("WM_DELETE_WINDOW", self._fechar)
        root.bind("<FocusOut>", self._perdeu_foco)
        for tecla, eixo, d in (("Left", "AZ", -1), ("Right", "AZ", 1),
                               ("Up", "ALT", 1), ("Down", "ALT", -1)):
            root.bind(f"<KeyPress-{tecla}>", lambda e, a=eixo, s=d: self._tecla(e, a, s, True))
            root.bind(f"<KeyRelease-{tecla}>", lambda e, a=eixo, s=d: self._tecla(e, a, s, False))
        root.bind("<Escape>", lambda e: self.parar())
        root.bind("<space>", self._espaco)

        self._habilitar(False)
        if endereco_inicial:
            self.var_porta.set(endereco_inicial)
            self.conectar()

    # =============== pecas da interface ===============
    def _pinta(self, widget, **mapa):
        """Registra quais cores da paleta o widget usa (para trocar o tema)."""
        self._pinturas.append((widget, mapa))
        return widget

    def _hover(self, botao, normal, realce):
        def entra(_):
            if str(botao["state"]) != "disabled":
                botao.config(bg=self.P[realce])
        botao.bind("<Enter>", entra, add="+")
        botao.bind("<Leave>", lambda _: botao.config(bg=self.P[normal]), add="+")

    def _botao(self, pai, texto, comando=None, tipo="neutro", fonte=F_BOTAO, **kw):
        cores = {"neutro": ("botao", "botao_hover", "texto"),
                 "latao": ("latao", "latao_hover", "latao_texto"),
                 "sinal": ("sinal", "sinal_hover", "sinal_texto")}[tipo]
        opcoes = dict(relief="flat", bd=0, padx=14, pady=7, cursor="hand2", highlightthickness=1)
        opcoes.update(kw)               # quem chama pode trocar o padrao (ex.: pady)
        b = tk.Button(pai, text=texto, command=comando, font=fonte, **opcoes)
        self._pinta(b, bg=cores[0], fg=cores[2], activebackground=cores[1],
                    activeforeground=cores[2], disabledforeground="fraco",
                    highlightbackground="painel", highlightcolor="latao")
        self._hover(b, cores[0], cores[1])
        return b

    def _rotulo(self, pai, texto="", cor="texto", fonte=F_TEXTO, fundo="painel", **kw):
        opcoes = dict(anchor="w", justify="left")
        opcoes.update(kw)               # quem chama pode trocar o padrao (ex.: justify)
        r = tk.Label(pai, text=texto, font=fonte, **opcoes)
        return self._pinta(r, bg=fundo, fg=cor)

    def _quadro(self, pai, fundo="painel", **kw):
        return self._pinta(tk.Frame(pai, **kw), bg=fundo)

    def _cartao(self, pai, titulo):
        """Painel com borda fina e rotulo em versalete. Devolve (cartao, corpo, detalhe)."""
        cartao = self._quadro(pai, highlightthickness=1)
        self._pinta(cartao, highlightbackground="linha", highlightcolor="linha")
        cab = self._quadro(cartao)
        cab.pack(fill="x", padx=16, pady=(12, 0))
        self._rotulo(cab, titulo, "fraco", F_ROTULO).pack(side="left")
        detalhe = self._rotulo(cab, "", "fraco", F_DADO)
        detalhe.pack(side="right")
        corpo = self._quadro(cartao)
        corpo.pack(fill="both", expand=True, padx=16, pady=(8, 14))
        return cartao, corpo, detalhe

    def _combo(self, pai, var, valores, fonte=F_TEXTO, **kw):
        cb = ttk.Combobox(pai, textvariable=var, values=valores, font=fonte, **kw)
        self._combos.append(cb)
        return cb

    # =============== montagem ===============
    def _montar(self):
        r = self.root
        self._pinta(r, bg="tinta")
        r.columnconfigure(0, weight=1)
        r.rowconfigure(1, weight=1)

        # ---- barra superior ----
        topo = self._quadro(r, "tinta")
        topo.grid(row=0, column=0, sticky="ew", padx=20, pady=(14, 10))
        self._rotulo(topo, "Telescópio Dobsoniano", "texto", F_MARCA, "tinta").pack(side="left")

        self.bt_noite = self._botao(topo, "Modo noturno", self.alternar_tema, fonte=F_TEXTO)
        self.bt_noite.pack(side="right", padx=(8, 0))
        self.bt_config = self._botao(topo, "Configurações", self.abrir_config, fonte=F_TEXTO)
        self.bt_config.pack(side="right", padx=(8, 0))
        self.bt_conectar = self._botao(topo, "Conectar", self.conectar, fonte=F_TEXTO)
        self.bt_conectar.pack(side="right", padx=(8, 0))
        self.var_porta = tk.StringVar()
        self.cb_porta = self._combo(topo, self.var_porta, [], width=30)
        self.cb_porta.pack(side="right", ipady=3)
        self.cb_porta.bind("<Button-1>", lambda e: self._listar_portas())
        self._listar_portas()
        chip = self._quadro(topo, "tinta")
        chip.pack(side="right", padx=(0, 16))
        self.cv_conexao = self._pinta(tk.Canvas(chip, width=10, height=10, highlightthickness=0), bg="tinta")
        self.cv_conexao.pack(side="left", padx=(0, 6))
        self.lb_conexao = self._rotulo(chip, "Desconectado", "fraco", F_TEXTO, "tinta")
        self.lb_conexao.pack(side="left")

        # ---- corpo em 3 colunas ----
        corpo = self._quadro(r, "tinta")
        corpo.grid(row=1, column=0, sticky="nsew", padx=20)
        corpo.columnconfigure(1, weight=1)
        corpo.rowconfigure(0, weight=1)

        esquerda = self._quadro(corpo, "tinta")
        esquerda.grid(row=0, column=0, sticky="ns")
        centro = self._quadro(corpo, "tinta")
        centro.grid(row=0, column=1, sticky="nsew", padx=14)
        direita = self._quadro(corpo, "tinta")
        direita.grid(row=0, column=2, sticky="ns")

        self._montar_mover(esquerda).pack(fill="x")
        self._montar_alinhamento(esquerda).pack(fill="both", expand=True, pady=(14, 0))
        self._montar_ceu(centro).pack(fill="both", expand=True)
        self._montar_alvo(direita).pack(fill="x")
        self._montar_estado(direita).pack(fill="both", expand=True, pady=(14, 0))

        # ---- mensagens ----
        rodape = self._quadro(r, "tinta")
        rodape.grid(row=2, column=0, sticky="ew", padx=20, pady=(12, 14))
        cartao, miolo, _ = self._cartao(rodape, "MENSAGENS")
        cartao.pack(fill="x")
        self.txt_log = tk.Text(miolo, height=3, font=F_DADO, relief="flat", wrap="word",
                               padx=0, pady=0, state="disabled", bd=0, highlightthickness=0)
        self._pinta(self.txt_log, bg="painel", fg="texto", insertbackground="texto",
                    selectbackground="botao_hover")
        self.txt_log.pack(fill="x")

    def _montar_mover(self, pai):
        cartao, c, _ = self._cartao(pai, "MOVER")
        pad = self._quadro(c)
        pad.pack(pady=(0, 8))
        self.botoes_mover = []
        for texto, linha, coluna, eixo, d in (("▲", 0, 1, "ALT", 1), ("◀", 1, 0, "AZ", -1),
                                              ("▶", 1, 2, "AZ", 1), ("▼", 2, 1, "ALT", -1)):
            b = self._botao(pad, texto, fonte=F_SETA, width=4, pady=2)
            b.grid(row=linha, column=coluna, padx=2, pady=2)
            b.bind("<ButtonPress-1>", lambda e, a=eixo, s=d: self._mover(a, s), add="+")
            b.bind("<ButtonRelease-1>", lambda e, a=eixo: self._soltar(a), add="+")
            self.botoes_mover.append(b)
        self.bt_parar_pad = self._botao(pad, "PARAR", self.parar, "sinal", width=6)
        self.bt_parar_pad.grid(row=1, column=1, padx=2, pady=2, sticky="nsew")

        linha = self._quadro(c)
        linha.pack(fill="x")
        self._rotulo(linha, "Velocidade", "texto", F_TEXTO).pack(side="left")
        self.lb_vel = self._rotulo(linha, "600 passos/s", "fraco", F_DADO)
        self.lb_vel.pack(side="right")
        self.var_vel = tk.IntVar(value=600)
        self.sc_vel = ttk.Scale(c, from_=20, to=3000, orient="horizontal", style="Latao.Horizontal.TScale",
                                variable=self.var_vel, command=self._ao_mexer_velocidade)
        self.sc_vel.pack(fill="x", pady=(4, 6))
        self.sc_vel.bind("<ButtonRelease-1>", lambda e: self._enviar_velocidade())
        self._rotulo(c, "Segure para mover, solte para parar. Setas do teclado também.",
                     "fraco", F_TEXTO, wraplength=260).pack(fill="x")
        return cartao

    def _montar_alinhamento(self, pai):
        cartao, c, self.lb_n_alinhamento = self._cartao(pai, "ALINHAMENTO")
        self.bt_zero = self._botao(c, "Zerar (horizontal, Norte)", self.zerar)
        self.bt_zero.pack(fill="x", pady=(2, 10))
        linha = self._quadro(c)
        linha.pack(fill="x")
        self.var_estrela = tk.StringVar()
        self.cb_estrela = self._combo(linha, self.var_estrela, ESTRELAS_TELA, width=14)
        self.cb_estrela.pack(side="left", fill="x", expand=True, ipady=3)
        self.bt_visiveis = self._botao(linha, "Visíveis", self.atualizar_visiveis, fonte=F_TEXTO)
        self.bt_visiveis.pack(side="left", padx=(8, 0))
        linha2 = self._quadro(c)
        linha2.pack(fill="x", pady=(8, 10))
        self.bt_alinhar = self._botao(linha2, "Alinhar nesta estrela", self.alinhar, "latao")
        self.bt_alinhar.pack(side="left", fill="x", expand=True)
        self.bt_limpar = self._botao(linha2, "Limpar", self.limpar_alinhamento, fonte=F_TEXTO)
        self.bt_limpar.pack(side="left", padx=(8, 0))
        self.lb_alinhamento = self._rotulo(c, SEM_ALINHAMENTO, "texto", F_TEXTO, wraplength=260)
        self.lb_alinhamento.pack(fill="x")
        self.lb_qualidade = self._rotulo(c, "", "fraco", F_DADO, wraplength=260)
        self.lb_qualidade.pack(fill="x", pady=(2, 0))
        return cartao

    def _montar_ceu(self, pai):
        cartao, c, self.lb_local = self._cartao(pai, "CÉU AGORA")
        self.cv_ceu = self._pinta(tk.Canvas(c, highlightthickness=0, bd=0), bg="painel")
        self.cv_ceu.pack(fill="both", expand=True)
        self.cv_ceu.bind("<Configure>", self._ao_redimensionar_ceu)
        # avisos sobre o mapa ficam fora dele, para nao encavalar com os nomes das estrelas
        self.lb_aviso_ceu = self._rotulo(c, "", "fraco", F_TEXTO, wraplength=520, justify="center",
                                         anchor="center")
        self.lb_aviso_ceu.pack(fill="x", pady=(4, 0))

        leituras = self._quadro(c)
        leituras.pack(fill="x", pady=(10, 0))
        for i in range(3):
            leituras.columnconfigure(i, weight=1)
        self.lb_alt = self._leitura(leituras, 0, "ALTITUDE", largura=9)
        self.lb_az = self._leitura(leituras, 1, "AZIMUTE", largura=12)
        bloco = self._quadro(leituras)
        bloco.grid(row=0, column=2, sticky="w")
        self._rotulo(bloco, "COORDENADAS", "fraco", F_ROTULO).pack(anchor="w")
        self.lb_radec = self._rotulo(bloco, "RA  —\nDEC —", "texto", F_LEITURA_M)
        self.lb_radec.pack(anchor="w", pady=(2, 0))
        self.lb_passos = self._rotulo(c, "passos —", "fraco", F_DADO)
        self.lb_passos.pack(fill="x", pady=(8, 0))
        return cartao

    def _ao_redimensionar_ceu(self, evento):
        # o aviso abaixo do mapa quebra linha na largura do mapa, nao num valor fixo
        self.lb_aviso_ceu.config(wraplength=max(200, evento.width - 20))
        self._desenhar_ceu()

    def _leitura(self, pai, coluna, titulo, largura):
        bloco = self._quadro(pai)
        bloco.grid(row=0, column=coluna, sticky="w")
        self._rotulo(bloco, titulo, "fraco", F_ROTULO).pack(anchor="w")
        # largura fixa em caracteres (fonte de largura fixa): o numero nao empurra a coluna vizinha
        valor = self._rotulo(bloco, "—", "texto", F_LEITURA, width=largura)
        valor.pack(anchor="w")
        return valor

    def _montar_alvo(self, pai):
        cartao, c, _ = self._cartao(pai, "ALVO")
        self.var_alvo = tk.StringVar(value="Júpiter")
        self.var_alvo.trace_add("write", lambda *a: setattr(self, "_alvo_texto", self.var_alvo.get()))
        self._alvo_texto = self.var_alvo.get()
        self.cb_alvo = self._combo(c, self.var_alvo, PLANETAS_TELA + ESTRELAS_TELA,
                                   fonte=F_LEITURA_M, width=20)
        self.cb_alvo.pack(fill="x", ipady=4)
        self._rotulo(c, "Planeta, estrela da lista ou RA Dec J2000\ndo Stellarium (ex.: 05:35:17 -05:23:28)",
                     "fraco", F_TEXTO).pack(fill="x", pady=(4, 0))
        self.lb_alvo = self._rotulo(c, "—", "rigel", F_LEITURA_M)
        self.lb_alvo.pack(fill="x", pady=(12, 12))
        botoes = self._quadro(c)
        botoes.pack(fill="x")
        self.bt_ir = self._botao(botoes, "Apontar", lambda: self._operacao("ir"), "latao")
        self.bt_ir.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.bt_seguir = self._botao(botoes, "Seguir", lambda: self._operacao("seguir"), "latao")
        self.bt_seguir.pack(side="left", expand=True, fill="x", padx=(4, 0))
        self.bt_parar = self._botao(c, "PARAR", self.parar, "sinal", fonte=("Bahnschrift SemiBold", 14))
        self.bt_parar.pack(fill="x", pady=(8, 0), ipady=4)
        self._rotulo(c, "Esc ou espaço também param.", "fraco", F_TEXTO).pack(fill="x", pady=(4, 0))
        return cartao

    def _montar_estado(self, pai):
        cartao, c, _ = self._cartao(pai, "ESTADO")
        self.lb_estado = self._rotulo(c, "Parado", "texto", F_TEXTO_FORTE, wraplength=280)
        self.lb_estado.pack(fill="x", anchor="n")
        return cartao

    # =============== tema ===============
    def alternar_tema(self):
        self.tema = "noturno" if self.tema == "padrao" else "padrao"
        self.bt_noite.config(text="Modo normal" if self.tema == "noturno" else "Modo noturno")
        self._aplicar_tema()

    def _aplicar_tema(self):
        P = self.P = PALETAS[self.tema]
        for w, mapa in self._pinturas:
            try:
                w.config(**{opcao: P[chave] for opcao, chave in mapa.items()})
            except tk.TclError:
                pass
        s = self._estilo
        s.configure("TCombobox", fieldbackground=P["entrada"], background=P["botao"],
                    foreground=P["texto"], arrowcolor=P["texto"], bordercolor=P["linha"],
                    lightcolor=P["linha"], darkcolor=P["linha"], selectbackground=P["botao_hover"],
                    selectforeground=P["texto"], insertcolor=P["texto"], padding=4)
        s.map("TCombobox", fieldbackground=[("readonly", P["entrada"]), ("disabled", P["painel"])],
              foreground=[("disabled", P["fraco"])], bordercolor=[("focus", P["latao"])],
              lightcolor=[("focus", P["latao"])])
        s.configure("Latao.Horizontal.TScale", background=P["latao"], troughcolor=P["linha"],
                    bordercolor=P["painel"], lightcolor=P["latao"], darkcolor=P["latao"])
        s.map("Latao.Horizontal.TScale", background=[("active", P["latao_hover"])])
        self.root.option_add("*TCombobox*Listbox.background", P["entrada"])
        self.root.option_add("*TCombobox*Listbox.foreground", P["texto"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", P["botao_hover"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", P["texto"])
        self.root.option_add("*TCombobox*Listbox.font", F_TEXTO)
        for cb in self._combos:   # listas ja criadas nao leem o option_add
            try:
                popdown = cb.tk.call("ttk::combobox::PopdownWindow", cb)
                cb.tk.call(f"{popdown}.f.l", "configure", "-background", P["entrada"],
                           "-foreground", P["texto"], "-selectbackground", P["botao_hover"])
            except tk.TclError:
                pass
        self.txt_log.tag_config("aviso", foreground=P["aviso"])
        self._desenhar_conexao()
        self._desenhar_ceu()

    def _desenhar_conexao(self):
        cv = self.cv_conexao
        cv.delete("all")
        cor = self.P["ok"] if self.ard else self.P["fraco"]
        cv.create_oval(1, 1, 9, 9, fill=cor, outline="")

    # =============== planisferio ===============
    def _geometria_ceu(self):
        w, h = self.cv_ceu.winfo_width(), self.cv_ceu.winfo_height()
        raio = max(40, min(w, h) / 2 - 34)
        return w / 2, h / 2, raio

    def _polar(self, r, az):
        """Ponto a 'r' px do centro na direcao do azimute 'az'. Vista de mapa (como
        uma bussola vista de cima): Norte em cima, Leste a DIREITA. Este e o unico
        lugar que define a orientacao; anel, estrelas e ponteiros passam por aqui."""
        cx, cy, _ = self._geometria_ceu()
        a = math.radians(az)
        return cx + r * math.sin(a), cy - r * math.cos(a)

    def _projetar(self, alt, az):
        """Voce no centro: o zenite. Horizonte na borda; mais baixo = mais longe do centro."""
        _, _, raio = self._geometria_ceu()
        return self._polar(raio * (90.0 - alt) / 90.0, az)

    def _desenhar_ceu(self):
        cv, P = self.cv_ceu, self.P
        cv.delete("all")
        cx, cy, raio = self._geometria_ceu()

        # ceu e grade de altitude (30 e 60 graus) e linha da altura minima
        cv.create_oval(cx - raio, cy - raio, cx + raio, cy + raio, fill=P["ceu"], outline=P["linha"])
        for alt in (30, 60):
            r = raio * (90 - alt) / 90
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=P["grade"], dash=(2, 4))
            cv.create_text(cx + 4, cy - r - 2, text=f"{alt}°", anchor="sw", fill=P["fraco"], font=F_CANVAS)
        r = raio * (90 - self.cfg.alt_minima) / 90
        cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=P["aviso"], dash=(1, 5))
        cv.create_line(cx - raio, cy, cx + raio, cy, fill=P["grade"])
        cv.create_line(cx, cy - raio, cx, cy + raio, fill=P["grade"])

        # anel graduado de latao: traco a cada 5 graus, maior a cada 10, numero a cada 30
        for grau in range(0, 360, 5):
            tam = 11 if grau % 30 == 0 else (7 if grau % 10 == 0 else 4)
            x1, y1 = self._polar(raio + 2, grau)
            x2, y2 = self._polar(raio + 2 + tam, grau)
            cv.create_line(x1, y1, x2, y2, fill=P["latao"], width=2 if grau % 30 == 0 else 1)
            if grau % 90 == 0:
                letra = {0: "N", 90: "L", 180: "S", 270: "O"}[grau]
                cv.create_text(*self._polar(raio + 24, grau), text=letra, fill=P["latao"],
                               font=F_CARDINAL)
            elif grau % 30 == 0:
                cv.create_text(*self._polar(raio + 22, grau), text=str(grau), fill=P["fraco"],
                               font=F_CANVAS)

        avisos = []
        if self.cfg.local_definido:
            # estrelas visiveis (azul = ceu); as usadas no alinhamento ganham anel de latao
            alinhadas = {n for n, _, _ in self._alinhadas}
            for nome, alt, az in self._estrelas_ceu:
                x, y = self._projetar(alt, az)
                cv.create_oval(x - 2.5, y - 2.5, x + 2.5, y + 2.5, fill=P["rigel"], outline="")
                if nome in alinhadas:
                    cv.create_oval(x - 7, y - 7, x + 7, y + 7, outline=P["latao"], width=1)
                cv.create_text(x + 6, y - 5, text=nome.title(), anchor="w", fill=P["fraco"], font=F_CANVAS)

            # alvo: linha pontilhada discreta desde o centro (voce) e anel azul
            if self._marca_alvo and self._marca_alvo[1] >= 0:
                nome, alt, az = self._marca_alvo
                x, y = self._projetar(alt, az)
                self._linha_do_centro(x, y, 10, P["rigel"], largura=1, traco=(1, 4))
                cv.create_oval(x - 10, y - 10, x + 10, y + 10, outline=P["rigel"], width=2)
                cv.create_text(x + 14, y + 10, text=nome, anchor="w", fill=P["rigel"], font=F_TEXTO)
        else:
            avisos.append("Defina o local em Configurações para ver as estrelas.")

        # telescopio: reticula de latao. Solida = pelo alinhamento (precisa);
        # tracejada = estimada pelos angulos da montagem (supoe zero ao Norte).
        if self._telescopio:
            self._reticula(*self._telescopio, tracejada=False)
        elif self._estimado:
            self._reticula(*self._estimado, tracejada=True)
            avisos.append("Mira tracejada = posição estimada, supondo que o Zerar foi feito com "
                          "o tubo apontando para o Norte. Alinhe uma estrela para precisão.")
        mira = self._telescopio or self._estimado
        if mira and mira[0] < 0:
            avisos.insert(0, f"Tubo abaixo do horizonte ({mira[0]:.0f}°): a mira fica na borda.")
        self.lb_aviso_ceu.config(text="  ".join(avisos))

    def _linha_do_centro(self, x, y, folga, cor, largura, traco):
        """Linha do centro (o observador) ate (x, y), parando 'folga' px antes."""
        cx, cy, _ = self._geometria_ceu()
        dist = math.hypot(x - cx, y - cy)
        if dist <= folga:
            return                                   # alvo praticamente no zenite
        k = (dist - folga) / dist
        self.cv_ceu.create_line(cx, cy, cx + (x - cx) * k, cy + (y - cy) * k, fill=cor,
                                width=largura, dash=traco)

    def _reticula(self, alt, az, tracejada):
        cv, P = self.cv_ceu, self.P
        cx, cy, raio = self._geometria_ceu()
        x, y = self._projetar(max(alt, -4), az)      # abaixo do horizonte: fica na borda
        cor = P["reticula"]
        traco = (4, 3) if tracejada else None
        # ponteiro do radar: do observador (centro) ate a mira. A direcao e o
        # azimute; o comprimento cresce quanto mais baixo o tubo aponta.
        self._linha_do_centro(x, y, 12, cor, largura=2, traco=traco)
        # indicador no anel graduado, como o de um circulo graduado de montagem
        ponta = self._polar(raio - 3, az)
        bx, by = self._polar(raio - 15, az)
        ux, uy = (bx - cx) / (raio - 15), (by - cy) / (raio - 15)   # direcao do raio
        lado = (-uy * 6, ux * 6)                                     # perpendicular a ela
        cv.create_polygon(ponta[0], ponta[1], bx + lado[0], by + lado[1], bx - lado[0], by - lado[1],
                          fill=cor if not tracejada else "", outline=cor, width=1)
        cv.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill=cor, outline="")   # voce
        cv.create_oval(x - 12, y - 12, x + 12, y + 12, outline=cor, width=2, dash=traco)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            cv.create_line(x + dx * 6, y + dy * 6, x + dx * 18, y + dy * 18, fill=cor, width=2,
                           dash=traco)

    # =============== conexao ===============
    def _listar_portas(self):
        portas = [f"{p.device}  ({p.description})" for p in serial.tools.list_ports.comports()]
        self.cb_porta["values"] = portas + [f"{SIMULADOR}  (simulador)"]
        if not self.var_porta.get() and self.cb_porta["values"]:
            self.var_porta.set(self.cb_porta["values"][0])

    def conectar(self):
        endereco = self.var_porta.get().split("  (")[0].strip()
        if not endereco:
            return
        if self.ard:
            self._desconectar()
        self.lb_conexao.config(text="Conectando...")
        self.bt_conectar.config(state="disabled")

        def tarefa():
            try:
                ard = Arduino(endereco)
                app = App(ard, self.cfg, caminho_config=self.caminho_config,
                          escrever=lambda t: self._post("log", t),
                          tecla_apertada=self._parar.is_set)
                # a linha de status do rastreamento vai para o painel, nao para o log
                app._status = lambda t: self._post("estado", t)
                app.dica_parar = "Clique em PARAR para interromper."
                self._post("conectado", (endereco, ard, app))
            except (ArduinoErro, serial.SerialException, OSError) as erro:
                self._post("falha_conexao", f"Não foi possível conectar em {endereco}: {erro}")

        threading.Thread(target=tarefa, daemon=True).start()

    def _desconectar(self):
        ard, self.ard, self.app = self.ard, None, None
        if ard:
            try:
                ard.exigir("STOP")
            except Exception:
                pass
            ard.fechar()
        self._telescopio = None
        self._habilitar(False)
        self.lb_conexao.config(text="Desconectado")
        self._desenhar_conexao()

    def _habilitar(self, sim):
        estado = "normal" if sim else "disabled"
        for w in (self.bt_ir, self.bt_seguir, self.bt_zero, self.bt_alinhar, self.bt_limpar,
                  self.bt_visiveis, *self.botoes_mover):
            w.config(state=estado)
        # PARAR fica sempre habilitado se conectado
        self.bt_parar.config(state="normal" if self.ard else "disabled")
        self.bt_parar_pad.config(state="normal" if self.ard else "disabled")

    def _ocupar(self, sim):
        """Durante ir/seguir, so PARAR funciona (mover a mao brigaria com o rastreamento)."""
        self._ocupado = sim
        estado = "disabled" if sim else "normal"
        for w in (self.bt_ir, self.bt_seguir, self.bt_zero, self.bt_alinhar, self.bt_limpar,
                  *self.botoes_mover):
            w.config(state=estado)
            if sim:
                w.config(bg=self.P["latao" if w in (self.bt_ir, self.bt_seguir, self.bt_alinhar)
                                   else "botao"])

    # =============== comunicacao entre threads ===============
    def _post(self, tipo, dado=None):
        self._fila.put((tipo, dado))

    def _processar_fila(self):
        try:
            while True:
                tipo, dado = self._fila.get_nowait()
                getattr(self, f"_ao_{tipo}")(dado)
        except queue.Empty:
            pass
        if not self._fechando:
            self._agendado = self.root.after(100, self._processar_fila)

    def _ao_log(self, texto):
        texto = texto.strip("\n")
        if not texto:
            return
        aviso = texto.startswith("!")
        if aviso:
            texto = texto[1:].strip()
        self.txt_log.config(state="normal")
        self.txt_log.insert("end", f"{time.strftime('%H:%M:%S')}  {texto}\n", ("aviso",) if aviso else ())
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")

    def _ao_estado(self, texto):
        self.lb_estado.config(text=texto)

    def _ao_conectado(self, dado):
        endereco, self.ard, self.app = dado
        nome = "simulador" if endereco.startswith("socket://") else endereco
        self.lb_conexao.config(text=f"Conectado · {nome}")
        self.bt_conectar.config(state="normal", text="Reconectar")
        self._desenhar_conexao()
        self._habilitar(True)
        self._enviar_velocidade()
        self._ao_log("Conectado.")
        self.app.avisos()
        self._atualizar_alinhamento()
        self._atualizar_local()
        if self.cfg.local_definido:
            self.atualizar_visiveis()

    def _ao_falha_conexao(self, texto):
        self.bt_conectar.config(state="normal")
        self.lb_conexao.config(text="Desconectado")
        self._ao_log("! " + texto)

    def _ao_fim(self, _):
        self._ocupar(False)
        self.lb_estado.config(text="Parado")
        self._atualizar_alinhamento()
        self._atualizar_local()

    def _ao_posicao(self, info):
        paz, palt, alt_m, az_m = info["passos"]
        self.lb_passos.config(text=f"passos AZ {paz} · ALT {palt}   ·   montagem alt {alt_m:.2f}° "
                                   f"az {az_m % 360:.2f}°")
        self._estimado = info.get("estimado")
        if info.get("ceu"):
            alt, az, ra, dec = info["ceu"]
            self._telescopio = (alt, az)
            self.lb_alt.config(text=f"{alt:6.2f}°", fg=self.P["texto"])
            self.lb_az.config(text=f"{az:6.2f}° {cardinal(az)}", fg=self.P["texto"])
            self.lb_radec.config(text=f"RA  {formatar_ra(ra)}\nDEC {formatar_dec(dec)}")
        elif self._estimado:
            # estimativa: em cinza e com "≈", para nao parecer medida precisa
            self._telescopio = None
            alt, az = self._estimado
            self.lb_alt.config(text=f"≈{alt:6.2f}°", fg=self.P["fraco"])
            self.lb_az.config(text=f"≈{az:6.2f}° {cardinal(az)}", fg=self.P["fraco"])
            self.lb_radec.config(text="RA  —\nDEC —")
        else:
            self._telescopio = None
            self.lb_alt.config(text="—", fg=self.P["texto"])
            self.lb_az.config(text="—", fg=self.P["texto"])
            self.lb_radec.config(text="RA  —\nDEC —")
        alvo = info.get("alvo")
        if isinstance(alvo, str):
            self.lb_alvo.config(text=alvo)
            self._marca_alvo = None
        elif alvo is not None:
            alt, az = alvo
            situacao = "" if alt >= self.cfg.alt_minima else "\nabaixo do limite de altura"
            self.lb_alvo.config(text=f"alt {alt:6.2f}°   az {az:6.2f}° {cardinal(az)}{situacao}")
            self._marca_alvo = (self._alvo_texto.strip(), alt, az)
        self._alinhadas = info.get("alinhadas", [])
        if "estrelas" in info:
            self._estrelas_ceu = info["estrelas"]
        self._desenhar_ceu()

    def _ao_reiniciou(self, _):
        if self.app:
            self.app.executar("")    # o App detecta o READY e apaga o alinhamento
            self._atualizar_alinhamento()

    def _ao_visiveis(self, nomes):
        if nomes:
            self.cb_estrela["values"] = nomes
            if self.var_estrela.get() not in nomes:
                self.var_estrela.set(nomes[0])
            self._ao_log(f"Estrelas visíveis agora, da mais alta para a mais baixa: {', '.join(nomes)}")
        else:
            self._ao_log("! Nenhuma estrela da lista está acima da altura mínima agora.")

    def _ao_chamar(self, funcao):
        funcao()

    # =============== threads de fundo ===============
    def _laco_comandos(self):
        while not self._fechando:
            try:
                comando = self._cmds.get(timeout=0.2)
            except queue.Empty:
                continue
            ard = self.ard
            if not ard:
                continue
            try:
                resposta = ard.enviar(comando)
                if resposta.startswith("ERR"):
                    self._post("log", f"! {comando} -> {resposta}")
            except ArduinoErro as erro:
                self._post("log", f"! Arduino: {erro}")

    def _laco_posicao(self):
        ultima_lista = 0.0
        while not self._fechando:
            time.sleep(0.5)
            app, ard = self.app, self.ard
            if not app or not ard:
                continue
            try:
                if ard.reiniciou:
                    self._post("reiniciou")
                paz, palt = ard.posicao()
                alt_m, az_m = app.conv.para_graus(paz, palt)
                info = {"passos": (paz, palt, alt_m, az_m)}
                if not app.modelo.pronto:
                    # Sem alinhamento, os angulos da montagem sao a melhor estimativa:
                    # a altitude vale desde o Zerar (tubo na horizontal); o azimute so
                    # vale se o Zerar foi feito com o tubo apontando para o Norte.
                    # Nao depende do local: alt/az do tubo e geometria local.
                    # Passa pelo vetor de direcao: um tubo girado alem da vertical
                    # (alt > 90 ou < -90) aponta para o azimute oposto, e
                    # angulos(vetor(...)) devolve a direcao real.
                    info["estimado"] = angulos(vetor(alt_m, az_m))
                agora = time.time()
                if self.cfg.local_definido:
                    ceu = app.ceu
                    if app.modelo.pronto:
                        alt, az = app.apontador.apontando_para(paz, palt)
                        info["ceu"] = (alt, az, *ceu.radec(alt, az, agora))
                        info["alinhadas"] = [(p[0], *ceu.altaz(ceu.resolver(p[0]), agora))
                                             for p in app.modelo.pontos if p[0] in ESTRELAS]
                    texto = self._alvo_texto.strip()
                    if texto:
                        try:
                            info["alvo"] = ceu.altaz(ceu.resolver(texto), agora)
                        except ValueError:
                            info["alvo"] = "alvo desconhecido"
                    if agora - ultima_lista > 30:      # o ceu gira 0,125° em 30 s
                        info["estrelas"] = ceu.estrelas_visiveis(0, agora)
                        ultima_lista = agora
                else:
                    info["alvo"] = "Defina o local em Configurações"
                self._post("posicao", info)
            except (ArduinoErro, OSError):
                pass   # desconectou ou fechando; a proxima volta tenta de novo
            except Exception as erro:          # nao deixa a thread morrer em silencio
                self._post("log", f"! Erro ao ler a posição: {erro}")

    # =============== acoes ===============
    def _mover(self, eixo, sentido):
        if not self.ard or self._ocupado:
            return
        if self._jog[eixo] != sentido:
            self._jog[eixo] = sentido
            self._cmds.put(f"JOG {eixo} {sentido}")

    def _soltar(self, eixo):
        if self._jog[eixo] != 0:
            self._jog[eixo] = 0
            self._cmds.put(f"JOG {eixo} 0")

    def _tecla(self, evento, eixo, sentido, apertou):
        if isinstance(evento.widget, CAMPOS_TEXTO):
            return     # setas editando texto nao movem o telescopio
        # Segurar a tecla gera repeticao automatica. Conforme o sistema, ela vem
        # como KeyPress repetido ou como pares Release+Press. Para os pares nao
        # virarem "para-anda-para-anda", o "soltou" so vale se nenhuma nova
        # pressao chegar em 80 ms.
        if self._soltura[eixo]:
            self.root.after_cancel(self._soltura[eixo])
            self._soltura[eixo] = None
        if apertou:
            self._mover(eixo, sentido)   # mesmo sentido de novo: nao reenvia
        else:
            self._soltura[eixo] = self.root.after(80, lambda: self._soltar_tecla(eixo))

    def _soltar_tecla(self, eixo):
        self._soltura[eixo] = None
        self._soltar(eixo)

    def _espaco(self, evento):
        if not isinstance(evento.widget, CAMPOS_TEXTO):
            self.parar()

    def _perdeu_foco(self, _evento):
        # <FocusOut> chega no widget que tinha o foco (via bindtags), nao na
        # janela; entao confere, logo depois, se a aplicacao inteira perdeu o foco.
        self.root.after(50, self._conferir_foco)

    def _conferir_foco(self):
        try:
            tem_foco = self.root.focus_get() is not None
        except (KeyError, tk.TclError):    # popup do combobox aberto
            tem_foco = True
        if not tem_foco:
            self._soltar("AZ")
            self._soltar("ALT")

    def _ao_mexer_velocidade(self, valor):
        v = int(round(float(valor) / 10) * 10)
        self.var_vel.set(v)
        self.lb_vel.config(text=f"{v} passos/s")

    def _enviar_velocidade(self):
        self._cmds.put(f"JOGSPEED {self.var_vel.get()}")

    def parar(self):
        self._parar.set()
        self._jog = {"AZ": 0, "ALT": 0}
        ard = self.ard
        if ard:
            # fora da fila: nao espera comandos pendentes
            threading.Thread(target=lambda: self._seguro(ard.exigir, "STOP"), daemon=True).start()
        # com operacao em curso, o "Parado" vem quando ela terminar (_ao_fim)
        self.lb_estado.config(text="Parando..." if self._ocupado else "Parado")

    def _seguro(self, funcao, *args):
        try:
            funcao(*args)
        except ArduinoErro as erro:
            self._post("log", f"! Arduino: {erro}")

    def _em_fundo(self, linha, estado):
        """Roda um comando do App numa thread, sem travar a janela."""
        if not self.app:
            return
        if self._ocupado:
            self._ao_log("! Aguarde a operação atual ou clique em PARAR.")
            return
        self._parar.clear()
        self._ocupar(True)
        self.lb_estado.config(text=estado)
        app = self.app

        def tarefa():
            try:
                app.executar(linha)
            except Exception as erro:
                self._post("log", f"! Erro inesperado: {erro}")
            finally:
                self._post("fim")

        threading.Thread(target=tarefa, daemon=True).start()

    def _operacao(self, verbo):
        alvo = self.var_alvo.get().strip()
        if not alvo:
            self._ao_log("! Escolha um alvo.")
            return
        estado = f"Apontando para {alvo}..." if verbo == "ir" else f"Apontando para {alvo}; depois segue."
        self._em_fundo(f"{verbo} {alvo}", estado)

    def zerar(self):
        if messagebox.askyesno("Zerar posição",
                               "O tubo está na horizontal?\n\n"
                               "A altitude passa a ser contada a partir daqui, e o alinhamento atual "
                               "será apagado.\n\n"
                               "Dica: se o tubo também estiver apontando para o Norte (bússola ou "
                               "celular, aproximado), o mapa já mostra para onde ele aponta antes do "
                               "alinhamento.", parent=self.root):
            self._em_fundo("zero", "Zerando...")

    def alinhar(self):
        estrela = self.var_estrela.get().strip()
        if not estrela:
            self._ao_log("! Escolha a estrela que está centralizada na ocular.")
            return
        self._em_fundo(f"alinhar {estrela}", f"Registrando {estrela}...")

    def limpar_alinhamento(self):
        if self.app:
            self.app.executar("limpar")
            self._atualizar_alinhamento()

    def atualizar_visiveis(self):
        app = self.app
        if not app:
            return
        if not self.cfg.local_definido:
            self._ao_log("! Defina o local em Configurações.")
            return

        def tarefa():
            try:
                lista = app.ceu.estrelas_visiveis(self.cfg.alt_minima)
                self._post("visiveis", [n.title() for n, _, _ in lista])
            except Exception as erro:
                self._post("log", f"! {erro}")

        threading.Thread(target=tarefa, daemon=True).start()

    def _atualizar_alinhamento(self):
        if not self.app or not self.app.modelo.pronto:
            self.lb_alinhamento.config(text=SEM_ALINHAMENTO)
            self.lb_qualidade.config(text="")
            self.lb_n_alinhamento.config(text="")
            return
        m = self.app.modelo
        n = len(m.pontos)
        nomes = ", ".join(p[0].title() for p in m.pontos)
        self.lb_n_alinhamento.config(text=f"{n} {'estrela' if n == 1 else 'estrelas'}")
        if n == 1:
            self.lb_alinhamento.config(text=f"1 ponto: {nomes}")
            self.lb_qualidade.config(text="supõe a base nivelada: alinhe uma 2ª estrela "
                                          "a 60–120° desta", fg=self.P["aviso"])
            return
        residuo = max(e for _, e in m.residuos()) * 60
        pior = max(abs(r - 1) for _, _, r in m.erro_de_escala()) * 100
        self.lb_alinhamento.config(text=f"{n} pontos: {nomes}")
        if pior <= 2:
            self.lb_qualidade.config(text=f"resíduo máx {residuo:.1f}'  ·  escala ok", fg=self.P["ok"])
        else:
            self.lb_qualidade.config(text=f"resíduo máx {residuo:.1f}'  ·  escala {pior:.1f}% fora: "
                                          f"reveja a redução", fg=self.P["aviso"])

    def _atualizar_local(self):
        if self.cfg.local_definido:
            lat, lon = self.cfg.latitude, self.cfg.longitude
            self.lb_local.config(text=f"{abs(lat):.2f}°{'S' if lat < 0 else 'N'}  "
                                      f"{abs(lon):.2f}°{'O' if lon < 0 else 'L'}")
        else:
            self.lb_local.config(text="local não definido")
        self._desenhar_ceu()

    # =============== configuracoes ===============
    def abrir_config(self):
        P = self.P
        jan = tk.Toplevel(self.root, bg=P["painel"], padx=24, pady=18)
        jan.title("Configurações")
        jan.transient(self.root)
        jan.grab_set()
        jan.resizable(False, False)
        variaveis = {}
        linha = 0

        def rotulo(texto, cor, fonte, **grid):
            tk.Label(jan, text=texto, font=fonte, bg=P["painel"], fg=P[cor], anchor="w",
                     justify="left").grid(sticky="w", **grid)

        for secao, campos in SECOES_CONFIG:
            rotulo(secao, "fraco", F_ROTULO, row=linha, column=0, columnspan=3, pady=(14 if linha else 0, 6))
            linha += 1
            if secao == "LOCAL":
                botao = tk.Button(jan, text="Usar minha localização do Windows", font=F_TEXTO,
                                  bg=P["botao"], fg=P["texto"], activebackground=P["botao_hover"],
                                  activeforeground=P["texto"], relief="flat", bd=0, padx=12, pady=5,
                                  cursor="hand2")
                botao.grid(row=linha, column=0, columnspan=2, sticky="w", pady=(0, 4))
                status = tk.Label(jan, text="", font=F_TEXTO, bg=P["painel"], fg=P["fraco"],
                                  anchor="w", justify="left", wraplength=420)
                status.grid(row=linha + 1, column=0, columnspan=3, sticky="w", pady=(0, 6))
                botao.config(command=lambda b=botao, s=status: self._usar_localizacao(variaveis, b, s))
                linha += 2
            for campo, nome, tipo, dica in campos:
                rotulo(nome, "texto", F_TEXTO, row=linha, column=0, pady=3)
                valor = getattr(self.cfg, campo)
                if tipo is bool:
                    var = tk.BooleanVar(value=bool(valor))
                    tk.Checkbutton(jan, variable=var, bg=P["painel"], activebackground=P["painel"],
                                   selectcolor=P["entrada"], fg=P["texto"], bd=0,
                                   highlightthickness=0).grid(row=linha, column=1, sticky="w", padx=(16, 0))
                else:
                    var = tk.StringVar(value="" if valor is None else f"{valor:g}" if isinstance(valor, float) else str(valor))
                    tk.Entry(jan, textvariable=var, font=F_LEITURA_M, width=11, bg=P["entrada"],
                             fg=P["texto"], insertbackground=P["texto"], relief="flat",
                             highlightthickness=1, highlightbackground=P["linha"],
                             highlightcolor=P["latao"]).grid(row=linha, column=1, sticky="w", padx=(16, 0), ipady=3)
                rotulo(dica, "fraco", F_TEXTO, row=linha, column=2, padx=(12, 0))
                variaveis[campo] = (var, tipo)
                linha += 1

        def salvar():
            try:
                self._salvar_config(variaveis)
            except (ValueError, KeyError) as erro:
                messagebox.showerror("Configurações", f"Valor inválido: {erro}", parent=jan)
                return
            jan.destroy()
            self._atualizar_alinhamento()
            self._atualizar_local()
            if self.app and self.cfg.local_definido:
                self.atualizar_visiveis()

        botoes = tk.Frame(jan, bg=P["painel"])
        botoes.grid(row=linha, column=0, columnspan=3, sticky="e", pady=(18, 0))
        tk.Button(botoes, text="Cancelar", command=jan.destroy, font=F_BOTAO, bg=P["botao"],
                  fg=P["texto"], activebackground=P["botao_hover"], relief="flat", bd=0,
                  padx=16, pady=6, cursor="hand2").pack(side="left", padx=(0, 8))
        tk.Button(botoes, text="Salvar", command=salvar, font=F_BOTAO, bg=P["latao"],
                  fg=P["latao_texto"], activebackground=P["latao_hover"], relief="flat", bd=0,
                  padx=20, pady=6, cursor="hand2").pack(side="left")

    def _usar_localizacao(self, variaveis, botao, status):
        botao.config(state="disabled")
        status.config(text="Perguntando ao Windows... (pode levar alguns segundos)", fg=self.P["fraco"])

        def tarefa():
            try:
                pos = localizacao.obter()
            except localizacao.LocalizacaoErro as erro:
                self._post("chamar", lambda: self._localizacao_falhou(botao, status, str(erro)))
                return
            self._post("chamar", lambda: self._localizacao_ok(variaveis, botao, status, pos))

        threading.Thread(target=tarefa, daemon=True).start()

    def _localizacao_ok(self, variaveis, botao, status, pos):
        if not status.winfo_exists():
            return                       # a janela de configuracoes ja foi fechada
        botao.config(state="normal")
        variaveis["latitude"][0].set(f"{pos.latitude:.4f}")
        variaveis["longitude"][0].set(f"{pos.longitude:.4f}")
        if pos.altitude_m is not None:
            variaveis["altitude_m"][0].set(f"{pos.altitude_m:.0f}")
            extra = ""
        else:
            extra = " A altitude não veio com precisão; ajuste à mão se quiser (pesa pouco)."
        status.config(fg=self.P["ok"],
                      text=f"Posição recebida do Windows, {localizacao.descrever_precisao(pos.precisao_m)}. "
                           f"Clique em Salvar para usar.{extra}")

    def _localizacao_falhou(self, botao, status, motivo):
        if not status.winfo_exists():
            return
        botao.config(state="normal")
        status.config(text=f"Não foi possível obter a localização: {motivo}", fg=self.P["aviso"])

    def _salvar_config(self, variaveis):
        novos = {}
        for campo, (var, tipo) in variaveis.items():
            atual = getattr(self.cfg, campo)
            if tipo is bool:
                novo = var.get()
            else:
                texto = var.get().strip().replace(",", ".")
                if texto == "":
                    if atual is None:
                        continue
                    raise ValueError(f"{campo} vazio")
                novo = tipo(float(texto)) if tipo is int else tipo(texto)
            if novo != atual:
                novos[campo] = novo

        lat = novos.pop("latitude", self.cfg.latitude)
        lon = novos.pop("longitude", self.cfg.longitude)
        alt = novos.pop("altitude_m", self.cfg.altitude_m)
        mudou_local = (lat, lon, alt) != (self.cfg.latitude, self.cfg.longitude, self.cfg.altitude_m)
        if mudou_local:
            if lat is None or lon is None:
                raise ValueError("preencha latitude e longitude")
            self._aplicar(f"local {lat} {lon} {alt}")
        for campo, valor in novos.items():
            texto = ("sim" if valor else "nao") if isinstance(valor, bool) else str(valor)
            self._aplicar(f"config {campo} {texto}")

    def _aplicar(self, linha):
        if self.app:
            self.app.executar(linha)       # salva e trata efeitos (alinhamento, SPEED...)
            return
        partes = linha.split()
        if partes[0] == "local":
            self.cfg.latitude, self.cfg.longitude = float(partes[1]), float(partes[2])
            self.cfg.altitude_m = float(partes[3])
        else:
            self.cfg.alterar(partes[1], partes[2])
        self.cfg.salvar(self.caminho_config)
        self._ao_log(f"{linha} (salvo)")

    # =============== saida ===============
    def _fechar(self):
        self._fechando = True
        self._parar.set()
        self._desconectar()
        # cancela o que esta agendado; senao o Tk tenta rodar depois de destruido
        for agendado in (self._agendado, *self._soltura.values()):
            if agendado:
                self.root.after_cancel(agendado)
        self.root.destroy()


def nitidez_em_telas_com_escala():
    """Sem isto, com o Windows em 125%/150% o sistema amplia a janela como
    imagem e o texto fica borrado. E o que o IDLE do Python tambem faz."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # ciente do DPI do monitor
    except (AttributeError, OSError):
        pass                                             # nao e Windows 8.1+


def main():
    nitidez_em_telas_com_escala()
    root = tk.Tk()
    Tela(root, sys.argv[1] if len(sys.argv) > 1 else None)
    root.mainloop()


if __name__ == "__main__":
    main()
