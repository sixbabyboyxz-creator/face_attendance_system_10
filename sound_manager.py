# -*- coding: utf-8 -*-
"""
sound_manager.py
ระบบเสียงแจ้งเตือน (Non-blocking)
"""

import winsound
import threading
import time

class SoundManager:
    def __init__(self):
        self._enabled = True
        self._last_played = {}
        self._lock = threading.Lock()
        
    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        
    def is_enabled(self) -> bool:
        return self._enabled

    def _play_sequence(self, sound_type, sequence):
        if not self._enabled:
            return
            
        now = time.time()
        
        with self._lock:
            last_time = self._last_played.get(sound_type, 0)
            if now - last_time < 0.2:  # 200ms debounce
                return
            self._last_played[sound_type] = now
            
        def _worker():
            for i, (freq, duration, gap) in enumerate(sequence):
                winsound.Beep(freq, duration)
                if gap > 0 and i < len(sequence) - 1:
                    time.sleep(gap / 1000.0)
                    
        threading.Thread(target=_worker, daemon=True).start()

    def play_success(self):
        # short high-pitched beep (1200Hz, 150ms) for successful scan
        self._play_sequence('success', [(1200, 150, 0)])

    def play_duplicate(self):
        # two short medium beeps (800Hz, 100ms each with 80ms gap) for duplicate/cooldown scan
        self._play_sequence('duplicate', [(800, 100, 80), (800, 100, 0)])

    def play_unknown(self):
        # one longer low beep (400Hz, 300ms) for unknown face
        self._play_sequence('unknown', [(400, 300, 0)])

    def play_error(self):
        # two long low beeps (300Hz, 200ms each with 100ms gap) for errors
        self._play_sequence('error', [(300, 200, 100), (300, 200, 0)])

    def play_capture(self):
        # camera shutter sound (short click, 2000Hz 50ms) for face enrollment capture
        self._play_sequence('capture', [(2000, 50, 0)])

sound = SoundManager()
