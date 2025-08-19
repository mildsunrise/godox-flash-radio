#!/usr/bin/env python3

import traceback
import numpy as np
import socket
import typing
import sys
from math import tau

colorize = sys.stdout.buffer.isatty()
def ansi_sgr(p: str, content: str):
	content = str(content)
	if not colorize: return content
	if not content.endswith('\x1b[m'):
		content += '\x1b[m'
	return f'\x1b[{p}m' + content
ansi_bold = lambda x: ansi_sgr('1', x)
ansi_dim = lambda x: ansi_sgr('2', x)
ansi_fg0 = lambda x: ansi_sgr('30', x)
ansi_fg1 = lambda x: ansi_sgr('31', x)
ansi_fg2 = lambda x: ansi_sgr('32', x)
ansi_fg3 = lambda x: ansi_sgr('33', x)
ansi_fg4 = lambda x: ansi_sgr('34', x)
ansi_fg5 = lambda x: ansi_sgr('35', x)
ansi_fg6 = lambda x: ansi_sgr('36', x)
ansi_fg7 = lambda x: ansi_sgr('37', x)
ansi_fgB0 = lambda x: ansi_sgr('90', x)
ansi_fgB1 = lambda x: ansi_sgr('91', x)
ansi_fgB2 = lambda x: ansi_sgr('92', x)
ansi_fgB3 = lambda x: ansi_sgr('93', x)
ansi_fgB4 = lambda x: ansi_sgr('94', x)
ansi_fgB5 = lambda x: ansi_sgr('95', x)
ansi_fgB6 = lambda x: ansi_sgr('96', x)
ansi_fgB7 = lambda x: ansi_sgr('97', x)
fmt_raw = ansi_fg6
fmt_metadata = ansi_fg4
fmt_key = ansi_fg3
fmt_target = ansi_fg5
fmt_bad = ansi_fg1

## LAYER 1

fs = 1e6
symbol_rate = 250e3
clock_tone = np.exp(np.arange(1024) * (-tau * symbol_rate/fs) * 1j)
exp_snr = -20

