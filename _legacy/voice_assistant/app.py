from __future__ import annotations

import argparse
import importlib
import multiprocessing as mp
import queue
import socket
import sys
import unicodedata
import webbrowser
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import quote_plus

GOOGLE_SEARCH_URL = "https://www.google.com/search?q="


class Intent(StrEnum):
    OPEN_URL = "open_url"
    SEARCH_WEB = "search_web"
    HELP = "help"
    EXIT = "exit"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class VoiceCommand:
    """Comando conhecido pelo assistente."""

    name: str
    description: str
    keywords: tuple[str, ...]
    url: str
    response: str


@dataclass(frozen=True)
class CommandMatch:
    intent: Intent
    spoken_text: str
    response: str
    url: str | None = None
    command: VoiceCommand | None = None


DEFAULT_COMMANDS: tuple[VoiceCommand, ...] = (
    VoiceCommand(
        name="bitcoin",
        description="Abrir a cotação atual do Bitcoin",
        keywords=("bitcoin", "btc", "cotacao bitcoin", "preco bitcoin"),
        url="https://dolarhoje.com/bitcoin-hoje/",
        response="Ok, abrindo a cotação atual do Bitcoin.",
    ),
    VoiceCommand(
        name="ethereum",
        description="Abrir a cotação atual do Ethereum",
        keywords=("ethereum", "ether", "eth", "cotacao ethereum", "preco ethereum"),
        url="https://dolarhoje.com/ethereum-hoje/",
        response="Ok, abrindo a cotação atual do Ethereum.",
    ),
    VoiceCommand(
        name="mempool",
        description="Abrir o mempool",
        keywords=("mempool", "mempool space", "taxas bitcoin"),
        url="https://mempool.space/pt/",
        response="Ok, abrindo o mempool.space.",
    ),
    VoiceCommand(
        name="arbitragem",
        description="Abrir o monitor de arbitragem",
        keywords=("arbitragem", "arbitragem cripto", "monitor de arbitragem"),
        url="https://cointradermonitor.com/arbitragem",
        response="Ok, abrindo oportunidades de arbitragem.",
    ),
    VoiceCommand(
        name="coinmarketcap",
        description="Abrir o CoinMarketCap em português",
        keywords=("criptomoeda", "criptomoedas", "coinmarketcap", "market cap"),
        url="https://coinmarketcap.com/pt-br/",
        response="Ok, abrindo o CoinMarketCap.",
    ),
    VoiceCommand(
        name="binance",
        description="Abrir a Binance Brasil",
        keywords=("binance", "corretora binance", "exchange binance"),
        url="https://www.binance.com/pt-BR/",
        response="Ok, abrindo a Binance.",
    ),
    VoiceCommand(
        name="dolar",
        description="Abrir a cotação do dólar",
        keywords=("dolar", "dólar", "cotacao dolar", "cotação dólar"),
        url="https://dolarhoje.com/",
        response="Ok, abrindo a cotação do dólar.",
    ),
    VoiceCommand(
        name="tradingview",
        description="Abrir o TradingView",
        keywords=("tradingview", "grafico", "gráfico", "graficos", "gráficos"),
        url="https://br.tradingview.com/markets/cryptocurrencies/prices-all/",
        response="Ok, abrindo gráficos de criptomoedas no TradingView.",
    ),
)


class Speaker(Protocol):
    def say(self, text: str) -> None:
        """Fala ou exibe uma resposta ao usuário."""
        ...


class Listener(Protocol):
    def listen(self) -> str:
        """Captura a próxima frase do usuário."""
        ...


class NoSpeechSpeaker:
    def say(self, text: str) -> None:
        print(text)


class Pyttsx3Speaker:
    def __init__(self, rate: int = 150, volume: float = 1.0) -> None:
        try:
            pyttsx3 = importlib.import_module("pyttsx3")
        except ImportError as exc:
            raise RuntimeError(
                "A dependência 'pyttsx3' não está instalada. "
                "Instale com 'pip install -e .[voice]' ou execute com --no-speech."
            ) from exc

        self._engine = pyttsx3.init()
        self._engine.setProperty("rate", rate)
        self._engine.setProperty("volume", volume)
        self._select_portuguese_voice()

    def say(self, text: str) -> None:
        print(text)
        self._engine.say(text)
        self._engine.runAndWait()

    def close(self) -> None:
        self._engine.stop()

    def _select_portuguese_voice(self) -> None:
        voices = self._engine.getProperty("voices")
        for voice in voices:
            voice_id = getattr(voice, "id", "").lower()
            voice_name = getattr(voice, "name", "").lower()
            voice_languages = " ".join(
                str(language).lower() for language in getattr(voice, "languages", [])
            )
            if any(
                token in f"{voice_id} {voice_name} {voice_languages}"
                for token in (
                    "brazil",
                    "brasil",
                    "portuguese",
                    "portugues",
                    "pt_br",
                    "pt-br",
                )
            ):
                self._engine.setProperty("voice", voice.id)
                return


