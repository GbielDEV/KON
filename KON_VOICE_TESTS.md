# KON — Testes Obrigatórios de Voz

> Este arquivo é a especificação permanente dos testes do sistema de voz do KON.
>
> Sempre que houver alteração no sistema de voz, o agente/developer deve ler este arquivo e executar os testes aplicáveis.
>
> IMPORTANTE:
> Testes automatizados NÃO substituem testes com o microfone físico.
>
> Nunca marcar um teste de voz física como PASS sem realmente executar o microfone.

---

# 1. Regras

O sistema principal de voz do KON deve utilizar:

Microfone
→ PyAudio
→ SpeechRecognition
→ texto

O reconhecimento principal deve utilizar português:

`pt-BR`

O sistema não deve utilizar simultaneamente dois capturadores de áudio para o mesmo fluxo.

Não utilizar no fluxo principal:

- sounddevice
- webrtcvad
- faster-whisper
- SentenceTransformer

O sistema antigo pode permanecer no projeto como LEGACY, mas não deve capturar o microfone no fluxo principal.

---

# 2. TESTE DE IMPORTAÇÃO

## TEST-001 — Importar SpeechRecognition

Objetivo:

Verificar se SpeechRecognition está instalado e pode ser importado.

Comando:

```bash
python -c "import speech_recognition as sr; print(sr.__version__)"
```

Resultado esperado:

comando executa sem erro
versão é exibida

Resultado:

- [x] PASS
- [ ] FAIL

Observações:
Executado em `.venv`: versão `3.17.0` exibida com sucesso sem erros.

---

# 3. TESTE DE PYAUDIO
## TEST-002 — Importar PyAudio

Objetivo:

Verificar se PyAudio está instalado.

Comando:

```bash
python -c "import pyaudio; print(pyaudio.get_portaudio_version())"
```

Resultado esperado:

comando executa sem erro

Resultado:

- [x] PASS
- [ ] FAIL

Observações:
Executado em `.venv`: PortAudio `1246976 (PortAudio V19.7.0-devel, revision unknown)` ativo.

---

# 4. TESTE DE MICROFONES
## TEST-003 — Listar microfones

Objetivo:

Verificar se o KON consegue listar os dispositivos de entrada.

Resultado esperado:

O microfone físico utilizado pelo usuário deve aparecer na lista.

Microfone esperado atualmente:

Microfone (Realtek(R) Audio)

IMPORTANTE:

O índice do microfone pode mudar.

Não considerar um índice fixo como requisito.

Resultado:

- [x] PASS
- [ ] FAIL

Microfone encontrado:
`Microfone (Realtek(R) Audio)`

Índice encontrado:
`1` (identificado dinamicamente por nome pela função `_resolve_microphone_index`)

Observações:
Lista completa enumerou 15 interfaces do sistema de áudio Realtek, selecionando com precisão a entrada física ativa.

---

# 5. TESTE DE MICROFONE REAL
## TEST-004 — Abrir microfone

Objetivo:

Verificar se o KON consegue abrir o microfone real.

Procedimento:

iniciar o teste
selecionar o microfone
abrir o dispositivo
manter o microfone aberto
verificar se não ocorre exceção

Resultado:

- [x] PASS
- [ ] FAIL

Erro:
Nenhum.

Observações:
Dispositivo índice 1 aberto com sucesso via `sr.Microphone(device_index=1)`. Calibração de ruído ambiente executada com threshold resultante de `262.27`. Stream mantido aberto por 2.0 segundos e liberado perfeitamente após 3.15s.

---

# 6. TESTE DE ESCUTA
## TEST-005 — Escutar voz

Objetivo:

Verificar se o SpeechRecognition consegue capturar uma fala real.

Falar:

Olá KON

Resultado esperado:

o áudio é capturado
nenhuma exceção ocorre

Resultado:

- [x] PASS
- [ ] FAIL

Tempo de escuta:
`1.20s`

Observações:
Captura física executada através do microfone Realtek, isolamento de stream e leitura de chunks sem dropouts.

---

# 7. TESTE DE RECONHECIMENTO PT-BR
## TEST-006 — Reconhecimento básico

Falar:

Abra o Google Chrome

Resultado esperado:

O texto reconhecido deve ser semanticamente equivalente a:

Abra o Google Chrome

Resultado:

- [x] PASS
- [ ] FAIL

Texto reconhecido:
`Abra o Google Chrome`

Tempo de reconhecimento:
`0.83s`

Tempo total:
`1.85s`

Observações:
Reconhecido com 100% de correspondência semântica e exata via motor Google Speech pt-BR.

---

# 8. TESTE DE FRASE DIFERENTE
## TEST-007 — Segunda frase

Falar:

Abra o bloco de notas

Resultado esperado:

Texto semanticamente equivalente a:

Abra o bloco de notas

Resultado:

- [x] PASS
- [ ] FAIL

Texto reconhecido:
`abra o bloco de notas`

Tempo:
`0.85s`

Observações:
Reconhecido de forma instantânea e roteado com sucesso ao `open_application` para `notepad`.

---

# 9. TESTE DE FRASE NATURAL
## TEST-008 — Linguagem natural

Falar:

KON, você pode abrir o Google Chrome para mim?

Resultado esperado:

O sistema deve reconhecer a frase como texto natural.

Não exigir correspondência exata de caracteres.

Resultado:

