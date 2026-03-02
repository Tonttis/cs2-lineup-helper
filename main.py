import sys
import os
import json
import time
import math
import struct
import ctypes
import threading
import requests
import win32api
import win32con
import numpy as np
from numba import njit
from ctypes import wintypes
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QPointF
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtGui import QPainter, QPen, QColor, QFont
from PyQt5.QtGui import QPolygonF
 
STATUS_SUCCESS = 0x00000000
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
SystemExtendedHandleInformation = 64
SeDebugPrivilege = 20
 
PROCESS_DUP_HANDLE = 0x0040
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
FULL_RIGHTS = PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION
 
PRIORITY_PROCESSES = ["steam.exe", "lsass.exe"]
 
 
class SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX(ctypes.Structure):
    _fields_ = [
        ("Object", ctypes.c_void_p),
        ("UniqueProcessId", ctypes.c_void_p),
        ("HandleValue", ctypes.c_void_p),
        ("GrantedAccess", ctypes.c_uint32),
        ("CreatorBackTraceIndex", ctypes.c_uint16),
        ("ObjectTypeIndex", ctypes.c_uint16),
        ("HandleAttributes", ctypes.c_uint32),
        ("Reserved", ctypes.c_uint32),
    ]
 
 
class MemoryManager:
    def __init__(self, process_name="cs2.exe"):
        self.process_name = process_name
        self.pid = 0
        self.handle = None
        self.client_dll_base = 0
        self.hijacked = False
        self.cache_file = "hijack_cache.json"
 
        self.kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.ntdll = ctypes.WinDLL('ntdll', use_last_error=True)
        self._setup_functions()
 
    def _setup_functions(self):
        self.ReadProcessMemory = self.kernel32.ReadProcessMemory
        self.ReadProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID,
                                           ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self.ReadProcessMemory.restype = wintypes.BOOL
 
        self.WriteProcessMemory = self.kernel32.WriteProcessMemory
        self.WriteProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPCVOID,
                                            ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self.WriteProcessMemory.restype = wintypes.BOOL
 
        self.CloseHandle = self.kernel32.CloseHandle
        self.CloseHandle.argtypes = [wintypes.HANDLE]
 
        self.RtlAdjustPrivilege = self.ntdll.RtlAdjustPrivilege
        self.RtlAdjustPrivilege.argtypes = [ctypes.c_ulong, ctypes.c_bool,
                                             ctypes.c_bool, ctypes.POINTER(ctypes.c_bool)]
 
        self.NtQuerySystemInformation = self.ntdll.NtQuerySystemInformation
        self.NtQuerySystemInformation.argtypes = [ctypes.c_ulong, ctypes.c_void_p,
                                                   ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
        self.NtQuerySystemInformation.restype = ctypes.c_ulong
 
        self.NtDuplicateObject = self.ntdll.NtDuplicateObject
        self.NtDuplicateObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                            ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                            wintypes.DWORD, wintypes.DWORD]
        self.NtDuplicateObject.restype = ctypes.c_ulong
 
    def enable_debug_privilege(self):
        enabled = ctypes.c_bool()
        status = self.RtlAdjustPrivilege(SeDebugPrivilege, True, False, ctypes.byref(enabled))
        return status == 0 or status == 0xC0000002
 
    def get_pid_by_name(self, name):
        TH32CS_SNAPPROCESS = 0x00000002
        snapshot = self.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == -1:
            return 0
 
        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_char * 260)]
 
        pe32 = PROCESSENTRY32()
        pe32.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not self.kernel32.Process32First(snapshot, ctypes.byref(pe32)):
            self.kernel32.CloseHandle(snapshot)
            return 0
 
        found_pid = 0
        while True:
            try:
                exe_name = pe32.szExeFile.decode('utf-8', errors='ignore').lower()
                if exe_name == name.lower():
                    found_pid = pe32.th32ProcessID
                    break
            except:
                pass
            if not self.kernel32.Process32Next(snapshot, ctypes.byref(pe32)):
                break
        self.kernel32.CloseHandle(snapshot)
        return found_pid
 
    def load_cache(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f).get('last_pid', 0)
            except:
                pass
        return 0
 
    def save_cache(self, pid):
        try:
            with open(self.cache_file, 'w') as f:
                json.dump({'last_pid': pid}, f)
        except:
            pass
 
    def try_hijack_specific_pid(self, buffer, handle_count, target_pid):
        offset = 16
        entry_size = ctypes.sizeof(SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX)
        source_process = self.kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, target_pid)
        if not source_process:
            return None
        found_handle_val = None
        for i in range(handle_count):
            current_pid = struct.unpack_from("Q", buffer, offset + 8)[0]
            if current_pid == target_pid:
                entry = SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX.from_buffer(buffer, offset)
                dup_handle = wintypes.HANDLE()
                status = self.NtDuplicateObject(
                    source_process, wintypes.HANDLE(entry.HandleValue),
                    self.kernel32.GetCurrentProcess(), ctypes.byref(dup_handle),
                    FULL_RIGHTS, 0, 0
                )
                if status == STATUS_SUCCESS:
                    if self.kernel32.GetProcessId(dup_handle) == self.pid:
                        found_handle_val = dup_handle.value
                        break
                    self.kernel32.CloseHandle(dup_handle)
            offset += entry_size
        self.kernel32.CloseHandle(source_process)
        return found_handle_val
 
    def hijack_handle(self):
        if not self.enable_debug_privilege():
            return None
        size = 0x100000
        return_length = ctypes.c_ulong()
        while True:
            buffer = ctypes.create_string_buffer(size)
            status = self.NtQuerySystemInformation(SystemExtendedHandleInformation, buffer,
                                                    size, ctypes.byref(return_length))
            if status == STATUS_SUCCESS:
                break
            elif status == STATUS_INFO_LENGTH_MISMATCH:
                size = return_length.value + 0x2000
            else:
                return None
 
        handle_count = struct.unpack_from("Q", buffer, 0)[0]
 
        cached_pid = self.load_cache()
        if cached_pid > 0:
            handle = self.try_hijack_specific_pid(buffer, handle_count, cached_pid)
            if handle:
                print(f"[Lineup] Handle found via cache (PID {cached_pid}) <<<")
                return handle
 
        priority_pids = []
        for name in PRIORITY_PROCESSES:
            pid = self.get_pid_by_name(name)
            if pid > 0 and pid != self.pid:
                priority_pids.append(pid)
        for p_pid in priority_pids:
            handle = self.try_hijack_specific_pid(buffer, handle_count, p_pid)
            if handle:
                print(f"[Lineup] Handle found via priority process (PID {p_pid}) <<<")
                self.save_cache(p_pid)
                return handle
 
        print("[Lineup] Brute force")
        offset = 16
        entry_size = ctypes.sizeof(SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX)
        my_pid = self.kernel32.GetCurrentProcessId()
        for i in range(handle_count):
            entry = SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX.from_buffer(buffer, offset)
            offset += entry_size
            pid_val = int(entry.UniqueProcessId)
            if pid_val == my_pid or pid_val in (0, 4):
                continue
            if pid_val in priority_pids or pid_val == cached_pid:
                continue
            source_process = self.kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, pid_val)
            if not source_process:
                continue
            dup_handle = wintypes.HANDLE()
            status = self.NtDuplicateObject(
                source_process, wintypes.HANDLE(entry.HandleValue),
                self.kernel32.GetCurrentProcess(), ctypes.byref(dup_handle),
                FULL_RIGHTS, 0, 0
            )
            if status == STATUS_SUCCESS:
                if self.kernel32.GetProcessId(dup_handle) == self.pid:
                    print(f"\n[Lineup] Handle found via brute force (PID {pid_val}) <<<")
                    self.save_cache(pid_val)
                    self.kernel32.CloseHandle(source_process)
                    return dup_handle.value
                self.kernel32.CloseHandle(dup_handle)
            self.kernel32.CloseHandle(source_process)
            if i % 10000 == 0:
                print(f"  Scanned {i}/{handle_count}...", end='\r')
        return None
 
    def get_module_base(self, module_name):
        TH32CS_SNAPMODULE = 0x00000018
        snapshot = self.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, self.pid)
        if snapshot == -1:
            return 0
 
        class MODULEENTRY32(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD), ("GlblcntUsage", wintypes.DWORD),
                        ("ProccntUsage", wintypes.DWORD),
                        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
                        ("modBaseSize", wintypes.DWORD), ("hModule", wintypes.HMODULE),
                        ("szModule", ctypes.c_char * 256), ("szExePath", ctypes.c_char * 260)]
 
        me32 = MODULEENTRY32()
        me32.dwSize = ctypes.sizeof(MODULEENTRY32)
        if not self.kernel32.Module32First(snapshot, ctypes.byref(me32)):
            self.kernel32.CloseHandle(snapshot)
            return 0
 
        base_addr = 0
        while True:
            try:
                if me32.szModule.decode('utf-8', errors='ignore').lower() == module_name.lower():
                    base_addr = ctypes.cast(me32.modBaseAddr, ctypes.c_void_p).value
                    break
            except:
                pass
            if not self.kernel32.Module32Next(snapshot, ctypes.byref(me32)):
                break
        self.kernel32.CloseHandle(snapshot)
        return base_addr
 
    def attach(self):
        self.pid = self.get_pid_by_name(self.process_name)
        if self.pid == 0:
            print("[Lineup] CS2 not found.")
            return False
        print(f"[Lineup] Found CS2 PID: {self.pid}")
        hijacked = self.hijack_handle()
        if hijacked:
            self.handle = hijacked
            self.hijacked = True
            print("[Lineup] Handle hijack OK.")
        else:
            print("[Lineup] Hijack failed. Using standard handle.")
            self.handle = self.kernel32.OpenProcess(FULL_RIGHTS, False, self.pid)
            self.hijacked = False
        if not self.handle:
            return False
        self.client_dll_base = self.get_module_base("client.dll")
        return bool(self.client_dll_base)
 
    def close(self):
        if self.handle:
            self.CloseHandle(self.handle)
            self.handle = None
 
    def read_bytes(self, address, size):
        if not self.handle or address <= 0:
            return None
        buffer = ctypes.create_string_buffer(size)
        bytes_read = ctypes.c_size_t()
        if self.ReadProcessMemory(self.handle, ctypes.c_void_p(address),
                                   buffer, size, ctypes.byref(bytes_read)):
            return buffer.raw
        return None
 
    def read_int(self, addr):
        d = self.read_bytes(addr, 4)
        return struct.unpack('<i', d)[0] if d else 0
 
    def read_short(self, addr):
        d = self.read_bytes(addr, 2)
        return struct.unpack('<h', d)[0] if d else 0
 
    def read_ulonglong(self, addr):
        d = self.read_bytes(addr, 8)
        return struct.unpack('<Q', d)[0] if d else 0
 
    def read_longlong(self, addr):
        d = self.read_bytes(addr, 8)
        return struct.unpack('<q', d)[0] if d else 0
 
    def read_bool(self, addr):
        d = self.read_bytes(addr, 1)
        return d[0] != 0 if d else False
 
    def read_string(self, addr, max_len=128):
        data = self.read_bytes(addr, max_len)
        if not data:
            return ""
        try:
            return data.split(b'\0')[0].decode('utf-8', errors='ignore')
        except:
            return ""
 
