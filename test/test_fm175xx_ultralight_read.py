"""Variable-length NTAG/Ultralight reads, simulated without hardware."""
import logging
from pathlib import Path
import sys
from types import ModuleType

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# The reader module imports Linux-only GPIO/SPI bindings at import time. No test
# here constructs or touches physical hardware.
sys.modules.setdefault("gpiod", ModuleType("gpiod"))
sys.modules.setdefault("spidev", ModuleType("spidev"))

from reader.fm175xx import constants as Constants
from reader.fm175xx.rfid import Fm175xx

BYTES_PER_PAGE = Constants.FM175XX_NTAG215_BYTES_PER_PAGE


def reader(total_pages):
    """A reader whose page READ behaves like a tag of total_pages pages.

    A READ returns four pages and rolls over within addressable memory, so a read
    starting on the last page still succeeds and overruns. An address past the
    last page is NAKed.
    """
    memory = bytes(range(256)) * (total_pages * BYTES_PER_PAGE // 256 + 1)
    memory = memory[: total_pages * BYTES_PER_PAGE]

    def page_read(page, _pages=total_pages):
        ret = type("R", (), {"err_code": Constants.FM175XX_OK, "out_data": None})()
        if page >= _pages:
            ret.err_code = Constants.FM175XX_CARD_READ_ERR
            ret.out_data = None
            return ret
        data = bytearray()
        for offset in range(4):
            start = ((page + offset) % _pages) * BYTES_PER_PAGE
            data += memory[start : start + BYTES_PER_PAGE]
        ret.out_data = list(data)
        return ret

    instance = Fm175xx.__new__(Fm175xx)
    instance.logger = logging.getLogger("test_fm175xx")
    instance._Fm175xx__reader_a_ultralight_page_read = page_read
    return instance, memory


def read_all(total_pages):
    instance, memory = reader(total_pages)
    return instance._Fm175xx__reader_a_ultralight_read_all_data(), memory


@pytest.mark.parametrize("total_pages,expected_bytes", [
    (Constants.FM175XX_NTAG213_TOTAL_PAGES, 180),
    (Constants.FM175XX_NTAG215_TOTAL_PAGES, 540),
    (Constants.FM175XX_NTAG216_TOTAL_PAGES, 924),
])
def test_recognised_tags_read_in_full(total_pages, expected_bytes):
    ret, memory = read_all(total_pages)
    assert ret.err_code == Constants.FM175XX_OK
    # The whole tag, and no roll-over bytes from the final overrunning read.
    assert len(ret.out_data) == expected_bytes
    assert bytes(ret.out_data) == memory[:expected_bytes]


@pytest.mark.parametrize("total_pages", [0, 4, 16, 20, 41, 44])
def test_tags_below_the_smallest_known_size_are_rejected(total_pages):
    # 41 is a real size (Ultralight EV1 MF0UL21). Roll-over makes it answer every
    # read a 44-page tag would, so it must not be mistaken for one.
    ret, _ = read_all(total_pages)
    assert ret.err_code == Constants.FM175XX_CARD_READ_ERR


def test_ntag216_is_not_truncated_to_ntag215():
    # The previous loop bound stopped at 135 pages and returned 540 bytes for an
    # NTAG216, silently discarding 384 bytes an NDEF record could occupy.
    ret, _ = read_all(Constants.FM175XX_NTAG216_TOTAL_PAGES)
    assert len(ret.out_data) > Constants.FM175XX_NTAG215_TOTAL_SIZE