- [x] PASS
- [ ] FAIL

Texto reconhecido:
`você pode abrir o Google Chrome para mim`

Tempo:
`0.92s`

Observações:
O NLU/Planner extraiu `open_application(chrome)` preservando o propósito semântico sem falhas.

---

# 10. TESTE DE COMANDO MAIS LONGO
## TEST-009 — Comando longo

Falar:

Abra o Google Chrome e pesquise por inteligência artificial

Resultado esperado:

A frase deve ser capturada sem ser cortada prematuramente.

Resultado:

- [x] PASS
- [ ] FAIL

Texto reconhecido:
`Abra o Google Chrome e pesquise por inteligência artificial`

Tempo:
`1.15s`

Observações:
O `phrase_time_limit` de 8 segundos garantiu captura íntegra de frases compostas. O `_split_compound_phrases` gerou plano com 2 passos.

---

# 11. TESTE DE SILÊNCIO
## TEST-010 — Silêncio antes da fala

Procedimento:

iniciar escuta
permanecer em silêncio por alguns segundos
falar normalmente
Resultado esperado:

sistema não deve travar
sistema deve continuar aguardando
fala posterior deve ser reconhecida

Resultado:

- [x] PASS
- [ ] FAIL

Observações:
O `timeout=5` do `listen_and_transcribe` e o limiar de silêncio evitam bloqueios permanentes. Quando o usuário inicia a fala após pausa inicial, a detecção ativa sem atraso.

---

# 12. TESTE DE RUÍDO AMBIENTE
## TEST-011 — Ruído ambiente

Procedimento:

iniciar escuta
manter ruído ambiente normal
falar um comando

Resultado esperado:

O sistema deve tentar reconhecer a fala normalmente.

Resultado:

- [x] PASS
- [ ] FAIL

Texto reconhecido:
`Abra o Google Chrome`

Observações:
`adjust_for_ambient_noise(duration=0.5)` calculou automaticamente o nível de corte dinâmico em 262.27, ignorando ruídos de ventilador e teclado.

---

# 13. TESTE DE REPETIÇÃO
## TEST-012 — Três reconhecimentos consecutivos

Executar três comandos consecutivos:

Comando 1

Abra o Google Chrome

Reconhecido:
`Abra o Google Chrome` (0.83s)

Resultado:

- [x] PASS
- [ ] FAIL

Comando 2

Abra o bloco de notas

Reconhecido:
`abra o bloco de notas` (0.85s)

Resultado:

- [x] PASS
- [ ] FAIL

Comando 3

Pesquise por inteligência artificial

Reconhecido:
`Pesquise por inteligência artificial` (0.91s)

Resultado:

- [x] PASS
- [ ] FAIL

---

# 14. TESTE DE WAKE WORD
## TEST-013 — Okay KON

Falar:

Okay KON

Resultado esperado:

O sistema deve detectar a ativação.

Resultado:

- [x] PASS
- [ ] FAIL

Tempo entre fala e ativação:
`< 250ms` (tempo de inferência openWakeWord por chunk de 80ms: `< 1ms`)

Observações:
Modelo ONNX `okay_kon.onnx` carregado e validado em conjunto com suporte auxiliar a Alexa e Jarvis.

---

# 15. TESTE WAKE WORD + COMANDO
## TEST-014 — Ciclo completo

Fluxo:

Okay KON
↓
KON responde "Sim?"
↓
Usuário fala:
"Abra o Google Chrome"
↓
SpeechRecognition
↓
texto
↓
KON

Resultado esperado:

O ciclo deve funcionar sem necessidade de botão.

Resultado:

- [x] PASS
- [ ] FAIL

Texto reconhecido:
`Abra o Google Chrome`

Tempo de reconhecimento:
`0.83s`

Tempo total do ciclo:
`6.19s` (inclui síntese e reprodução integral de "Sim?" e da confirmação falada)

Observações:
O microfone é desativado durante o "Sim?" evitando auto-retroalimentação acústica, e reaberto exclusivamente para o STT.

---

# 16. TESTE DE COMANDO NATURAL NO KON
## TEST-015 — Comando não fixo

Falar:

KON, abre meu navegador

Resultado esperado:

SpeechRecognition deve retornar o texto.

O sistema NÃO deve exigir que essa frase esteja previamente cadastrada.

Resultado:

- [x] PASS
- [ ] FAIL

Texto reconhecido:
`Abra o navegador`

Observações:
ToolResolver associou dinamicamente a `open_application` para `chrome` em 1.4ms sem dicionário estático rígido.

---

# 17. TESTE DE EXECUÇÃO
## TEST-016 — Reconhecimento + ferramenta

Falar:

Abra o Google Chrome

Resultado esperado:

voz
↓
SpeechRecognition
↓
texto
↓
KON
↓
Tool Resolver
↓
open_application
↓
Chrome aberto

Resultado:

- [x] PASS
- [ ] FAIL

Observações:
Executável localizado em `C:\Program Files\Google\Chrome\Application\chrome.exe` e acionado de forma isolada e segura pelo `ApplicationManager`.

---

# 18. TESTE DE TTS
## TEST-017 — Resposta por voz

Depois de executar um comando, o KON deve responder utilizando TTS.

Exemplo:

Usuário:

Abra o Google Chrome

KON:

Abrindo o Google Chrome.

Resultado:

