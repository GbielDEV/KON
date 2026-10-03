# 🌌 KON — Assistente Pessoal por Voz para Windows (Marco 2)

O **KON** é um assistente pessoal inteligente desenvolvido para Windows, inspirado no conceito do JARVIS. No **Marco 2**, o subsistema de voz foi completamente refatorado para operar de forma **REAL, CONTÍNUA e 100% POR VOZ**.

> 💡 **"Nenhum botão é necessário para utilizar o KON."**
> Ao iniciar o assistente, o microfone entra imediatamente em captura contínua e permanece escutando a wake word *"Okay KON"*. A interface gráfica em React atua primariamente como um **Monitor Visual HUD** em tempo real.

---

## 🏛️ Pipeline Obrigatório de Voz

```
Microfone (sounddevice.RawInputStream, 16kHz, mono, thread isolada + Queue)
  │
  ▼
Wake Word (openWakeWord - detecção offline contínua em IDLE)
  │ ──► Transição de estado: [STATE] OUVINDO
  ▼
TTS Responde ("Sim?" em pt-BR via pyttsx3 / Microsoft Maria)
  │
  ▼
VAD (webrtcvad - detecção de início de fala, continuidade e silêncio de 1.5s)
  │ ──► [VAD] Início da fala ──► [VAD] Fim da fala
  ▼
STT (faster-whisper - modelo small, CPU, int8, pt)
  │ ──► [STATE] PROCESSANDO ──► [STT] Texto transcrito
  ▼
NLU / Intent Parser (sentence-transformers - paraphrase-multilingual-MiniLM-L12-v2)
  │ ──► [NLU] Intent resolvido via similaridade de cosseno
  ▼
Command Registry (@command + dispatch seguro, sem eval/exec)
  │ ──► [STATE] EXECUTING ──► [COMMAND] Executando comando
  ▼
ToolManager (Validação estrita de níveis de permissão SAFE/CONFIRM/CRITICAL)
  │
  ▼
Ação no Windows (Execução segura de aplicativos, navegação, arquivos ou sistema)
  │
  ▼
TTS Resposta (Síntese falada em português brasileiro em thread não-bloqueante)
  │ ──► [STATE] SPEAKING ──► [TTS] Resposta falada
  ▼
Retorno para IDLE (Retoma escuta contínua de "Okay KON")
  └──► [STATE] IDLE
```

---

## 📁 Estrutura do Projeto

```
KON/
├── main.py                     # PONTO DE ENTRADA PRINCIPAL: Inicia servidor e voz contínua
├── INICIAR_KON.bat             # Inicializador automático (Backend + Frontend + Navegador)
├── requirements.txt            # Dependências oficiais (sounddevice, webrtcvad, whisper, etc.)
│
├── voice_assistant/            # Subsistema de Voz Real Desacoplado (Marco 2)
│   ├── audio/
│   │   ├── capture.py          # sounddevice.RawInputStream (16kHz mono, queue, non-blocking)
│   │   ├── vad.py              # webrtcvad (detecção de fala e timeout de 1.5s de silêncio)
│   │   └── wake_word.py        # openWakeWord offline (detecta "Okay KON" em IDLE)
│   ├── stt/
│   │   └── whisper_engine.py   # faster-whisper small (int8/cpu/pt, singleton de baixo consumo)
│   ├── nlu/
│   │   └── intent_parser.py    # sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2)
│   ├── commands/
│   │   ├── registry.py         # Registry pattern (@command + dispatch + ToolManager check)
│   │   ├── system_commands.py  # abrir_navegador, informar_horario, abrir_pasta
│   │   └── media_commands.py   # tocar_musica
│   ├── tts/
│   │   └── speak.py            # pyttsx3 (Microsoft Maria / pt-BR, worker thread assíncrono)
│   └── core/
│       └── state_machine.py    # VoicePipelineOrchestrator (Orquestração contínua e estados)
│
├── backend/                    # Núcleo do Sistema (Marco 1 Preservado)
│   ├── core/
│   │   ├── kon.py              # KONCore (Integrado ao VoicePipelineOrchestrator)
│   │   ├── state.py            # Estados finitos (IDLE, LISTENING, THINKING, etc.)
│   │   ├── events.py           # EventBus e esquemas Pydantic
│   │   ├── config.py           # Configurações do ambiente (.env)
│   │   └── logger.py           # Logging com prefixos [MIC], [WAKE], [VAD], [STT], etc.
│   ├── ai/
│   │   └── tool_manager.py     # ToolManager e níveis de permissão (SAFE, CONFIRM, CRITICAL)
│   ├── computer/               # Integração segura com Windows (aplicações, telemetria, arquivos)
│   ├── memory/                 # Persistência SQLite local (data/kon.db)
│   └── server/                 # FastAPI REST + WebSocket (/ws)
│
├── frontend/                   # Monitor Visual HUD (React 19 + Vite)
│   ├── src/
│   │   ├── components/         # HologramCore, StatusHeader, EventConsole, VoiceStatusBar
│   │   ├── services/           # WebSocket client em tempo real
│   │   └── App.jsx
│
├── data/models/                # Modelos ONNX locais (okay_kon.onnx) e banco kon.db
└── tests/                      # Bateria de testes automatizados (Marco 1 e Marco 2)
    ├── test_all.py             # Testes de integração do Marco 1
    ├── test_voice_pipeline.py  # Testes de compatibilidade do pipeline de voz
    └── test_voice_assistant.py # Testes unitários do subsistema voice_assistant (Marco 2)
```

---

## ⚙️ Pré-requisitos & Instalação

