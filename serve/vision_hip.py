"""Environment for the opt-in Windows HIP image encoder. The text engine keeps its own SDK."""
from __future__ import annotations

import ntpath


def reserve_args(args: list[str]) -> list[str]:
    """Keep generate.cpp's Windows HIP floor when vision makes the reserve explicit.

    The encoder warms before the text cache is sized; its memory is already absent
    from free VRAM. This is the existing engine safety margin, not a second image budget.
    """
    flag = "--vram-reserve-mib"
    positions = [i for i, value in enumerate(args) if value == flag or value.startswith(flag + "=")]
    if not positions:
        return args + [flag, "2560"]
    i = positions[0]
    if len(positions) != 1 or args[i] != flag or i + 1 >= len(args):
        raise ValueError("HIP vision requires one --vram-reserve-mib value (at least 2560)")
    value = args[i + 1]
    if not value.isascii() or not value.isdigit() or int(value) < 2560:
        raise ValueError("HIP vision --vram-reserve-mib must be an integer of at least 2560")
    return args


def windows_hip_env(vision: dict, parent: dict) -> dict:
    root = str(vision.get("rocm_root") or "")
    exe = str(vision.get("exe") or "")
    device = vision.get("hip_device")
    if not ntpath.isabs(root) or not ntpath.isabs(exe):
        raise ValueError("HIP vision needs absolute rocm_root and exe paths")
    if ntpath.normcase(ntpath.dirname(exe)) != ntpath.normcase(ntpath.join(root, "bin")):
        raise ValueError("HIP vision exe must be in its private ROCm root/bin, beside that SDK's DLLs")
    if isinstance(device, bool) or not isinstance(device, int) or device < 0:
        raise ValueError("HIP vision needs one non-negative hip_device ordinal from its own SDK")
    env = dict(parent)
    remove = {"PATH", "HIP_PATH", "ROCM_PATH", "ROCM_HOME", "HIP_DEVICE_LIB_PATH", "LLVM_PATH",
              "ROCBLAS_TENSILE_LIBPATH", "HIPBLASLT_TENSILE_LIBPATH", "GGML_BACKEND_PATH",
              "HIP_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES", "CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER",
              "HSA_OVERRIDE_GFX_VERSION", "GPU_DEVICE_ORDINAL"}
    # Windows environment keys are case-insensitive, including hand-written Path/Hip_Path entries.
    for key in list(env):
        if key.upper() in remove or key.upper().startswith("STRATA_"):
            del env[key]
    system_root = next((str(v) for k, v in env.items() if k.upper() == "SYSTEMROOT"), r"C:\Windows")
    env["PATH"] = ";".join([ntpath.join(root, "bin"), ntpath.join(root, "lib", "llvm", "bin"),
                             ntpath.join(system_root, "System32"), system_root])
    env["HIP_PATH"] = env["ROCM_PATH"] = root
    env["HIP_DEVICE_LIB_PATH"] = ntpath.join(root, "lib", "llvm", "amdgcn", "bitcode")
    env["LLVM_PATH"] = ntpath.join(root, "lib", "llvm")
    env["HIP_PLATFORM"] = "amd"
    env["HIP_VISIBLE_DEVICES"] = str(device)
    temp_dir = str(vision.get("temp_dir") or ntpath.join(root, "tmp"))
    if not ntpath.isabs(temp_dir) or " " in temp_dir:
        raise ValueError("HIP vision temp_dir must be absolute and contain no spaces")
    for key in list(env):
        if key.upper() in {"TEMP", "TMP", "TMPDIR", "AMD_COMGR_CACHE_DIR"}:
            del env[key]
    env["TEMP"] = env["TMP"] = temp_dir
    env["AMD_COMGR_CACHE_DIR"] = ntpath.join(temp_dir, "comgr")
    return env
