"""
Real system telemetry collector for Windows using psutil and platform.
"""
from datetime import datetime, timezone
import time
import platform
import psutil
from typing import Any, Dict, Optional


class SystemTelemetry:
    """
    Collects real-time hardware and OS metrics.
    """
    _boot_time: float = time.time()

    @staticmethod
    def get_cpu_percent() -> float:
        """
        Returns real CPU usage percentage (interval=None for non-blocking query).
        """
        try:
            return round(psutil.cpu_percent(interval=None), 1)
        except Exception:
            return 0.0

    @staticmethod
    def get_ram_info() -> Dict[str, Any]:
        """
        Returns real RAM usage in GB and percentage.
        """
        try:
            mem = psutil.virtual_memory()
            return {
                "percent": round(mem.percent, 1),
                "used_gb": round(mem.used / (1024 ** 3), 2),
                "total_gb": round(mem.total / (1024 ** 3), 2),
                "available_gb": round(mem.available / (1024 ** 3), 2)
            }
        except Exception:
            return {
                "percent": 0.0,
                "used_gb": 0.0,
                "total_gb": 0.0,
                "available_gb": 0.0
            }

    @staticmethod
    def get_os_info() -> Dict[str, str]:
        """
        Returns detailed OS and architecture information.
        """
        return {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor() or "x86_64"
        }

    @classmethod
    def get_uptime_seconds(cls) -> int:
        """
        Returns assistant process uptime in seconds.
        """
        return int(time.time() - cls._boot_time)

    @classmethod
    def format_uptime(cls, seconds: int) -> str:
        """
        Formats seconds into HH:MM:SS format.
        """
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @classmethod
    def snapshot(
        cls,
        assistant_state: str = "IDLE",
        voice_telemetry: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Generates a complete telemetry snapshot including hardware and voice pipeline stats.
        """
        uptime_sec = cls.get_uptime_seconds()
        ram = cls.get_ram_info()
        base_data = {
            "cpu_percent": cls.get_cpu_percent(),
            "ram_percent": ram["percent"],
            "ram_used_gb": ram["used_gb"],
            "ram_total_gb": ram["total_gb"],
            "uptime_seconds": uptime_sec,
            "uptime_formatted": cls.format_uptime(uptime_sec),
            "assistant_state": assistant_state,
            "os": cls.get_os_info(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            # Gemini Live Voice Subsystem (ADA V2 Blueprint)
            "microphone_available": True,
            "microphone_device": "Microfone Realtek (16kHz PCM)",
            "gemini_live_connected": False,
            "native_audio": True,
            "engine": "Gemini Live Native Audio",
            "model": "models/gemini-2.5-flash-native-audio-preview-12-2025",
        }
        if voice_telemetry:
            base_data.update(voice_telemetry)
        return base_data

    @staticmethod
    def get_disk_info() -> Dict[str, Any]:
        """
        Returns storage partition usage (total, used, free, percent).
        """
        disks = []
        msg_parts = []
        for part in psutil.disk_partitions(all=False):
            if "cdrom" in part.opts or part.fstype == "":
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
                total_gb = round(usage.total / (1024 ** 3), 1)
                free_gb = round(usage.free / (1024 ** 3), 1)
                used_gb = round(usage.used / (1024 ** 3), 1)
                disks.append({
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "total_gb": total_gb,
                    "used_gb": used_gb,
                    "free_gb": free_gb,
                    "percent": usage.percent,
                })
                msg_parts.append(f"Disco {part.device}: {free_gb} GB livres de {total_gb} GB ({usage.percent}% em uso)")
            except Exception:
                continue

        summary = "; ".join(msg_parts) if msg_parts else "Nenhum disco detectado."
        return {
            "success": True,
            "disks": disks,
            "message": summary,
        }

    @staticmethod
    def get_processes(limit: int = 10, search: Optional[str] = None) -> Dict[str, Any]:
        """
        Returns running processes filtered by search or ordered by memory usage.
        """
        procs = []
        clean_search = search.lower().strip() if search else None

        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info']):
            try:
                p_name = p.info['name'] or ""
                if clean_search and clean_search not in p_name.lower():
                    continue

                mem_mb = round(p.info['memory_info'].rss / (1024 * 1024), 1) if p.info['memory_info'] else 0.0
                procs.append({
                    "pid": p.info['pid'],
                    "name": p_name,
                    "memory_mb": mem_mb,
                    "memory_percent": round(p.info['memory_percent'] or 0.0, 1),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Sort by memory descending
        procs.sort(key=lambda x: x["memory_mb"], reverse=True)
        top = procs[:limit]

        if clean_search:
            msg = f"Encontrados {len(procs)} processos correspondentes a '{search}'."
        else:
            top_names = ", ".join(p['name'] for p in top[:3])
            msg = f"Atualmente {len(procs)} processos estão em execução. Principais por consumo: {top_names}."

        return {
            "success": True,
            "total_count": len(procs),
            "processes": top,
            "message": msg,
        }

    @staticmethod
    def get_datetime() -> Dict[str, Any]:
        """
        Returns formatted date, time, weekday, and timezone for Brazil / Local.
        """
        now = datetime.now()
        weekdays_pt = [
            "Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
            "Sexta-feira", "Sábado", "Domingo"
        ]
        weekday_name = weekdays_pt[now.weekday()]
        time_str = now.strftime("%H:%M")
        date_str = now.strftime("%d/%m/%Y")
        msg = f"Hoje é {weekday_name}, dia {date_str}, e agora são {time_str}."

        return {
            "success": True,
            "date": date_str,
            "time": time_str,
            "weekday": weekday_name,
            "timestamp_iso": now.isoformat(),
            "message": msg,
        }