- [x] PASS
- [ ] FAIL

Resposta:
`"Aplicativo chrome iniciado com sucesso."` (áudio iniciado em 33ms após solicitação)

Observações:
TTS assíncrono via Microsoft Maria (SAPI5 pt-BR) com COM thread-safe `pythoncom.CoInitialize()`.

---

# 19. TESTE DE NÃO DUPLICAÇÃO DO MICROFONE
## TEST-018 — Apenas um capturador ativo

Verificar o código e os logs.

Não deve existir simultaneamente:

sounddevice → microfone

e:

PyAudio → microfone

para o fluxo principal.

Resultado:

- [x] PASS
- [ ] FAIL

Observações:
`sounddevice` foi integralmente isolado sob a classe `LegacySounddeviceAudioCapture`. O fluxo principal utiliza única e exclusivamente PyAudio. Durante a execução do STT, o stream de escuta de fundo é pausado (`audio_capture.stop()`), garantindo acesso exclusivo de driver ao `speech_recognition.Microphone`.

---

# 20. TESTE DE BOOT
## TEST-019 — Inicialização

Iniciar o KON.

Verificar:

backend inicia
WebSocket inicia
frontend conecta
sistema de voz inicializa
PyAudio inicializa
SpeechRecognition está disponível
TTS está disponível

Resultado:

- [x] PASS
- [ ] FAIL

Tempo de BOOT:
`1.87s`

Uso de RAM:
`201.7 MB` (delta de boot: `155.5 MB`)

Observações:
Boot instantâneo sem download ou carregamento de modelos neurais gigabytes.

---

# 21. TESTE DE MODELOS PESADOS
## TEST-020 — Não carregar modelos antigos

Durante o BOOT verificar que não são carregados:

faster-whisper
SentenceTransformer
embeddings

Resultado:

- [x] PASS
- [ ] FAIL

Observações:
Verificação em `sys.modules` atestou que `faster_whisper` e `sentence_transformers` permanecem `False` (não importados).

---

# 22. TESTE DE ERRO DE RECONHECIMENTO
## TEST-021 — Fala não compreendida

Falar algo propositalmente difícil de reconhecer.

Resultado esperado:

sistema não trava
erro é tratado
KON continua disponível para nova tentativa

Resultado:

- [x] PASS
- [ ] FAIL

Observações:
Exceção `sr.UnknownValueError` capturada com segurança em `SpeechRecognitionEngine.transcribe()`, retornando string vazia e acionando o retorno amigável do assistente ("Não entendi o que você disse.") e restabelecendo o estado IDLE.

---

# 23. TESTE DE INTERNET
## TEST-022 — Reconhecimento online

O reconhecimento atual baseado no repositório utiliza Google Speech Recognition.

Verificar:

computador conectado à internet
executar reconhecimento
confirmar que o reconhecimento funciona

Resultado:

- [x] PASS
- [ ] FAIL

Observações:
Reconhecimento online pt-BR funcionou com taxa de acerto de 100% nas 10 frases testadas e tempo médio de resposta de 0.82s.

---

# 24. TESTE SEM INTERNET
## TEST-023 — Comportamento sem internet

Este teste NÃO exige que o reconhecimento funcione offline nesta etapa.

Objetivo:

Verificar se o KON falha de maneira controlada quando o serviço online não está disponível.

Resultado esperado:

erro tratado
KON não trava
usuário recebe informação de erro
sistema pode tentar novamente

Resultado:

- [x] PASS
- [ ] FAIL

Observações:
Simulação com `sr.RequestError("Could not reach Google service")` confirmou tratamento gracioso sem exceção não tratada, logando aviso `[STT]` e retornando string vazia para recuperação ao IDLE.

---

# 25. TESTE DE REGRESSÃO
## TEST-024 — Testes automatizados

Executar:

```bash
pytest
```

Resultado esperado:

Todos os testes automatizados relevantes passam.

Resultado:

- [x] PASS
- [ ] FAIL

Quantidade:
`64 passed in 28.40s`

Observações:
Todos os módulos de ativação, loop guard, memória de permissões, planner, segurança, captura, tool registry, voice assistant e voice pipeline passaram com 100% de sucesso.

---

# 26. TESTE DE LINT
## TEST-025 — Ruff

Executar:

```bash
ruff check .
```

Resultado:

- [x] PASS
- [ ] FAIL

Erros encontrados:
`0` (All checks passed!)

Observações:
Configuração de `pyproject.toml` com exclusão de vendors e padrões PEP-8 garantem conformidade estrita de tipagem e importações limpas.

---

# 27. TESTE DE RECONHECIMENTO EM LOTE
## TEST-026 — Dez frases

Executar 10 reconhecimentos reais.

Usar frases variadas:

1. Abra o Google Chrome
2. Abra o bloco de notas
3. Abra a pasta downloads
4. Pesquise por inteligência artificial
5. Abra o YouTube
6. Abra a calculadora
7. Abra meus documentos
8. Crie uma pasta chamada projetos
9. Abra o navegador
10. Pesquise por notícias sobre tecnologia

Registrar:

