"""Write the POC's test images using only the standard library (no Pillow needed).

Sized against imagor 1.6.3's defaults: MaxWidth/MaxHeight 9999 and MaxResolution
81,000,000 px, where an animated image counts width x (frame height x frames).
Existing files are left alone, so you can also drop your own images into ./images.
"""
import os
import struct
import zlib

OUT_DIR = "/images/poc"


def png(width, height, rgb):
    """Solid-colour RGB PNG."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    row = b"\x00" + bytes(rgb) * width  # filter byte + pixels
    compressor = zlib.compressobj(9)
    idat = b"".join(compressor.compress(row) for _ in range(height)) + compressor.flush()
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", idat)
            + chunk(b"IEND", b""))


def lzw(pixels, min_code_size):
    """GIF LZW, mirroring giflib's encoder (EGifCompressLine) so decoders agree on code widths."""
    clear, eoi = 1 << min_code_size, (1 << min_code_size) + 1
    out = bytearray()
    bits = nbits = 0
    width, next_code = min_code_size + 1, eoi + 1

    def emit(code):
        nonlocal bits, nbits, width
        bits |= code << nbits
        nbits += width
        while nbits >= 8:
            out.append(bits & 0xFF)
            bits >>= 8
            nbits -= 8
        if next_code >= (1 << width) and width < 12:
            width += 1

    emit(clear)
    table = {}
    prefix = pixels[0]
    for k in pixels[1:]:
        code = table.get((prefix, k))
        if code is not None:
            prefix = code
            continue
        emit(prefix)
        if next_code >= 4095:  # table full: start over
            emit(clear)
            table, width, next_code = {}, min_code_size + 1, eoi + 1
        else:
            table[(prefix, k)] = next_code
            next_code += 1
        prefix = k
    emit(prefix)
    emit(eoi)
    if nbits:
        out.append(bits & 0xFF)
    return bytes(out)


def sub_blocks(data):
    return b"".join(bytes([len(data[i:i + 255])]) + data[i:i + 255] for i in range(0, len(data), 255)) + b"\x00"


def gif(width, height, frames, palette=((220, 20, 60), (30, 144, 255))):
    """Looping animated GIF whose solid frames alternate between the two palette colours."""
    encoded = [sub_blocks(lzw([index] * (width * height), 2)) for index in range(2)]
    data = bytearray(b"GIF89a")
    data += struct.pack("<HHBBB", width, height, 0xF0, 0, 0)  # 2-colour global palette
    data += bytes(channel for colour in palette for channel in colour)
    data += b"\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00"  # loop forever
    for frame in range(frames):
        data += b"\x21\xF9\x04\x00" + struct.pack("<H", 10) + b"\x00\x00"  # 100ms delay
        data += b"\x2C" + struct.pack("<HHHHB", 0, 0, width, height, 0)
        data += b"\x02" + encoded[frame % 2]
    data += b"\x3B"
    return bytes(data)


IMAGES = {
    # control: 0.5 MP -> 200
    "small.png": lambda: png(800, 600, (46, 139, 87)),
    # width 10000 > MaxWidth 9999 -> 422
    "wide.png": lambda: png(10000, 100, (220, 20, 60)),
    # control: 200 x (200 x 10 frames) = 0.4 MP -> 200
    "small-anim.gif": lambda: gif(200, 200, 10),
    # 1000 x (1000 x 90 frames) = 90 MP > MaxResolution 81 MP -> 422, the case seen in dev
    "big-anim.gif": lambda: gif(1000, 1000, 90),
}


# 70 distinct over-limit images (copies of wide.png) for the burst test against the 60/min Sentry cap
BURST_COUNT = 70
IMAGES.update({f"burst/wide-{i:02d}.png": IMAGES["wide.png"] for i in range(1, BURST_COUNT + 1)})


if __name__ == "__main__":
    os.makedirs(os.path.join(OUT_DIR, "burst"), exist_ok=True)
    for name, build in IMAGES.items():
        path = os.path.join(OUT_DIR, name)
        if os.path.exists(path):
            print(f"[seed-images] {name}: exists, skipped", flush=True)
            continue
        data = build()
        with open(path + ".tmp", "wb") as f:
            f.write(data)
        os.replace(path + ".tmp", path)
        print(f"[seed-images] {name}: wrote {len(data):,} bytes", flush=True)
