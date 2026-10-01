"""Reader for Aniimo's Common/Data/pmdata.bin (all game config tables in one file).

Reverse-engineered from the file itself (build 3603741); the loader is native code,
so every rule below was inferred from the data and then checked across the whole file
(all 76,171 key lists parse and every string-key pointer lands on a string start).

Layout
------
The file ends with a trailer:  u8 1 | 6 x (u32 start, u32 end, u32 count) | u32 root
  S0 strings      NUL-terminated UTF-8, referenced by absolute offset
  S1 key lists    u32 (unknown, not an array length) | u8 numKeyType | u32 nKeys | u32 nNumericKeys
                  | nNumericKeys numeric keys (width by type) | rest as u32 string ptrs
  S2 type tags    one byte per slot (array part first, then keys)
  S3 slot offsets u8 width code (1=u8, 3=u16, 5=u32) | one offset per slot
  S4 shapes       12 bytes: (S1 key list, S2 type tags, S3 offsets)
  S5 records      u32 -> S4 shape, then the value bytes; slot offsets are relative
                  to the record start. Identical values are shared, so slots overlap.

Value type codes
----------------
  0 double, 1 u8, 2 i8, 3 u16, 4 i16, 5 u32, 6 i32, 7 string ptr, 8 table ptr, 9 bool
  100 + code = same type, but the value is stored inline in the SHAPE instead of the record,
  so every row sharing that shape shares the value (the exporter's dedup of common values).
  For an inline slot the offset is self-relative and points backwards: the value lives at
  (address of that slot's offset entry) - offset, which lands in the bytes before S3.
  Found because homeland_config.homeLotteryCostItemCount rows 1,2,3,6,7 are all type 101
  yet must hold 1,2,3,6,7. Two wrong guesses came first and both decoded "fine" on most rows:
  "1xx = zero value" turned them into 0, and "packed in slot order" was right for 96% of
  shapes and wrong for the rest. tests/test_pmdata.py pins the cases that exposed each.
"""
import struct

_NUM = {0: ('d', 8), 1: ('B', 1), 2: ('b', 1), 3: ('H', 2), 4: ('h', 2), 5: ('I', 4), 6: ('i', 4)}
_SIZE = {0: 8, 1: 1, 2: 1, 3: 2, 4: 2, 5: 4, 6: 4, 7: 4, 8: 4, 9: 1}
_OFFW = {1: ('B', 1), 3: ('H', 2), 5: ('I', 4)}


class PmData:
    def __init__(self, path):
        """`path`: the file, or its bytes (the Egg Heist tool reads it straight out of the game's archive)."""
        if isinstance(path, (bytes, bytearray)):
            self.d = bytes(path)
        else:
            with open(path, "rb") as f:
                self.d = f.read()
        d = self.d
        tail = len(d) - (1 + 6 * 12 + 4)
        if d[tail] != 1:
            raise ValueError("unexpected trailer marker; format may have changed")
        self.sections = [struct.unpack_from('<III', d, tail + 1 + 12 * i) for i in range(6)]
        self.root = struct.unpack_from('<I', d, tail + 1 + 72)[0]
        self._strings = {}
        self._modules = None

    def string(self, off):
        s = self._strings.get(off)
        if s is None:
            end = self.d.index(b"\0", off)
            s = self._strings[off] = self.d[off:end].decode("utf-8", "replace")
        return s

    def _shape(self, rec):
        d = self.d
        kp, tp, op = struct.unpack_from('<III', d, struct.unpack_from('<I', d, rec)[0])
        _, kt, n, m = struct.unpack_from('<IBII', d, kp)
        fmt, size = _NUM[kt]
        keys = list(struct.unpack_from(f'<{m}{fmt}', d, kp + 13)) if m else []
        keys += [self.string(p) for p in struct.unpack_from(f'<{n - m}I', d, kp + 13 + m * size)]
        raw = d[tp:tp + n]
        ofmt, w = _OFFW[d[op]]
        offs = struct.unpack_from(f'<{n}{ofmt}', d, op + 1)
        slots = []  # (base type, absolute address or None, offset relative to the record)
        for j, (t, o) in enumerate(zip(raw, offs)):
            if t >= 100:
                slots.append((t - 100, op + 1 + j * w - o, None))
            else:
                slots.append((t, None, o))
        return keys, slots

    def value(self, t, p):
        d = self.d
        if t == 7:
            return self.string(struct.unpack_from('<I', d, p)[0])
        if t == 8:
            return self.table(struct.unpack_from('<I', d, p)[0])
        if t == 9:
            return bool(d[p])
        fmt, _ = _NUM[t]
        v = struct.unpack_from('<' + fmt, d, p)[0]
        return int(v) if t == 0 and v == int(v) and abs(v) < 2**53 else v

    def table(self, rec, lazy=False):
        """Decode an S5 record. Pure arrays come back as lists, everything else as dicts."""
        keys, slots = self._shape(rec)
        addr = [(t, a if a is not None else rec + o) for t, a, o in slots]
        if lazy:
            return dict(zip(keys, addr))
        out = {k: self.value(t, p) for k, (t, p) in zip(keys, addr)}
        if keys and keys == list(range(1, len(keys) + 1)):
            return [out[i] for i in range(1, len(keys) + 1)]  # Lua sequence
        return out

    def modules(self):
        """Module name (without the 'Data.' prefix) -> S5 record offset."""
        if self._modules is None:
            lazy = self.table(self.root, lazy=True)
            self._modules = {k: struct.unpack_from('<I', self.d, p)[0] for k, (t, p) in lazy.items() if t == 8}
        return self._modules

    def module(self, name):
        return self.table(self.modules()[name])