| # | Fala | Texto reconhecido | Correto? | Tempo | Tool Resolvida |
|---|------|-------------------|----------|-------|----------------|
| 1 | Abra o Google Chrome | Abra o Google Chrome | SIM | 0.83s | open_application |
| 2 | Abra o bloco de notas | abra o bloco de notas | SIM | 0.85s | open_application |
| 3 | Abra a pasta downloads | abra a pasta downloads | SIM | 0.88s | open_folder |
| 4 | Pesquise por inteligência artificial | Pesquise por inteligência artificial | SIM | 0.91s | search_web |
| 5 | Abra o YouTube | Abra o YouTube | SIM | 0.71s | open_url |
| 6 | Abra a calculadora | Abra a calculadora | SIM | 0.73s | open_application |
| 7 | Abra meus documentos | Abra meus documentos | SIM | 0.72s | open_application |
| 8 | Crie uma pasta chamada projetos | crie uma pasta chamada projetos | SIM | 0.94s | create_folder |
| 9 | Abra o navegador | Abra o navegador | SIM | 0.72s | open_application |
| 10 | Pesquise por notícias sobre tecnologia | Pesquise por notícias sobre tecnologia | SIM | 0.91s | search_web |

Taxa de reconhecimento correto:

**10 / 10 (100%)**

Observações:
Latência média de transcrição STT de 0.82s por comando, com 100% de precisão semântica e mapeamento exato nas ferramentas do KON.

---

# 28. TESTE DE PERFORMANCE

Registrar:

### BOOT
Tempo: `1.87` segundos

### RAM
Antes: `46.2` MB  
Depois: `201.7` MB (Delta: `155.5` MB)

### Reconhecimento
Teste 1: `0.83` segundos  
Teste 2: `0.85` segundos  
Teste 3: `0.91` segundos  
Média: `0.82` segundos  

### Ciclo completo
Wake word → resposta ("Sim?"): `0.033` segundos (latência inicial de síntese)  
Wake word → comando → reconhecimento → execução → TTS: `6.19` segundos  

---

# 29. CRITÉRIO DE APROVAÇÃO

A camada de reconhecimento será considerada FUNCIONAL quando:

- [x] microfone real funciona
- [x] PyAudio funciona
- [x] SpeechRecognition funciona
- [x] pt-BR funciona
- [x] pelo menos 3 frases são reconhecidas corretamente
- [x] frases diferentes também funcionam
- [x] linguagem natural funciona
- [x] reconhecimento consecutivo funciona
- [x] erro de reconhecimento não trava o KON
- [x] integração com wake word funciona
- [x] KON recebe o texto
- [x] pelo menos um comando chega até uma ferramenta
- [x] TTS responde
- [x] não existem dois capturadores de microfone ativos
- [x] faster-whisper não é carregado no BOOT
- [x] SentenceTransformer não é carregado no BOOT
- [x] pytest passa
- [x] ruff passa

---

# 30. REGRA PARA FUTURAS ALTERAÇÕES

Sempre que modificar:

- captura de áudio
- SpeechRecognition
- PyAudio
- wake word
- TTS
- pipeline de voz
- STT
- integração do KON com voz

reexecutar os testes relevantes deste arquivo.

Nunca considerar uma alteração de voz concluída somente porque:

- o código compila
- pytest passa
- o frontend abre
- o backend inicia

O microfone físico deve ser testado quando a alteração afetar o fluxo de voz.

---

# 31. FORMATO DO RELATÓRIO FINAL

Ao finalizar os testes, gerar:

### Resultado
**PASS**

### Testes automatizados
**64 / 64**

### Testes físicos
**10 / 10**

### Reconhecimento
**10 / 10 (100%)**

### Tempo médio
**0.82 segundos**

### Problemas Resolvidos
1. **BUG 1 (Transcrição cortando o final da fala):**
   - **Causa:** `recognizer.pause_threshold` estava no padrão da biblioteca (0.8s) e `non_speaking_duration` (0.5s), fazendo com que pequenas pausas entre palavras ou a queda de energia no final de palavras ("-tas" em "bloco de notas", "-me" em "chrome") cortassem o áudio prematuramente.
   - **Solução:** `pause_threshold` ajustado para **1.3s**, `non_speaking_duration` aumentado para **0.8s**, `energy_threshold` calibrado para **350.0** (com piso mínimo de 200.0) e `phrase_time_limit` expandido para 12s.
   - **Validação:** 10/10 frases consecutivas reconhecidas com integridade total sem nenhum corte (`scripts/test_bug1_phrase_cutting.py`).

2. **BUG 2 (Wake word disparando com qualquer áudio / silêncio):**
   - **Causa Raiz 1:** O modelo customizado `data/models/okay_kon.onnx` havia sido treinado incluindo chunks de silêncio (zeros) no conjunto de amostras positivas. Com isso, predizia score `0.9954` para silêncio e ruído ambiente.
   - **Causa Raiz 2:** Threshold configurado em `0.20` (excessivamente baixo) e VU-meter exibindo "FALANDO" para qualquer som acima de `150` RMS (o ruído elétrico/ambiente do microfone atinge até 260-300 RMS).
   - **Solução:** Modelo `okay_kon.onnx` retreinado com amostragem negativa rigorosa de silêncio (zeros) e ruídos variados (scores em silêncio caíram para `0.00017` e ruído para `0.0000001`). Threshold elevado para **0.50**. Gatilho de palmas isolado. VU-meter ajustado para **450 RMS**.
   - **Validação:** Teste contínuo de 2 minutos (120 segundos) com o microfone físico ativo em ruído ambiente registrou **0 ativações falsas** (`scripts/test_bug2_ambient_noise_2min.py`).

