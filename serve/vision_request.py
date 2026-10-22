"""HIP request accounting and SVE verification, independent of the server module.

The server binds its existing source loader and cancellation exception internally.
This module does not select devices, launch processes, or change request limits.
"""
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import time
import uuid


class ImageRequestFatal(ValueError):
    """A failed image request, never a recoverable unreadable-tool-image note."""


class HipImageRequest:
    """One HIP prepare operation's cancellation and payload-free evidence.

    No new aggregate limits: existing per-image/body/context/timeouts apply.
    """
    def __init__(self, messages, cancel, vision, *, load_source, cancelled_error):
        self._load_source = load_source
        self._cancelled_error = cancelled_error
        self.id = uuid.uuid4().hex
        self.cancel = cancel
        self.vision = vision
        self.fetched, self.features = {}, {}
        self.source_bytes = self.feature_bytes = 0
        self.rows = []
        self.indices = {}
        for message in messages:
            content = message.get("content")
            for item in content if isinstance(content, list) else ():
                if isinstance(item, dict) and item.get("type") == "image":
                    index = len(self.rows)
                    self.indices[id(item)] = index
                    self.rows.append(dict(index=index, role=message.get("role"), type="image"))
        self.native_started = self.finished = False
        self.emit("begin", image_count=len(self.rows))

    def emit(self, phase, **fields):
        print("[strata-image] " + json.dumps(dict(request_id=self.id, at=time.time(), phase=phase, **fields)), flush=True)

    def check(self):
        if self.cancel is not None and self.cancel.is_set():
            raise self._cancelled_error()

    def load(self, source):
        self.check()
        if source not in self.fetched:
            try:
                raw = source if isinstance(source, bytes) else self._load_source(source, 20 << 20)
            finally:
                self.check()
            self.source_bytes += len(raw)
            self.fetched[source] = raw
        return self.fetched[source]

    def encoded(self, index, path, n, cache_hit, raw):
        self.check()
        try:
            with Path(path).open("rb") as stream:
                header = stream.read(20)
                magic, count, nx, ny, width = struct.unpack("<5i", header)
                size = os.fstat(stream.fileno()).st_size
                if (magic != 0x31455653 or count != n or not 0 < n <= self.vision.max_tokens or nx <= 0 or ny <= 0
                        or nx * ny != n or width != self.vision.n_embd or size != 20 + n * width * 4):
                    raise ValueError("invalid cached/current SVE shape")
                data = header + stream.read()
                import array
                values = array.array("f")
                values.frombytes(data[20:])
                if not all(math.isfinite(value) for value in values):
                    raise ValueError("non-finite SVE embedding")
        except ImageRequestFatal:
            raise
        except (OSError, ValueError, struct.error) as error:
            raise ImageRequestFatal("HIP image embedding verification failed") from error
        sha = hashlib.sha256(data).hexdigest()
        if index in self.features and self.features[index] != (str(path), n, sha):
            raise ImageRequestFatal("HIP image occurrence changed during preparation")
        if index not in self.features:
            self.feature_bytes += size
            self.features[index] = (str(path), n, sha)
            if not hasattr(self.vision, "request_pins"):self.vision.request_pins = {}
            self.vision.request_pins.setdefault(self.id,set()).add(str(path))
            self.rows[index].update(source_bytes=len(raw), source_sha256=hashlib.sha256(raw).hexdigest(),
                cache_hit=cache_hit, n=n, nx=nx, ny=ny, width=width, sve_bytes=size, sve_sha256=sha)
            self.emit("encoded", **self.rows[index])
        self.check()

    def release_prepare(self):
        with self.vision.lock:
            getattr(self.vision, "request_pins", {}).pop(self.id, None)
        self.fetched.clear()  # do not keep image/source bytes through native generation
        self.features.clear()

    @contextlib.contextmanager
    def encoder_lock(self, lock):
        self.check()
        while not lock.acquire(timeout=.1):
            self.check()
        try:
            self.check()
            yield
        finally:
            lock.release()
