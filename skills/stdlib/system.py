"""skills.stdlib.system — volume and brightness controls with fallback methods."""


def volume_mute_then_set(target_level: int) -> dict:
    """
    Set system volume to an exact percentage.

    Method 1 (preferred): pycaw Windows Core Audio API — instant and precise.
    Method 2 (fallback):  simulated keystrokes — slow but always available.

    Args:
        target_level: Target volume level (0-100)

    Returns:
        dict with success, method used, value, and message.
    """
    target_level = max(0, min(100, int(target_level)))

    # ── Method 1: pycaw (instant, exact) ─────────────────────────────────────
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMasterVolumeLevelScalar(target_level / 100.0, None)
        return {
            "success": True,
            "action": "volume_mute_then_set",
            "method": "pycaw",
            "value": target_level,
            "message": f"Volume set to {target_level}% via Windows Core Audio.",
        }
    except Exception:
        pass  # pycaw unavailable — fall through to keypress method

    # ── Method 2: keypress simulation (fallback) ──────────────────────────────
    import pyautogui
    import time

    try:
        # Drive volume to 0 (50 presses @ ≈2% each covers full range)
        for _ in range(50):
            pyautogui.press("volumedown")
            time.sleep(0.02)
        time.sleep(0.05)

        if target_level > 0:
            presses_needed = target_level // 2
            for _ in range(presses_needed):
                pyautogui.press("volumeup")
                time.sleep(0.05)

        return {
            "success": True,
            "action": "volume_mute_then_set",
            "method": "keypress_simulation",
            "value": target_level,
            "message": f"Volume set to ~{target_level}% via keypress simulation (pycaw unavailable).",
        }
    except Exception as e:
        return {
            "success": False,
            "action": "volume_mute_then_set",
            "methods_tried": ["pycaw", "keypress_simulation"],
            "error": str(e),
        }


def brightness_set_robust(target_level: int) -> dict:
    """
    Set screen brightness using three fallback methods for maximum reliability.
    
    Methods tried in sequence:
    1. screen_brightness_control library (most reliable)
    2. WMI PowerShell (Windows native)
    3. Keyboard simulation (ultimate fallback)
    
    Args:
        target_level: Target brightness level (0-100)
    
    Returns:
        dict with success status, method used, and result details
    """
    import time
    
    # Clamp value
    target_level = max(0, min(100, int(target_level)))
    
    # Method 1: screen_brightness_control library
    try:
        import screen_brightness_control as sbc
        current = sbc.get_brightness()
        sbc.set_brightness(target_level)
        # Verify the change
        new_brightness = sbc.get_brightness()
        if abs(new_brightness - target_level) <= 5:  # Allow small tolerance
            return {
                "success": True,
                "action": "brightness_set_robust",
                "method": "screen_brightness_control",
                "value": target_level,
                "previous_value": current,
                "message": f"Brightness set to {target_level}% using screen_brightness_control library."
            }
    except Exception:
        pass  # Fall through to next method
    
    # Method 2: WMI PowerShell (Windows native)
    try:
        import subprocess
        powershell_script = f"""
        $brightness = {target_level}
        $wmi = Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods
        $wmi.WmiSetBrightness(1, $brightness)
        """
        result = subprocess.run(
            ["powershell", "-Command", powershell_script],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return {
                "success": True,
                "action": "brightness_set_robust",
                "method": "wmi_powershell",
                "value": target_level,
                "message": f"Brightness set to {target_level}% using WMI PowerShell."
            }
    except Exception:
        pass  # Fall through to next method
    
    # Method 3: Keyboard simulation (ultimate fallback)
    try:
        import pyautogui
        
        # First get current brightness if possible, otherwise estimate
        # Press brightness keys to reach target
        # Assume each keypress changes brightness by ~5%
        brightness_step = 5
        
        # Try to decrease brightness first (in case we're above target)
        presses_down = 100 // brightness_step  # Max presses to go to 0
        for _ in range(presses_down):
            pyautogui.press('brightnessdown')
            time.sleep(0.05)
        
        time.sleep(0.3)
        
        # Now increase to target
        presses_up = target_level // brightness_step
        for _ in range(presses_up):
            pyautogui.press('brightnessup')
            time.sleep(0.05)
        
        return {
            "success": True,
            "action": "brightness_set_robust",
            "method": "keyboard_simulation",
            "value": target_level,
            "message": f"Brightness set to {target_level}% using keyboard simulation (fallback method)."
        }
    except Exception as e:
        return {
            "success": False,
            "action": "brightness_set_robust",
            "methods_tried": ["screen_brightness_control", "wmi_powershell", "keyboard_simulation"],
            "error": str(e),
            "message": "All brightness control methods failed."
        }
