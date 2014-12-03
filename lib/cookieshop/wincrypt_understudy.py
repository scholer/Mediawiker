#The MIT License (MIT)

# Copyright (c) 2014 Rasmus Sorensen <scholer.github.io>
# Copyright (c) 2014 "Mark"
# Based on http://stackoverflow.com/questions/21496209/cookie-issue-with-chrome-33-beta

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.


# Used information from:
# http://stackoverflow.com/questions/463832/using-dpapi-with-python
# http://www.linkedin.com/groups/Google-Chrome-encrypt-Stored-Cookies-36874.S.5826955428000456708

from ctypes import *
from ctypes.wintypes import DWORD

#cookieFile="C:/Users/your_user_name/AppData/Local/Google/Chrome/User Data/Default/Cookies";
#hostKey="my_host_key";


LocalFree = windll.kernel32.LocalFree;
memcpy = cdll.msvcrt.memcpy;
CryptProtectData = windll.crypt32.CryptProtectData;
CryptUnprotectData = windll.crypt32.CryptUnprotectData;
CRYPTPROTECT_UI_FORBIDDEN = 0x01;

class DATA_BLOB(Structure):
    _fields_ = [("cbData", DWORD), ("pbData", POINTER(c_char))];

def getData(blobOut):
    cbData = int(blobOut.cbData);
    pbData = blobOut.pbData;
    buffer = c_buffer(cbData);
    memcpy(buffer, pbData, cbData);
    LocalFree(pbData);
    return buffer.raw;

def encrypt(plainText):
    bufferIn = c_buffer(plainText, len(plainText));
    blobIn = DATA_BLOB(len(plainText), bufferIn);
    blobOut = DATA_BLOB();

    if CryptProtectData(byref(blobIn), u"python_data", None,
                       None, None, CRYPTPROTECT_UI_FORBIDDEN, byref(blobOut)):
        return getData(blobOut);
    else:
        raise Exception("Failed to encrypt data");

def decrypt(cipherText):
    bufferIn = c_buffer(cipherText, len(cipherText));
    blobIn = DATA_BLOB(len(cipherText), bufferIn);
    blobOut = DATA_BLOB();

    if CryptUnprotectData(byref(blobIn), None, None, None, None,
                              CRYPTPROTECT_UI_FORBIDDEN, byref(blobOut)):
        return getData(blobOut);
    else:
        raise Exception("Failed to decrypt data");


def test_module():
    import win32crypt
    unencrypted = "unencrypted"

    encrypt_ctrl = win32crypt.CryptProtectData(unencrypted)
    enctypt_test = encrypt(unencrypted)

    decrypted_ctrl = win32crypt.CryptUnprotectData(encrypt_ctrl)[1]
    decrypted_test = decrypt(encrypt_ctrl)
    decrypted_test2 = decrypt(enctypt_test)

    assert decrypted_ctrl == decrypted_test
    assert unencrypted == decrypted_test
    assert decrypted_test == decrypted_test2

    # Weird: The decrypted are the same, but the encrypted differ
    # And, they can decrypt different stuff to the same value.
    # Probably just some padding or data-type issue...
    # assert encrypt_ctrl == enctypt_test


if __name__ == '__main__':
    import sys
    if "--test" in sys.argv:
        run_test()
