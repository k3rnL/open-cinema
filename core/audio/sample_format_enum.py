from enum import Enum


class SampleFormatEnum(Enum):
    INVALID = "Invalid"
    U8 = "U8"
    ALAW = "ALAW"
    ULAW = "ULAW"
    S16LE = "S16LE"
    S16BE = "S16BE"
    FLOAT32LE = "FLOAT32LE"
    FLOAT32BE = "FLOAT32BE"
    S32LE = "S32LE"
    S32BE = "S32BE"
    S24LE = "S24LE"
    S24BE = "S24BE"
    S24_32LE = "S24_32LE"
    S24_32BE = "S24_32BE"