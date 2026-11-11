"""Launch an argument-free PTX kernel through the NVIDIA driver."""
import ctypes as C
import sys
lib = C.CDLL('libcuda.so.1')
ptr = C.c_void_p
uint = C.c_uint
signatures = {
 'cuInit': [uint], 'cuDeviceGet': [C.POINTER(C.c_int), C.c_int],
 'cuDevicePrimaryCtxRetain': [C.POINTER(ptr), C.c_int],
 'cuCtxSetCurrent': [ptr], 'cuModuleLoad': [C.POINTER(ptr), C.c_char_p],
 'cuModuleGetFunction': [C.POINTER(ptr), ptr, C.c_char_p],
 'cuLaunchKernel': [ptr, uint, uint, uint, uint, uint, uint, uint, ptr, ptr, ptr],
 'cuCtxSynchronize': [],
}
for name, types in signatures.items():
 f = getattr(lib, name); f.argtypes = types; f.restype = C.c_int

def check(name, *args):
 code = getattr(lib, name)(*args)
 if code: raise RuntimeError(f'{name} failed: CUDA driver error {code}')

check('cuInit', 0)
device = C.c_int(); check('cuDeviceGet', C.byref(device), 0)
ctx = ptr(); check('cuDevicePrimaryCtxRetain', C.byref(ctx), device)
check('cuCtxSetCurrent', ctx)
module = ptr(); check('cuModuleLoad', C.byref(module), sys.argv[1].encode())
kernel = ptr(); check('cuModuleGetFunction', C.byref(kernel), module, sys.argv[2].encode())
grid = list(map(int, sys.argv[3].split(',')))
block = list(map(int, sys.argv[4].split(',')))
check('cuLaunchKernel', kernel, *grid, *block, 0, None, None, None)
check('cuCtxSynchronize')
