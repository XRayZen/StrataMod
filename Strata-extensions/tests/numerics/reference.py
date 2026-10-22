"""Independent CPU references; no imports from the native reader/decoder/G."""
import math
import struct


def fp32(value):
    try:
        return struct.unpack('<f', struct.pack('<f', value))[0]
    except OverflowError:
        return math.copysign(math.inf, value)


def fp32_bits(value):
    return f'{struct.unpack("<I", struct.pack("<f", fp32(value)))[0]:08x}'


def bf16_bits(value):
    bits = int(fp32_bits(value), 16)
    if bits & 0x7f800000 == 0x7f800000:
        return f'{(bits >> 16) | (0x40 if bits & 0x7fffff else 0):04x}'
    return f'{((bits + 0x7fff + ((bits >> 16) & 1)) >> 16) & 0xffff:04x}'


def bf16(value):
    return struct.unpack('<f', struct.pack('<I', int(bf16_bits(value), 16) << 16))[0]


def decode_block(kind, raw):
    """Q format oracle for one native block, separate from future T08/G code."""
    sizes = {0: 4, 8: 34, 39: 17, 43: 33}
    if kind not in sizes or len(raw) != sizes[kind]:
        raise ValueError('unsupported type or wrong block length')
    if kind == 0:
        return [struct.unpack('<f', raw)[0]]
    if kind == 8:
        scale = struct.unpack('<e', raw[:2])[0]
        return [fp32(scale * code) for code in struct.unpack('<32b', raw[2:])]
    if kind == 39:
        # Mathematical E2M1 magnitude; unlike the native candidate's doubled LUT.
        magnitudes = (0., .5, 1., 1.5, 2., 3., 4., 6.)
        result = []
        for nibble in [byte & 15 for byte in raw[1:]] + [byte >> 4 for byte in raw[1:]]:
            magnitude = magnitudes[nibble & 7]
            value = math.ldexp(magnitude, raw[0] - 127)
            # Native ggml/Maya integer E2M1 tables canonicalize both zero codes.
            # This is distinct from ideal E2M1 signed zero and other formats.
            result.append(0. if magnitude == 0 else fp32(-value if nibble & 8 else value))
        return result
    result = []
    # Fixed Maya native candidate materializes the scale in FP32 before
    # multiplication. At e255 it is +inf, including for zero/half codes.
    scale = fp32(math.ldexp(1., raw[0] - 127))
    for byte in raw[1:]:
        exponent, fraction = (byte >> 3) & 15, byte & 7
        if exponent == 15 and fraction == 7:
            value = math.nan
        elif exponent == 0:
            value = math.ldexp(fraction / 8., -6)
        else:
            value = math.ldexp(1 + fraction / 8., exponent - 7)
        value = -value if byte & 128 else value
        result.append(fp32(value * scale))
    return result


def rmsnorm_trace(pattern, weight, hidden, epsilon, early_cast=False):
    """N-readable official RMS formula under the declared fixed-fixture FP32 order.

    Constant-magnitude power-of-two inputs make squared sums exact for H5120;
    this does not assert a generic official GPU reduction topology.
    """
    if (not pattern or hidden <= 0 or hidden % len(pattern)
            or not all(math.isfinite(v) for v in pattern + [weight, epsilon])):
        raise ValueError('invalid RMS fixture')
    xs = [bf16(v) for v in pattern] * (hidden // len(pattern))
    total = 0.
    for value in xs:
        total = fp32(total + fp32(value * value))
    variance = fp32(total / hidden)
    added = fp32(variance + fp32(epsilon))
    inverse = fp32(1 / math.sqrt(added))
    normalized = [fp32(v * inverse) for v in xs[:len(pattern)]]
    if early_cast:
        normalized = [bf16(v) for v in normalized]
    products = [fp32(v * bf16(weight)) for v in normalized]
    return dict(variance_fp32=fp32_bits(variance), add_epsilon_fp32=fp32_bits(added),
                rsqrt_fp32=fp32_bits(inverse), pre_output_fp32_pattern=[fp32_bits(v) for v in products],
                output_bf16_pattern=[bf16_bits(v) for v in products], output_shape=[1,hidden])
