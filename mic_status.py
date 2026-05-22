import ctypes
import sys

if sys.platform != "darwin":
    raise RuntimeError("CoreAudio is macOS-only")

# Load CoreAudio framework
coreaudio = ctypes.CDLL(
    "/System/Library/Frameworks/CoreAudio.framework/Versions/A/CoreAudio"
)

# Load CoreMediaIO for camera detection
coremediaio = ctypes.CDLL(
    "/System/Library/Frameworks/CoreMediaIO.framework/Versions/A/CoreMediaIO"
)

# Four-char codes (big-endian)
def _fcc(s: str) -> int:
    return (ord(s[0]) << 24) | (ord(s[1]) << 16) | (ord(s[2]) << 8) | ord(s[3])


# --- CoreAudio (mic) ---
kAudioObjectSystemObject = 1
kAudioHardwarePropertyDefaultInputDevice = _fcc("dIn ")
kAudioObjectPropertyScopeGlobal = _fcc("glob")
kAudioObjectPropertyElementMain = 0
# From CoreAudio.bridgesupport (value64), not 'run '
kAudioDevicePropertyDeviceIsRunningSomewhere = 1735356005


class AudioObjectPropertyAddress(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


AudioObjectGetPropertyData = coreaudio.AudioObjectGetPropertyData
AudioObjectGetPropertyData.argtypes = [
    ctypes.c_uint32,  # inObjectID
    ctypes.POINTER(AudioObjectPropertyAddress),
    ctypes.c_uint32,  # inQualifierDataSize
    ctypes.c_void_p,  # inQualifierData
    ctypes.POINTER(ctypes.c_uint32),  # ioDataSize
    ctypes.c_void_p,  # outData
]
AudioObjectGetPropertyData.restype = ctypes.c_int32


# --- CoreMediaIO (camera) ---
kCMIOObjectSystemObject = 1
kCMIOHardwarePropertyDevices = _fcc("dev#")
kCMIOObjectPropertyScopeGlobal = _fcc("glob")
kCMIOObjectPropertyElementMaster = 0
kCMIODevicePropertyDeviceIsRunningSomewhere = _fcc("gone")
kCMIOObjectPropertyScopeWildcard = _fcc("****")
kCMIOObjectPropertyElementWildcard = 0xFFFFFFFF
kCMIOHardwareNoError = 0


class CMIOObjectPropertyAddress(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


CMIOObjectGetPropertyDataSize = coremediaio.CMIOObjectGetPropertyDataSize
CMIOObjectGetPropertyDataSize.argtypes = [
    ctypes.c_uint32,  # objectID
    ctypes.POINTER(CMIOObjectPropertyAddress),
    ctypes.c_uint32,  # qualifierDataSize
    ctypes.c_void_p,  # qualifierData
    ctypes.POINTER(ctypes.c_uint32),  # dataSize
]
CMIOObjectGetPropertyDataSize.restype = ctypes.c_int32

CMIOObjectGetPropertyData = coremediaio.CMIOObjectGetPropertyData
CMIOObjectGetPropertyData.argtypes = [
    ctypes.c_uint32,  # objectID
    ctypes.POINTER(CMIOObjectPropertyAddress),
    ctypes.c_uint32,  # qualifierDataSize
    ctypes.c_void_p,  # qualifierData
    ctypes.c_uint32,  # dataSize
    ctypes.POINTER(ctypes.c_uint32),  # dataUsed
    ctypes.c_void_p,  # data
]
CMIOObjectGetPropertyData.restype = ctypes.c_int32


def get_default_input_device_id() -> int:
    addr = AudioObjectPropertyAddress(
        mSelector=kAudioHardwarePropertyDefaultInputDevice,
        mScope=kAudioObjectPropertyScopeGlobal,
        mElement=kAudioObjectPropertyElementMain,
    )
    dev_id = ctypes.c_uint32(0)
    size = ctypes.c_uint32(ctypes.sizeof(dev_id))
    status = AudioObjectGetPropertyData(
        kAudioObjectSystemObject,
        ctypes.byref(addr),
        0,
        None,
        ctypes.byref(size),
        ctypes.byref(dev_id),
    )
    if status != 0:
        raise RuntimeError(
            f"AudioObjectGetPropertyData(default input) failed: {status}"
        )
    return dev_id.value


def is_mic_in_use() -> bool:
    dev_id = get_default_input_device_id()
    addr = AudioObjectPropertyAddress(
        mSelector=kAudioDevicePropertyDeviceIsRunningSomewhere,
        mScope=kAudioObjectPropertyScopeGlobal,
        mElement=kAudioObjectPropertyElementMain,
    )
    running = ctypes.c_uint32(0)
    size = ctypes.c_uint32(ctypes.sizeof(running))
    status = AudioObjectGetPropertyData(
        dev_id,
        ctypes.byref(addr),
        0,
        None,
        ctypes.byref(size),
        ctypes.byref(running),
    )
    if status != 0:
        raise RuntimeError(
            f"AudioObjectGetPropertyData(running) failed: {status}"
        )
    return bool(running.value)


def is_camera_in_use() -> bool:
    """Return True if any camera (video device) is currently in use."""
    addr = CMIOObjectPropertyAddress(
        mSelector=kCMIOHardwarePropertyDevices,
        mScope=kCMIOObjectPropertyScopeGlobal,
        mElement=kCMIOObjectPropertyElementMaster,
    )
    data_size = ctypes.c_uint32(0)
    status = CMIOObjectGetPropertyDataSize(
        kCMIOObjectSystemObject,
        ctypes.byref(addr),
        0,
        None,
        ctypes.byref(data_size),
    )
    if status != kCMIOHardwareNoError or data_size.value == 0:
        return False
    # dataSize is count * sizeof(CMIODeviceID); CMIODeviceID is UInt32
    device_ids = (ctypes.c_uint32 * (data_size.value // 4))()
    data_used = ctypes.c_uint32(0)
    status = CMIOObjectGetPropertyData(
        kCMIOObjectSystemObject,
        ctypes.byref(addr),
        0,
        None,
        data_size.value,
        ctypes.byref(data_used),
        ctypes.byref(device_ids),
    )
    if status != kCMIOHardwareNoError:
        return False
    n = data_used.value // 4
    run_addr = CMIOObjectPropertyAddress(
        mSelector=kCMIODevicePropertyDeviceIsRunningSomewhere,
        mScope=kCMIOObjectPropertyScopeWildcard,
        mElement=kCMIOObjectPropertyElementWildcard,
    )
    for i in range(n):
        dev_id = device_ids[i]
        running = ctypes.c_uint32(0)
        size = ctypes.c_uint32(ctypes.sizeof(running))
        status = CMIOObjectGetPropertyData(
            dev_id,
            ctypes.byref(run_addr),
            0,
            None,
            ctypes.sizeof(running),
            ctypes.byref(size),
            ctypes.byref(running),
        )
        if status == kCMIOHardwareNoError and running.value:
            return True
    return False


def is_recording() -> bool:
    """Return True if mic or camera is in use (we consider that 'recording')."""
    return is_mic_in_use() or is_camera_in_use()


if __name__ == "__main__":
    mic = is_mic_in_use()
    cam = is_camera_in_use()
    rec = is_recording()
    print(f"mic_in_use={mic}, camera_in_use={cam}, recording={rec}")
