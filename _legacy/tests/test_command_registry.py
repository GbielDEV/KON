from voice_assistant.app import CommandRegistry, Intent, extract_search_term, normalize


def test_normalize_removes_accents_and_extra_spaces() -> None:
    assert normalize("  Cotação   DÓLAR  ") == "cotacao dolar"


def test_matches_bitcoin_command() -> None:
    match = CommandRegistry().match("abrir cotação do Bitcoin")

    assert match.intent == Intent.OPEN_URL
    assert match.command is not None
    assert match.command.name == "bitcoin"
    assert match.url == "https://dolarhoje.com/bitcoin-hoje/"


def test_matches_new_ethereum_command() -> None:
    match = CommandRegistry().match("preço ethereum")

    assert match.intent == Intent.OPEN_URL
    assert match.command is not None
    assert match.command.name == "ethereum"


def test_extracts_web_search_term() -> None:
    assert extract_search_term("pesquisar por melhores carteiras bitcoin") == (
        "melhores carteiras bitcoin"
    )


def test_unknown_command_falls_back_to_google_search() -> None:
    match = CommandRegistry().match("noticias sobre inteligencia artificial")

    assert match.intent == Intent.SEARCH_WEB
    assert match.url == "https://www.google.com/search?q=noticias+sobre+inteligencia+artificial"


def test_help_and_exit_intents() -> None:
    registry = CommandRegistry()

    assert registry.match("ajuda").intent == Intent.HELP
    assert registry.match("sair").intent == Intent.EXIT