class MicrophoneListener:
    def __init__(
        self,
        language: str = "pt-BR",
        timeout: int = 5,
        phrase_time_limit: int = 8,
        device_index: int | None = None,
        recognition_timeout: int = 10,
        force_ipv4: bool = True,
    ) -> None:
        try:
            sr = importlib.import_module("speech_recognition")
        except ImportError as exc:
            raise RuntimeError(
                "A dependência 'SpeechRecognition' não está instalada. "
                "Instale com 'pip install -e .[voice]'."
            ) from exc

        self._sr = sr
        self._language = language
        self._timeout = timeout
        self._phrase_time_limit = phrase_time_limit
        self._device_index = device_index
        self._recognition_timeout = recognition_timeout
        self._force_ipv4 = force_ipv4
        self._recognizer = sr.Recognizer()
        self._recognizer.operation_timeout = recognition_timeout

    def listen(self) -> str:
        try:
            with self._sr.Microphone(device_index=self._device_index) as source:
                print("Ajustando ruído ambiente... fale após o aviso.")
                self._recognizer.adjust_for_ambient_noise(source, duration=0.6)
                print("Ouvindo...")
                audio = self._recognizer.listen(
                    source,
                    timeout=self._timeout,
                    phrase_time_limit=self._phrase_time_limit,
                )

            print("Reconhecendo...")
            return recognize_google_with_timeout(
                audio=audio,
                language=self._language,
                timeout=self._recognition_timeout,
                force_ipv4=self._force_ipv4,
            )
        except TimeoutError as exc:
            raise RuntimeError(
                "Tempo esgotado ao chamar o serviço de reconhecimento do Google. "
                "Verifique sua conexão ou tente novamente."
            ) from exc
        except self._sr.WaitTimeoutError:
            return ""
        except self._sr.UnknownValueError:
            return ""
        except self._sr.RequestError as exc:
            raise RuntimeError(
                "Erro ao se conectar com o serviço de reconhecimento de voz."
            ) from exc
        except AttributeError as exc:
            raise RuntimeError(
                "PyAudio não está instalado ou não foi encontrado. "
                "Instale com 'pip install -e .[voice]'."
            ) from exc


def recognize_google_with_timeout(
    audio: Any,
    language: str,
    timeout: int,
    force_ipv4: bool,
) -> str:
    wav_data = audio.get_wav_data()
    sample_rate = audio.sample_rate
    sample_width = audio.sample_width

    context = mp.get_context("fork") if sys.platform != "win32" else mp.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(
        target=_recognize_google_worker,
        args=(wav_data, sample_rate, sample_width, language, timeout, force_ipv4, result_queue),
    )
    try:
        process.start()
        process.join(timeout)

        if process.is_alive():
            process.terminate()
            process.join(1)
            raise TimeoutError

        try:
            status, payload = result_queue.get_nowait()
        except queue.Empty as exc:
            raise RuntimeError("O reconhecimento de voz encerrou sem retornar resultado.") from exc

        if status == "ok":
            return payload
        if status == "unknown":
            return ""
        if status == "request_error":
            raise RuntimeError("Erro ao se conectar com o serviço de reconhecimento de voz.")

        raise RuntimeError(f"Erro inesperado no reconhecimento de voz: {payload}")
    finally:
        result_queue.close()
        result_queue.join_thread()
        process.close()


def _recognize_google_worker(
    wav_data: bytes,
    sample_rate: int,
    sample_width: int,
    language: str,
    timeout: int,
    force_ipv4: bool,
    result_queue: Any,
) -> None:
    try:
        sr = importlib.import_module("speech_recognition")
    except ImportError as exc:
        result_queue.put(("error", str(exc)))
        return

    try:
        previous_timeout = socket.getdefaulttimeout()
        previous_getaddrinfo = socket.getaddrinfo
        socket.setdefaulttimeout(timeout)
        if force_ipv4:
            socket.getaddrinfo = _ipv4_getaddrinfo(previous_getaddrinfo)
        try:
            recognizer = sr.Recognizer()
            audio = sr.AudioData(wav_data, sample_rate, sample_width)
            text = recognizer.recognize_google(audio, language=language)
        finally:
            socket.setdefaulttimeout(previous_timeout)
            socket.getaddrinfo = previous_getaddrinfo
        result_queue.put(("ok", text))
    except sr.UnknownValueError:
        result_queue.put(("unknown", ""))
    except sr.RequestError as exc:
        result_queue.put(("request_error", str(exc)))
    except Exception as exc:
        result_queue.put(("error", str(exc)))