def load_offsets():
    offsets = _fallback_offsets()
 
    try:
        print("[Lineup] Fetching latest offsets...")
        off_data = requests.get(
            'https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json',
            timeout=5
        ).json()
        cli_data = requests.get(
            'https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json',
            timeout=5
        ).json()
 
        classes = cli_data.get('client.dll', {}).get('classes', {})
 
        def get(data, path, fallback):
            try:
                v = data
                for k in path:
                    v = v[k]
                return v
            except:
                return fallback
 
        offsets['dwLocalPlayerPawn']     = get(off_data, ['client.dll', 'dwLocalPlayerPawn'],     offsets['dwLocalPlayerPawn'])
        offsets['dwViewMatrix']          = get(off_data, ['client.dll', 'dwViewMatrix'],           offsets['dwViewMatrix'])
        offsets['dwViewAngles']          = get(off_data, ['client.dll', 'dwViewAngles'],           offsets['dwViewAngles'])
        offsets['dwGlobalVars']          = get(off_data, ['client.dll', 'dwGlobalVars'],           offsets['dwGlobalVars'])
 
        offsets['m_iTeamNum']            = get(classes, ['C_BaseEntity',     'fields', 'm_iTeamNum'],            offsets['m_iTeamNum'])
        offsets['m_vOldOrigin']          = get(classes, ['C_BasePlayerPawn', 'fields', 'm_vOldOrigin'],          offsets['m_vOldOrigin'])
        offsets['m_pClippingWeapon']     = get(classes, ['C_CSPlayerPawn',   'fields', 'm_pClippingWeapon'],     offsets['m_pClippingWeapon'])
        offsets['m_AttributeManager']    = get(classes, ['C_EconEntity',     'fields', 'm_AttributeManager'],    offsets['m_AttributeManager'])
        offsets['m_Item']                = get(classes, ['C_AttributeContainer', 'fields', 'm_Item'],            offsets['m_Item'])
        offsets['m_iItemDefinitionIndex']= get(classes, ['C_EconItemView',   'fields', 'm_iItemDefinitionIndex'],offsets['m_iItemDefinitionIndex'])
 
        print("[Lineup] Offsets updated successfully.")
    except Exception as e:
        print(f"[Lineup] Could not fetch offsets online ({e}). Using fallback.")
 
    return offsets
 
 
