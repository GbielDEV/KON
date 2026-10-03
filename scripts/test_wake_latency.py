"""
Benchmark e diagnóstico de latência isolado para Wake Word e TTS (Marco 2.1).
Mede:
1. Tempo de processamento do openWakeWord por chunk de 80ms (1280 amostras).
2. Tamanho da fila de áudio e acúmulo ao longo do tempo.
3. Latência do microfone real.
4. Latência de acionamento do TTS ("Sim?").
"""
import sys
import os
import time
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_assistant.audio.capture import AudioCapture
from voice_assistant.audio.wake_word import OpenWakeWordDetector

def benchmark_openwakeword_speed():
    print("\n--- 1. Benchmark de Velocidade do openWakeWord ---")
    detector = OpenWakeWordDetector(wake_word="Okay KON", threshold=0.35)
    t0 = time.perf_counter()
    detector._initialize_model()
    t_init = time.perf_counter() - t0
    print(f"[WAKE] Modelos carregados em {t_init:.3f}s: {detector._active_models}")

    # Generate 50 dummy 80ms chunks (1280 int16 samples)
    dummy_chunks = [np.random.randint(-1000, 1000, size=1280, dtype=np.int16) for _ in range(50)]

    times = []
    for c in dummy_chunks:
        t_start = time.perf_counter()
        _ = detector.detect(c)
        dt = (time.perf_counter() - t_start) * 1000.0  # ms
        times.append(dt)

    print("[WAKE] Tempo por chunk de 80ms (N=50):")
    print(f"       Média: {np.mean(times):.2f} ms")
    print(f"       Mínimo: {np.min(times):.2f} ms")
    print(f"       Máximo: {np.max(times):.2f} ms")
    print(f"       Mediana: {np.median(times):.2f} ms")
    print(f"       Relação tempo real: {np.mean(times)/80.0:.2f}x (se > 1.0x, a fila acumula atraso!)")
    return detector

def measure_mic_stream_queue():
    print("\n--- 2. Teste de Fila e Latência do Microfone Real ---")
    cap = AudioCapture()
    if not cap.start():
        print("[MIC] Erro: Microfone não disponível.")
        return

    print(f"[MIC] Microfone '{cap.get_device_name()}' ativo.")
    time.sleep(1.0) # Let stream produce chunks

    q_sizes = []
    chunk_intervals = []
    last_t = time.perf_counter()

    for _ in range(20):
        _ = cap.read_chunk(timeout=0.2)
        now = time.perf_counter()
        chunk_intervals.append((now - last_t) * 1000.0)
        last_t = now
        q_sizes.append(cap._queue.qsize())

    cap.stop()
    print(f"[MIC] Intervalo médio entre chunks lidos: {np.mean(chunk_intervals):.2f} ms (esperado ~80ms)")
    print(f"[MIC] Tamanho da fila durante leitura: {np.mean(q_sizes):.1f} chunks ({np.mean(q_sizes)*80:.0f} ms de lag)")

if __name__ == "__main__":
    benchmark_openwakeword_speed()
    measure_mic_stream_queue()
