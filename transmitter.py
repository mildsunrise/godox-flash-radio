from typing import Optional
import numpy as np
from enum import Enum, unique
import struct
import sys

SYMBOL_PULSE = np.exp(-np.linspace(-3, +3, 17)**2)
# hamming, cutoff 150kHz, transition ends at 400kHz, 40dB (15 samples)
CHANNEL_FILTER = [-0.0006575763109140098,0.0023783978540450335,0.013170169666409492,0.03827238082885742,0.07778549939393997,0.1230134591460228,0.15937483310699463,0.17332567274570465,0.15937483310699463,0.1230134591460228,0.07778549939393997,0.03827238082885742,0.013170169666409492,0.0023783978540450335,-0.0006575763109140098]

@unique
class FlashMode(Enum):
	TTL = 0
	MANUAL = 1
	STROBE = 2

@unique
class ShortCommand(Enum):
	CAMERA_SHUTTER_PREPARE = 0b00011010
	CAMERA_SHUTTER_FLASH = 0b00011001
	FLASH_PREPARE = 0b00010001
	FLASH_TEST = 0b00001001
	SHUTTER = 0b00001010
	FLASH_UNPREPARE = 0b00100001

	LIGHTS_OFF = 0b10001000
	LIGHTS_ON = 0b10001001

	BEEP_OFF = 0b10000000
	BEEP_ON = 0b10000001

	UNK_1 = 0b01000000

class Command:
	netid: int
	def __init__(self, netid: int = 0) -> None:
		self.netid = netid

	# radio layer

	def rf_burst(self, bits: list[int]):
		symbols = np.array([ [+1,-1][b] for b in bits ])
		symbols.resize([8, len(symbols)])  # 250kHz to 2MHz
		signal = np.convolve(symbols.T.reshape(-1), SYMBOL_PULSE) / 1.2
		signal = np.exp(2j * np.pi * np.cumsum(signal) * (200e3 / 2e6))
		signal = np.convolve(signal, CHANNEL_FILTER)

		signal = signal.astype('complex64').view('float32')
		assert np.amax(np.abs(signal)) <= 1.0001
		signal = np.round(signal * 127).astype('int8')
		sys.stdout.buffer.write(signal.tobytes())

	# low level

	def command(self, payload_type: int, payload: bytes):
		netid = 50024 // (self.netid+1)
		payload = struct.pack('>HHB', netid, netid, payload_type) + payload
		bits = [ (b >> i) & 1 for b in payload for i in reversed(range(8)) ]
		bits = [1, 0] * 16 + bits + bits[-1:]
		self.rf_burst(bits)

	def short_command(self, cmd: ShortCommand):
		self.command(0b11010101, struct.pack('>B', cmd.value))

	def set_property(self, group: Optional[int], key: int, value: int):
		self.command(0b10101001, payload=struct.pack('>BBB', group if group != None else 0x50, key, value))

	# properties

	def set_flash_mode(self, group: Optional[int], value: FlashMode):
		self.set_property(group, 0xB1, value.value)

	''' Flash Zoom level '''
	def set_flash_zoom(self, group: Optional[int], value: int):
		self.set_property(group, 0xB2, value)

	''' Flash High speed sync '''
	def set_flash_hsync(self, group: Optional[int], value: bool):
		self.set_property(group, 0xB3, int(value))

	''' Flash Trigger mode? '''
	def set_flash_unk4(self, group: Optional[int], value: int):
		self.set_property(group, 0xB4, value)

	''' Flash Camera metering? '''
	def set_flash_unk7(self, group: Optional[int], value: int):
		self.set_property(group, 0xB7, value)

	''' Flash exposure (in negated tenths of a stop) '''
	def set_flash_exposure(self, group: Optional[int], mode: FlashMode, value: int):
		self.set_property(group, {
			FlashMode.TTL: 0xB9,
			FlashMode.MANUAL: 0xBC,
			FlashMode.STROBE: 0xBD,
		}[mode], value)

	''' Flash Strobe count '''
	def set_flash_strobe_count(self, group: Optional[int], value: int):
		self.set_property(group, 0xBE, value)

	''' Flash Strobe frequency (in Hz) '''
	def set_flash_strobe_freq(self, group: Optional[int], value: int):
		self.set_property(group, 0xBF, value)

	# 0xC0: ("Unknown?",),

	''' Modelling Lights Intensity (in %) '''
	def set_light_intensity(self, group: Optional[int], value: int):
		self.set_property(group, 0xD1, value)

	''' Modelling Lights Enabled '''
	def set_light_enabled(self, group: Optional[int], value: bool):
		self.set_property(group, 0xD3, int(value))

	''' Modelling Lights Proportional '''
	def set_light_proportional(self, group: Optional[int], value: bool):
		self.set_property(group, 0xD6, int(value))