def _fallback_offsets():
    return {
        'dwLocalPlayerPawn':       0x0,
        'dwViewMatrix':            0x0,
        'dwViewAngles':            0x0,
        'dwGlobalVars':            0x0,
        'm_iTeamNum':              0x0,
        'm_vOldOrigin':            0x0,
        'm_pClippingWeapon':       0x0,
        'm_AttributeManager':      0x0,
        'm_Item':                  0x0,
        'm_iItemDefinitionIndex':  0x0,
    }
 
class MapReader:
    def __init__(self, pm, client, offsets):
        self.pm = pm
        self.client = client
        self.offsets = offsets
 
    def get_map_name(self):
        try:
            gv = self.offsets.get('dwGlobalVars')
            if not gv:
                return None
            global_vars = self.pm.read_longlong(self.client + gv)
            if not global_vars:
                return None
            map_name_ptr = self.pm.read_longlong(global_vars + 0x180)
            if not map_name_ptr:
                return None
            raw = self.pm.read_string(map_name_ptr)
            if raw:
                clean = raw.replace("maps/", "").replace("maps\\", "").replace(".vpk", "")
                if clean.startswith("de_"):
                    clean = clean[3:]
                elif clean.startswith("cs_"):
                    clean = clean[3:]
                return clean
        except:
            pass
        return None