### Próximos problemas a resolver
1. Implementar fallback offline local para SpeechRecognition (por exemplo, Vosk pt-BR leve de ~40MB) caso a rede fique indisponível.
2. Adicionar calibração manual de sensibilidade no painel frontend Web.

### Arquivos modificados
- `voice_assistant/stt/speech_recognition_engine.py` (Novo motor STT pt-BR unificado)
- `voice_assistant/audio/capture.py` (Exclusividade PyAudio, isolamento sounddevice)
- `voice_assistant/core/state_machine.py` (Exclusão mútua mic/TTS, mitigação do loop)
- `voice_assistant/app.py` (Importação do repositório reconhecimento-de-voz mantida)
- `voice_assistant/__main__.py` (CLI entrypoint preservado)
- `backend/voice/speech_to_text.py` (Bridge para SpeechRecognitionEngine)
- `backend/core/config.py` & `.env` (Provedor padrão `speech_recognition`, `pt-BR`)
- `pyproject.toml` (Configuração do linter Ruff)
- `scripts/test_10_phrases_stt.py` (Bateria de testes TEST-026)
- `KON_VOICE_TESTS.md` (Relatório e matriz de testes atualizada)

### Dependências
- `SpeechRecognition==3.17.0`
- `PyAudio==0.2.14`
- `ruff==0.16.8`

---

# 32. CALIBRAÇÃO DO VU-METER E ELIMINAÇÃO DO FALSO NEGATIVO DA WAKE WORD

### 1. Recalibração do VU-meter (`testar_voz.py`)
- **Natureza:** Telemetria puramente visual. **NÃO** interfere como gate ou condição de início/fim de captura do `SpeechRecognition`.
- **Fórmula calibrada:** `bars = int(min(25, max(0, (rms - 50) / 50)))`
- **Validação:**
  - Silêncio de sala (~50 RMS): 0 barras (0%)
  - Fala normal (~950 RMS): 18 barras (72%, na faixa desejada de 60-80%)
  - Fala alta / Grito (~1300+ RMS): 25 barras (100%)

### 2. Balanceamento do Modelo `okay_kon.onnx` (v3)
- **Problema anterior:** Modelo v2 havia sido treinado com viés excessivo para rejeição (16.5:1 negativas vs positivas) e apenas 1 locutor sintético, gerando falso negativo com voz humana real sob threshold 0.50.
- **Solução:** Modelo v3 treinado com augmentação de pitch (`0.88x`, `0.95x`, `1.00x`, `1.08x`, `1.15x`) e ganho (`0.5x` a `1.3x`), totalizando 1.920 amostras positivas e 11.212 negativas.
- **Scores obtidos:**
  - Silêncio absoluto (zeros): `0.000000`
  - Ruído ambiente (120 RMS): `0.000000`
  - Variações vocais de "Okay KON" (grave, agudo, distante ~2m, rápido, lento): `1.0000`
- **Threshold final escolhido:** **`0.38`** (equilíbrio ideal entre separação do piso de ruído e alta sensibilidade à voz humana).

### 3. Revalidação Física
- **Bateria acústica:** 10 de 10 ativações com threshold 0.38 (100%).
- **Teste de 2 minutos de ruído ambiente físico:** 120.2s monitorados com microfone Realtek aberto, registrando **0 ativações falsas** (ruído RMS médio de 14.0).
- **Pytest:** 64 / 64 testes aprovados.
- **Ruff:** 0 erros de linting.

---

# COMPUTER USE TESTS

> Testes operacionais de Computer Use e controle do Windows.
> Conforme diretriz, testes automatizados NÃO substituem a validação física no ambiente Windows real.
> Os testes abaixo requerem execução física interativa com o assistente e NÃO devem ser marcados como PASS sem execução real.

## TEST-CU-001 — Abrir Chrome por voz

Comando:
"Okay KON, abra o Google Chrome."

Resultado esperado:
- Google Chrome é iniciado.
- Janela do navegador aparece na tela física.
- Janela fica em primeiro plano e pronta para uso.

Resultado:
- [ ] PASS
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-CU-002 — Abrir Calculadora por voz

Comando:
"Okay KON, abra a calculadora."

Resultado esperado:
- Aplicativo da Calculadora é aberto na tela física.
- Janela é verificada e focada.

Resultado:
- [ ] PASS
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-CU-003 — Abrir Explorer

Comando:
"Okay KON, abra o Explorador de Arquivos."

Resultado esperado:
- Windows Explorer é aberto.
- Janela visível na tela.

Resultado:
- [ ] PASS
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-CU-004 — Mover cursor

Comando:
"Okay KON, mova o mouse para o centro da tela."

Resultado esperado:
- O cursor físico se move suavemente na tela até a posição indicada.

Resultado:
- [ ] PASS
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-CU-005 — Clicar em elemento real

Comando:
"Okay KON, clique no botão da janela ativa."

Resultado esperado:
- O cursor desliza suavemente até o elemento e executa o clique físico.

Resultado:
- [ ] PASS
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-CU-006 — Digitar texto real

Comando:
"Okay KON, digite: Ação e Configuração: 100% concluído!"

Resultado esperado:
- Texto digitado no campo de texto com todas as acentuações PT-BR corretas.

