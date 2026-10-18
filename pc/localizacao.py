"""
Localizacao pelo servico de localizacao do Windows.

Usa a API GeoCoordinateWatcher do .NET Framework (System.Device), que ja vem
no Windows, chamada pelo Windows PowerShell. Nao instala nada e nao usa
servico de terceiros: quem estima a posicao e o proprio Windows (GPS se houver,
senao redes Wi-Fi proximas, senao a rede/IP; a precisao varia de metros a
dezenas de km e e informada).

Exige: Configuracoes > Privacidade e seguranca > Localizacao ligada, com
"Permitir que aplicativos da area de trabalho acessem sua localizacao".

Precisao necessaria: pouca. Um erro de localizacao gira o ceu calculado de
forma rigida e constante, e o alinhamento com 2 estrelas (uma rotacao)
absorve esse erro. A coordenada da cidade ja basta.
"""

import subprocess
import sys
from dataclasses import dataclass

_SCRIPT = r"""
Add-Type -AssemblyName System.Device
$w = New-Object System.Device.Location.GeoCoordinateWatcher([System.Device.Location.GeoPositionAccuracy]::High)
[void]$w.TryStart($false, [TimeSpan]::FromSeconds(10))
$fim = (Get-Date).AddSeconds(__ESPERA__)
while ($w.Position.Location.IsUnknown -and (Get-Date) -lt $fim -and $w.Permission -ne 'Denied') {
    Start-Sleep -Milliseconds 250
}
$l = $w.Position.Location
$c = [Globalization.CultureInfo]::InvariantCulture
if ($w.Permission -eq 'Denied') { 'ERRO;negada' }
elseif ($l.IsUnknown) { 'ERRO;' + $w.Status }
else { 'OK;' + $l.Latitude.ToString($c) + ';' + $l.Longitude.ToString($c) + ';' +
       $l.Altitude.ToString($c) + ';' + $l.HorizontalAccuracy.ToString($c) + ';' +
       $l.VerticalAccuracy.ToString($c) }
$w.Stop()
"""

# Acima disso a altitude informada nao e confiavel (posicao por rede/IP).
PRECISAO_VERTICAL_MAXIMA_M = 100.0


class LocalizacaoErro(Exception):
    pass


@dataclass
class Posicao:
    latitude: float
    longitude: float
    altitude_m: float | None      # None quando o Windows nao informa com precisao
    precisao_m: float             # raio estimado do erro horizontal


def _numero(texto):
    try:
        valor = float(texto)
    except ValueError:
        return None
    return None if valor != valor else valor      # NaN -> None


def obter(espera_s=12):
    """Pergunta ao Windows onde estamos. Pode levar alguns segundos."""
    if sys.platform != "win32":
        raise LocalizacaoErro("a localizacao automatica so funciona no Windows")
    script = _SCRIPT.replace("__ESPERA__", str(int(espera_s)))
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=espera_s + 20,
            # sem isto, uma janela de console pisca na tela (e pode roubar o foco)
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as erro:
        raise LocalizacaoErro(f"nao consegui consultar o Windows: {erro}") from None

    linha = next((l for l in r.stdout.splitlines() if l.startswith(("OK;", "ERRO;"))), None)
    if linha is None:
        raise LocalizacaoErro(f"resposta inesperada do Windows: {(r.stderr or r.stdout).strip()[:200]}")
    partes = linha.split(";")
    if partes[0] == "ERRO":
        motivo = partes[1]
        if motivo == "negada":
            raise LocalizacaoErro(
                "o Windows negou acesso a localizacao. Ative em Configuracoes > Privacidade e "
                "seguranca > Localizacao, inclusive 'Permitir que aplicativos da area de trabalho "
                "acessem sua localizacao'.")
        if motivo == "Disabled":
            raise LocalizacaoErro("o servico de localizacao do Windows esta desligado.")
        raise LocalizacaoErro(
            f"o Windows nao conseguiu estimar a posicao (estado: {motivo}). Sem Wi-Fi ou rede "
            f"isso e comum; digite a latitude e a longitude.")

    lat, lon, alt, prec_h, prec_v = (_numero(p) for p in partes[1:6])
    if lat is None or lon is None:
        raise LocalizacaoErro("o Windows devolveu uma posicao invalida")
    if prec_v is None or prec_v > PRECISAO_VERTICAL_MAXIMA_M:
        alt = None
    return Posicao(lat, lon, alt, prec_h if prec_h is not None else float("nan"))


def descrever_precisao(metros):
    if metros != metros:
        return "precisão desconhecida"
    if metros >= 1000:
        return f"precisão de ~{metros / 1000:.0f} km"
    return f"precisão de ~{metros:.0f} m"