def _ipv4_getaddrinfo(original_getaddrinfo: Any) -> Any:
    def getaddrinfo(
        host: str,
        port: int,
        family: int = 0,
        socket_type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[Any]:
        return original_getaddrinfo(host, port, socket.AF_INET, socket_type, proto, flags)

    return getaddrinfo


class TypedListener:
    def listen(self) -> str:
        return input("Digite um comando: ").strip()


class CommandRegistry:
    def __init__(self, commands: tuple[VoiceCommand, ...] = DEFAULT_COMMANDS) -> None:
        self._commands = commands

    @property
    def commands(self) -> tuple[VoiceCommand, ...]:
        return self._commands

    def match(self, spoken_text: str) -> CommandMatch:
        normalized_text = normalize(spoken_text)
        if not normalized_text:
            return CommandMatch(
                intent=Intent.UNKNOWN,
                spoken_text=spoken_text,
                response="Desculpe, não consegui ouvir o comando.",
            )

        if contains_any(normalized_text, ("sair", "encerrar", "fechar assistente", "parar")):
            return CommandMatch(
                intent=Intent.EXIT,
                spoken_text=spoken_text,
                response="Até mais!",
            )

        if contains_any(normalized_text, ("ajuda", "comandos", "o que voce faz", "opcoes")):
            return CommandMatch(
                intent=Intent.HELP,
                spoken_text=spoken_text,
                response=self.help_text(),
            )

        search_term = extract_search_term(normalized_text)
        if search_term:
            url = f"{GOOGLE_SEARCH_URL}{quote_plus(search_term)}"
            return CommandMatch(
                intent=Intent.SEARCH_WEB,
                spoken_text=spoken_text,
                response=f"Ok, pesquisando por {search_term}.",
                url=url,
            )

        command = self._find_command(normalized_text)
        if command:
            return CommandMatch(
                intent=Intent.OPEN_URL,
                spoken_text=spoken_text,
                response=command.response,
                url=command.url,
                command=command,
            )

        fallback_url = f"{GOOGLE_SEARCH_URL}{quote_plus(spoken_text.strip())}"
        return CommandMatch(
            intent=Intent.SEARCH_WEB,
            spoken_text=spoken_text,
            response="Não encontrei um atalho específico. Vou pesquisar isso no Google.",
            url=fallback_url,
        )

    def help_text(self) -> str:
        command_names = ", ".join(command.name for command in self._commands)
        return (
            "Você pode pedir: "
            f"{command_names}. Também entendo 'pesquisar por ...', 'ajuda' e 'sair'."
        )

    def _find_command(self, normalized_text: str) -> VoiceCommand | None:
        ranked_matches: list[tuple[int, VoiceCommand]] = []
        for command in self._commands:
            for keyword in command.keywords:
                normalized_keyword = normalize(keyword)
                if normalized_keyword in normalized_text:
                    ranked_matches.append((len(normalized_keyword), command))

        if not ranked_matches:
            return None

        ranked_matches.sort(key=lambda item: item[0], reverse=True)
        return ranked_matches[0][1]


def normalize(text: str) -> str:
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(character) != "Mn"
    )
    return " ".join(without_accents.split())


def contains_any(text: str, candidates: tuple[str, ...]) -> bool:
    return any(normalize(candidate) in text for candidate in candidates)


def extract_search_term(normalized_text: str) -> str | None:
    prefixes = (
        "pesquisar por ",
        "pesquise por ",
        "procure por ",
        "buscar por ",
        "busque por ",
        "google ",
    )
    for prefix in prefixes:
        if normalized_text.startswith(prefix):
            term = normalized_text.removeprefix(prefix).strip()
            return term or None
    return None


