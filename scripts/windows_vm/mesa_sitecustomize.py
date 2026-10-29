# Test-VM-only graphics driver injection; not part of the IIMT distribution.
import ctypes
import os

os.environ.setdefault("GALLIUM_DRIVER", "llvmpipe")
_mesa_directory = os.add_dll_directory(r"C:\IIMTVerify\mesa")
_mesa = ctypes.WinDLL(r"C:\IIMTVerify\mesa\opengl32.dll")
