"""AMD image policy helpers; the server retains the encoder owner and lifecycle."""
import subprocess


def max_tokens(cfg: dict, hip_required: bool) -> int:
    if hip_required:
        cap = cfg.get("max_tokens", 300)
        if isinstance(cap, bool) or not isinstance(cap, int) or not 1 <= cap <= 1024:
            raise ValueError("HIP vision max_tokens must be an integer between 1 and 1024; start with 300")
        value = cap
    else:
        value = int(cfg.get("max_tokens") or 0)
    if hip_required and cfg.get("min_tokens") and int(cfg["min_tokens"]) > value:
        raise ValueError("HIP vision min_tokens exceeds max_tokens")
    return value


def capability(self) -> dict:
    available = self.alive()
    return {"enabled": True, "available": available, "backend": "hip" if self.hip_required else "legacy",
            "error": None if available else self.error or "the image encoder is not running",
            "cleanup_pending": self.cleanup_pending}


def stop(self, force=False, *, cleanup_pending_error):
    """Retain this Popen (and its process handle) until poll/wait proves exit."""
    proc = self.proc
    kill_error = None
    try:
        if proc is not None and proc.poll() is None:
            if not force:
                try:
                    proc.stdin.write("QUIT\n")
                    proc.stdin.flush()
                    proc.wait(timeout=10)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    force = True
            if force:
                try:
                    proc.kill()
                except OSError as exc:
                    kill_error = exc
                proc.wait(timeout=5)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        self.stopped, self.cleanup_pending = True, True
        self.error = f"HIP vision cleanup pending (pid={getattr(proc, 'pid', None)}): {exc}"
        if kill_error is not None:
            self.error += f"; kill failed: {kill_error}"
        raise cleanup_pending_error(self) from exc
    self.proc = None
    self.stopped, self.cleanup_pending, self.error = True, False, None


def checked_image(self, data: bytes) -> bytes:
    """Validate compressed input and dimensions before any decoder allocates pixels."""
    if len(data) > 20 << 20:
        raise ValueError("the image source is larger than 20 MiB")
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            if im.format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError("HIP vision accepts JPEG, PNG and WebP")
            if min(w, h) <= 0 or max(w, h) > 4096 or w * h > 4_000_000:
                raise ValueError("HIP vision requires edges <=4096 and at most 4000000 pixels")
            im.verify()
    except Exception as e:
        raise ValueError(f"the image could not be read ({e})") from None
    return self.normalize(data)