class VoiceAssistant:
    def __init__(
        self,
        listener: Listener,
        speaker: Speaker,
        registry: CommandRegistry | None = None,
        browser: webbrowser.BaseBrowser | None = None,
    ) -> None:
        self._listener = listener
        self._speaker = speaker
        self._registry = registry or CommandRegistry()
        self._browser = browser

    @property
    def registry(self) -> CommandRegistry:
        return self._registry

    def run_once(self) -> bool:
        self._speaker.say("Olá! O que você deseja buscar?")
        spoken_text = self._listener.listen()
        if spoken_text:
            print(f"Você disse: {spoken_text}")

        match = self._registry.match(spoken_text)
        self._speaker.say(match.response)

        if match.url:
            self._open_url(match.url)

        return match.intent != Intent.EXIT

    def _open_url(self, url: str) -> None:
        if self._browser:
            self._browser.open_new_tab(url)
            return
        webbrowser.open_new_tab(url)

    def close(self) -> None:
        close = getattr(self._speaker, "close", None)
        if callable(close):
            close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="assistente-voz",
        description=(
            "Assistente de voz em português para abrir atalhos de cripto e pesquisar na web."
        ),
    )
    parser.add_argument(
        "--typed",
        action="store_true",
        help="Lê comandos pelo teclado em vez do microfone.",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Continua ouvindo comandos até você dizer 'sair'.",
    )
    parser.add_argument(
        "--no-speech",
        action="store_true",
        help="Desativa a fala por voz e imprime as respostas no terminal.",
    )
    parser.add_argument(
        "--list-commands",
        action="store_true",
        help="Lista os atalhos disponíveis e encerra.",
    )
    parser.add_argument(
        "--list-microphones",
        action="store_true",
        help="Lista os microfones detectados e encerra.",
    )
    parser.add_argument(
        "--microphone-index",
        type=int,
        default=None,
        help="Índice do microfone que deve ser usado. Veja --list-microphones.",
    )
    parser.add_argument(
        "--language",
        default="pt-BR",
        help="Idioma usado no reconhecimento do Google Speech Recognition. Padrão: pt-BR.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=5,
        help="Tempo máximo, em segundos, aguardando início da fala. Padrão: 5.",
    )
    parser.add_argument(
        "--phrase-time-limit",
        type=int,
        default=8,
        help="Tempo máximo, em segundos, para uma frase. Padrão: 8.",
    )
    parser.add_argument(
        "--recognition-timeout",
        type=int,
        default=10,
        help="Tempo máximo, em segundos, para resposta do serviço de reconhecimento. Padrão: 10.",
    )
    parser.add_argument(
        "--no-force-ipv4",
        action="store_false",
        dest="force_ipv4",
        help="Não força IPv4 na chamada ao Google Speech Recognition.",
    )
    return parser


def create_assistant(args: argparse.Namespace) -> VoiceAssistant:
    listener: Listener
    if args.typed:
        listener = TypedListener()
    else:
        listener = MicrophoneListener(
            language=args.language,
            timeout=args.timeout,
            phrase_time_limit=args.phrase_time_limit,
            device_index=args.microphone_index,
            recognition_timeout=args.recognition_timeout,
            force_ipv4=args.force_ipv4,
        )

    speaker: Speaker = NoSpeechSpeaker() if args.no_speech else Pyttsx3Speaker()
    return VoiceAssistant(listener=listener, speaker=speaker)


def print_commands(registry: CommandRegistry) -> None:
    for command in registry.commands:
        keywords = ", ".join(command.keywords)
        print(f"- {command.name}: {command.description} ({keywords})")
    print("- pesquisar por <termo>: pesquisa qualquer assunto no Google")
    print("- ajuda: lista comandos disponíveis")
    print("- sair: encerra o assistente")


def print_microphones() -> None:
    try:
        sr = importlib.import_module("speech_recognition")
    except ImportError as exc:
        raise RuntimeError(
            "A dependência 'SpeechRecognition' não está instalada. "
            "Instale com 'pip install -e .[voice]'."
        ) from exc

    for index, name in enumerate(sr.Microphone.list_microphone_names()):
        print(f"{index}: {name}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    registry = CommandRegistry()

    assistant: VoiceAssistant | None = None
    try:
        if args.list_commands:
            print_commands(registry)
            return 0

        if args.list_microphones:
            print_microphones()
            return 0

        assistant = create_assistant(args)
        keep_running = True
        while keep_running:
            keep_running = assistant.run_once() and args.continuous
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\nAssistente encerrado.")
        return 130
    except RuntimeError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    finally:
        if assistant is not None:
            assistant.close()


if __name__ == "__main__":
    raise SystemExit(main())
