"""Small Windows system-load sampler; unknown readings never mean healthy."""
import os,time
class SystemLoad:
    def __init__(self):self.previous=None
    def sample(self):
        result={'cpu_percent':None,'available_gb':None,'memory_percent':None,'available':False}
        if os.name!='nt':return result
        try:
            import ctypes
            from ctypes import wintypes
            class Memory(ctypes.Structure):
                _fields_=[('length',wintypes.DWORD),('load',wintypes.DWORD)]+[(n,ctypes.c_ulonglong) for n in ('total','available','page_total','page_available','virtual_total','virtual_available','extended')]
            mem=Memory();mem.length=ctypes.sizeof(mem)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):return result
            idle=wintypes.FILETIME();kernel=wintypes.FILETIME();user=wintypes.FILETIME()
            if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle),ctypes.byref(kernel),ctypes.byref(user)):return result
            val=lambda f:(f.dwHighDateTime<<32)|f.dwLowDateTime
            current=(val(idle),val(kernel)+val(user))
            if self.previous:
                di=current[0]-self.previous[0];dt=current[1]-self.previous[1]
                if dt>0:result['cpu_percent']=round(max(0,min(100,100*(1-di/dt))),1)
            self.previous=current
            result.update(available_gb=round(mem.available/1024**3,2),memory_percent=int(mem.load))
            result['available']=result['cpu_percent'] is not None
        except (OSError,AttributeError,ValueError):pass
        return result
