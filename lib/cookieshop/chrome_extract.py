#The MIT License (MIT)

# Copyright (c) 2012 Jordan Wright <jordan-wright.github.io>
# Copyright (c) 2014 Rasmus Sorensen <scholer.github.io>

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


"""

from __future__ import print_function
import os
import sys
import warnings
import tempfile

libdir = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse
try:
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
    # https://github.com/ghaering/pysqlite  (https://docs.python.org/2/library/sqlite3.html) -- is C code...
    # pypi.python.org/pypi/PyDbLite , www.pydblite.net/en/index.html -- pure python, but a tad different from sqlite3.
    # from pydblite import sqlite # pydblite relies on built-in sqlite3 or pysqlite2...
    pass

# We also need win32crypt and Crypto... long way to go...
try:
    from Crypto.Cipher import AES
    from Crypto.Protocol.KDF import PBKDF2
except ImportError:
    warnings.warn("Could not import Crypto module.")
    # Crypto alternatives?
    # pyOCB (github.com/kravietz/pyOCB) - could be used, but Chrome encrypts as CBC, not OCB.
    # AES-Python (https://github.com/bozhu/AES-Python)
    #AES-python (, https://github.com/bozhu/AES-Python)
    #--- another pure-python implementation. However, does not have an easy-to-use interface.
    #PythonAES, https://github.com/caller9/pythonaes
    #- another pure-python implementation.
    #TLSlite (https://github.com/trevp/tlslite)
    #--- has pure-python AES in https://github.com/trevp/tlslite/blob/master/tlslite/utils/python_aes.py
    # dlitz has PBKDF2 has pure-python module: github.com/dlitz/python-pbkdf2

    # Oh, I tried to use PyCrypto, but is seems it is also not python3.x compatible...? (I get an error...)
    # But pypi.python.org/pypi/pycrypto states that it is compatible with python 3.3 ?
    # Edit: PyCrypto's setup is expected to run 2to3 on the code.

    # The key issue:
    #from pbkdf2 import PBKDF2 as PBKDF2_cls
    # PBKDF2 from pbkdf2 is different from Crypto.Protocol.KDF
    #def PBKDF2(password, salt, dkLen=16, count=1000, prf=None):
    #    keybuf = PBKDF2(password, salt, count)
    #    return keybuf.read(dkLen)
    # Edit: Just use the Crypto.Protocol.KDF module.
    from adhoc_crypto.KDF import PBKDF2
try:
    import win32crypt
except ImportError:
    warnings.warn("Could not import win32crypt module. If you are on Windows, please install the pywin32 package.")
    win32crypt = None
    from wincrypt_understudy import decrypt as win_decrypt  # Seems good enough...

crypt_iv = b' ' * 16






# PATHS:

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
    import warnings
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
        my_pass = my_pass.encode('utf8')
        iterations = 1003
    # If running Chromium on Linux
    elif sys.platform == 'linux':
        my_pass = 'peanuts'.encode('utf8')
        iterations = 1
    else:
        raise Exception("This script only works on OSX or Linux.")

    # Generate key from values above
    key = PBKDF2(my_pass, salt, length, iterations)
    return key


def chrome_decrypt(encrypted_value, key=None):
    """
    Decrypt value using Chrome's platform-dependent symmetric encryption scheme using key.
    """
    # For windows, chrome just uses
    if sys.platform == 'win32':
        # CryptUnprotectData returns a two-string tuple. Not sure what the first value is...
        # This is more obfucation, so might change at some point...
        if win32crypt:
            _, decrypted = win32crypt.CryptUnprotectData(encrypted_value, None, None, None, 0)
        else:
            # Understudy:
            win_decrypt(encrypted_value)
        return decrypted

    # Encrypted cookies should be prefixed with 'v10' according to the Chromium code. Strip it off.
    # (Only for OSX/Linux...?)
    encryption_scheme_version, encrypted_value = encrypted_value[:3], encrypted_value[3:]

    # Strip padding by taking off number indicated by padding
    # eg if last is '\x0e' then ord('\x0e') == 14, so take off 14.
    # You'll need to change this function to use ord() for python2.
    def clean(x):
        """ Remove padding and decode to utf8 """
        return x[:-x[-1]].decode('utf8')

    cipher = AES.new(key, AES.MODE_CBC, IV=crypt_iv)
    decrypted = cipher.decrypt(encrypted_value)

    return clean(decrypted)



def query_db(dbpath, query):
    """
    Connects to database in dbpath, queries with query
    and returns all matching rows as a list by calling fetchall()
    """
    # Connect to the Database
    print("Connecting to chrome database:", dbpath)
    conn = sqlite3.connect(dbpath)
    cursor = conn.cursor()
    try:
        with sqlite3.connect(dbpath) as conn:
            # Get the results
            # Consider using  conn.execute(sql) as short-hand for querying and returning all results...
            #cursor.execute(query)
            #res = cursor.fetchall()
            cursor = conn.execute(query)
            res = cursor.fetchall()
        print("- %s rows retrieved!" % len(res))
    except sqlite3.OperationalError:
        print("- Could not connect to database: %s" % dbpath)
        print("- Database might be locked, e.g. if chrome is currently running.")
        print("- Will create a copy and try again...")
        # TemporaryDirectory only for python 3.2+ :
        #with tempfile.TemporaryDirectory() as tempdir:
        try:
            tempdir = tempfile.TemporaryDirectory()
        except AttributeError:
            tempdir = tempfile.mkdtemp()
        tempdbpath = os.path.join(tempdir, os.path.basename(dbpath))
        import shutil
        print("Copying db to temp file:", tempdbpath)
        shutil.copy(dbpath, tempdbpath)
        print("Connecting to chrome database:", tempdbpath)
        with sqlite3.connect(tempdbpath) as conn:
            cursor = conn.execute(query)
            res = cursor.fetchall()
            #conn = sqlite3.connect(tempdbpath)
            #cursor = conn.cursor()
            ## Get the results
            #cursor.execute(query)
        print("- %s rows retrieved!" % len(res))
        del cursor
        conn.close()
        try:
            os.remove(tempdbpath)
            try:
                tempdir.cleanup()
            except AttributeError:
                shutil.rmtree(tempdir)
        except WindowsError as e:
            print(e)

    return res


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



def get_chrome_cookies(url):

    key = make_chrome_cryptkey() # Encryption key (is None for Windows)
    query = cookie_query_for_domain(url)
    # SQL query returns rows with: name, value, encrypted_value

    cookie_entries = query_db(cookies_dbpath, query)  # Gets the full results list and closes db connection
    cookies_dict = {k: chrome_decrypt(ev, key=key) if ev else v for k, v, ev in cookie_entries}

    return cookies_dict



def main():
    print_logins()



if __name__ == '__main__':
    main()
