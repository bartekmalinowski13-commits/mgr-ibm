"""Format parser plugins (KiCad 6-9, CSV BOM) producing ``ParsedDesign``."""

from bomagent_cad.base import FileRef, FormatParser, ParseError, UnsupportedFormatError
from bomagent_cad.registry import detect, parse_files

__version__ = "1.0.0"
__all__ = [
    "FileRef",
    "FormatParser",
    "ParseError",
    "UnsupportedFormatError",
    "detect",
    "parse_files",
]
