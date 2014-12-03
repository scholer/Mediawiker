# Used information from:
# http://stackoverflow.com/questions/463832/using-dpapi-with-python
# http://www.linkedin.com/groups/Google-Chrome-encrypt-Stored-Cookies-36874.S.5826955428000456708

# pylint: disable=W0301

from ctypes import c_buffer
#from ctypes import *
from ctypes.wintypes import DWORD
import sqlite3;

cookieFile="C:/Users/your_user_name/AppData/Local/Google/Chrome/User Data/Default/Cookies";
hostKey="my_host_key";

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

conn = sqlite3.connect(cookieFile);
c = conn.cursor();
c.execute("""\
SELECT
    host_key,
    name,
    path,
    value,
    encrypted_value
FROM cookies
WHERE host_key = '{0}'
;
""".format(hostKey));

cookies = c.fetchmany(10);
c.close();

for row in cookies:
    dc = decrypt(row[4]);
    print( \
"""
host_key: {0}
name: {1}
path: {2}
value: {3}
encrpyted_value: {4}
""".format(row[0], row[1], row[2], row[3], dc));
