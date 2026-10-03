"""
Unit tests for the ToolResolver and multi-step PlanExecutor.
Tests general natural language interpretation without relying on rigid intent lists.
"""
from backend.ai.planner import ToolResolver, PlanExecutor


def test_resolver_single_actions():
    resolver = ToolResolver()

    # Browser / App
    p1 = resolver.resolve("Abra o Google Chrome")
    assert p1.success
    assert len(p1.steps) == 1
    assert p1.steps[0].tool == "open_application"
    assert p1.steps[0].arguments.get("application") == "chrome"

    # Close App
    p2 = resolver.resolve("Feche o Chrome")
    assert p2.success
    assert p2.steps[0].tool == "close_application"
    assert p2.steps[0].arguments.get("application") == "chrome"

    # Open Folder
    p3 = resolver.resolve("Abra a pasta Downloads")
    assert p3.success
    assert p3.steps[0].tool == "open_folder"
    assert p3.steps[0].arguments.get("folder") == "Downloads"

    # System Telemetry
    p4 = resolver.resolve("Qual é o uso de memória do computador?")
    assert p4.success
    assert p4.steps[0].tool == "system_info"
    assert p4.steps[0].arguments.get("metric") == "memory"

    # Screenshot
    p5 = resolver.resolve("Tire um print da tela")
    assert p5.success
    assert p5.steps[0].tool == "take_screenshot"


def test_resolver_parameter_extraction():
    resolver = ToolResolver()

    # Create folder with custom name and parent
    p_folder = resolver.resolve("Crie uma pasta chamada Projetos dentro de Downloads")
    assert p_folder.success
    assert len(p_folder.steps) == 1
    step = p_folder.steps[0]
    assert step.tool == "create_folder"
    assert step.arguments.get("name") == "Projetos"
    assert step.arguments.get("parent") == "Downloads"

    # Search file with extension
    p_search = resolver.resolve("Procure aquele arquivo PDF que criei ontem")
    assert p_search.success
    assert p_search.steps[0].tool == "search_file"
    assert p_search.steps[0].arguments.get("extension") == "pdf"


def test_resolver_compound_actions():
    resolver = ToolResolver()

    # Multi-action query: "Abra o Chrome e depois entre no YouTube"
    plan = resolver.resolve("Abra o Chrome e depois entre no YouTube")
    assert plan.success
    assert len(plan.steps) == 2
    assert plan.steps[0].tool == "open_application"
    assert plan.steps[0].arguments.get("application") == "chrome"
    assert plan.steps[1].tool == "open_url"
    assert "youtube.com" in plan.steps[1].arguments.get("url", "")


def test_plan_executor_execution():
    resolver = ToolResolver()
    executor = PlanExecutor()

    plan = resolver.resolve("Qual é o uso de memória do computador?")
    assert plan.success

    res = executor.execute_plan(plan)
    assert res["success"] is True
    assert "memória" in res["message"].lower() or "ram" in res["message"].lower()


def test_resolver_direct_file_path_and_window_actions():
    resolver = ToolResolver()

    # 1. Direct path with backslashes and drive letter -> open_file
    p_open_path = resolver.resolve(r"Abra C:\Users\Joao\Downloads\trabalho.pdf")
    assert p_open_path.success
    assert p_open_path.steps[0].tool == "open_file"
    assert "trabalho.pdf" in p_open_path.steps[0].arguments.get("path", "")

    # 2. Open file with extension
    p_open_file = resolver.resolve("Abra o arquivo notas.txt")
    assert p_open_file.success
    assert p_open_file.steps[0].tool == "open_file"
    assert "notas.txt" in p_open_file.steps[0].arguments.get("path", "")

    # 3. Window state command
    p_max = resolver.resolve("Maximize essa janela")
    assert p_max.success
    assert p_max.steps[0].tool == "maximize_window"

    # 4. Search with 'onde esta'
    p_onde = resolver.resolve("Onde está o trabalho.pdf?")
    assert p_onde.success
    assert p_onde.steps[0].tool == "search_file"
    assert "trabalho.pdf" in p_onde.steps[0].arguments.get("query", "")