def to_bits(burst):
	# crop burst using a more precise power gating
	burst_p = 20*np.log10(np.abs(burst))
	p_level = np.median(burst_p)
	burst_p -= p_level
	b_start, b_end = np.where(np.diff(burst_p > exp_snr, prepend=False, append=False))[0]
	burst_p_int = np.abs(burst_p[b_start+3:b_end-3])
	burst_p = burst_p[b_start:b_end]; burst = burst[b_start:b_end]

	assert np.amax(burst_p_int) < 3
	assert np.std(burst_p_int) < 0.75

	# FM demodulate
	burst = np.angle(burst[1:] * burst[:-1].conj()) * (fs / tau)

	# recover clock
	clock_bin = np.mean(clock_tone[:len(burst)] * np.abs(burst))
	phase = np.angle(clock_bin)
	burst_fft = np.fft.rfft(burst)
	burst_fft.resize(len(burst)*8 // 2)
	interp_burst = np.fft.irfft(burst_fft * 8, len(burst)*8)
	sample_p = np.arange(np.mod(-phase/tau, 1) * fs/symbol_rate, len(burst) - 0.5, fs/symbol_rate)
	sample_ixs = np.round(sample_p * 8).astype('int')
	symbols = interp_burst[sample_ixs]

	assert np.abs(np.abs(clock_bin) - 40e3) < 10e3
	assert np.abs(np.mean(np.abs(symbols)) - 150e3) < 30e3
	assert np.std(np.abs(symbols)) < 75e3

	bits = symbols < 0
	bits = ''.join(str(int(x)) for x in bits)
	if bits.startswith('01010101'):
		bits = '1' + bits
	return p_level, bits


## LAYER 2

IDS = { (50024 // (id+1)): id for id in range(100) }

def fmt_stops(x: int) -> str:
	if x == 0xFF: return "OFF"
	assert x < 100 # refuse to format suspiciously high values, just in case
	stops = -x/10
	base, adjustment = divmod(stops, 1)
	return f'{stops:.1f} stops (1/{2**int(-base)} {adjustment:+.1f})'

PROPERTIES = {
	0xB1: ("Flash Mode", ["TTL", "Manual", "Strobe"].__getitem__),
	0xB2: ("Flash Zoom level", int),
	0xB3: ("Flash High speed sync", bool),
	0xB4: ("Flash Trigger mode?",),
	0xB7: ("Flash Camera metering?",),
	0xB9: ("Flash TTL exposure", fmt_stops),
	0xBC: ("Flash Manual exposure", fmt_stops),
	0xBD: ("Flash Strobe exposure", fmt_stops),
	0xBE: ("Flash Strobe count", int),
	0xBF: ("Flash Strobe frequency", "{} Hz".format),
	# 0xC0: ("Unknown?",),
	0xD1: ("Modelling Lights Intensity", "{}%".format),
	0xD3: ("Modelling Lights Enabled", bool),
	0xD6: ("Modelling Lights Proportional", bool),
}

SHORT_PAYLOADS = {
	0b00011010: 'Camera shutter prepare?',
	0b00011001: 'Camera shutter flash',
	0b00010001: 'Flash prepare?',
	0b00001001: 'Flash test',
	0b00001010: 'Shutter?',
	0b00100001: 'Flash unprepare?',

	0b10001000: 'Modelling lights OFF',
	0b10001001: 'Modelling lights ON',

	0b10000000: 'Beep OFF',
	0b10000001: 'Beep ON',

	0b01000000: 'UNKNOWN! Third setting?'
}

def parse_message(bits: str):
	pos = 0
	def consume(i: int) -> int:
		nonlocal pos
		assert len(bits) >= pos + i
		x, pos = bits[pos:][:i], pos + i
		return int(x, 2)

	sync = consume(32)
	assert sync == int('10'*16, 2), f'not starting with sync: {sync:#x}'

	w_id = consume(16); w_id_2 = consume(16)
	assert w_id == w_id_2, f'wireless IDs differ, {w_id:#x} != {w_id_2:#x}'
	assert w_id in IDS, f'invalid wireless ID: {w_id:#x}'
	msg = fmt_target(f"[ID {IDS[w_id]:2}]") + '  '

	flags = consume(8)
	if flags == 0b11010101:
		payload = consume(8)
		payload_fmt = fmt_key(name) if (name := SHORT_PAYLOADS.get(payload)) else fmt_bad('UNKNOWN')
		msg += fmt_raw(f'{payload:08b}') + f' ({ansi_bold(payload_fmt) if (payload >> 6) == 0b00 else payload_fmt})'
	elif flags == 0b10101001:
		target = consume(8)
		target_fmt = "All units" if target == 0x50 else \
		             f" Group {target:X} " if 0xA <= target <= 0xE else \
		             f"Unknown target: 0x{target:02X}"
		msg += fmt_target(f'[{target_fmt}]')

		prop_id = consume(8)
		prop = PROPERTIES.get(prop_id)
		msg += f' {fmt_key(prop[0]) if prop else fmt_bad("UNKNOWN")} ' + fmt_raw(f'(0x{prop_id:02X})')

		value = consume(8)
		value_fmt = f'{value:3} / ' + fmt_raw(f'{value:08b}')
		if prop and len(prop) >= 2:
			try:
				value_fmt = str(prop[1](value))
			except Exception:
				value_fmt = fmt_bad('<unexpected / invalid>')
		msg += f' = {value_fmt} ' + fmt_raw(f'(0x{value:02X})')
	else:
		raise AssertionError(f'unexpected type / flags: {flags:08b}')

	assert int(bits[pos-1:pos], 2) == consume(1), "final bit not matching"
	assert len(bits) - pos <= 1, f'garbage after frame: {bits[pos:]}'
	return msg


## RECEIVER LOOP (POWER GATING)

def read_into(fn: typing.Callable[[memoryview], int], buffer):
	view = memoryview(buffer)
	view = view.cast('B', [view.nbytes])
	while len(view):
		if (nread := fn(view)) == 0:
			raise EOFError
		view = view[nread:]

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect(('localhost', 20000))

threshold_db = -30
threshold = 10**(threshold_db/20)

in_progress = 0
sample_n = 0
last_burst = 0
buf = np.empty((102_400,), dtype='complex64')
print('Receiving...', flush=True)
while True:
	read_into(s.recv_into, buf[in_progress:])

	pts = np.where(np.diff(np.abs(buf) > threshold, prepend=False))[0]
	pts, rest = pts[:len(pts)//2*2].reshape(-1, 2), pts[len(pts)//2*2:]

	for idx in pts:
		if idx[1] - idx[0] < 200: continue
		try:
			p_level, bits = to_bits(buf[range(*idx)])
			msg = parse_message(bits)
		except Exception as ex:
			traceback.print_exc()
			continue

		silence = sample_n + idx[0] - last_burst
		if silence > fs*0.01: print()
		metadata = fmt_metadata(f'{silence/fs*1e3:10.2f}ms  {p_level:5.1f}dB')
		print(metadata + '  ' + msg, flush=True)
		last_burst = sample_n + idx[1]

	rest = rest[0] if len(rest) else len(buf)
	sample_n += rest
	rest = buf[rest:].copy()
	buf[:len(rest)] = rest
	in_progress = len(rest)
