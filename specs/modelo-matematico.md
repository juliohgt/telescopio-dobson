# Modelo matemático

## Convenções

- **Azimute:** 0 = Norte, 90 = Leste, 180 = Sul, 270 = Oeste (a do skyfield).
- **Altitude:** 0 = horizonte, 90 = zênite.
- **Vetor de direção:** `vetor(alt, az) = (cos alt · cos az, cos alt · sin az, sin alt)`
  no referencial (Norte, Leste, Cima). `angulos(v)` faz o caminho inverso, com o
  azimute em [0, 360).
- **Montagem:** AZ positivo = Norte→Leste (horário visto de cima); ALT positivo sobe o tubo.

## Do céu à altitude/azimute (`astro.py`)

`Ceu.altaz(alvo, t)` usa o skyfield: observador = Terra (efeméride de421) + local
(WGS84) → `observe(alvo).apparent().altaz(...)`. Isso inclui precessão, nutação,
aberração e paralaxe (relevante para a Lua).

- **Refração:** o skyfield **só a aplica se a temperatura for informada**
  (`temperature_C`); sem isso, perto do horizonte o erro chega a ~0,5°. O código
  passa a temperatura da configuração e `pressure_mbar='standard'`
  (1010 × e^(−altitude/9100) mbar).
- **Inverso** (`Ceu.radec`, para o "para onde estou apontando"): primeiro desfaz a
  refração com `alt_real = alt_aparente − refraction(alt_aparente)`. A função
  `refraction()` do skyfield recebe a altitude aparente, como o `refract()` dele a
  usa, então é uma subtração direta. Sem isso, a 1° de altura a volta errava ~20′.
- **Estrelas:** coordenadas ICRS/J2000 digitadas à mão a partir de catálogos baseados
  no Hipparcos; o movimento próprio foi ignorado (pior caso: Alfa Centauri, ~1,6′ desde 2000).
- **Hora:** relógio do Windows. Ver "Erros de local e de relógio" abaixo.

Conferência física usada nos testes: a altura do polo celeste é igual à latitude.
Deu 23,68° para latitude −23,55°; a diferença de 0,13° é a precessão do polo desde 2000.

## Passos ↔ ângulos da montagem (`montagem.Conversor`)

```
passos_por_grau = passos_por_volta × microstep × redução / 360
alt_m = sinal_alt × passos_alt / ppg_alt
az_m  = sinal_az  × passos_az  / ppg_az        (acumulado: pode passar de 360)
```

O **Zerar** define a origem: altitude 0 com o tubo na horizontal. O azimute 0 é
arbitrário; se o Zerar for feito com o tubo apontando para o Norte, os ângulos da
montagem já são uma estimativa da direção no céu (a tela mostra a mira tracejada).

**Caminho mais curto no azimute:** `delta = ((alvo − atual + 180) mod 360) − 180`.
Ex.: atual 350°, alvo 10° → anda +20°, não −340°.

## Alinhamento (`montagem.ModeloAlinhamento`)

A relação entre o referencial da **montagem** e o do **céu** (alt/az verdadeiros) é
**fixa no tempo**, porque a montagem não se move em relação ao chão. Por isso estrelas
medidas em instantes diferentes podem ser combinadas.

- **1 estrela:** deslocamento simples, `Δalt = alt_m − alt_céu` e `Δaz = az_m − az_céu`.
  Supõe a base nivelada. Com a base desnivelada, erra longe do ponto alinhado (o teste
  com 3° de desnível mostra erro > 1°).
- **2 ou mais estrelas:** rotação 3D `R` que minimiza `Σ |R·mᵢ − sᵢ|²` (m = vetor da
  montagem, s = vetor do céu): o **algoritmo de Kabsch**.
  ```
  H = Mᵀ S          (M e S: um vetor por linha)
  U, Σ, Vᵀ = svd(H)
  d = sinal(det(V Uᵀ))
  R = V · diag(1, 1, d) · Uᵀ
  ```
  O `d` garante uma rotação própria (sem espelhamento). A rotação absorve o Norte
  desconhecido e a base desnivelada. Ela **não** corrige escala (redução errada) nem
  eixos não perpendiculares.
- **Separação mínima:** estrelas a menos de 15° uma da outra são recusadas (rotação
  mal definida); o ideal é 60–120°.
- **Resíduo:** ângulo entre `R·mᵢ` e `sᵢ` de cada ponto. Com 3 estrelas e ruído de
  0,05°, o teste aponta uma 4ª direção com erro < 0,15°.

### Erro de escala (diagnóstico de redução errada)

Rotação preserva ângulos. Então, para cada par de estrelas,
`razão = separação medida pela montagem / separação real` deveria ser 1. Se passar de
**2%** (`TOLERANCIA_ESCALA`), a redução ou o microstep configurados estão errados:
razão > 1 = redução configurada **menor** que a real; razão < 1 = **maior**.

Isso **detecta**, mas não **calcula** o valor certo: na esfera, errar a escala dos
eixos por um fator k não multiplica a separação por k (no teste, k = 2 deu razão
1,39). Para corrigir, meça a redução no eixo (ver [hardware.md](hardware.md)).

### Erros de local e de relógio

Errar o local por alguns km, ou o relógio por um valor constante, equivale a girar
todo o céu calculado de forma **rígida e constante** em relação ao céu real. Como o
alinhamento com 2+ estrelas é justamente uma rotação, ele absorve esse erro. A
consequência prática: a coordenada da cidade basta, e a precisão de 200 m a 20 km
do serviço de localização do Windows é suficiente. Com 1 estrela, o deslocamento não
absorve esse erro por completo.

## Rastreamento (`rastreio.Rastreador`)

A cada ciclo de período P (1 s):

```
pos   = POS?                                   (realimentação)
alvo  = passos_para(altaz(objeto, t + P))      (antecipação)
RATE  = limitar((alvo − pos) / P, velocidade_max)
```

O eixo chega onde o objeto **vai estar** no fim do ciclo. Atraso, latência do Bluetooth
e arredondamento de passos viram erro medido no ciclo seguinte, que é corrigido. Em
montagem alt-az as duas velocidades mudam o tempo todo, por isso são recalculadas a cada ciclo.

Por que por velocidade e não com um GOTO por ciclo: GOTO repetido faria o motor partir,
frear e parar a cada segundo, aos trancos; por velocidade, os passos saem espaçados por igual.

**Limites físicos (não do software):**
- **Zênite:** a velocidade de azimute necessária cresce sem limite perto do zênite;
  ela é limitada a `velocidade_max`, e o erro cresce até o objeto se afastar.
- **Rotação de campo:** a imagem gira durante o rastreamento. Não importa na
  observação visual; borra a foto de longa exposição.

## GoTo em duas passadas

Um GOTO longo pode levar dezenas de segundos, e o céu gira 15″/s. A segunda passada
recalcula o alvo e corrige o deslocamento.

## Tubo além da vertical

Com `alt_m` fora de [−90°, 90°] (possível no simulador; impossível numa Dobsoniana
real), o tubo aponta para o azimute oposto. A tela usa `angulos(vetor(alt_m, az_m))`,
que devolve a direção real.
