"""CPU-only fake streams; no native process or SDK is started."""
import io
from pathlib import Path
import tempfile
import threading
import unittest

from tools.vision.encode_io import EncodeIO

ROOT = Path(__file__).resolve().parents[2]


class Blocked(io.BytesIO):
    def __init__(self):
        super().__init__()
        self.release = threading.Event()

    def readline(self, size=-1):
        self.release.wait()
        return b''


class BrokenReader(io.BytesIO):
    def readline(self, size=-1):
        raise OSError('fake read failure')


class ShortWriter(io.BytesIO):
    def write(self, value):
        return len(value) - 1


class EncodeIOTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / '.vision-tmp', prefix='encode-io-fake-')
        self.addCleanup(self.tmp.cleanup)
        self.raw = Path(self.tmp.name) / 'stdout.raw'

    def make(self, data):
        writer = io.BytesIO()
        transport = EncodeIO(writer, io.BytesIO(data), self.raw)
        self.assertTrue(transport.close_reader(1))
        return transport, writer

    def test_ready_ok_eof_and_exact_raw(self):
        data = b'READY 2560\r\nOK 160 16 10 23\n'
        transport, _ = self.make(data)
        self.assertEqual(transport.read_event(), dict(kind='ready', width=2560))
        self.assertEqual(transport.read_event(), dict(kind='ok', n=160, nx=16, ny=10, ms=23))
        self.assertEqual(transport.read_event(), dict(kind='eof'))
        self.assertEqual(self.raw.read_bytes(), data)

    def test_error_and_malformed_are_explicit(self):
        for index, data in enumerate((b'ERR cannot read image\n', b'OK 0 1 1 0\n', b'READY true\n',
                                      b'OK 1 1 1 nan\n', b'READY 2560', b'\xff\n')):
            with self.subTest(data=data):
                self.raw = Path(self.tmp.name) / f'raw-{index}'
                transport, _ = self.make(data)
                self.assertEqual(transport.read_event()['kind'], 'error')

    def test_line_and_queue_overflow_cannot_be_success(self):
        transport, _ = self.make(b'ERR ' + b'x' * 4093 + b'\n')
        self.assertEqual(transport.read_event()['kind'], 'error')
        self.assertIn('line limit', transport.read_event()['reason'])
        self.raw = Path(self.tmp.name) / 'overflow.raw'
        transport, _ = self.make(b'READY 2560\n' * 33)
        self.assertEqual(transport.read_event()['kind'], 'error')
        self.assertIn('queue overflow', transport.read_event()['reason'])

    def test_exact_line_and_queue_limits(self):
        data = b'ERR ' + b'x' * 4091 + b'\n'
        transport, _ = self.make(data)
        self.assertEqual(transport.read_event(), dict(kind='error', reason='x' * 4091))
        self.assertEqual(self.raw.read_bytes(), data)
        self.raw = Path(self.tmp.name) / 'queue32.raw'
        transport, _ = self.make(b'READY 2560\n' * 32)
        for _ in range(32):
            self.assertEqual(transport.read_event(), dict(kind='ready', width=2560))
        self.assertEqual(transport.read_event(), dict(kind='eof'))

    def test_timeout_and_unknown_reader_exit_are_not_eof(self):
        source = Blocked()
        transport = EncodeIO(io.BytesIO(), source, self.raw)
        self.assertIsNone(transport.read_event(timeout=.001))
        self.assertFalse(transport.close_reader(.001))
        source.release.set()
        self.assertTrue(transport.close_reader(1))
        self.assertEqual(transport.read_event()['kind'], 'eof')

    def test_commands_preserve_native_path_split_and_reject_injection(self):
        transport, writer = self.make(b'')
        transport.send_encode('C:/private/image with space.png', 'C:/private/out.sve')
        transport.send_quit()
        self.assertEqual(writer.getvalue(), b'ENC C:/private/image with space.png C:/private/out.sve\nQUIT\n')
        for image, output in (('relative.png', 'C:/out.sve'), ('C:/a.png', 'C:/out space.sve'),
                              ('C:/a\nQUIT', 'C:/out.sve'), ('C:/a.png', 'C:/x\x00.sve'),
                              ('C:/a.png', 'relative.sve')):
            with self.subTest(image=image, output=output):
                with self.assertRaises(ValueError):
                    transport.send_encode(image, output)

    def test_text_stream_and_write_failure(self):
        transport = EncodeIO(io.StringIO(), io.StringIO('READY 2560\n'), self.raw)
        self.assertTrue(transport.close_reader(1))
        self.assertEqual(transport.read_event(), dict(kind='ready', width=2560))
        transport.send_quit()
        self.assertEqual(transport.stdin.getvalue(), 'QUIT\n')
        transport.stdin.close()
        with self.assertRaises(ValueError):
            transport.send_quit()

    def test_read_exception_short_write_and_raw_collision(self):
        transport = EncodeIO(ShortWriter(), BrokenReader(), self.raw)
        self.assertTrue(transport.close_reader(1))
        self.assertIn('fake read failure', transport.read_event()['reason'])
        with self.assertRaisesRegex(OSError, 'Short native stdin write'):
            transport.send_quit()
        with self.assertRaises(FileExistsError):
            EncodeIO(io.BytesIO(), io.BytesIO(), self.raw)

    def test_invalid_waits_rejected(self):
        transport, _ = self.make(b'')
        for value in (-1, float('nan'), float('inf'), True, '1'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    transport.read_event(value)
                with self.assertRaises(ValueError):
                    transport.close_reader(value)


if __name__ == '__main__':
    unittest.main()
