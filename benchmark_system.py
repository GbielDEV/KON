"""
System Benchmark for KON Architecture Refactoring.
Measures:
1. Boot & Initialization Time (Orchestrator, ToolRegistry, Planner, LoopGuard)
2. STT Warmup & Transcription Time (faster-whisper optimized settings)
3. Tool Resolution & Multi-step Planning Latency
4. RAM Memory Footprint
"""
import time
import os
import psutil
import numpy as np

def measure_benchmark():
    print("=" * 60)
    print("   KON ARCHITECTURE REFACTORING - BENCHMARK EXECUTION")
    print("=" * 60)

    process = psutil.Process(os.getpid())
    ram_initial_mb = process.memory_info().rss / (1024 * 1024)
    print(f"[*] Initial Process RAM: {ram_initial_mb:.2f} MB")

    # 1. Orchestrator / NLU Boot Time
    t0 = time.perf_counter()
    from voice_assistant.core.state_machine import VoicePipelineOrchestrator
    orchestrator = VoicePipelineOrchestrator()
    t_boot = time.perf_counter() - t0
    print(f"[1] Orchestrator + Planner Boot Time: {t_boot:.3f} s")

    # 2. Tool Resolution Latency (Single & Multi-step)
    test_commands = [
        "abra o google chrome",
        "abra o bloco de notas e depois abra a pasta documentos",
        "crie uma pasta chamada TesteKON na pasta downloads",
        "tire um print da tela",
        "qual o uso de memoria do computador",
        "pesquise clima hoje no google",
        "fechar google chrome"
    ]
    t0 = time.perf_counter()
    for cmd in test_commands:
        plan = orchestrator.tool_resolver.resolve(cmd)
        assert plan.success, f"Failed to resolve: {cmd}"
    t_plan_total = time.perf_counter() - t0
    t_plan_avg = (t_plan_total / len(test_commands)) * 1000
    print(f"[2] Planner Average Latency (7 diverse commands): {t_plan_avg:.2f} ms")

    # 3. Whisper STT Benchmark
    t0 = time.perf_counter()
    from voice_assistant.stt.whisper_engine import WhisperSTTEngine
    stt = WhisperSTTEngine(model_size="small")
    stt.preload()
    t_stt_load = time.perf_counter() - t0
    print(f"[3] Whisper STT Load Time: {t_stt_load:.3f} s")

    # Generate 2.5 seconds of synthetic audio (silence / tone)
    sample_rate = 16000
    duration = 2.5
    synthetic_audio = (np.sin(2 * np.pi * 440 * np.linspace(0, duration, int(sample_rate * duration))) * 1000).astype(np.int16).tobytes()

    t0 = time.perf_counter()
    _ = stt.transcribe(synthetic_audio)
    t_stt_transcribe = time.perf_counter() - t0
    print(f"[4] Whisper STT Transcription Latency (2.5s audio): {t_stt_transcribe:.3f} s")

    # 4. RAM Usage After Full Load
    ram_final_mb = process.memory_info().rss / (1024 * 1024)
    sys_mem = psutil.virtual_memory()
    print(f"[5] Process RAM Post-Load: {ram_final_mb:.2f} MB")
    print(f"[6] Total System RAM Used: {sys_mem.used / (1024**3):.2f} GB / {sys_mem.total / (1024**3):.2f} GB ({sys_mem.percent}%)")
    print("=" * 60)
    print("BENCHMARK COMPLETED SUCCESSFULLY.")

if __name__ == "__main__":
    measure_benchmark()
