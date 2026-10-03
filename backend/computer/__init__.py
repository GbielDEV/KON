"""
Computer Automation & Hardware Services for KON Assistant.
Provides deterministic system access (Filesystem, System, Apps) and Computer Use (Mouse, Keyboard, Screen, Windows, Browser).
"""
from backend.computer.windows import WindowsService
from backend.computer.system import SystemTelemetry
from backend.computer.applications import ApplicationManager
from backend.computer.files import FileManager
from backend.computer.filesystem import FileSystemService
from backend.computer.mouse import MouseController
from backend.computer.keyboard import KeyboardController
from backend.computer.screen import ScreenService
from backend.computer.browser import ComputerBrowser
from backend.computer.computer_use import ComputerUseService
from backend.computer.uia import UIAutomationService

__all__ = [
    "WindowsService",
    "SystemTelemetry",
    "ApplicationManager",
    "FileManager",
    "FileSystemService",
    "MouseController",
    "KeyboardController",
    "ScreenService",
    "ComputerBrowser",
    "ComputerUseService",
    "UIAutomationService",
]