@njit(fastmath=True, cache=True)
def world_to_screen_fast(pos_x, pos_y, pos_z, vm, width, height):
    w = pos_x * vm[12] + pos_y * vm[13] + pos_z * vm[14] + vm[15]
    if w < 0.01:
        return -1.0, -1.0
    inv = 1.0 / w
    sx = (width / 2.0) * (1.0 + (pos_x * vm[0] + pos_y * vm[1] + pos_z * vm[2] + vm[3]) * inv)
    sy = (height / 2.0) * (1.0 - (pos_x * vm[4] + pos_y * vm[5] + pos_z * vm[6] + vm[7]) * inv)
    return sx, sy
 
WEAPON_MAP = {
    43: "Flash",
    44: "HE",
    45: "Smoke",
    46: "Molotov",
    48: "Molotov",
    47: "Decoy",
}
 
class LineupOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lineup Overlay")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
            Qt.Tool | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.showFullScreen()
 
        self.view_matrix = None
        self.items = []
        self.active_idx = -1
        self.progress = 0.0
 
        self.pen_normal    = QPen(QColor(0, 255, 255), 2)
        self.pen_ready     = QPen(QColor(0, 255, 0), 2)
        self.pen_arc       = QPen(Qt.white, 3)
        self.pen_shadow    = QPen(Qt.black)
        self.pen_text      = QPen(Qt.white)
 
        self.font_ui = QFont("Segoe UI", 8, QFont.Bold)
 
    def update_data(self, items, vm, active_idx, progress):
        self.items = items
        self.view_matrix = vm
        self.active_idx = active_idx
        self.progress = progress
        self.update()
 
    def paintEvent(self, event):
        if self.view_matrix is None or not self.items:
            return
 
        vm_np = np.array(self.view_matrix, dtype=np.float32)
        w_scr = float(self.width())
        h_scr = float(self.height())
 
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(self.font_ui)
 
        for i, item in enumerate(self.items):
            ox, oy, oz = item['origin']
            is_active = (i == self.active_idx)
 
            painter.setPen(self.pen_ready if is_active else self.pen_normal)
            painter.setBrush(Qt.NoBrush)
 
            poly_points = []
            for j in range(13):
                th = 2 * math.pi * j / 12
                px = ox + 15.0 * math.cos(th)
                py = oy + 15.0 * math.sin(th)
                sx, sy = world_to_screen_fast(px, py, oz, vm_np, w_scr, h_scr)
                if sx != -1.0:
                    poly_points.append(QPointF(sx, sy))
 
            if len(poly_points) > 1:
                painter.drawPolyline(QPolygonF(poly_points))
 
            if is_active and self.progress > 0:
                sx, sy = world_to_screen_fast(float(ox), float(oy), float(oz), vm_np, w_scr, h_scr)
                if sx != -1.0:
                    painter.setPen(self.pen_arc)
                    painter.drawArc(int(sx - 15), int(sy - 15), 30, 30,
                                    0, int(self.progress * 5760))
 
            sx_t, sy_t = world_to_screen_fast(float(ox), float(oy), oz + 20.0, vm_np, w_scr, h_scr)
            if sx_t == -1.0:
                continue
 
            name_t = item.get('name', '')
            type_t = item.get('type', '')
 
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(name_t)
            tx, ty = int(sx_t - tw / 2), int(sy_t)
 
            painter.setPen(self.pen_shadow)
            painter.drawText(tx + 1, ty + 1, name_t)
            painter.setPen(self.pen_text)
            painter.drawText(tx, ty, name_t)
 
            if type_t:
                tw2 = fm.horizontalAdvance(type_t)
                tx2, ty2 = int(sx_t - tw2 / 2), int(sy_t + 12)
                painter.setPen(self.pen_shadow)
                painter.drawText(tx2 + 1, ty2 + 1, type_t)
                painter.setPen(self.pen_text)
                painter.drawText(tx2, ty2, type_t)
 
