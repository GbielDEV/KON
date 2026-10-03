"""
Windows UI Automation Service for KON Assistant.
Provides structured inspection of GUI accessibility trees, element coordinate resolution,
and native UI control using Windows UIAutomationCore API via comtypes.
"""
from __future__ import annotations

import ctypes
from typing import Dict, Any, List, Optional, Tuple

import win32gui
from backend.core.logger import kon_logger

user32 = ctypes.windll.user32

# Map of standard UI Automation Control Type IDs to human-readable names
CONTROL_TYPE_NAMES = {
    50000: "Button",
    50001: "Calendar",
    50002: "CheckBox",
    50003: "ComboBox",
    50004: "Edit",
    50005: "Hyperlink",
    50006: "Image",
    50008: "List",
    50009: "ListItem",
    50010: "Menu",
    50011: "MenuItem",
    50012: "ProgressBar",
    50013: "RadioButton",
    50014: "ScrollBar",
    50015: "Slider",
    50016: "Spinner",
    50017: "StatusBar",
    50018: "Tab",
    50019: "TabItem",
    50020: "Text",
    50021: "ToolBar",
    50022: "ToolTip",
    50023: "Tree",
    50024: "TreeItem",
    50025: "Custom",
    50026: "Group",
    50027: "Thumb",
    50028: "DataGrid",
    50029: "DataItem",
    50030: "Document",
    50031: "SplitButton",
    50032: "Window",
    50033: "Pane",
    50034: "Header",
    50035: "HeaderItem",
    50036: "Table",
    50037: "TitleBar",
    50038: "Separator",
}


class UIAutomationService:
    """
    Direct interface to Windows UI Automation accessibility infrastructure.
    Allows discovering buttons, text fields, tabs, and links with their exact desktop coordinates.
    """

    _uia_instance = None

    @classmethod
    def _get_uia(cls):
        """Initializes and caches the IUIAutomation COM instance."""
        if cls._uia_instance is None:
            try:
                import comtypes
                import comtypes.client

                # Ensure UIAutomationClient module is generated and loaded
                try:
                    from comtypes.gen import UIAutomationClient
                    _ = UIAutomationClient.CUIAutomation
                except (ImportError, AttributeError):
                    comtypes.client.GetModule("UIAutomationCore.dll")

                from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation
                cls._uia_instance = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
            except Exception as e:
                kon_logger.debug(f"[UIA] Não foi possível inicializar IUIAutomation COM: {e}")
                return None
        return cls._uia_instance

    @classmethod
    def inspect_window_elements(
        cls,
        hwnd: Optional[int] = None,
        max_elements: int = 40,
    ) -> List[Dict[str, Any]]:
        """
        Inspects structured interactive elements (buttons, inputs, links, tabs)
        in the target window (or foreground window if hwnd is omitted).
        Returns a list of elements with their names, types, bounding boxes, and center coordinates.
        """
        target_hwnd = hwnd or win32gui.GetForegroundWindow()
        elements: List[Dict[str, Any]] = []

        uia = cls._get_uia()
        if not uia:
            return elements

        try:
            from comtypes.gen.UIAutomationClient import TreeScope_Descendants

            root_element = uia.ElementFromHandle(target_hwnd) if target_hwnd else uia.GetRootElement()
            if not root_element:
                return elements

            true_cond = uia.CreateTrueCondition()
            all_elements = root_element.FindAll(TreeScope_Descendants, true_cond)
            count = all_elements.Length

            for i in range(min(count, 200)):
                try:
                    el = all_elements.GetElement(i)
                    name = el.CurrentName
                    ctl_id = el.CurrentControlType
                    ctl_type = CONTROL_TYPE_NAMES.get(ctl_id, "Element")

                    if name and len(name.strip()) > 0:
                        rect = el.CurrentBoundingRectangle
                        w = rect.right - rect.left
                        h = rect.bottom - rect.top
                        # Keep only valid interactive elements with visible size
                        if w > 4 and h > 4:
                            center_x = rect.left + w // 2
                            center_y = rect.top + h // 2
                            elements.append({
                                "name": name.strip(),
                                "type": ctl_type,
                                "bounds": {
                                    "x": rect.left,
                                    "y": rect.top,
                                    "width": w,
                                    "height": h,
                                    "right": rect.right,
                                    "bottom": rect.bottom,
                                },
                                "center": [center_x, center_y],
                            })
                            if len(elements) >= max_elements:
                                break
                except Exception:
                    continue

        except Exception as exc:
            kon_logger.debug(f"[UIA] Erro na inspeção de elementos da janela {target_hwnd}: {exc}")

        return elements

    @classmethod
    def find_element(
        cls,
        query: str,
        control_type: Optional[str] = None,
        hwnd: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Searches for a specific interactive element by name/label (case-insensitive)
        and optional control_type (e.g. 'Button', 'Edit', 'TabItem').
        Returns element dictionary with center coordinates if found.
        """
        clean_q = query.strip().lower()
        elements = cls.inspect_window_elements(hwnd=hwnd, max_elements=80)

        # 1. Exact match
        for el in elements:
            el_name = el["name"].lower()
            if el_name == clean_q:
                if not control_type or el["type"].lower() == control_type.lower():
                    return el

        # 2. Substring match
        for el in elements:
            el_name = el["name"].lower()
            if clean_q in el_name:
                if not control_type or el["type"].lower() == control_type.lower():
                    return el

        return None

    @classmethod
    def get_element_coordinates(
        cls,
        query: str,
        control_type: Optional[str] = None,
        hwnd: Optional[int] = None,
    ) -> Optional[Tuple[int, int]]:
        """
        Returns the (x, y) center desktop coordinates of an element matching query.
        """
        match = cls.find_element(query, control_type=control_type, hwnd=hwnd)
        if match and "center" in match:
            return match["center"][0], match["center"][1]
        return None
