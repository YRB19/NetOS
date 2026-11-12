import struct
import unittest

from provider_probe import decode_upstox_frame


def varint(value: int) -> bytes:
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def vfield(number: int, value: int) -> bytes:
    return varint(number << 3) + varint(value)


def dfield(number: int, value: float) -> bytes:
    return varint((number << 3) | 1) + struct.pack("<d", value)


def bfield(number: int, value: bytes) -> bytes:
    return varint((number << 3) | 2) + varint(len(value)) + value


class UpstoxDecoderTests(unittest.TestCase):
    def test_decodes_full_equity_feed_and_market_depth(self):
        ltpc = dfield(1, 2500.5) + vfield(2, 1731412800000) + vfield(3, 12) + dfield(4, 2488.0)
        quote = vfield(1, 100) + dfield(2, 2500.0) + vfield(3, 90) + dfield(4, 2501.0)
        market_level = bfield(1, quote)
        ohlc = bfield(1, b"1d") + dfield(2, 2480.0) + dfield(3, 2510.0) + dfield(4, 2470.0) + dfield(5, 2500.5) + vfield(6, 123456) + vfield(7, 1731412800000)
        market_ohlc = bfield(1, ohlc)
        market_ff = bfield(1, ltpc) + bfield(2, market_level) + bfield(4, market_ohlc) + dfield(5, 2498.5) + vfield(6, 999999) + dfield(7, 0.0) + dfield(8, 0.0) + dfield(9, 10000.0) + dfield(10, 8000.0)
        full_feed = bfield(1, market_ff)
        feed = bfield(2, full_feed)
        entry = bfield(1, b"NSE_EQ|INE002A01018") + bfield(2, feed)
        frame = vfield(1, 1) + bfield(2, entry) + vfield(3, 1731412801000)

        decoded = decode_upstox_frame(frame)
        self.assertEqual(decoded["type"], "live_feed")
        instrument = decoded["feeds"]["NSE_EQ|INE002A01018"]["fullFeed"]["marketFF"]
        self.assertEqual(instrument["ltpc"]["ltp"], 2500.5)
        self.assertEqual(instrument["marketLevel"]["bidAskQuote"][0]["askP"], 2501.0)
        self.assertEqual(instrument["marketOHLC"]["ohlc"][0]["interval"], "1d")
        self.assertEqual(instrument["atp"], 2498.5)
        self.assertEqual(instrument["tbq"], 10000.0)

    def test_preserves_unknown_fields(self):
        unknown = bfield(99, b"future-field")
        frame = vfield(1, 1) + unknown
        decoded = decode_upstox_frame(frame)
        self.assertEqual(decoded["_unknown_fields"][0]["field_number"], 99)
        self.assertIn("6675747572652d6669656c64", decoded["_unknown_fields"][0]["raw_hex"])


if __name__ == "__main__":
    unittest.main()