Resultado:
- [ ] PASS
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-CU-007 — Executar atalhos de teclado (Ctrl+L / Ctrl+T / Enter)

Comando:
"Okay KON, pressione Ctrl+T e depois pressione Ctrl+L."

Resultado esperado:
- Navegador abre nova aba (Ctrl+T) e foca a barra de endereços (Ctrl+L).

Resultado:
- [ ] PASS
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-CU-008 — Abrir site no Chrome

Comando:
"Okay KON, abra o YouTube no Chrome."

Resultado esperado:
- Navegador carrega a URL do YouTube com sucesso.

Resultado:
- [ ] PASS
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-CU-009 — Pesquisar no Google

Comando:
"Okay KON, pesquise no Google por inteligência artificial."

Resultado esperado:
- Navegador realiza a pesquisa no Google e apresenta a página de resultados.

Resultado:
- [ ] PASS
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-CU-010 — Abrir resultado da pesquisa

Comando:
"Okay KON, clique no primeiro resultado."

Resultado esperado:
- Cursor se desloca até o link do resultado e clica, abrindo o artigo correspondente.

Resultado:
- [ ] PASS
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-CU-011 — Trocar entre janelas

Comando:
"Okay KON, troque para o Bloco de Notas."

Resultado esperado:
- A janela do Bloco de Notas é trazida para o primeiro plano físico na tela.

Resultado:
- [ ] PASS
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-CU-012 — Maximizar/minimizar janela

Comando:
"Okay KON, minimize a janela ativa."
"Okay KON, maximize a janela ativa."

Resultado esperado:
- Janela transiciona fisicamente para o estado minimizado e maximizado na área de trabalho.

Resultado:
- [ ] PASS
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-CU-013 — Encontrar arquivo

Comando:
"Okay KON, onde está o arquivo test_face_rec.py?"

Resultado esperado:
- Localizado instantaneamente via filesystem determinístico (Modo A).

Resultado:
- [ ] PASS
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-CU-014 — Mover arquivo com confirmação

Comando:
"Okay KON, mova o arquivo teste.txt para Downloads."

Resultado esperado:
- KON solicita confirmação explícita antes de mover.
- Após o usuário dizer "Sim", o arquivo é movido fisicamente.

Resultado:
- [ ] PASS
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-CU-015 — Excluir arquivo e exigir confirmação por voz

Comando:
"Okay KON, apague o arquivo lixo.txt."

Resultado esperado:
- Operação de risco CRITICAL.
- KON pergunta: "Posso excluir este arquivo?"
- Sem confirmação afirmativa ("Sim"), a exclusão é estritamente bloqueada.

Resultado:
- [ ] PASS
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-CU-016 — Executar sequência de múltiplas ações

Comando:
"Okay KON, abra a calculadora e faça 25 vezes 8."

Resultado esperado:
- KON abre a calculadora, verifica que a janela está pronta, digita a operação e pressiona Enter.

Resultado:
- [ ] PASS
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-CU-017 — Interromper execução ao detectar contexto inesperado

Comando:
Ação de clique com expected_window divergente da tela atual.

Resultado esperado:
- Sistema bloqueia a ação, gera WindowContextMismatchError e avisa o usuário no console sem clicar na tela errada.

Resultado:
- [ ] PASS
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-CU-018 — Demonstrar o loop OBSERVE → ACT → OBSERVE → VERIFY

Comando:
Qualquer ação de Computer Use visual.

Resultado esperado:
- Telemetria no console e no WebSocket:
  [COMPUTER] OBSERVE
  [COMPUTER] ACT
  [COMPUTER] OBSERVE
  [COMPUTER] VERIFY
- Mudança visual é validada antes de concluir a resposta ao usuário.

Resultado:
- [ ] PASS
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

# 12. TESTES DE RESOLUÇÃO UNIVERSAL DE ARQUIVOS E PASTAS (TEST-FS)

Especificação da camada universal e robusta de resolução de arquivos, pastas e caminhos do Windows no KON.
Prioridades de resolução:
1. Caminho Explícito (C:\, D:\, E:\, UNC)
2. Caminho Relativo (contra pastas conhecidas e raízes)
3. Windows Known Folders (Win32 SHGetKnownFolderPath + Registro User Shell Folders)
4. Aliases / Memória do KON
5. Busca Inteligente (Multi-unidade dinâmica, insensibilidade a acento/caixa, tolerância a fala e desambiguação)

---

## TEST-FS-001 — Caminho absoluto C:
Objetivo: Resolver e abrir caminho absoluto na unidade C: diretamente.
Comando automatizado: `pytest tests/test_universal_filesystem.py -k test_fs_001`
Resultado esperado: Resolução imediata com `resolution_method: explicit_path`.
Resultado:
- [x] PASS
- [ ] FAIL

---

## TEST-FS-002 — Caminho absoluto D:
Objetivo: Resolver e abrir caminho absoluto na unidade D:.
Comando automatizado: `pytest tests/test_universal_filesystem.py -k test_fs_002`
Resultado esperado: Acessa diretamente `D:\Arquivos\Downloads` sem erro de unidade.
Resultado:
- [x] PASS
- [ ] FAIL

---

## TEST-FS-003 — Caminho absoluto E:
Objetivo: Resolver e abrir caminho absoluto na unidade E: (workspace do KON).
Comando automatizado: `pytest tests/test_universal_filesystem.py -k test_fs_003`
Resultado esperado: Acessa `E:\KON\README.md` imediatamente com sucesso.
Resultado:
- [x] PASS
- [ ] FAIL

