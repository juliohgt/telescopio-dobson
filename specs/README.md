# Especificações

Documentação técnica do controlador. O [README da raiz](../README.md) explica como
usar; aqui está o **porquê** de cada decisão e os detalhes para quem vai montar,
testar ou mudar o projeto.

| Documento | Conteúdo | Leia quando for... |
|---|---|---|
| [requisitos.md](requisitos.md) | objetivo, escopo, requisitos e premissas | entender o que o sistema promete e o que não promete |
| [hardware.md](hardware.md) | lista de materiais, ligações, alimentação, Vref, mecânica | montar ou alterar a parte elétrica e mecânica |
| [firmware.md](firmware.md) | papel do Arduino e protocolo serial completo | mexer no `.ino`, no simulador ou na comunicação |
| [arquitetura.md](arquitetura.md) | módulos Python, fluxo de dados, threads da tela | mexer no código do PC |
| [modelo-matematico.md](modelo-matematico.md) | convenções, coordenadas, alinhamento, rastreamento | mexer em cálculo, alinhamento ou GoTo |
| [interface.md](interface.md) | tela de controle e app de texto | mexer na interface |
| [testes.md](testes.md) | testes automatizados e roteiro de teste no hardware | validar o projeto, no PC ou no telescópio |
| [pendencias.md](pendencias.md) | limitações conhecidas e próximos passos | planejar a próxima melhoria |

## Situação em uma frase

O software (firmware, cálculo, alinhamento, GoTo, rastreamento e tela) está pronto
e testado **contra um simulador**; **nada foi testado no hardware real**.
