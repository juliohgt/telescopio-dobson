# Pendências e próximos passos

## Não verificado

| Item | Situação |
|---|---|
| **Hardware real** | nada foi testado no telescópio. Seguir o [roteiro em testes.md](testes.md#roteiro-do-primeiro-teste-no-hardware) |
| **Coordenadas das estrelas** (`astro.ESTRELAS`) | digitadas à mão a partir de catálogos; os testes provam a coerência do código, não cada coordenada. Conferir no Stellarium as que forem usadas |
| **Testes da tela com o layout atual** | os 6 testes opcionais passaram no layout anterior e não foram rodados de novo |
| **Modo noturno** | conferido só sem janela (as cores trocam); não foi revisado visualmente |
| **Teclado do modo manual no terminal** | lido com `msvcrt`; não testado dentro de terminais embutidos (ex.: o do VS Code) |
| **ATmega168** | o firmware compila (91% da flash), mas sobram só 316 bytes de RAM para a pilha. Se a placa reiniciar sozinha, o caminho é tirar o canal USB do firmware (os buffers da `Serial` liberam ~200 bytes) e usar só o Bluetooth |
| **Windows 10** | a tela usa as fontes Bahnschrift e Cascadia Mono; sem a Cascadia (vem com o Windows Terminal), o Tk usa outra fonte. Só visual, não testado |

## Limitações conhecidas

- **Sem limite de altitude no movimento manual:** GoTo e rastreamento recusam alvos
  fora do curso, mas os botões de mover deixam o tubo passar do horizonte. Numa
  Dobsoniana real o tubo bate no batente e o motor força ou perde passos.
  **Próximo passo recomendado.**
- **Malha aberta:** sem encoders, a posição vem da contagem de passos; se a
  transmissão patinar ou o motor perder passos, o erro passa despercebido.
- **Sem limite de voltas no azimute:** o caminho curto pode acumular voltas e enrolar cabos.
- **Alinhamento não é salvo:** fechar o programa ou reiniciar o Arduino exige alinhar
  de novo. É intencional (a posição em malha aberta não sobrevive a um reinício), mas
  poderia ser salvo se o Arduino não reiniciar.
- **Erro de escala detecta, não corrige:** a redução certa precisa ser medida no eixo.
- **Rotação de campo:** inerente à montagem alt-az; inviabiliza foto de longa exposição.

## Próximos passos possíveis

| Ideia | Ganho | Custo |
|---|---|---|
| Limite de altitude no movimento manual | protege a mecânica | pequeno |
| Encoders nos eixos | imune a passos perdidos e escorregamento | hardware + firmware |
| Driver ASCOM em C#/.NET | Stellarium, N.I.N.A. e Cartes du Ciel comandam o telescópio | médio |
| Protocolo LX200 no PC (servidor TCP) | SkySafari e Stellarium sem ASCOM | médio |
| Módulo GPS (ex.: NEO-6M) | local e hora exatos no campo, sem internet | pequeno + fiação |
| Catálogo maior (Messier, NGC) | mais alvos por nome | pequeno |
| Salvar o alinhamento | não realinhar se só o PC reiniciou | pequeno |