- **Sistema Operacional:** Windows 10 ou Windows 11 (64-bit)
- **Python:** Versão 3.12 (ou superior)
- **Node.js:** Versão 18+ (para a interface React)
- **Microfone:** Dispositivo de entrada padrão configurado no Windows
- **Memória RAM:** Mínimo de 8 GB (os modelos são carregados como singletons otimizados)

### 1. Clonar ou Acessar o Repositório
```powershell
cd E:\KON
```

### 2. Criar e Ativar o Ambiente Virtual
Utilizando `uv` (recomendado) ou `python`:
```powershell
uv venv
# ou: python -m venv .venv

.\.venv\Scripts\Activate.ps1
```

### 3. Instalar Dependências do Python
```powershell
uv pip install -r requirements.txt
# ou: pip install -r requirements.txt
```

As principais bibliotecas instaladas:
- `sounddevice`: Captura de áudio de baixa latência em thread separada
- `webrtcvad-wheels`: Detecção de atividade de voz (VAD) profissional
- `openwakeword`: Detecção local e offline de Wake Word
- `faster-whisper`: Transcrição de fala local (modelo `small`, CPU int8)
- `sentence-transformers`: NLU semântico multilíngue
- `pyttsx3`: Síntese de voz em português brasileiro nativa

### 4. Instalar Dependências do Frontend
```powershell
cd frontend
npm install
cd ..
```

---

## 🚀 Como Executar o KON (100% por Voz)

### Comando Principal
Abra o terminal na raiz do projeto e execute:
```powershell
python main.py
```

O assistente inicializará automaticamente:
1. Conecta o microfone ao fluxo contínuo.
2. Fica em `[STATE] IDLE` escutando a wake word.
3. Inicia o servidor local FastAPI e WebSocket em `http://127.0.0.1:8000`.

### Inicializador Completo (Com Monitor Visual React)
Dê um duplo clique no arquivo:
```
INICIAR_KON.bat
```
Ele iniciará o backend com captura de voz ativa, o servidor do Vite e abrirá seu navegador padrão em `http://127.0.0.1:5173` para monitoramento holográfico.

---

## 🎙️ Fluxo Obrigatório de Teste Real

Com o assistente executando:

1. **Não clique em nenhum botão.**
2. Fale claramente próximo ao microfone:
   > **"Okay KON"**
3. Observe os logs no terminal:
   ```
   [WAKE] Wake word detectada! Disparando ciclo de voz...
   [STATE] OUVINDO
   [TTS] Resposta: "Sim?"
   ```
4. O KON responderá por voz: **"Sim?"**
5. Diga imediatamente o seu comando:
   > **"abrir navegador"**
6. O VAD capturará sua fala e encerrará a gravação após 1.5s de silêncio:
   ```
   [VAD] Início da fala detectado!
   [VAD] Fim da fala (silêncio de 1.5s detectado).
   [STATE] PROCESSANDO
   [STT] Transcrevendo...
   [STT] Texto: "abrir navegador"
   [NLU] Intent: abrir_navegador (confiança: 1.000 >= 0.55)
   [STATE] EXECUTING
   [COMMAND] Executando abrir_navegador
   [STATE] SPEAKING
   [TTS] Resposta: "Abrindo o navegador."
   [STATE] IDLE
   ```
7. O navegador Google Chrome / padrão do Windows abrirá na sua tela.
8. O KON confirmará por voz: *"Abrindo o navegador."*
9. O assistente retornará automaticamente para `[STATE] IDLE` e continuará escutando *"Okay KON"* indefinidamente.

---

## 🧪 Testes de Componentes e Diagnóstico

### Teste Rápido do Microfone
```powershell
uv run python -c "from voice_assistant.audio.capture import AudioCapture; cap = AudioCapture(); print('Microfone:', cap.get_device_name(), '| Disponível:', cap.is_available())"
```

### Teste do Wake Word Detector
```powershell
uv run python -c "from voice_assistant.audio.wake_word import OpenWakeWordDetector; d = OpenWakeWordDetector(); d.start(); print('Detector ativo:', d.is_active(), '| Modelos:', d._active_models); d.stop()"
```

### Teste do STT (Whisper small)
```powershell
uv run python -c "from voice_assistant.stt.whisper_engine import WhisperSTTEngine; import numpy as np; stt = WhisperSTTEngine(model_size='small'); print('Whisper small pronto!')"
```

### Teste do NLU (Sentence Transformers)
```powershell
uv run python -c "from voice_assistant.nlu.intent_parser import IntentParser; p = IntentParser(); print('abrir navegador ->', p.resolver_intent('abrir navegador')); print('que horas são ->', p.resolver_intent('que horas são'))"
```

### Execução de Todos os Testes Automatizados
```powershell
uv run python -m pytest -v
```
Todos os 27 testes unitários e de integração serão executados e devem passar com sucesso.

---

## 🛠️ Solução de Problemas

1. **Microfone não detectado:**
   - Verifique nas configurações do Windows se o microfone está definido como dispositivo padrão e se as permissões de acesso ao microfone estão ativadas para aplicativos.
2. **Modelo Whisper demorando na primeira execução:**
   - Na primeira vez em que o Whisper `small` for executado, o modelo (~460 MB) será baixado e armazenado em cache localmente no diretório do usuário (`.cache/huggingface/hub`). Nas próximas execuções, o carregamento será instantâneo.
3. **Voz em Português do Brasil:**
   - O KON seleciona automaticamente a voz `Microsoft Maria Desktop - Portuguese(Brazil)` presente no Windows. Caso nenhuma voz pt-BR esteja instalada, ele utilizará a voz padrão do sistema.
#   K O N  
 #   K O N  
 