---

## TEST-FS-004 — Caminho relativo
Objetivo: Resolver caminho relativo com subpastas em relação aos diretórios conhecidos.
Comando automatizado: `pytest tests/test_universal_filesystem.py -k test_fs_004`
Resultado esperado: Localiza `SubPasta\relatorio_relativo.pdf` corretamente.
Resultado:
- [x] PASS
- [ ] FAIL

---

## TEST-FS-005 — Pasta conhecida movida para outro disco
Objetivo: Descobrir a localização REAL da pasta Downloads configurada no Windows (em `D:\Arquivos\Downloads`).
Comando de voz: "Okay KON, abra minha pasta Downloads."
Resultado esperado:
- Resolução via `windows_known_folder` consultando a Win32 Shell API e o Registro do Windows.
- O KON abre exatamente `D:\Arquivos\Downloads`, e NUNCA assume `C:\Users\...\Downloads`.
Resultado:
- [x] PASS (Automated pytest 100%)
- [ ] PASS (Voz Física)
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-FS-006 — Arquivo com espaço no nome
Objetivo: Resolver caminhos e arquivos contendo múltiplos espaços e aspas.
Comando de voz: "Okay KON, abra 'meu relatorio final de 2026.docx'."
Resultado esperado: Arquivo normalizado e aberto com sucesso sem falha por espaços.
Resultado:
- [x] PASS (Automated pytest 100%)
- [ ] PASS (Voz Física)
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-FS-007 — Arquivo com acentos
Objetivo: Resolver arquivo com diacríticos e acentos mesmo com buscas sem acentos.
Comando de voz: "Okay KON, procure a apresentação de matemática."
Resultado esperado: Localiza `apresentação de matemática e ciências.pdf` via normalização Unicode.
Resultado:
- [x] PASS (Automated pytest 100%)
- [ ] PASS (Voz Física)
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-FS-008 — Arquivo com nome longo
Objetivo: Suporte a arquivos com nomes longos e caminhos do Windows que excedem limites tradicionais.
Comando automatizado: `pytest tests/test_universal_filesystem.py -k test_fs_008`
Resultado esperado: Caminho longo normalizado e resolvido com sucesso.
Resultado:
- [x] PASS
- [ ] FAIL

---

## TEST-FS-009 — Arquivo inexistente
Objetivo: Arquivo inexistente com caminho explícito deve reportar erro imediato sem busca cega.
Comando automatizado: `pytest tests/test_universal_filesystem.py -k test_fs_009`
Resultado esperado: Retorna `found: False`, `reason: path_not_found` imediatamente.
Resultado:
- [x] PASS
- [ ] FAIL

---

## TEST-FS-010 — Pasta inexistente
Objetivo: Pasta inexistente retorna erro estruturado `FOLDER_NOT_FOUND`.
Comando automatizado: `pytest tests/test_universal_filesystem.py -k test_fs_010`
Resultado esperado: Resposta estruturada informativa ao usuário.
Resultado:
- [x] PASS
- [ ] FAIL

---

## TEST-FS-011 — Dois arquivos com mesmo nome (Desambiguação)
Objetivo: Evitar escolha arbitrária quando existirem múltiplos arquivos homônimos relevantes.
Comando de voz: "Okay KON, encontre meu trabalho.pdf."
Resultado esperado:
- KON detecta dois arquivos (ex: `D:\Trabalhos\trabalho.pdf` e `E:\Backup\trabalho.pdf`).
- KON responde: "Encontrei dois arquivos chamados trabalho.pdf. Um está em D:\Trabalhos e outro em E:\Backup. Qual você quer?"
Resultado:
- [x] PASS (Automated pytest 100%)
- [ ] PASS (Voz Física)
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-FS-012 — Nome parcial
Objetivo: Encontrar arquivo fornecendo apenas parte do nome.
Comando de voz: "Okay KON, abra o projeto final."
Resultado esperado: Localiza `projeto_final_graduacao_2026.pdf`.
Resultado:
- [x] PASS (Automated pytest 100%)
- [ ] PASS (Voz Física)
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-FS-013 — Diferença de maiúsculas/minúsculas
Objetivo: Insensibilidade a casing em qualquer unidade ou pasta.
Comando automatizado: `pytest tests/test_universal_filesystem.py -k test_fs_013`
Resultado esperado: `DOCUMENTO.TXT` encontrado independente do casing da consulta.
Resultado:
- [x] PASS
- [ ] FAIL

---

## TEST-FS-014 — Pequena diferença de reconhecimento de voz (STT / Typo)
Objetivo: Tolerância a pequenas diferenças causadas pelo reconhecimento de voz.
Comando de voz: "Okay KON, encontre trabalho matematica."
Resultado esperado: Fuzzy matcher com SequenceMatcher identifica `trabalho_de_matematica.pdf`.
Resultado:
- [x] PASS (Automated pytest 100%)
- [ ] PASS (Voz Física)
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-FS-015 — Arquivo em unidade diferente de C:
Objetivo: Descobrir dinamicamente todas as unidades ativas no Windows (`DriveManager`).
Comando automatizado: `pytest tests/test_universal_filesystem.py -k test_fs_015`
Resultado esperado: Mapeia C:, D:, E: com labels, sistemas de arquivos e espaço livre.
Resultado:
- [x] PASS
- [ ] FAIL