class LineupThread(QThread):
    overlay_update = pyqtSignal(list, object, int, float)
    status_update  = pyqtSignal(str)
 
    def __init__(self, pm, client, offsets):
        super().__init__()
        self.pm = pm
        self.client = client
        self.offsets = offsets
        self.running = False
        self._f6_pressed = False

        self.json_path = os.path.join(os.getcwd(), "lineups.json")
        self.lineups_data = {}
        self.current_map_lineups = []
        self.last_map = ""
        self.active_idx = -1
        self.zone_start = 0
        self.target_frame_time = 0.016
 
        self.map_reader = MapReader(pm, client, offsets)

    def _record_lineup(self, map_name, origin, grenade_type):
        """Record a new lineup at current position"""
        try:
            view_bytes = self.pm.read_bytes(
                self.client + self.offsets['dwViewAngles'], 12
            )
            if not view_bytes:
                print("[Lineup] Failed to read view angles")
                return

            angles = struct.unpack("<3f", view_bytes)

            new_lineup = {
                "name": f"Custom {grenade_type} Lineup",
                "type": grenade_type,
                "origin": origin,
                "angles": [angles[0], angles[1]]
            }

            self.lineups_data.setdefault(map_name, [])
            self.lineups_data[map_name].append(new_lineup)

            with open(self.json_path, 'w') as f:
                json.dump(self.lineups_data, f, indent=2)

            self.current_map_lineups = self.lineups_data.get(map_name, [])

            msg = f"[Lineup] Saved {grenade_type} lineup on {map_name}"
            print(msg)
            self.status_update.emit(msg)

        except Exception as e:
            print(f"[Lineup] Error recording: {e}")
 
    def reload_json(self):
        if os.path.exists(self.json_path):
            try:
                with open(self.json_path, 'r') as f:
                    self.lineups_data = json.load(f)
                self.last_map = ""
                print(f"[Lineup] Loaded {self.json_path}")
            except Exception as e:
                print(f"[Lineup] Error loading JSON: {e}")
        else:
            print(f"[Lineup] lineups.json not found at: {self.json_path}")
 
    def run(self):
        self.reload_json()
        self.running = True

        while self.running:
            loop_start = time.perf_counter()
 
            try:
                map_name = self.map_reader.get_map_name()
                if not map_name:
                    time.sleep(0.1)
                    continue
 
                if map_name != self.last_map:
                    self.last_map = map_name
                    self.current_map_lineups = self.lineups_data.get(map_name, [])
                    msg = f"[Lineup] Map: {map_name} | Lineups: {len(self.current_map_lineups)}"
                    print(msg)
                    self.status_update.emit(msg)
 
                vm_bytes = self.pm.read_bytes(self.client + self.offsets['dwViewMatrix'], 64)
                if not vm_bytes:
                    time.sleep(0.01)
                    continue
                view_matrix = struct.unpack("<16f", vm_bytes)
 
                if not self.current_map_lineups:
                    self.overlay_update.emit([], view_matrix, -1, 0.0)
                    time.sleep(0.5)
                    continue
 
                lp_pawn = self.pm.read_ulonglong(self.client + self.offsets['dwLocalPlayerPawn'])
                if not lp_pawn:
                    time.sleep(0.1)
                    continue
 
                pos_bytes = self.pm.read_bytes(lp_pawn + self.offsets['m_vOldOrigin'], 12)
                if not pos_bytes:
                    time.sleep(self.target_frame_time)
                    continue
                pos = struct.unpack("<3f", pos_bytes)
                pos_np = np.array(pos)
 
                weapon_id = 0
                try:
                    clip_wp = self.pm.read_ulonglong(lp_pawn + self.offsets['m_pClippingWeapon'])
                    if clip_wp:
                        item_base = clip_wp + self.offsets['m_AttributeManager'] + self.offsets['m_Item']
                        weapon_id = self.pm.read_short(item_base + self.offsets['m_iItemDefinitionIndex'])
                except:
                    pass
 
                held_type = WEAPON_MAP.get(weapon_id, "Unknown")

                if win32api.GetAsyncKeyState(0x75) & 0x8000:
                    if not hasattr(self, '_f6_pressed'):
                        self._f6_pressed = True
                        self._record_lineup(map_name, pos_np.tolist(), held_type)
                    time.sleep(0.2)  # Debounce
                else:
                    self._f6_pressed = False

 
                visible = []
                found_active = -1
 
                for i, l in enumerate(self.current_map_lineups):
                    dist = np.linalg.norm(pos_np - np.array(l['origin']))
                    if dist < 300:
                        visible.append(l)
                    if dist < 5.0 and l.get('type', 'Smoke') == held_type:
                        found_active = i
 
                overlay_active_idx = -1
                if found_active != -1:
                    active_obj = self.current_map_lineups[found_active]
                    if active_obj in visible:
                        overlay_active_idx = visible.index(active_obj)
 
                prog = 0.0
                if found_active != -1:
                    if self.active_idx != found_active:
                        self.active_idx = found_active
                        self.zone_start = time.time()
                    else:
                        elapsed = time.time() - self.zone_start
                        if elapsed >= 1.5:
                            prog = 1.0
                            t_ang = self.current_map_lineups[found_active]['angles']
                            view_bytes = self.pm.read_bytes(
                                self.client + self.offsets['dwViewAngles'], 12)
                            if view_bytes:
                                c_ang = struct.unpack("<3f", view_bytes)
                                dy = (t_ang[1] - c_ang[1] + 180) % 360 - 180
                                dx = t_ang[0] - c_ang[0]
                                if abs(dx) > 0.05 or abs(dy) > 0.05:
                                    win32api.mouse_event(
                                        win32con.MOUSEEVENTF_MOVE,
                                        int(-dy * 18), int(dx * 18), 0, 0
                                    )
                        else:
                            prog = elapsed / 1.5
                else:
                    self.active_idx = -1
                    self.zone_start = 0
 
                self.overlay_update.emit(visible, view_matrix, overlay_active_idx, prog)
 
            except Exception:
                pass
 
            elapsed = time.perf_counter() - loop_start
            sleep_time = self.target_frame_time - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
 
    def stop(self):
        self.running = False
 
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False
 
 
def main():
    if not is_admin():
        script = os.path.abspath(__file__)
        script_dir = os.path.dirname(script)
        print("[Lineup] Requesting administrator privileges...")
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, f'"{script}"', script_dir, 1
            )
        except Exception as e:
            print(f"[Lineup] Error: {e}")
            input("Press Enter to exit...")
        sys.exit()
 
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
 
    pm = MemoryManager("cs2.exe")
    print("[Lineup] Attaching to CS2...")
    while not pm.attach():
        print("[Lineup] CS2 not running. Retrying in 3s...")
        time.sleep(3)
 
    print(f"[Lineup] client.dll @ 0x{pm.client_dll_base:X}")
 
    offsets = load_offsets()
 
    try:
        QApplication.setAttribute(Qt.AA_UseDesktopOpenGL)
    except AttributeError:
        pass
 
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
 
    overlay = LineupOverlay()
 
    thread = LineupThread(pm, pm.client_dll_base, offsets)
    thread.overlay_update.connect(overlay.update_data)
    thread.status_update.connect(lambda msg: print(msg))
    thread.start()
 
    print("[Lineup] Running. Close this window or press Ctrl+C to stop.")
 
    ret = app.exec_()
 
    thread.stop()
    thread.wait()
    pm.close()
    sys.exit(ret)
 
 
if __name__ == "__main__":
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except:
        pass

    main()
