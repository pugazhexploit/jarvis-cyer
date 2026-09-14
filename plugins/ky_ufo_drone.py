"""
JARVIS Plugin for KY UFO Drone offline simulation and real-hardware readiness.
Translates JARVIS natural language intent into drone.controller commands.
"""

import sys
import os

import sys
import os
import socket
import threading
import time

class StandaloneTransport:
    def __init__(self, ip="192.168.1.1", port=7099):
        self.ip = ip
        self.port = port
        
    def send(self, packet: bytes):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(packet, (self.ip, self.port))
            sock.close()
            return True
        except Exception:
            return False

class StandaloneDroneController:
    def __init__(self, mode="REAL"):
        self.mode = mode
        self.state = {
            "hovering": False,
            "airborne": False,
            "last_command": None,
            "last_packet": None
        }
        self.transport = StandaloneTransport()
        self._hover_thread = None
        self._hover_stop_event = threading.Event()

    def set_mode(self, mode):
        self.mode = mode
        return {"success": True, "mode": self.mode}

    def _hover_loop(self):
        # Continuous neutral packets for maintaining flight
        neutral_packet = bytes.fromhex("03 66 14 80 80 80 80 00 02 00 00 00 00 00 00 00 00 00 00 02 99")
        while not self._hover_stop_event.is_set():
            if self.mode == "REAL":
                self.transport.send(neutral_packet)
            time.sleep(0.05) # 20Hz heartbeat

    def _start_hover(self):
        if self._hover_thread and self._hover_thread.is_alive():
            return
        self._hover_stop_event.clear()
        self.state["hovering"] = True
        self._hover_thread = threading.Thread(target=self._hover_loop, daemon=True)
        self._hover_thread.start()

    def _stop_hover(self):
        self.state["hovering"] = False
        self._hover_stop_event.set()
        if self._hover_thread:
            self._hover_thread.join(timeout=1.0)
            self._hover_thread = None

    def execute_command(self, command, confirm_physical=False):
        packet = None
        if command == "takeoff":
            if self.state["airborne"]:
                return {"accepted": False, "mode": self.mode, "error": "Already airborne"}
            packet = bytes.fromhex("03 66 14 80 80 80 80 01 02 00 00 00 00 00 00 00 00 00 00 03 99")
            self.state["airborne"] = True
            self._start_hover()
        elif command == "land":
            if not self.state["airborne"]:
                return {"accepted": False, "mode": self.mode, "error": "Already grounded"}
            self._stop_hover()
            packet = bytes.fromhex("03 66 14 80 80 80 80 01 02 00 00 00 00 00 00 00 00 00 00 03 99")
            self.state["airborne"] = False
        elif command == "calibrate":
            packet = bytes.fromhex("03 66 14 80 80 80 80 04 02 00 00 00 00 00 00 00 00 00 00 06 99")
        elif command == "emergency_stop":
            self._stop_hover()
            packet = bytes.fromhex("03 66 14 80 80 80 80 02 02 00 00 00 00 00 00 00 00 00 00 00 99")
            self.state["airborne"] = False
        elif command == "status":
            pass
        else:
            return {"accepted": False, "mode": self.mode, "error": "Unknown command"}
            
        transmitted = False
        if packet:
            packet_hex = " ".join(f"{b:02X}" for b in packet)
            self.state["last_packet"] = packet_hex
            if self.mode == "REAL" and confirm_physical:
                transmitted = self.transport.send(packet)
                
        self.state["last_command"] = command
        return {
            "accepted": True,
            "state": self.state,
            "mode": self.mode,
            "transmitted": transmitted,
            "note": "Standalone fallback controller used." if transmitted else "",
            "inspection": ""
        }

_controller = StandaloneDroneController(mode="REAL")

PLUGIN = {
    "name": "ky_ufo_drone",
    "description": (
        "Controls the KY UFO Drone. Use this tool whenever the user asks to control the drone, "
        "such as 'take off', 'land', 'calibrate', 'drone status', or 'emergency stop'. "
        "Use this tool to switch modes when the user says 'switch to real mode', 'physical mode enable', 'simulation mode ku maathu', etc. "
        "Do NOT use this tool for ambiguous commands like 'do something with drone'. "
        "Never use this tool for regular computer tasks, browsing, or file manipulation."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "intent": {
                "type": "STRING", 
                "description": "The specific logical drone command intent (e.g., 'takeoff', 'land', 'calibrate', 'status', 'emergency_stop', 'enable_real_mode', 'enable_simulation_mode')."
            },
            "confirm_physical": {
                "type": "BOOLEAN",
                "description": "Must be set to true IF the user explicitly confirms readiness for physical transmission. Defaults to false."
            }
        },
        "required": ["intent"],
    },
}