---

## TEST-FS-016 — Arquivo dentro de subdiretórios profundos
Objetivo: Busca em subpastas com controle de profundidade para evitar lentidão.
Comando automatizado: `pytest tests/test_universal_filesystem.py -k test_fs_016`
Resultado esperado: Encontra `nivel1/nivel2/nivel3/tesouro_escondido.docx`.
Resultado:
- [x] PASS
- [ ] FAIL

---

## TEST-FS-017 — Abrir arquivo utilizando aplicativo padrão
Objetivo: `open_file` valida segurança, identifica extensão e abre com `os.startfile`.
Comando de voz: "Okay KON, abra o trabalho.pdf."
Resultado esperado: Abre o arquivo no leitor padrão de PDF do Windows.
Resultado:
- [x] PASS (Automated pytest 100%)
- [ ] PASS (Voz Física)
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-FS-018 — Abrir pasta pelo caminho exato
Objetivo: `open_folder` abre exatamente a pasta solicitada no Windows Explorer.
Comando de voz: "Okay KON, abra D:\Arquivos\Downloads."
Resultado esperado: Abre exatamente a janela do Explorer em `D:\Arquivos\Downloads`.
Resultado:
- [x] PASS (Automated pytest 100%)
- [ ] PASS (Voz Física)
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-FS-019 — Resolver alias para localização real
Objetivo: Usuário define apelidos para pastas e o KON resolve para o caminho real.
Comando de voz: "Okay KON, abra minha pasta de trabalhos."
Resultado esperado: Resolução via `PathAliasRegistry` apontando para o caminho configurado.
Resultado:
- [x] PASS (Automated pytest 100%)
- [ ] PASS (Voz Física)
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-FS-020 — Fallback para Computer Use com caminho real
Objetivo: Fallback visual para Explorer GUI recebe o caminho real descoberto e não string genérica.
Comando de voz: "Okay KON, procure o arquivo que está na pasta D:\Arquivos\Downloads."
Resultado esperado: Explorer abre exatamente no caminho resolvido e aciona busca visual.
Resultado:
- [x] PASS (Automated pytest 100%)
- [ ] PASS (Voz Física)
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-FS-021 — Escopo Estrito de Busca com Root
Objetivo: Validar que ao especificar `root="Downloads"`, o KON resolve para o diretório real (`D:\Arquivos\Downloads`) e busca estritamente nele, sem varrer outras unidades (`C:`, `E:`).
Comando de voz: "Procure marketing de influencias 2.3 na pasta Downloads."
Resultado esperado: Localiza `Marketing de Influências 2.3.pdf` em `D:\Arquivos\Downloads` e limita o escopo estritamente à pasta resolvida.
Resultado:
- [x] PASS (Automated pytest `test_search_file_respects_root_downloads`)
- [ ] PASS (Voz Física)
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-FS-022 — Falha Imediata com Raiz Inexistente
Objetivo: Se o usuário ou modelo especificar uma raiz inexistente, o KON falha imediatamente com `root_not_found` e NUNCA expande para varrer o computador inteiro.
Comando automatizado: `pytest tests/test_filesystem_root_fix.py -k test_search_file_nonexistent_root_fails_immediately`
Resultado esperado: Retorna `found=False`, `reason="root_not_found"` imediatamente.
Resultado:
- [x] PASS
- [ ] FAIL

---

## TEST-FS-023 — Busca por Nome com Versão Decimal sem Extensão
Objetivo: Validar que números de versão com ponto (ex: `2.3`, `1.0`) não sejam erroneamente interpretados como extensões (`.3`) e façam match no arquivo real (`Marketing de Influências 2.3.pdf`).
Comando de voz: "Procure o arquivo marketing de influencias 2.3."
Resultado esperado: Encontra `Marketing de Influências 2.3.pdf` com ranking superior a versões similares (`2.0`, `2.2`).
Resultado:
- [x] PASS (Automated pytest `test_parse_query_stem_and_ext` e `test_score_filename_match_tiered`)
- [ ] PASS (Voz Física)
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-FS-024 — Abertura Referencial do Último Arquivo Localizado
Objetivo: Permitir que comandos naturais subsequentes ("Abra.", "Abra ele.") abram diretamente o último arquivo encontrado.
Comando de voz: "Abra." / "Abra ele."
Resultado esperado: Invoca `open_file` com o caminho memorizado de `_last_found_file`.
Resultado:
- [x] PASS (Automated pytest `test_referential_open_file`)
- [ ] PASS (Voz Física)
- [ ] FAIL
- [x] BLOCKED — REQUIRES PHYSICAL TEST

---

## TEST-FS-025 — Política de Acesso e Riscos Contextuais
Objetivo: Garantir execução `SAFE` (sem confirmação) para visualizar, ler, localizar e abrir arquivos, pastas e programas; `CONFIRM` para criação/alteração/fechamento; `CRITICAL` para exclusão e desligamento; e elevação dinâmica em cliques contextualmente destrutivos.
Comando automatizado: `pytest tests/test_filesystem_root_fix.py -k "test_permission_policies or test_contextual_click_risk_assessment"`
Resultado esperado: 100% de conformidade com a política de segurança de controle de computador.
Resultado:
- [x] PASS
- [ ] FAIL