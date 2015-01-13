#!/usr/bin/env python
# -*- coding: utf-8 -*-
## Copyright (c) 2014 Rasmus Sorensen <scholer.github.io> rasmusscholer@gmail.com

##    This program is free software: you can redistribute it and/or modify
##    it under the terms of the GNU General Public License as published by
##    the Free Software Foundation, either version 3 of the License, or
##    (at your option) any later version.
##
##    This program is distributed in the hope that it will be useful,
##    but WITHOUT ANY WARRANTY; without even the implied warranty of
##    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
##    GNU General Public License for more details.
##
##    You should have received a copy of the GNU General Public License
##    along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""

Ad-in sqlite3 replacement module for when sqlite3 is not available in the python build.
Made for Sublime Text 3 and the build-in python 3.3 interpreter.

Usage:

    >>> from .sqlite3_adhoc import connect
or
    >>> import sqlite3_adhoc as sqlite3

How is this module created:
    1) Unpack platform-specific python package.
    2) Copy sqlite3 files to sub-folder.
        This includes: __init__.py, _sqlite3.lib, _sqlite3.pyd, dbapi2.py, dump.py
        and, for Windows: sqlite3.dll
        and, for OS X : sqlite3.so

The only changes made to these to get it to work is:
    #   In dbapi2.py change line 26 to use relative import rather than absolute, i.e.
        change "from _sqlite3 import *" to "from ._sqlite3 import *"

"""


import os
import sys
import platform
#print("__file__ : ", __path__)
#print("__path__ : ", __path__)


# This may be more reliable on OS X, c.f. https://docs.python.org/2/library/platform.html
is_64bits = sys.maxsize > 2**32

if sys.platform == 'win32':
    if '64' in platform.architecture()[0]:
        subdir = 'sqlite3_win32_64bit'
        #from .sqlite3_win32_64bit.dbapi2 import *
        from .sqlite3_win32_64bit import dbapi2 as sqlite3
    else:
        subdir = 'sqlite_win32_32bit'
        #from .sqlite3_win32_32bit.dbapi2 import *
        from .sqlite3_win32_32bit import dbapi2 as sqlite3
elif sys.platform == 'darwin':
    if is_64bits:
        subdir = 'sqlite_darwin_64bit'
        #from .sqlite3_darwin_64bit.dbapi2 import *
        from .sqlite3_darwin_64bit import dbapi2 as sqlite3
    else:
        #from .sqlite3_darwin_32bit.dbapi2 import *
        subdir = 'sqlite_darwin_32bit'
        from .sqlite3_darwin_32bit import dbapi2 as sqlite3
else:
    raise ImportError("Unsupported platform")

print("sqlite3 stand-in: Using", subdir)
# __path__ is a list of folders to look for python modules for this module
__path__ = [os.path.join(__path__[0], subdir)]
print("sqlite3 __path__ : ", __path__)

# doesn't work, use imp module.. but modifying __path__ should be sufficient..
#from subdir import *
