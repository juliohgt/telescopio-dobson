# Interface

Duas formas de usar, com os mesmos comandos por baixo (`telescopio.App`):

- **Tela de controle** (`pc/tela.py`): janela do Windows com botões e mapa do céu.
- **App de texto** (`pc/telescopio.py`): comandos digitados no terminal.

## Tela de controle

```
┌──────────────────────────────────────────────────────────────────────┐
│ Telescópio Dobsoniano    ● Conectado · COM5  [porta▾] [Conectar] ... │
├─────────────┬──────────────────────────────────────┬─────────────────┤
│ MOVER       │ CÉU AGORA                            │ ALVO            │
│  ▲ ◀ ■ ▶ ▼  │        radar com anel graduado       │ [Júpiter    ▾]  │
│ velocidade  │                                      │ alt / az        │
├─────────────┤ ALTITUDE   AZIMUTE    COORDENADAS    │ [Apontar][Seguir]│
│ ALINHAMENTO │                                      │ [    PARAR    ] │
│ Zerar       │ passos · ângulos da montagem         ├─────────────────┤
│ estrela ▾   │                                      │ ESTADO          │
├─────────────┴──────────────────────────────────────┴─────────────────┤
│ MENSAGENS                                                            │
└──────────────────────────────────────────────────────────────────────┘
```

### Radar do céu
- **Você está no centro**, que é o zênite; a borda é o horizonte. Quanto mais longe
  do centro, mais baixo no céu.
- Orientação de **bússola vista de cima**: Norte em cima, **Leste à direita**. Mapas
  celestes impressos põem o Leste à esquerda porque são feitos para segurar acima da
  cabeça; aqui a escolha foi a vista de bússola. A orientação é definida num único
  lugar, `Tela._polar()`.
- **Anel graduado em latão**: traço a cada 5°, número a cada 30°, pontos cardeais (N, L, S, O).
- **Mira**: linha de latão do centro (você) até a mira, mais um triângulo no anel
  marcando o azimute.
  - **sólida** = posição pelo alinhamento (precisa);
  - **tracejada**, com leituras "≈" em cinza = estimativa pelos ângulos da montagem,
    supondo que o Zerar foi feito com o tubo apontando para o Norte. Aparece mesmo
    sem local definido (alt/az do tubo é geometria local).
- **Estrelas** da lista em azul (exigem o local definido); as usadas no alinhamento
  ganham um anel de latão.
- **Alvo**: anel azul, com linha pontilhada desde o centro.
- **Linha tracejada amarela**: altura mínima.
- Avisos (local não definido, mira estimada, tubo abaixo do horizonte) ficam **abaixo**
  do mapa, para não se misturarem com os nomes das estrelas.

### Cores com significado

| Cor | Significa |
|---|---|
| Latão `#C9A45C` | o instrumento: mira, ponteiro, botões de ação |
| Azul `#8DB6F5` | o céu: estrelas, alvo |
| Vermelho `#E0574F` | só o PARAR |
| Fundo azul-tinta `#0E1420` | noite, sem preto puro |

**Modo noturno:** a mesma estrutura, toda em vermelho com pouco brilho. A visão
adaptada ao escuro (bastonetes da retina) é pouco sensível ao vermelho; luz branca ou
azul a desfaz, e ela leva de 20 a 30 minutos para voltar.

**Tipografia:** Bahnschrift (estilo DIN, de placa de instrumento) nos rótulos; Segoe
UI Variable no texto; Cascadia Mono nas leituras (dígitos de largura fixa não
"dançam" quando o número muda).

### Comportamentos de segurança
- **Segurar para mover:** solta o botão (ou a tecla), o eixo para. A repetição
  automática do teclado é filtrada: o "soltou" só vale se nenhuma nova pressão chegar
  em 80 ms.
- **A janela perdeu o foco** com um botão pressionado → os dois eixos param.
- **Durante Apontar/Seguir**, só o PARAR fica ativo: mover à mão brigaria com o rastreamento.
- **PARAR, Esc ou espaço** param tudo; o PARAR não espera fila.
- O **Zerar** pede confirmação (apaga o alinhamento).
- A janela nunca é maior que a tela (em 150% de escala, 800 px virariam 1200).

### Configurações
Local (com **Usar minha localização do Windows**), mecânica (redução, microstep,
passos por volta, inversão de sentido) e limites (altura mínima, velocidade,
aceleração, ciclo do rastreamento). Mudar a mecânica ou o local apaga o alinhamento,
porque a conversão passos↔graus ou o céu calculado mudam.

## App de texto (`telescopio.py`)

```
local <lat> <lon> [altitude_m]   config [campo valor]   zero   manual
estrelas   ver <alvo>   alinhar <alvo>   alinhamento   limpar
ir <alvo>   seguir <alvo>   onde   parar   ajuda   sair
```

`<alvo>`: estrela da lista, `lua`, planeta (`marte`, `jupiter`...) ou `RA Dec` J2000
(ex.: `05:35:17 -05:23:28`). Aceita vírgula decimal (`-23,55`).

## Textos

Mensagens dizem o que fazer, não só o que houve: "Sem alinhamento. Centralize uma
estrela na ocular, escolha o nome e clique em Alinhar." Erros explicam a causa e a
correção (ex.: separação medida diferente da real → reveja a redução).