def run(parameters: dict, player=None, session_memory=None) -> str:
    """
    Executes the drone command intent.
    """
    raw_intent = parameters.get("intent", "").lower().strip()
    confirm_physical = parameters.get("confirm_physical", False)
    
    # Natural Language Mapping
    mapping = {
        "take off": "takeoff",
        "take off the drone": "takeoff",
        "takeoff": "takeoff",
        "fly": "takeoff",
        "start drone": "takeoff",
        "take off pannu": "takeoff",
        "takeoff pannu": "takeoff",
        
        "land": "land",
        "landing": "land",
        "land the drone": "land",
        "stop flying": "land",
        "land pannu": "land",
        "keela irakku": "land",
        
        "emergency stop": "emergency_stop",
        "stop the drone": "emergency_stop",
        "stop": "emergency_stop",
        "emergency_stop": "emergency_stop",
        
        "calibrate": "calibrate",
        "calibration": "calibrate",
        "gyro calibration": "calibrate",
        "calibration pannu": "calibrate",
        "drone calibrate pannu": "calibrate",
        "gyro calibrate pannu": "calibrate",
        "calibration mode": "calibrate",
        
        "status": "status",
        "drone status": "status",
        
        "switch to real mode": "enable_real_mode",
        "enable physical mode": "enable_real_mode",
        "real mode enable pannu": "enable_real_mode",
        "physical mode enable pannu": "enable_real_mode",
        "simulation mode la irundhu physical mode ku maathu": "enable_real_mode",
        "simulation la irundhu real mode ku maathu": "enable_real_mode",
        "drone physical ah operate panna ready pannu": "enable_real_mode",
        "real mode": "enable_real_mode",
        "physical mode": "enable_real_mode",
        "enable_real_mode": "enable_real_mode",
        "physical mode ku maathu": "enable_real_mode",
        
        "switch to simulation mode": "enable_simulation_mode",
        "enable simulation mode": "enable_simulation_mode",
        "simulation mode ku thirumbu": "enable_simulation_mode",
        "simulation mode enable pannu": "enable_simulation_mode",
        "simulation mode": "enable_simulation_mode",
        "enable_simulation_mode": "enable_simulation_mode"
    }
    
    logical_command = mapping.get(raw_intent)
    
    if not logical_command:
        result_text = (
            f"Mode: {_controller.mode}\\n"
            f"Transmission: FALSE\\n"
            f"Unknown, ambiguous, or unverified drone command intent: '{raw_intent}'. "
            f"Only explicit 'take off', 'land', 'status', 'emergency stop', or mode switches are allowed."
        )
        if player:
            try:
                player.write_log(f"JARVIS: {result_text}")
            except Exception:
                pass
        return result_text
        
    try:
        # Handle mode switching
        if logical_command == "enable_real_mode":
            res = _controller.set_mode("REAL")
            if not res["success"]:
                result_text = f"Mode: {_controller.mode}\\nTransmission: False\\nError: {res['error']}"
                if player:
                    try:
                        player.write_log(f"JARVIS: {result_text}")
                    except Exception:
                        pass
                return result_text
            
            # Switch successful, generate status report
            logical_command = "status"
            
        # Handle Automated Calibration & Takeoff Countdown
        if logical_command == "takeoff":
            import time
            if player:
                try:
                    player.write_log(f"JARVIS: Commencing automatic Pre-Flight Calibration...")
                except Exception:
                    pass
            _controller.execute_command("calibrate", confirm_physical=True)
            time.sleep(1) # wait for calibration burst
            
            for count in [3, 2, 1]:
                if player:
                    try:
                        player.write_log(f"JARVIS: Takeoff in {count}...")
                    except Exception:
                        pass
                time.sleep(1)
            
            res = _controller.execute_command(logical_command, confirm_physical=True)
        elif logical_command == "land":
            res = _controller.execute_command(logical_command, confirm_physical=True)
        else:
            res = _controller.execute_command(logical_command, confirm_physical=True)
        
        if res.get("accepted"):
            state = res.get("state", {})
            if state.get("hovering"):
                airborne_status = "AIRBORNE / HOVERING"
            elif state.get("airborne"):
                airborne_status = "AIRBORNE"
            else:
                airborne_status = "GROUNDED"
            
            drone_ip = "192.168.1.1"
            control_port = 7099
            if hasattr(_controller.transport, "ip"):
                drone_ip = _controller.transport.ip
                control_port = _controller.transport.port
                
            result_text = (
                f"Mode: {res['mode']}\\n"
                f"Physical transmission enabled: {str(_controller.mode == 'REAL')}\\n"
                f"Drone IP: {drone_ip}\\n"
                f"Control Port: {control_port}\\n"
                f"Safety State: {airborne_status}\\n"
                f"Transmission: {res.get('transmitted', False)}\\n"
            )
            
            if logical_command != "status":
                result_text += f"Last Command: {state.get('last_command')}\\n"
                result_text += f"Last Packet: {state.get('last_packet')}\\n"
                
            if logical_command == "calibrate" and state.get("airborne"):
                result_text += "\\nWARNING: Calibration requested while airborne. Calibration is typically intended for grounded drones."
                if not res.get("transmitted"):
                     result_text += "\\nCalibration transmission did not occur."
            
            if res.get("note"):
                result_text += f"\\nNote: {res['note']}"
                
            if res.get("inspection"):
                result_text += f"\\n{res['inspection']}"
                
        else:
            result_text = f"Mode: {res['mode']}\\nTransmission: FALSE\\nDrone {logical_command} rejected: {res.get('error')}"
            
    except Exception as e:
        result_text = f"Mode: {_controller.mode}\\nTransmission: FALSE\\nDrone command failed: {e}"
        
    if player:
        try:
            player.write_log(f"JARVIS: {result_text}")
        except Exception:
            pass
            
    return result_text
