"""Bounded native encoder stdio only; process ownership stays with the caller.

Use binary Popen pipes for byte-exact raw stdout. Text streams are also accepted,
but their raw log represents the received text re-encoded as UTF-8. No method
proves native exit, closes a caller-owned pipe, or starts/retries an ENC.
"""
import io
import math
from pathlib import Path, PureWindowsPath
import queue
import re
import threading


class EncodeIO:
    QUEUE_SIZE = 32
    MAX_LINE_BYTES = 4096  # Includes the newline (and optional CR).

    def __init__(self, stdin, stdout, raw_stdout_path):
        self.stdin, self.stdout = stdin, stdout
        self._events = queue.Queue(maxsize=self.QUEUE_SIZE)
        self._error = None
        self._eof = False
        self._raw = Path(raw_stdout_path).open('xb')
        self._reader = threading.Thread(target=self._read, name='encoder-stdout', daemon=True)
        try:
            self._reader.start()
        except BaseException:
            self._raw.close()
            raise

    def _fail(self, reason):
        # Out-of-band and sticky: a full queue cannot hide failure behind an OK.
        if self._error is None:
            self._error = dict(kind='error', reason=reason)

    @staticmethod
    def _parse(line):
        match = re.fullmatch(r'READY ([1-9][0-9]*)', line)
        if match:
            width = int(match[1])
            if width <= 2147483647:
                return dict(kind='ready', width=width)
        match = re.fullmatch(r'OK ([1-9][0-9]*) ([1-9][0-9]*) ([1-9][0-9]*) ([0-9]+)', line)
        if match:
            n, nx, ny, ms = map(int, match.groups())
            if max(n, nx, ny) <= 2147483647 and math.isfinite(float(ms)):
                return dict(kind='ok', n=n, nx=nx, ny=ny, ms=ms)
        if line.startswith('ERR '):
            return dict(kind='error', reason=line[4:])
        raise ValueError('Malformed native encoder response')

    def _read(self):
        try:
            while True:
                line = self.stdout.readline(self.MAX_LINE_BYTES + 1)
                if line in (b'', ''):
                    self._eof = True
                    break
                raw = line.encode('utf-8', errors='strict') if isinstance(line, str) else line
                self._raw.write(raw)
                self._raw.flush()
                if len(raw) > self.MAX_LINE_BYTES:
                    raise ValueError('Native stdout line limit exceeded')
                if not raw.endswith(b'\n'):
                    raise ValueError('Native stdout ended with an incomplete line')
                text = raw[:-1].removesuffix(b'\r').decode('utf-8', errors='strict')
                event = self._parse(text)
                if event['kind'] == 'error':
                    self._fail(event['reason'])
                    break
                try:
                    self._events.put_nowait(event)
                except queue.Full:
                    raise ValueError('Native stdout queue overflow') from None
        except Exception as error:
            self._fail(f'{type(error).__name__}: {error}')
        finally:
            try:
                self._raw.close()
            except Exception as error:
                self._fail(f'Raw stdout close failed: {error}')

    def read_event(self, timeout=.05):
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError('A finite nonnegative read timeout is required')
        if self._error is not None:
            return dict(self._error)
        try:
            event = self._events.get(timeout=timeout)
        except queue.Empty:
            event = dict(kind='eof') if self._eof else None
        # Also cover a reader failure concurrent with queue.get().
        return dict(self._error) if self._error is not None else event

    @staticmethod
    def _path(value, *, output=False):
        value = str(value)
        if not value or any(c in value for c in '\r\n\x00') or not PureWindowsPath(value).is_absolute():
            raise ValueError('Native ENC paths must be absolute and contain no CR/LF/NUL')
        if output and ' ' in value:
            raise ValueError('Native ENC output path cannot contain spaces')
        return value

    def _send(self, command):
        data = command if isinstance(self.stdin, io.TextIOBase) else command.encode('utf-8')
        written = self.stdin.write(data)
        if written != len(data):
            raise OSError('Short native stdin write; command will not be retried')
        self.stdin.flush()

    def send_encode(self, absimage, absoutput):
        image = self._path(absimage)
        output = self._path(absoutput, output=True)
        self._send(f'ENC {image} {output}\n')

    def send_quit(self):
        self._send('QUIT\n')

    def close_reader(self, timeout):
        """Wait only; False means reader termination is unconfirmed.

        A blocked caller-owned pipe is not closed here. The runtime must arrange
        process/pipe cleanup and can call again; True proves only thread exit.
        """
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError('A finite nonnegative join timeout is required')
        self._reader.join(timeout)
        return not self._reader.is_alive()
