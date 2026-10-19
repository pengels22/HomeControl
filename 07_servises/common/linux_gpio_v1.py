"""Physical input-only GPIO ABI v1 transport for Jetson's Linux 4.9 kernel.

Uses the installed linux/gpio.h UAPI. Never issues SET_VALUES or output flags.
No inversion, pull configuration, or simulation fallback is provided.
"""
import fcntl
import os
import struct

GET_LINEINFO = 0xc048b402
GET_LINEHANDLE = 0xc16cb403
GET_VALUES = 0xc040b408


class LinuxGPIOV1InputTransport:
    def __init__(self, chip, line, consumer):
        self.line = int(line)
        self.fd = None
        chip_fd = os.open(chip, os.O_RDONLY | os.O_CLOEXEC)
        try:
            info = bytearray(struct.pack('=II32s32s', self.line, 0, b'', b''))
            fcntl.ioctl(chip_fd, GET_LINEINFO, info, True)
            _, flags, _, _ = struct.unpack('=II32s32s', info)
            if flags & 3:
                raise OSError('refusing GPIO line already owned or configured as output')
            request = bytearray(364)
            struct.pack_into('=I', request, 0, self.line)
            struct.pack_into('=I', request, 256, 1)  # GPIOHANDLE_REQUEST_INPUT only
            request[324:356] = consumer.encode()[:31].ljust(32, b'\0')
            struct.pack_into('=I', request, 356, 1)
            fcntl.ioctl(chip_fd, GET_LINEHANDLE, request, True)
            self.fd = struct.unpack_from('=i', request, 360)[0]
            if self.fd < 0:
                raise OSError('GPIO input handle unavailable')
        finally:
            os.close(chip_fd)

    def read(self):
        if self.fd is None:
            raise OSError('GPIO input closed')
        data = bytearray(64)
        fcntl.ioctl(self.fd, GET_VALUES, data, True)
        return bool(data[0])

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
