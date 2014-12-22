#!/usr/bin/env python
# -*- coding: utf-8 -*-

# pylint: disable=W0142,C0302
# W0142="* or ** magic"
# C0302="Too many lines in module"
# pylint: disable=R0914,R0912,R0915
# Too many branches, variables and lines in function
# pylint: disable=W0511,C0111
## ToDos, missing docstrings,
# pylint: disable=W0611
## Unused imports,
# pylint: disable=F0401,E1101,W0232,R0903,R0201,W0613,W0201
## Unable to import, no __init__, no member, too few lines, method-could-be-function, unused argument, attribute defined outside __init__

"""

Main module for Mediawikier package.

To import from within Sublime:
>>> from Mediawiker import mediawiker

Mediawikier settings:

    "mediawiker_file_rootdir": null,        # Specify a default dir for wiki files.
    "mediawiker_use_subdirs": false,        #
    "mediawiker_title_to_filename": true    #
    "mediawiki_quote_plus": true,           # Use quote_plus rather than quote, will convert slashes and use '+' for space rather than '%20'

    "mediawiker_clipboard_as_defaultpagename": false,   # Insert clipboard content as default page name (saves you a "ctrl+v" keystroke, horray).
    "mediawiker_newtab_ongetpage": true,    # Open wikipages in a new tab.
    "mediawiker_clearpagename_oninput": true, #  ??

    "mediawiker_files_extension": ["mediawiki", "wiki", "wikipedia", ""],   # File extensions recognized and allowed.

    "mediawiker_mark_as_minor": false,      #
"""


from __future__ import print_function
import sys
import os
from os.path import splitext, basename, dirname, join
import imp
pythonver = sys.version_info[0]

import webbrowser
import urllib
import re
import sublime
import sublime_plugin
import base64
from hashlib import md5
import uuid
from datetime import date

# https://github.com/wbond/sublime_package_control/wiki/Sublime-Text-3-Compatible-Packages
# http://www.sublimetext.com/docs/2/api_reference.html
# http://www.sublimetext.com/docs/3/api_reference.html
# sublime.message_dialog

### Add pyfiglet library to path: ###
# (pyfiglet is used to print big ascii letters and is used by e.g. MediawikerInsertBigTodoTextCommand)
# pwaller's original pyfiglet uses pkg_resources module,
# which is not available in Sublime Text, so must use '-rs' version
# from https://github.com/scholer/pyfiglet
# Zip all files to 'pyfiglet-rs.zip', and ensure that the zipfiles structure matches this:
# pyfiglet-rs.zip/setup.py
# pyfiglet-rs.zip/pyfiglet/version.py
# pyfiglet-rs.zip/pyfiglet/fonts
# Then move pyfiglet-rs.zip to the directory containing this file.
try:
    # Use up-to-date library, if available:
    import pyfiglet
except ImportError:
    # Use included library:
    PYFIGLET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib', 'pyfiglet.zip')
    sys.path.append(PYFIGLET_PATH)
    try:
        import pyfiglet
        print("Imported pyfiglet from local zip library.")
    except ImportError:
        print("Could not import local pyfiglet from zip; big text will not be available.")

st_version = 2
if int(sublime.version()) > 3000:
    st_version = 3
else:
    FileExistsError = WindowsError

# import custom ssl module on linux
# thnx to wbond and his SFTP module!
# http://sublimetext.userecho.com/topic/50801-bundle-python-ssl-module/

arch_lib_path = None
if sublime.platform() == 'linux':
    arch_lib_path = join(dirname(__file__), 'lib', 'st%d_linux_%s' % (st_version, sublime.arch()))
    print('Mediawiker: enabling custom linux ssl module')
    for ssl_ver in ['1.0.0', '10', '0.9.8']:
        lib_path = join(arch_lib_path, 'libssl-' + ssl_ver)
        sys.path.append(lib_path)
        try:
            import _ssl
            print('Mediawiker: successfully loaded _ssl module for libssl.so.%s' % ssl_ver)
            break
        except (ImportError) as e:
            print('Mediawiker: _ssl module import error - ' + str(e))
    if '_ssl' in sys.modules:
        try:
            if sys.version_info < (3,):
                plat_lib_path = join(sublime.packages_path(), 'Mediawiker', 'lib', 'st2_linux')
                m_info = imp.find_module('ssl', [plat_lib_path])
                m = imp.load_module('ssl', *m_info)
            else:
                import ssl
                print('Mediawiker: ssl loaded!')
        except (ImportError) as e:
            print('Mediawiker: ssl module import error - ' + str(e))

# after ssl mwclient import
# in httpmw.py http_compat will be reloaded
if pythonver >= 3:
    # NOTE: load from package, not used now because custom ssl
    # current_dir = dirname(__file__)
    # if '.sublime-package' in current_dir:
    #     sys.path.append(current_dir)
    #     import mwclient
    # else:
    #     from . import mwclient
    from . import mwclient
else:
    import mwclient

CATEGORY_NAMESPACE = 14  # category namespace number
IMAGE_NAMESPACE = 6  # image namespace number
TEMPLATE_NAMESPACE = 10  # template namespace number


def mw_get_setting(key, default_value=None):
    """ Returns setting for key <key>, defaulting to default_value if not present (default: None) """
    settings = sublime.load_settings('Mediawiker.sublime-settings')
    return settings.get(key, default_value)


def mw_set_setting(key, value):
    """ Set setting for key <key>, to value <value>. """
    settings = sublime.load_settings('Mediawiker.sublime-settings')
    settings.set(key, value)
    sublime.save_settings('Mediawiker.sublime-settings')


def mw_enco(value):
    ''' for md5 hashing string must be encoded '''
    if pythonver >= 3:
        return value.encode('utf-8')
    return value


def mw_deco(value):
    ''' for py3 decode from bytes '''
    if pythonver >= 3:
        return value.decode('utf-8')
    return value




def mw_get_digest_header(header, username, password, path):
    """ Return an auth header for use in the "Digest" authorization realm. """
    HEADER_ATTR_PATTERN = r'([\w\s]+)=\"?([^".]*)\"?'
    METHOD = "POST"
    header_attrs = {}
    hprms = header.split(', ')
    for hprm in hprms:
        params = re.findall(HEADER_ATTR_PATTERN, hprm)
        for param in params:
            header_attrs[param[0]] = param[1]

    cnonce = str(uuid.uuid4())  # random clients string..
    nc = '00000001'
    realm = header_attrs['Digest realm']
    nonce = header_attrs['nonce']
    qop = header_attrs.get('qop', 'auth')
    digest_uri = header_attrs.get('uri', path)
    algorithm = header_attrs.get('algorithm', 'MD5')
    # TODO: ?
    # opaque = header_attrs.get('opaque', '')
    entity_body = ''  # TODO: ?

    if algorithm == 'MD5':
        ha1 = md5(mw_enco('%s:%s:%s' % (username, realm, password))).hexdigest()
    elif algorithm == 'MD5-Sess':
        ha1 = md5(mw_enco('%s:%s:%s' % (md5(mw_enco('%s:%s:%s' % (username, realm, password))), nonce, cnonce))).hexdigest()

    if 'auth-int' in qop:
        ha2 = md5(mw_enco('%s:%s:%s' % (METHOD, digest_uri, md5(entity_body)))).hexdigest()
    elif 'auth' in qop:
        ha2 = md5(mw_enco('%s:%s' % (METHOD, digest_uri))).hexdigest()

    if 'auth' in qop or 'auth-int' in qop:
        response = md5(mw_enco('%s:%s:%s:%s:%s:%s' % (ha1, nonce, nc, cnonce, qop, ha2))).hexdigest()
    else:
        response = md5(mw_enco('%s:%s:%s' % (ha1, nonce, ha2))).hexdigest()

    # auth = 'username="%s", realm="%s", nonce="%s", uri="%s", response="%s", opaque="%s", qop="%s", nc=%s, cnonce="%s"' % (username, realm, nonce, digest_uri, response, opaque, qop, nc, cnonce)
    auth = 'username="%s", realm="%s", nonce="%s", uri="%s", response="%s", qop="%s", nc=%s, cnonce="%s"' % (username, realm, nonce, digest_uri, response, qop, nc, cnonce)
    return auth


def mw_get_connect(password=''):
    """ Returns a mwclient connection to the active MediaWiki site. """
    DIGEST_REALM = 'Digest realm'
    BASIC_REALM = 'Basic realm'
    site_name_active = mw_get_setting('mediawiki_site_active')
    site_list = mw_get_setting('mediawiki_site')
    site_params = site_list[site_name_active]
    site = site_params['host']
    path = site_params['path']
    username = site_params['username']
    domain = site_params['domain']
    is_https = site_params.get('https', False)
    if is_https:
        sublime.status_message('Trying to get https connection to https://%s' % site)
    host = site if not is_https else ('https', site)
    proxy_host = site_params.get('proxy_host', '')
    if proxy_host:
        # proxy_host format is host:port, if only host defined, 80 will be used
        host = proxy_host if not is_https else ('https', proxy_host)
        proto = 'https' if is_https else 'http'
        path = '%s://%s%s' % (proto, site, path)
        sublime.message_dialog('Connection with proxy: %s %s' % (host, path))
    # If the mediawiki instance has OpenID login (e.g. google), it is easiest to
    # login by injecting the open_id_session_id cookie into the session's cookie jar:
    inject_cookies = site_params.get('cookies')

    try:
        # It would be nice to be able to pass in old cookies, but that is not part of the original design.
        # we have:
        # <Site>sitecon . <HTTPPool> connection [list of ((scheme, hostname), <HTTP(S)PersistentConnection> connection) tuples]
        # <HTTP(S)PersistentConnection> connection._conn = <httplib.HTTP(S)Connection>
        # connection.cookies is a dict[host] = <CookieJar> , either individual or shared pool (if pool is provided to connection init)
        # Note: For cookies[host], host is hostname string e.g. "lab.wyss.harvard.edu"; not ('https', 'harvard.edu') tuple.
        # CookieJar is a subclass of dict. I've changed it's __init__ so you can initialize it as a dict.
        # connection.post(<host>, ...) finds the host in the connection pool,
        sitecon = mwclient.Site(host=host, path=path, inject_cookies=inject_cookies)
    except mwclient.HTTPStatusError as exc:
        e = exc.args if pythonver >= 3 else exc
        is_use_http_auth = site_params.get('use_http_auth', False)
        http_auth_login = site_params.get('http_auth_login', '')
        http_auth_password = site_params.get('http_auth_password', '')
        if e[0] == 401 and is_use_http_auth and http_auth_login:
            http_auth_header = e[1].getheader('www-authenticate')
            custom_headers = {}
            realm = None
            if http_auth_header.startswith(BASIC_REALM):
                realm = BASIC_REALM
            elif http_auth_header.startswith(DIGEST_REALM):
                realm = DIGEST_REALM

            if realm is not None:
                if realm == BASIC_REALM:
                    auth = mw_deco(base64.standard_b64encode(mw_enco('%s:%s' % (http_auth_login, http_auth_password))))
                    custom_headers = {'Authorization': 'Basic %s' % auth}
                elif realm == DIGEST_REALM:
                    auth = mw_get_digest_header(http_auth_header, http_auth_login, http_auth_password, '%sapi.php' % path)
                    custom_headers = {'Authorization': 'Digest %s' % auth}

                if custom_headers:
                    sitecon = mwclient.Site(host=host, path=path, custom_headers=custom_headers)
            else:
                error_message = 'HTTP connection failed: Unknown realm.'
                sublime.status_message(error_message)
                raise Exception(error_message)
        else:
            sublime.status_message('HTTP connection failed: %s' % e[1])
            raise Exception('HTTP connection failed.')
    except mwclient.HTTPRedirectError as e:
        # if redirect to '/login.php' page:
        sublime.status_message('Connection to server failed. If you are logging in with an open_id session cookie, it may have expired. (HTTPRedirectError)')
        raise(e)


    # if login is not empty - auth required
    if username:
        try:
            sitecon.login(username=username, password=password, domain=domain)
            sublime.status_message('Logon successfully.')
        except mwclient.LoginError as e:
            sublime.status_message('Login failed: %s' % e[1]['result'])
            return
    elif inject_cookies:
        sublime.status_message('Connected using cookies: %s' % ", ".join(inject_cookies.keys()))
        print('Connected using cookies: %s' % ", ".join(inject_cookies.keys()))
    else:
        sublime.status_message('Connection without authorization')
    return sitecon


def mw_get_page_text(site, title):
    denied_message = 'You have not rights to edit this page. Click OK button to view its source.'
    page = site.Pages[title]
    if page.can('edit'):
        return True, page.edit()
    else:
        if sublime.ok_cancel_dialog(denied_message):
            return False, page.edit()
        else:
            return False, ''


def mw_strquote(string_value, quote_plus=None, safe=None):
    """
    str quote and unquote:
        quoting will replace reserved characters (: ; ? @ & = + $ , /) with encoded versions,
        unquoting will reverse the process.
        The parameter safe='/' specified which characters not to touch.
    quote_plus will further replace spaces with '+' and defaults to safe='' (i.e. all reserved are replaced.)
    Note that the 'safe' argument only applies when quoting; unquoting will always convert all.

    Consider using (un)quote_plus variants.
    This will escape '/' to '%2F' and replace space ' ' with '+' rather than '%20'.
    """
    # Support for "quote_plus":
    if quote_plus is None:
        quote_plus = mw_get_setting("mediawiki_quote_plus", False)
    if safe is None:
        safe = mw_get_setting("mediawiker_quote_safe", '' if quote_plus else '/')
    if pythonver >= 3:
        quote = urllib.parse.quote_plus if quote_plus else urllib.parse.quote
        return quote(string_value, safe=safe)
    else:
        quote = urllib.quote_plus if quote_plus else urllib.quote
        return quote(string_value.encode('utf-8'), safe=safe)


def mw_strunquote(string_value, quote_plus=None):
    """ Reverses the effect of mw_strquote() """
    if quote_plus is None:
        quote_plus = mw_get_setting("mediawiki_quote_plus", False)
    if pythonver >= 3:
        unquote = urllib.parse.unquote_plus if quote_plus else urllib.parse.unquote
        return unquote(string_value)
    else:
        # Python 2 urllib does not handle unicode. However, is it really needed to encode/decode?
        unquote = urllib.unquote_plus if quote_plus else urllib.quote
        return unquote(string_value.encode('ascii')).decode('utf-8')



def mw_pagename_clear(pagename):
    """ Return clear pagename if page-url was set instead of.."""
    site_name_active = mw_get_setting('mediawiki_site_active')
    site_list = mw_get_setting('mediawiki_site')
    site = site_list[site_name_active]['host']
    pagepath = site_list[site_name_active]['pagepath']
    try:
        pagename = mw_strunquote(pagename)
    except UnicodeEncodeError:
        pass
    except Exception:
        pass

    if site in pagename:
        pagename = re.sub(r'(https?://)?%s%s' % (site, pagepath), '', pagename)

    sublime.status_message('Page name was cleared.')
    return pagename


def mw_save_mypages(title, storage_name='mediawiker_pagelist'):

    title = title.replace('_', ' ')  # for wiki '_' and ' ' are equal in page name
    pagelist_maxsize = mw_get_setting('mediawiker_pagelist_maxsize')
    site_name_active = mw_get_setting('mediawiki_site_active')
    mediawiker_pagelist = mw_get_setting(storage_name, {})

    # if site_name_active not in mediawiker_pagelist:
    #     mediawiker_pagelist[site_name_active] = []

    # my_pages = mediawiker_pagelist[site_name_active]
    my_pages = mediawiker_pagelist.setdefault(site_name_active, [])

    if my_pages:
        if title in my_pages:
            # for sorting - remove *before* trimming size, not after.
            my_pages.remove(title)
        while len(my_pages) >= pagelist_maxsize:
            my_pages.pop(0)

    my_pages.append(title)
    mw_set_setting(storage_name, mediawiker_pagelist)


def mw_get_title():
    """
    Returns page title of active tab from view_name or from file_name.
    Be careful to make sure that the round-trip:
        make_filename -> mw_get_title() ->  make_filename()
    Maps 1:1.
    """

    view_name = sublime.active_window().active_view().name()
    if view_name:
        print("DEBUG: view_name: ", view_name, "mw_strunquote(view_name)=", mw_strunquote(view_name))
        return mw_strunquote(view_name)
    else:
        # haven't view.name, try to get from view.file_name (without extension)
        file_name = sublime.active_window().active_view().file_name()
        if file_name:
            wiki_extensions = mw_get_setting('mediawiker_files_extension')
            title, ext = splitext(basename(file_name))
            if ext[1:] in wiki_extensions and title:
                print("DEBUG: rewriting filename_stem %s -> %s" % (title, mw_strunquote(title)))
                return mw_strunquote(title)
            else:
                sublime.status_message('Unauthorized file extension for mediawiki publishing. Check your configuration for correct extensions.')
                return ''
    return ''

def mw_get_filename(title):
    """
    Return a file-system friendly/compatible filename from title.
    """
    file_rootdir = mw_get_setting('mediawiker_file_rootdir', None)
    if not file_rootdir:
        return mw_strquote(title)
    use_subdirs = mw_get_setting('mediawiker_use_subdirs', False)
    if use_subdirs:
        filename = os.path.join(file_rootdir, *(mw_strquote(item) for item in os.path.split(title)))
        filedir = os.path.dirname(filename)
        if not os.path.isdir(filedir):
            print("Making dir:", filedir)
            os.makedirs(filedir)
        return filename
    return os.path.join(file_rootdir, mw_strquote(title))
    # If you use subdirs, then you should also adjust mw_get_title() so that is can accomodate:


def mw_get_hlevel(header_string, substring):
    return int(header_string.count(substring) / 2)


def mw_get_category(category_full_name):
    ''' From full category name like "Category:Name" return tuple (Category, Name) '''
    if ':' in category_full_name:
        return category_full_name.split(':')
    else:
        return 'Category', category_full_name


def mw_get_page_url(page_name=''):
    """ Returns URL of page with title of the active document, or <page_name> if given. """

    site_name_active = mw_get_setting('mediawiki_site_active')
    site_list = mw_get_setting('mediawiki_site')
    site = site_list[site_name_active]["host"]

    is_https = False
    if 'https' in site_list[site_name_active]:
        is_https = site_list[site_name_active]["https"]

    proto = 'https' if is_https else 'http'
    pagepath = site_list[site_name_active]["pagepath"]
    if not page_name:
        # For URLs, we need to quote spaces to '%20' rather than '+' and not replace '/' with '%2F'
        # Thus, force use of quote rather than quote_plus and use safe='/'.
        page_name = mw_strquote(mw_get_title(), quote_plus=False, safe='/')
    if page_name:
        return '%s://%s%s%s' % (proto, site, pagepath, page_name)
    else:
        return ''


def get_template_params(template):
    """
    There might be cases where we want to have the actual parameters
    and not just a string, so I've split this out into separate functions.
    Returns a list of parameters used in the template:
    Usage:
        >>> text = 'hi {{{1}}} - nice to see {{{2|you}}}. Have a nice {{{time|day}}}'
        >>> get_template_params(text)
        ['1', '2|you', 'time|day']
    """
    pattern = r'\{{3}(.*?)\}{3}' # Changed regex pattern so we only capture the argument and not the braces.
    parameters = re.findall(pattern, template)
    return parameters

def get_template_params_dict(template, defaultvalue=''):
    """
    As get_template_params, but returns a dict of {paramname : defaultvalue}.
    Use the defaultvalue keyword to specify the default value for parameters that
    don't specify a default value in the template (default is an empty string, '').
    Usage:
        >>> text = 'hi {{{1}}} - nice to see {{{2|you}}}. Have a nice {{{time|day}}}'
        >>> get_template_params(text, default='')
        {'1': '', '2': 'you', 'time: 'day'}
    """
    parameters = get_template_params(template)
    parameters = dict((split[0], split[1] if len(split) > 1 else defaultvalue) for split in
                  (param.split('|') for param in parameters)) # Python 2.6 does not support dict comprehensions.
    return parameters

# This should be a function; not a method. ("self" isn't used).
def get_template_params_str(text):
    """
    Mediawiki Template parameters can be provided in three way:
        Anonymous: {{myTemplate|firstparam|2ndparam}} - will replate {{{1}}} with firstparam and {{{2}}} with 2ndparam
        Numbered:  {{myTemplate|2=2ndparam|1=firstparam}} - same result as above.
        Named:     {{myTemplate|sec=2ndparam|fir=firstparam}} - will replace {{{sec}}} with 2ndparam and {{{fir}}} with firstparam
    In a template, the parameter placeholders can have default values:
        {{{1|the1param}}}, {{{other|someotherparam}}}
    If a parameter is not given when referencing the template with {{myTemplate}},
    and the parameter placeholder in the template does not have a default value,
    then the parameter placeholder is simply displayed in the output, e.g. {{{1}}}.

    Usage: Typical usage is when referencing (by transclusion or substitution) a template:
        >>> template = "hi {{{1}}} - nice to see {{{2|you}}}. Have a nice {{{time|day}}}"
        >>> params_str = get_template_params_str(template) # Returns '|1=\n|2=you\n|time=day\n'
        >>> template_link_text = {{%s%s%s}} % ('myTemplate', '\n' if params_str else '', params_str)
        >>> print template_link_text
        {{myTemplate:
        }}
    """
    params_dict = get_template_params_dict(text)
    return ''.join('|%s=%s\n' % (name, defval) for name, defval in sorted(params_dict.items()))

def substitute_template_params(template, params, defaultvalue='', keep_unmatched=False):
    """
    Return template where where named placeholders have been substituted with parameters.
    Args:
        template : The template to substitute, e.g. "first: {{{firstparam}}} and another: {{{secondparam}}}, and a third: {{{thirdparam}}}."
        params : dict of named parameters. Use '1' as string for paramter placeholder {{{1}}}, etc. (I recommend using named placeholders...)
        defaultvalue : Default value to use if a parameter placeholder name is not found in the params dict.
        keep_unmatched : If this is set to True, then only replace parameter placeholder that are found in the 'params' dict.
            E.g. if params does not include the key 'someparam', then occurences of the
            placeholder {{{someparam}}} in the template will NOT be replaced by defaultvalue,
            but instead {{{someparam}}} is kept. This simulates the native behaviour of mediawiki.
            (But note that this function does NOT account for <noinclude> or <!-- --> tags!)
    Usage:
        >>> template = "first: {{{firstparam}}} and another: {{{secondparam}}}";
        >>> substitute_template_params(template, {'firstparam': '1st'}, defaultvalue='empty')
        'first: 1st and another: empty'
        >>> substitute_template_params(template, {'firstparam': '1st'}, keep_unmatched=True)
        'first: 1st and another: {{{secondparam}}}'
    """
    pattern = r"\{{3}(.*?)\}{3}"
    # match.group(0) returns the full match, match.group(N) returns the Nth subgroup match.
    if keep_unmatched:
        def repl(match):
            return params.get(match.group(1), match.group(0))
    else:
        def repl(match):
            return params.get(match.group(1), defaultvalue)
    return re.sub(pattern, repl, template)


class MediawikerInsertTextCommand(sublime_plugin.TextCommand):
    """
    Command string: mediawiker_insert_text
    When run, insert text at position.
    If position is None, insert at current position.
    Other commonly-used shortcuts are:
        cursor_position = self.view.sel()[0].begin()
        end_of_file = self.view.size()
        start_of_file = 0
    """
    def run(self, edit, position, text):
        if position is None:
            # Note: Probably better to use built-in command, "insert":
            # { "keys": ["enter"], "command": "insert", "args": {"characters": "\n"} }
            position = self.view.sel()[0].begin()
        self.view.insert(edit, position, text)


class MediawikerPageCommand(sublime_plugin.WindowCommand):
    """
    Prepare all actions with the wiki.
    The general pipeline is:
    # MediawikerPageCommand.run()
    ##  reads settings and prepares a few things
    ##  exits by calling MediawikerPageCommand.on_done()
    # MediawikerPageCommand.on_done()
    ##  calls MediawikerValidateConnectionParamsCommand.run(title, action) through window.run_command
    # MediawikerValidateConnectionParamsCommand.run(title, action)
    ##  Retrieves password if required.
    ##  Invoked call_page, which invokes run_command(action, kwargs-with-title-and-password)

    # In summary:
            .run()       -> .on_done()
         MediawikerPageCommand -> MediawikerValidateConnectionParamsCommand -> Mediawiker(ShowPage/PublishPage/AddCategory/etc)Command

    When describing a command as string, it has format mediawiker_publish_page,
    which refers to the class MediawikerPublishPageCommand.

    The title parameter must be wikipage title, it cannot be a filename (quoted).
    """

    action = ''
    is_inputfixed = False
    run_in_new_window = False

    def run(self, action, title=''):
        self.action = action
        actions_validate = ['mediawiker_publish_page', 'mediawiker_add_category',
                            'mediawiker_category_list', 'mediawiker_search_string_list',
                            'mediawiker_add_image', 'mediawiker_add_template',
                            'mediawiker_upload']

        if self.action == 'mediawiker_show_page':
            if mw_get_setting('mediawiker_newtab_ongetpage'):
                self.run_in_new_window = True

            if not title:
                pagename_default = ''
                # use clipboard or selected text for page name
                if bool(mw_get_setting('mediawiker_clipboard_as_defaultpagename')):
                    pagename_default = sublime.get_clipboard().strip()
                if not pagename_default:
                    selection = self.window.active_view().sel()
                    # for selreg in selection:
                    #     pagename_default = self.window.active_view().substr(selreg).strip()
                    #     break
                    pagename_default = self.window.active_view().substr(selection[0]).strip()
                self.window.show_input_panel('Wiki page name:', mw_pagename_clear(pagename_default), self.on_done, self.on_change, None)
            else:
                self.on_done(title)
        elif self.action == 'mediawiker_reopen_page':
            # get page name
            if not title:
                title = mw_get_title()
            self.action = 'mediawiker_show_page'
            self.on_done(title)
        elif self.action in actions_validate:
            self.on_done('')

    def on_change(self, title):
        if title:
            pagename_cleared = mw_pagename_clear(title)
            if title != pagename_cleared:
                self.window.show_input_panel('Wiki page name:', pagename_cleared, self.on_done, self.on_change, None)

    def on_done(self, title):
        if self.run_in_new_window:
            sublime.active_window().new_file()
            self.run_in_new_window = False
        try:
            if title:
                title = mw_pagename_clear(title)
            self.window.run_command("mediawiker_validate_connection_params", {"title": title, "action": self.action})
        except ValueError as e:
            sublime.message_dialog(e)


class MediawikerOpenPageCommand(sublime_plugin.WindowCommand):
    ''' alias to Get page command '''

    def run(self):
        self.window.run_command("mediawiker_page", {"action": "mediawiker_show_page"})


class MediawikerReopenPageCommand(sublime_plugin.WindowCommand):
    """
    Reopen the current views's page (in current view).
    Will overwrite current view's buffer content.
    Command string: mediawiker_reopen_page
    """
    def run(self):
        # Yeah, this is kind of a weird one. MediawikerPageCommand will intercept
        # 'mediawiker_reopen_page' action and use 'mediawiker_show_page' instead.
        # So, no - it is not an infinite loop, although it would seem like it ;-)
        self.window.run_command("mediawiker_page", {"action": "mediawiker_reopen_page"})

class MediawikerAskReopenPageCommand(sublime_plugin.WindowCommand):
    """
    Reopen the current views's page (in current view).
    Will ask for confirmation before invoking the normal reopen page command.
    Command string: mediawiker_ask_reopen_page
    """
    def run(self):
        do_reopen = sublime.ok_cancel_dialog("Re-open page? (Note: This will overwrite existing content in current view.)")
        if do_reopen:
            print("Reopening page, do_reopen =", do_reopen)
            self.window.run_command("mediawiker_page", {"action": "mediawiker_reopen_page"})
        else:
            print("Re-open page cancelled, do_reopen =", do_reopen)


class MediawikerPostPageCommand(sublime_plugin.WindowCommand):
    ''' alias to Publish page command '''

    def run(self):
        self.window.run_command("mediawiker_page", {"action": "mediawiker_publish_page"})


class MediawikerSetCategoryCommand(sublime_plugin.WindowCommand):
    ''' alias to Add category command '''

    def run(self):
        self.window.run_command("mediawiker_page", {"action": "mediawiker_add_category"})


class MediawikerInsertImageCommand(sublime_plugin.WindowCommand):
    ''' alias to Add image command '''

    def run(self):
        self.window.run_command("mediawiker_page", {"action": "mediawiker_add_image"})


class MediawikerInsertTemplateCommand(sublime_plugin.WindowCommand):
    ''' alias to Add template command '''

    def run(self):
        self.window.run_command("mediawiker_page", {"action": "mediawiker_add_template"})


class MediawikerFileUploadCommand(sublime_plugin.WindowCommand):
    """
    Alias to Upload TextCommand.
    Command string: mediawiker_file_upload
    """

    def run(self):
        self.window.run_command("mediawiker_page", {"action": "mediawiker_upload"})


class MediawikerCategoryTreeCommand(sublime_plugin.WindowCommand):
    ''' alias to Category list command '''

    def run(self):
        self.window.run_command("mediawiker_page", {"action": "mediawiker_category_list"})


class MediawikerSearchStringCommand(sublime_plugin.WindowCommand):
    ''' alias to Search string list command '''

    def run(self):
        self.window.run_command("mediawiker_page", {"action": "mediawiker_search_string_list"})


class MediawikerPageListCommand(sublime_plugin.WindowCommand):

    def run(self, storage_name='mediawiker_pagelist'):
        site_name_active = mw_get_setting('mediawiki_site_active')
        mediawiker_pagelist = mw_get_setting(storage_name, {})
        self.my_pages = mediawiker_pagelist.get(site_name_active, [])
        if self.my_pages:
            self.my_pages.reverse()
            # error 'Quick panel unavailable' fix with timeout..
            sublime.set_timeout(lambda: self.window.show_quick_panel(self.my_pages, self.on_done), 1)
        else:
            sublime.status_message('List of pages for wiki "%s" is empty.' % (site_name_active))

    def on_done(self, index):
        if index >= 0:
            # escape from quick panel return -1
            title = self.my_pages[index]
            try:
                self.window.run_command("mediawiker_page", {"title": title, "action": "mediawiker_show_page"})
            except ValueError as e:
                sublime.message_dialog(e)


class MediawikerValidateConnectionParamsCommand(sublime_plugin.WindowCommand):
    """
    It seems like this is called (with run) in MediawikerPageCommand.run()
    in order to perform last preparations before executing the action that
    interacts with the wiki.

    action is typically a Window/TextCommand that interacts with the mediawiki server,
    e.g. mediawikier_show_page (MediawikerShowPageCommand).

    title must be wikipage title, not filename.

    """
    site = None
    password = ''
    title = ''
    action = ''
    is_hide_password = False
    PASSWORD_CHAR = u'\u25CF'

    def run(self, title, action):
        self.is_hide_password = mw_get_setting('mediawiker_password_input_hide')
        self.PASSWORD_CHAR = mw_get_setting('mediawiker_password_char')
        self.action = action  # TODO: check for better variant
        self.title = title
        site = mw_get_setting('mediawiki_site_active')
        site_list = mw_get_setting('mediawiki_site')
        self.password = site_list[site]["password"]
        if site_list[site]["username"]:
            # auth required if username exists in settings
            if not self.password:
                # need to ask for password
                self.window.show_input_panel('Password:', '', self.on_done, self.on_change, None)
            else:
                self.call_page()
        else:
            # auth is not required
            self.call_page()

    def _get_password(self, str_val):
        self.password = self.password + str_val.replace(self.PASSWORD_CHAR, '')
        return self.PASSWORD_CHAR * len(self.password)

    def on_change(self, str_val):
        if str_val:
            if self.is_hide_password:
                # password hiding hack..
                if str_val:
                    password = str_val
                    str_val = self._get_password(str_val)
                    if password != str_val:
                        password = str_val
                        self.window.show_input_panel('Password:', str_val, self.on_done, self.on_change, None)
        else:
            self.password = ''

    def on_done(self, password):
        if not self.is_hide_password:
            self.password = password
        self.call_page()

    def call_page(self):
        self.window.active_view().run_command(self.action, {"title": self.title, "password": self.password})


class MediawikerShowPageCommand(sublime_plugin.TextCommand):
    """
    When run is invoked, loads the page with the given title from server
    into the view through which this TextCommand was invoked, erasing
    all previous content in the view.

    The run requires a 'password' argument; this is often obtained by invoking this
    through the MediawikerPageCommand WindowCommand (which again obtains the password
    if required by invoking MediawikerValidateConnectionParamsCommand).
    """

    def run(self, edit, title, password):
        sitecon = mw_get_connect(password)
        is_writable, text = mw_get_page_text(sitecon, title)
        if is_writable and not text:
            sublime.status_message('Wiki page %s is not exists. You can create new..' % (title))
            text = '<New wiki page: Remove this with text of the new page>'
        if is_writable:
            self.view.erase(edit, sublime.Region(0, self.view.size()))
            self.view.set_syntax_file('Packages/Mediawiker/Mediawiki.tmLanguage')
            self.view.set_name(title)
            if mw_get_setting('mediawiker_title_to_filename', True):
                # If mediawiker_title_to_filename is specified, the title is cast to a
                # "filesystem friendly" alternative by quoting. When posting, this is converted
                # back to the original title.
                filename = mw_get_filename(title)
                print("mw_get_filename('%s') returned '%s' -- using this to set the name." % (title, filename))
                # I like to have a default directory where I store my mediawiki pages.
                # I use the settings key 'mediawiker_file_rootdir' to specify this directory,
                # which is prefixed to the file, if specified:
                # (should possibly be specified on a per-wiki basis.)
                # I then use the view's default_dir setting to change to this dir:
                # There are also some considerations for pages with '/' in the title,
                # this can either be quoted or we can place the file in a sub-directory.
                if mw_get_setting('mediawiker_file_rootdir', None):
                    # If mediawiker_file_rootdir is set, then filename is a path with rootdir
                    # Update the view's working dir to reflect this:
                    self.view.settings().set('default_dir', os.path.dirname(filename))
                    self.view.set_name(os.path.basename(filename))
                else:
                    self.view.set_name(filename)
            #self.view._wikipage_title = title # Save this.
            self.view.run_command('mediawiker_insert_text', {'position': 0, 'text': text})
            sublime.status_message('Page %s was opened successfully into view "%s".' % (title, self.view.name()))



class MediawikerPublishPageCommand(sublime_plugin.TextCommand):
    my_pages = None
    page = None
    title = ''
    current_text = ''

    def run(self, edit, title, password):
        sitecon = mw_get_connect(password)
        self.title = mw_get_title()
        if self.title:
            self.page = sitecon.Pages[self.title]
            if self.page.can('edit'):
                self.current_text = self.view.substr(sublime.Region(0, self.view.size()))
                summary_message = 'Changes summary (%s):' % mw_get_setting('mediawiki_site_active')
                self.view.window().show_input_panel(summary_message, '', self.on_done, None, None)
            else:
                sublime.status_message('You have not rights to edit this page')
        else:
            sublime.status_message('Can\'t publish page with empty title')
            return

    def on_done(self, summary):
        try:
            summary = '%s%s' % (summary, mw_get_setting('mediawiker_summary_postfix', ' (by SublimeText.Mediawiker)'))
            mark_as_minor = mw_get_setting('mediawiker_mark_as_minor')
            if self.page.can('edit'):
                # invert minor settings command '!'
                if summary[0] == '!':
                    mark_as_minor = not mark_as_minor
                    summary = summary[1:]
                self.page.save(self.current_text, summary=summary.strip(), minor=mark_as_minor)
            else:
                sublime.status_message('You have not rights to edit this page')
        except mwclient.EditError as e:
            sublime.status_message('Can\'t publish page %s (%s)' % (self.title, e))
        sublime.status_message('Wiki page %s was successfully published to wiki.' % (self.title))
        mw_save_mypages(self.title)


class MediawikerShowTocCommand(sublime_plugin.TextCommand):
    items = []
    regions = []
    pattern = r'^(={1,5})\s?(.*?)\s?={1,5}'

    def run(self, edit):
        self.items = []
        self.regions = []
        self.regions = self.view.find_all(self.pattern)
        # self.items = map(self.get_header, self.regions)
        self.items = [self.get_header(x) for x in self.regions]
        sublime.set_timeout(lambda: self.view.window().show_quick_panel(self.items, self.on_done), 1)

    def get_header(self, region):
        TAB_SIZE = ' ' * 4
        return re.sub(self.pattern, r'\1\2', self.view.substr(region)).replace('=', TAB_SIZE)[len(TAB_SIZE):]

    def on_done(self, index):
        if index >= 0:
            # escape from quick panel returns -1
            self.view.show(self.regions[index])
            self.view.sel().clear()
            self.view.sel().add(self.regions[index])


class MediawikerShowInternalLinksCommand(sublime_plugin.TextCommand):
    items = []
    regions = []
    pattern = r'\[{2}(.*?)(\|.*?)?\]{2}'
    actions = ['Goto internal link', 'Open page in editor', 'Open page in browser']
    selected = None

    def run(self, edit):
        self.items = []
        self.regions = []
        self.regions = self.view.find_all(self.pattern)
        self.items = [mw_strunquote(self.get_header(x)) for x in self.regions]
        if self.items:
            sublime.set_timeout(lambda: self.view.window().show_quick_panel(self.items, self.on_select), 1)
        else:
            sublime.status_message('No internal links was found.')

    def get_header(self, region):
        return re.sub(self.pattern, r'\1', self.view.substr(region))

    def on_select(self, index):
        if index >= 0:
            self.selected = index
            sublime.set_timeout(lambda: self.view.window().show_quick_panel(self.actions, self.on_done), 1)

    def on_done(self, index):
        if index == 0:
            # escape from quick panel returns -1
            self.view.show(self.regions[self.selected])
            self.view.sel().clear()
            self.view.sel().add(self.regions[self.selected])
        elif index == 1:
            sublime.set_timeout(lambda: self.view.window().run_command("mediawiker_page", {"action": "mediawiker_show_page", "title": self.items[self.selected]}), 1)
        elif index == 2:
            url = mw_get_page_url(self.items[self.selected])
            print("Opening URL:", url)
            webbrowser.open(url)


class MediawikerShowExternalLinksCommand(sublime_plugin.TextCommand):
    items = []
    regions = []
    pattern = r'[^\[]\[{1}(\w.*?)(\s.*?)?\]{1}[^\]]'
    actions = ['Goto external link', 'Open link in browser']
    selected = None

    def run(self, edit):
        self.items = []
        self.regions = []
        self.regions = self.view.find_all(self.pattern)
        self.items = [self.get_header(x) for x in self.regions]
        self.urls = [self.get_url(x) for x in self.regions]
        if self.items:
            sublime.set_timeout(lambda: self.view.window().show_quick_panel(self.items, self.on_select), 1)
        else:
            sublime.status_message('No external links was found.')

    def prepare_header(self, header):
        maxlen = 70
        link_url = mw_strunquote(header.group(1))
        link_descr = re.sub(r'<.*?>', '', header.group(2))
        postfix = '..' if len(link_descr) > maxlen else ''
        return '%s: %s%s' % (link_url, link_descr[:maxlen], postfix)

    def get_header(self, region):
        # return re.sub(self.pattern, r'\1: \2', self.view.substr(region))
        return re.sub(self.pattern, self.prepare_header, self.view.substr(region))

    def get_url(self, region):
        return re.sub(self.pattern, r'\1', self.view.substr(region))

    def on_select(self, index):
        if index >= 0:
            self.selected = index
            sublime.set_timeout(lambda: self.view.window().show_quick_panel(self.actions, self.on_done), 1)

    def on_done(self, index):
        if index == 0:
            # escape from quick panel returns -1
            self.view.show(self.regions[self.selected])
            self.view.sel().clear()
            self.view.sel().add(self.regions[self.selected])
        elif index == 1:
            webbrowser.open(self.urls[self.selected])


class MediawikerEnumerateTocCommand(sublime_plugin.TextCommand):
    items = []
    regions = []

    def run(self, edit):
        self.items = []
        self.regions = []
        pattern = '^={1,5}(.*)?={1,5}'
        self.regions = self.view.find_all(pattern)
        header_level_number = [0, 0, 0, 0, 0]
        len_delta = 0
        for r in self.regions:
            if len_delta:
                # prev. header text was changed, move region to new position
                r_new = sublime.Region(r.a + len_delta, r.b + len_delta)
            else:
                r_new = r
            region_len = r_new.b - r_new.a
            header_text = self.view.substr(r_new)
            level = mw_get_hlevel(header_text, "=")
            current_number_str = ''
            i = 1
            # generate number value, start from 1
            while i <= level:
                position_index = i - 1
                header_number = header_level_number[position_index]
                if i == level:
                    # incr. number
                    header_number += 1
                    # save current number
                    header_level_number[position_index] = header_number
                    # reset sub-levels numbers
                    header_level_number[i:] = [0] * len(header_level_number[i:])
                if header_number:
                    current_number_str = "%s.%s" % (current_number_str, header_number) if current_number_str else '%s' % (header_number)
                # incr. level
                i += 1

            #get title only
            header_text_clear = header_text.strip(' =\t')
            header_text_clear = re.sub(r'^(\d\.)+\s+(.*)', r'\2', header_text_clear)
            header_tag = '=' * level
            header_text_numbered = '%s %s. %s %s' % (header_tag, current_number_str, header_text_clear, header_tag)
            len_delta += len(header_text_numbered) - region_len
            self.view.replace(edit, r_new, header_text_numbered)


class MediawikerSetActiveSiteCommand(sublime_plugin.WindowCommand):
    site_keys = []
    site_on = '>'
    site_off = ' ' * 3
    site_active = ''

    def run(self):
        self.site_active = mw_get_setting('mediawiki_site_active')
        sites = mw_get_setting('mediawiki_site')
        # self.site_keys = map(self.is_checked, list(sites.keys()))
        self.site_keys = [self.is_checked(x) for x in sites.keys()]
        sublime.set_timeout(lambda: self.window.show_quick_panel(self.site_keys, self.on_done), 1)

    def is_checked(self, site_key):
        checked = self.site_on if site_key == self.site_active else self.site_off
        return '%s %s' % (checked, site_key)

    def on_done(self, index):
        # not escaped and not active
        if index >= 0 and not self.site_keys[index].startswith(self.site_on):
            mw_set_setting("mediawiki_site_active", self.site_keys[index].strip())


class MediawikerOpenPageInBrowserCommand(sublime_plugin.WindowCommand):
    def run(self):
        url = mw_get_page_url()
        if url:
            print("Opening URL:", url)
            webbrowser.open(url)
        else:
            sublime.status_message('Can\'t open page with empty title')
            return


class MediawikerAddCategoryCommand(sublime_plugin.TextCommand):
    categories_list = None
    title = ''
    sitecon = None

    category_root = ''
    category_options = [['Set category', ''], ['Open category', ''], ['Back to root', '']]

    # TODO: back in category tree..

    def run(self, edit, title, password):
        self.sitecon = mw_get_connect(password)
        self.category_root = mw_get_category(mw_get_setting('mediawiker_category_root'))[1]
        sublime.active_window().show_input_panel('Wiki root category:', self.category_root, self.get_category_menu, None, None)
        # self.get_category_menu(self.category_root)

    def get_category_menu(self, category_root):
        category = self.sitecon.Categories[category_root]
        self.categories_list_names = []
        self.categories_list_values = []

        for page in category:
            if page.namespace == CATEGORY_NAMESPACE:
                self.categories_list_values.append(page.name)
                self.categories_list_names.append(page.name[page.name.find(':') + 1:])
        sublime.set_timeout(lambda: sublime.active_window().show_quick_panel(self.categories_list_names, self.on_done), 1)

    def on_done(self, idx):
        # the dialog was cancelled
        if idx >= 0:
            self.category_options[0][1] = self.categories_list_values[idx]
            self.category_options[1][1] = self.categories_list_names[idx]
            sublime.set_timeout(lambda: sublime.active_window().show_quick_panel(self.category_options, self.on_done_final), 1)

    def on_done_final(self, idx):
        if idx == 0:
            # set category
            index_of_textend = self.view.size()
            self.view.run_command('mediawiker_insert_text', {'position': index_of_textend, 'text': '[[%s]]' % self.category_options[idx][1]})
        elif idx == 1:
            self.get_category_menu(self.category_options[idx][1])
        else:
            self.get_category_menu(self.category_root)


class MediawikerCsvTableCommand(sublime_plugin.TextCommand):
    """
    selected text, csv data to wiki table.
    Command string: mediawiker_csv_table
    """

    delimiter = '|'

    # TODO: rewrite as simple to wiki command
    def run(self, edit):
        self.delimiter = mw_get_setting('mediawiker_csvtable_delimiter', '|')
        table_header = '{|'
        table_footer = '|}'
        table_properties = ' '.join(['%s="%s"' % (prop, value) for prop, value in mw_get_setting('mediawiker_wikitable_properties', {}).items()])
        cell_properties = ' '.join(['%s="%s"' % (prop, value) for prop, value in mw_get_setting('mediawiker_wikitable_cell_properties', {}).items()])
        if cell_properties:
            cell_properties = ' %s | ' % cell_properties

        for region in self.view.sel():
            table_data_dic_tmp = []
            table_data = ''
            # table_data_dic_tmp = map(self.get_table_data, self.view.substr(region).split('\n'))
            table_data_dic_tmp = [self.get_table_data(x) for x in self.view.substr(region).split('\n')]

            # verify and fix columns count in rows
            if table_data_dic_tmp:
                cols_cnt = len(max(table_data_dic_tmp, key=len))
                for row in table_data_dic_tmp:
                    if row:
                        while cols_cnt - len(row):
                            row.append('')

                for row in table_data_dic_tmp:
                    if row:
                        if table_data:
                            table_data += '\n|-\n'
                            column_separator = '||'
                        else:
                            table_data += '|-\n'
                            column_separator = '!!'

                        for col in row:
                            col_sep = column_separator if row.index(col) else column_separator[0]
                            table_data += '%s%s%s ' % (col_sep, cell_properties, col)

                self.view.replace(edit, region, '%s %s\n%s\n%s' % (table_header, table_properties, table_data, table_footer))

    def get_table_data(self, line):
        if self.delimiter in line:
            return line.split(self.delimiter)
        return []


class MediawikerEditPanelCommand(sublime_plugin.WindowCommand):
    options = []
    SNIPPET_CHAR = u'\u24C8'

    def run(self):
        self.SNIPPET_CHAR = mw_get_setting('mediawiker_snippet_char')
        self.options = mw_get_setting('mediawiker_panel', {})
        if self.options:
            office_panel_list = ['\t%s' % val['caption'] if val['type'] != 'snippet' else '\t%s %s' % (self.SNIPPET_CHAR, val['caption']) for val in self.options]
            self.window.show_quick_panel(office_panel_list, self.on_done)

    def on_done(self, index):
        if index >= 0:
            # escape from quick panel return -1
            try:
                action_type = self.options[index]['type']
                action_value = self.options[index]['value']
                if action_type == 'snippet':
                    # run snippet
                    self.window.active_view().run_command("insert_snippet", {"name": action_value})
                elif action_type == 'window_command':
                    # run command
                    self.window.run_command(action_value)
                elif action_type == 'text_command':
                    # run command
                    self.window.active_view().run_command(action_value)
            except ValueError as e:
                sublime.status_message(e)


class MediawikerTableWikiToSimpleCommand(sublime_plugin.TextCommand):
    ''' convert selected (or under cursor) wiki table to Simple table (TableEdit plugin) '''

    # TODO: wiki table properties will be lost now...
    def run(self, edit):
        selection = self.view.sel()
        table_region = None

        if not self.view.substr(selection[0]):
            table_region = self.table_getregion()
        else:
            table_region = selection[0]  # only first region will be proceed..

        if table_region:
            text = self.view.substr(table_region)
            text = self.table_fixer(text)
            self.view.replace(edit, table_region, self.table_get(text))
            # Turn on TableEditor
            try:
                self.view.run_command('table_editor_enable_for_current_view', {'prop': 'enable_table_editor'})
            except Exception as e:
                sublime.status_message('Need to correct install plugin TableEditor: %s' % e)

    def table_get(self, text):
        tbl_row_delimiter = r'\|\-(.*)'
        tbl_cell_delimiter = r'\n\s?\||\|\||\n\s?\!|\!\!'  # \n| or || or \n! or !!
        rows = re.split(tbl_row_delimiter, text)

        tbl_full = []
        for row in rows:
            if row and row[0] != '{':
                tbl_row = []
                cells = re.split(tbl_cell_delimiter, row, re.DOTALL)[1:]
                for cell in cells:
                    cell = cell.replace('\n', '')
                    cell = ' ' if not cell else cell
                    if cell[0] != '{' and cell[-1] != '}':
                        cell = self.delim_fixer(cell)
                        tbl_row.append(cell)
                tbl_full.append(tbl_row)

        tbl_full = self.table_print(tbl_full)
        return tbl_full

    def table_print(self, table_data):
        CELL_LEFT_BORDER = '|'
        CELL_RIGHT_BORDER = ''
        ROW_LEFT_BORDER = ''
        ROW_RIGHT_BORDER = '|'
        tbl_print = ''
        for row in table_data:
            if row:
                row_print = ''.join(['%s%s%s' % (CELL_LEFT_BORDER, cell, CELL_RIGHT_BORDER) for cell in row])
                row_print = '%s%s%s' % (ROW_LEFT_BORDER, row_print, ROW_RIGHT_BORDER)
                tbl_print += '%s\n' % (row_print)
        return tbl_print

    def table_getregion(self):
        cursor_position = self.view.sel()[0].begin()
        pattern = r'^\{\|(.*?\n?)*\|\}'
        regions = self.view.find_all(pattern)
        for reg in regions:
            if reg.a <= cursor_position <= reg.b:
                return reg

    def table_fixer(self, text):
        text = re.sub(r'(\{\|.*\n)(\s?)(\||\!)(\s?[^-])', r'\1\2|-\n\3\4', text)  # if |- skipped after {| line, add it
        return text

    def delim_fixer(self, string_data):
        REPLACE_STR = ':::'
        return string_data.replace('|', REPLACE_STR)


class MediawikerTableSimpleToWikiCommand(sublime_plugin.TextCommand):
    ''' convert selected (or under cursor) Simple table (TableEditor plugin) to wiki table '''
    def run(self, edit):
        selection = self.view.sel()
        table_region = None
        if not self.view.substr(selection[0]):
            table_region = self.gettable()
        else:
            table_region = selection[0]  # only first region will be proceed..

        if table_region:
            text = self.view.substr(table_region)
            table_data = self.table_parser(text)
            self.view.replace(edit, table_region, self.drawtable(table_data))

    def table_parser(self, text):
        table_data = []
        TBL_HEADER_STRING = '|-'
        need_header = False
        if text.split('\n')[1][:2] == TBL_HEADER_STRING:
            need_header = True
        for line in text.split('\n'):
            if line:
                row_data = []
                if line[:2] == TBL_HEADER_STRING:
                    continue
                elif line[0] == '|':
                    cells = line[1:-1].split('|')  # without first and last char "|"
                    for cell_data in cells:
                        row_data.append({'properties': '', 'cell_data': cell_data, 'is_header': need_header})
                    if need_header:
                        need_header = False
            if row_data and type(row_data) is list:
                table_data.append(row_data)
        return table_data

    def gettable(self):
        cursor_position = self.view.sel()[0].begin()
        # ^([^\|\n].*)?\n\|(.*\n)*?\|.*\n[^\|] - all tables regexp (simple and wiki)?
        pattern = r'^\|(.*\n)*?\|.*\n[^\|]'
        regions = self.view.find_all(pattern)
        for reg in regions:
            if reg.a <= cursor_position <= reg.b:
                table_region = sublime.Region(reg.a, reg.b - 2)  # minus \n and [^\|]
                return table_region

    def drawtable(self, table_list):
        ''' draw wiki table '''
        TBL_START = '{|'
        TBL_STOP = '|}'
        TBL_ROW_START = '|-'
        CELL_FIRST_DELIM = '|'
        CELL_DELIM = '||'
        CELL_HEAD_FIRST_DELIM = '!'
        CELL_HEAD_DELIM = '!!'
        REPLACE_STR = ':::'

        text_wikitable = ''
        table_properties = ' '.join(['%s="%s"' % (prop, value) for prop, value in mw_get_setting('mediawiker_wikitable_properties', {}).items()])

        need_header = table_list[0][0]['is_header']
        is_first_line = True
        for row in table_list:
            if need_header or is_first_line:
                text_wikitable += '%s\n%s' % (TBL_ROW_START, CELL_HEAD_FIRST_DELIM)
                text_wikitable += self.getrow(CELL_HEAD_DELIM, row)
                is_first_line = False
                need_header = False
            else:
                text_wikitable += '\n%s\n%s' % (TBL_ROW_START, CELL_FIRST_DELIM)
                text_wikitable += self.getrow(CELL_DELIM, row)
                text_wikitable = text_wikitable.replace(REPLACE_STR, '|')

        return '%s %s\n%s\n%s' % (TBL_START, table_properties, text_wikitable, TBL_STOP)

    def getrow(self, delimiter, rowlist=None):
        if rowlist is None:
            rowlist = []
        cell_properties = ' '.join(['%s="%s"' % (prop, value) for prop, value in mw_get_setting('mediawiker_wikitable_cell_properties', {}).items()])
        cell_properties = '%s | ' % cell_properties if cell_properties else ''
        try:
            return delimiter.join(' %s%s ' % (cell_properties, cell['cell_data'].strip()) for cell in rowlist)
        except Exception as e:
            print('Error in data: %s' % e)


class MediawikerCategoryListCommand(sublime_plugin.TextCommand):
    password = ''
    pages = {}  # pagenames -> namespaces
    pages_names = []  # pagenames for menu
    category_path = []
    CATEGORY_NEXT_PREFIX_MENU = '> '
    CATEGORY_PREV_PREFIX_MENU = '. . '
    category_prefix = ''  # "Category" namespace name as returned language..

    def run(self, edit, title, password):
        self.password = password
        if self.category_path:
            category_root = mw_get_category(self.get_category_current())[1]
        else:
            category_root = mw_get_category(mw_get_setting('mediawiker_category_root'))[1]
        sublime.active_window().show_input_panel('Wiki root category:', category_root, self.show_list, None, None)

    def show_list(self, category_root):
        if not category_root:
            return
        self.pages = {}
        self.pages_names = []

        category_root = mw_get_category(category_root)[1]

        if not self.category_path:
            self.update_category_path('%s:%s' % (self.get_category_prefix(), category_root))

        if len(self.category_path) > 1:
            self.add_page(self.get_category_prev(), CATEGORY_NAMESPACE, False)

        for page in self.get_list_data(category_root):
            if page.namespace == CATEGORY_NAMESPACE and not self.category_prefix:
                self.category_prefix = mw_get_category(page.name)[0]
            self.add_page(page.name, page.namespace, True)
        if self.pages:
            self.pages_names.sort()
            sublime.set_timeout(lambda: sublime.active_window().show_quick_panel(self.pages_names, self.get_page), 1)
        else:
            sublime.message_dialog('Category %s is empty' % category_root)

    def add_page(self, page_name, page_namespace, as_next=True):
        page_name_menu = page_name
        if page_namespace == CATEGORY_NAMESPACE:
            page_name_menu = self.get_category_as_next(page_name) if as_next else self.get_category_as_prev(page_name)
        self.pages[page_name] = page_namespace
        self.pages_names.append(page_name_menu)

    def get_list_data(self, category_root):
        ''' get objects list by category name '''
        sitecon = mw_get_connect(self.password)
        return sitecon.Categories[category_root]

    def get_category_as_next(self, category_string):
        return '%s%s' % (self.CATEGORY_NEXT_PREFIX_MENU, category_string)

    def get_category_as_prev(self, category_string):
        return '%s%s' % (self.CATEGORY_PREV_PREFIX_MENU, category_string)

    def category_strip_special_prefix(self, category_string):
        return category_string.lstrip(self.CATEGORY_NEXT_PREFIX_MENU).lstrip(self.CATEGORY_PREV_PREFIX_MENU)

    def get_category_prev(self):
        ''' return previous category name in format Category:CategoryName'''
        return self.category_path[-2]

    def get_category_current(self):
        ''' return current category name in format Category:CategoryName'''
        return self.category_path[-1]

    def get_category_prefix(self):
        if self.category_prefix:
            return self.category_prefix
        else:
            return 'Category'

    def update_category_path(self, category_string):
        if category_string in self.category_path:
            self.category_path = self.category_path[:-1]
        else:
            self.category_path.append(self.category_strip_special_prefix(category_string))

    def get_page(self, index):
        if index >= 0:
            # escape from quick panel return -1
            page_name = self.category_strip_special_prefix(self.pages_names[index])
            if self.pages[page_name] == CATEGORY_NAMESPACE:
                self.update_category_path(page_name)
                self.show_list(page_name)
            else:
                try:
                    sublime.active_window().run_command("mediawiker_page", {"title": page_name, "action": "mediawiker_show_page"})
                except ValueError as e:
                    sublime.message_dialog(e)


class MediawikerSearchStringListCommand(sublime_plugin.TextCommand):
    password = ''
    title = ''
    search_limit = 20
    pages_names = []
    search_result = None

    def run(self, edit, title, password):
        self.password = password
        sublime.active_window().show_input_panel('Wiki search:', '', self.show_results, None, None)

    def show_results(self, search_value=''):
        # TODO: paging?
        self.pages_names = []
        self.search_limit = mw_get_setting('mediawiker_search_results_count')
        if search_value:
            self.search_result = self.do_search(search_value)
        if self.search_result:
            for _ in range(self.search_limit):
                try:
                    page_data = self.search_result.next()
                    self.pages_names.append([page_data['title'], page_data['snippet']])
                except Exception as e:
                    print("Exception during search_result generation:", repr(e))
            te = ''
            search_number = 1
            for pa in self.pages_names:
                te += '### %s. %s\n* [%s](%s)\n\n%s\n' % (search_number, pa[0], pa[0], mw_get_page_url(pa[0]), self.antispan(pa[1]))
                search_number += 1

            if te:
                self.view = sublime.active_window().new_file()
                self.view.set_syntax_file('Packages/Markdown/Markdown.tmLanguage')
                self.view.set_name('Wiki search results: %s' % search_value)
                self.view.run_command('mediawiker_insert_text', {'position': 0, 'text': te})
            elif search_value:
                sublime.message_dialog('No results for: %s' % search_value)

    def antispan(self, text):
        span_replace_open = "`"
        span_replace_close = "`"
        # bold and italic tags cut
        text = text.replace("'''", "")
        text = text.replace("''", "")
        # spans to bold
        text = re.sub(r'<span(.*?)>', span_replace_open, text)
        text = re.sub(r'<\/span>', span_replace_close, text)
        # divs cut
        text = re.sub(r'<div(.*?)>', '', text)
        text = re.sub(r'<\/div>', '', text)
        return text

    def do_search(self, string_value):
        sitecon = mw_get_connect(self.password)
        namespace = mw_get_setting('mediawiker_search_namespaces')
        return sitecon.search(search=string_value, what='text', limit=self.search_limit, namespace=namespace)


class MediawikerAddImageCommand(sublime_plugin.TextCommand):
    password = ''
    image_prefix_min_lenght = 4
    images_names = []

    def run(self, edit, password, title=''):
        self.password = password
        self.image_prefix_min_lenght = mw_get_setting('mediawiker_image_prefix_min_length', 4)
        sublime.active_window().show_input_panel('Wiki image prefix (min %s):' % self.image_prefix_min_lenght, '', self.show_list, None, None)

    def show_list(self, image_prefix):
        if len(image_prefix) >= self.image_prefix_min_lenght:
            sitecon = mw_get_connect(self.password)
            images = sitecon.allpages(prefix=image_prefix, namespace=IMAGE_NAMESPACE)  # images list by prefix
            # self.images_names = map(self.get_page_title, images)
            self.images_names = [self.get_page_title(x) for x in images]
            sublime.set_timeout(lambda: sublime.active_window().show_quick_panel(self.images_names, self.on_done), 1)
        else:
            sublime.message_dialog('Image prefix length must be more than %s. Operation canceled.' % self.image_prefix_min_lenght)

    def get_page_title(self, obj):
        return obj.page_title

    def on_done(self, idx):
        if idx >= 0:
            index_of_cursor = self.view.sel()[0].begin()
            self.view.run_command('mediawiker_insert_text', {'position': index_of_cursor, 'text': '[[Image:%s]]' % self.images_names[idx]})



class MediawikerAddTemplateCommand(sublime_plugin.TextCommand):
    password = ''
    templates_names = []
    sitecon = None

    def run(self, edit, password, title=''):
        self.password = password
        sublime.active_window().show_input_panel('Wiki template prefix:', '', self.show_list, None, None)

    def show_list(self, image_prefix):
        self.templates_names = []
        self.sitecon = mw_get_connect(self.password)
        templates = self.sitecon.allpages(prefix=image_prefix, namespace=TEMPLATE_NAMESPACE)  # images list by prefix
        for template in templates:
            self.templates_names.append(template.page_title)
        sublime.set_timeout(lambda: sublime.active_window().show_quick_panel(self.templates_names, self.on_done), 1)

    def on_done(self, idx):
        if idx >= 0:
            template = self.sitecon.Pages['Template:%s' % self.templates_names[idx]]
            text = template.edit()
            params_text = self.get_template_params(text)
            index_of_cursor = self.view.sel()[0].begin()
            # Create "{{myTemplate:}}
            template_text = '{{%s%s}}' % (self.templates_names[idx], params_text)
            self.view.run_command('mediawiker_insert_text', {'position': index_of_cursor, 'text': template_text})


class MediawikerCliCommand(sublime_plugin.WindowCommand):

    def run(self, url):
        if url:
            # print('Opening page: %s' % url)
            sublime.set_timeout(lambda: self.window.run_command("mediawiker_page", {"action": "mediawiker_show_page", "title": self.proto_replacer(url)}), 1)

    def proto_replacer(self, url):
        if sublime.platform() == 'windows' and url.endswith('/'):
            url = url[:-1]
        elif sublime.platform() == 'linux' and url.startswith("'") and url.endswith("'"):
            url = url[1:-1]
        return url.split("://")[1]


class MediawikerUploadCommand(sublime_plugin.TextCommand):
    """
    Uploads a single file, prompts the user for (1) filepath, (2) destination filename and (3) description.
    Command string: mediawiker_upload .
    """

    password = None
    file_path = None
    file_destname = None
    file_descr = None

    def run(self, edit, password, title=''):
        self.password = password
        sublime.active_window().show_input_panel('File path:', '', self.get_destfilename, None, None)

    def get_destfilename(self, file_path):
        if file_path:
            self.file_path = file_path
            file_destname = basename(file_path)
            sublime.active_window().show_input_panel('Destination file name [%s]:' % (file_destname), file_destname, self.get_filedescr, None, None)

    def get_filedescr(self, file_destname):
        if not file_destname:
            file_destname = basename(self.file_path)
        self.file_destname = file_destname
        sublime.active_window().show_input_panel('File description:', '', self.on_done, None, None)

    def on_done(self, file_descr=''):
        sitecon = mw_get_connect(self.password)
        if file_descr:
            self.file_descr = file_descr
        else:
            self.file_descr = '%s as %s' % (basename(self.file_path), self.file_destname)
        try:
            with open(self.file_path, 'rb') as f:
                sitecon.upload(f, self.file_destname, self.file_descr)
            sublime.status_message('File %s successfully uploaded to wiki as %s' % (self.file_path, self.file_destname))
        except IOError as e:
            sublime.message_dialog('Upload io error: %s' % e)
        except ValueError as e:
            # This might happen in predata['token'] = image.get_token('edit'), if e.g. title is invalid.
            sublime.message_dialog('Upload error, invalid destination file name/title:\n %s' % e)
        except Exception as e:
            print("UPLOAD ERROR:", repr(e))
            sublime.message_dialog('Upload error: %s' % e)



class MediawikerBatchUploadCommand(sublime_plugin.WindowCommand):
    """
    Windows command alias for MediawikerUploadBatchViewCommand.
    Command string: mediawiker_batch_upload

    Note: Does it make sense to run this without an active view?
    Windows Commands should always be able to run even if no view is open.
    """
    def run(self):
        self.window.active_view().run_command("mediawiker_upload_batch_view")



class MediawikerUploadBatchViewCommand(sublime_plugin.TextCommand):
    """
    == Batch upload command ==
    (Command string: mediawiker_upload_batch_view)
    Reads filepaths from the current view's buffer and uploads them.
    The current view's buffer must be in the format of:
        <filepath>, <destname>, <file description>, <link_options>, <link_caption>
    e.g.
        /home/me/picture.jpg, xmas_tree.jpg, A picture of a christmas tree, 500px|framed, X-mas tree!
    If destname is empty or missing, the file's filename is used.
    If description is missing, an empty string is used.
    If tab ('\t') is present, this is used as field delimiter, otherwise comma (',') is used.

    Image links are printed to the current view. The output can be customized by two means:
    globally, using the mediawiker_insert_image_options settings key (value should be a dict), or
    per-view, by marking the first line in the view with '#' followed by an info dict in json format, e.g.
        # {"options": "frameless|center|500px", caption="RS123 TEM Images", "link_fmt": "[[Has image::File:%(destname)s|%(options)s|%(caption)s]]"}
    (remember, JSON format requires double quotes ("key", not 'key') when loading from strings)
    Note: I used to also have , "imageformat": "frameless", "imagesize": "500px", but these are now deprechated in
    favor of a single combined "options" as used above.
    As indicated above, both the mediawiker_insert_image_options settings item and the first #-marked JSON line
    should both specify a dict with one or more of the following items:
        "link_fmt" : controls the overall link format.
        "options" and "caption" are both inserted by string interpolation with link_fmt.

    Bonus tip:  On Windows, use ShellTools' (or equivalent) "copy path" context menu
                entry to easily get the path of multiple files from Explorer.
                Use Excel, Python, or similar if you want to change destname
                or add a description for each file.
    """

    password = None
    files = None # list of 3-string tuples, each tuple is (<filepath>, <destname>, <filedescription>)

    def parseUploadBatchText(self, text, fieldsep=None):
        """
        Parse text and return list of 3-string tuples,
        each tuple is (<filepath>, <destname>, <filedescription>, <link_options>, <link_caption>)
        """
        # Ensure that we have '\n' as line terminator.
        linesep = '\n'
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        # Split to lines, discarting empty lines:
        lines = (line.strip() for line in text.split(linesep) if line.strip())
        info = None
        if text[0] == '#':
            infoline = next(lines)[1:]
            import json
            try:
                info = json.loads(infoline)
            except ValueError as e:
                print("JSON ValueError, could not parse string '%s' - '%s'" % (infoline, e))
        # Proceed, discart lines starting with '#':
        # I use a list rather than generator to make it easy to probe the first line:
        lines = [line for line in lines if line[0] != '#']
        if fieldsep is None:
            fieldsep = '\t' if '\t' in lines[0] else ','
        files = [[field.strip() for field in line.split(fieldsep)] for line in lines]
        print("DEBUG: info=%s, files=%s" % (info, files))
        return files, info

    def appendText(self, text, edit=None):
        if edit is None:
            edit = self.edit
        self.view.insert(edit, self.view.size(), text)

    def print_help(self):
        msg = self.__doc__
        self.appendText(msg)
        print(msg)

    def run(self, edit, password='', title=''):
        """ This is the entry point where the command is invoked. """
        self.password = password
        # self.view = sublime.active_view() # This is set by the sublime_plugin.TextCommand's __init__ method.
        self.edit = edit
        self.text = self.view.substr(sublime.Region(0, self.view.size()))
        if not self.text.strip():
            ## A blank buffer means that the user probably wants help. print help and return.
            self.print_help()
            return

        self.files, view_image_link_options = self.parseUploadBatchText(self.text)
        # Not sure how to handle this in case of macros/repeats...

        sitecon = mw_get_connect(self.password)
        # dict used to change how images are inserted.
        image_link_options = {'caption': '', 'options': '', 'filedescription_as_caption': False,
                              'link_fmt': '\n[[File:%(destname)s|%(options)s|%(caption)s]]\n'}
        image_link_options.update(mw_get_setting('mediawiker_insert_image_options', {}))
        # Update with options from first line of view:
        if view_image_link_options:
            image_link_options.update(view_image_link_options)
        # http://www.mediawiki.org/wiki/Help:Images
        # If semantic mediawiki is used, the user might want to chage the link format to:
        # [[Has image::File:%(destname)s|%(options)s|%(caption)s]]
        link_fmt = image_link_options.pop('link_fmt')
        filedescription_as_caption = image_link_options.pop('filedescription_as_caption')

        self.appendText("\nUploading %s files...:\n(Each line is interpreted as: filepath, destname, filedesc, link_options, link_caption\n" % len(self.files))

        for row in self.files:
            filepath = row[0]
            destname = row[1] if len(row) > 1 and row[1] else os.path.basename(filepath)
            filedesc = row[2] if len(row) > 2 else '%s as %s' % (basename(filepath), destname)
            link_options = row[3] if len(row) > 3 else None
            link_caption = row[4] if len(row) > 4 else (filedesc if filedescription_as_caption else None)
            # Default caption to file description? There is a request to be able to use file
            # description as image caption, but that hasn't been implemented,
            # http://www.mediawiki.org/wiki/Help_talk:Images#File_feature_request_-_Defaulting_to_image_description_in_Commons

            # Make per-file link_options dict:
            file_image_link_options = image_link_options.copy()
            for k, v in {'destname': destname, 'caption': link_caption, 'options': link_options}.items():
                if v:
                    file_image_link_options[k] = v

            try:
                with open(filepath, 'rb') as f:
                    print("\nAttempting to upload file %s to destination '%s' (description: '%s')...\n" % (filepath, destname, filedesc))
                    upload_info = sitecon.upload(f, destname, filedesc)
                    print("MediawikerUploadBatchViewCommand(): upload_info:", upload_info)
                if 'warnings' in upload_info:
                    msg = "Warnings while uploading file '%s': %s \nIt is likely that this file has not been properly uploaded." % (destname, upload_info.get('warnings'))
                else:
                    msg = 'File %s successfully uploaded to wiki as %s' % (filepath, destname)
                sublime.status_message(msg)
                print(msg)
                image_link = link_fmt % file_image_link_options
                print(image_link)
                self.appendText(image_link)
            except IOError as e:
                sublime.status_message('Upload IO error: "%s" for file "%s"' % (e, filepath))
                msg = "\n--- Could not upload file %s; IOError '%s'" % (filepath, e)
                print(msg)
                self.appendText(msg)
            except ValueError as e:
                # This might happen in predata['token'] = image.get_token('edit'), if e.g. title is invalid.
                msg = "\n--- Could not upload file %s; ValueError '%s' -- likely invalid destination filename/title, '%s'" % (filepath, e, destname)
                sublime.status_message('Upload error "%s", invalid destination file name/title "%s" for file "%s"' % (e, filepath, destname))
                self.appendText(msg)
                print(msg)
            except Exception as e:
                # Does this include login/login-cookie errors?
                # Should I break the for-loop in this case?
                print("UPLOAD ERROR:", repr(e))
                #import traceback
                #traceback.print_exc()
                sublime.message_dialog('Upload error: %s' % e)
                msg = "\n--- Other EXCEPTION '%s' while uploading file %s to destination '%s'" % (repr(e), filepath, destname)
                self.appendText(msg)
                print(msg)
                break


# Re-factoring out so I can use it elsewhere as well:
def get_figlet_text(text):
    font = 'colossal' # This is case *sensitive* (on *nix and if pyfiglet is zipped).
    try:
        from pyfiglet import Figlet
    except ImportError:
        print("ERROR, could not import pyfiglet, big text not available.")
        print("sys.path=", sys.path)
        return text
    f = Figlet(font)
    f.Font.smushMode = 64
    return f.renderText(text)

def adjust_figlet_todo(bigtext, header=None):
    """ Adjust figlet to make it a 'TODO' text (indented, fixed-width). """
    bigtext = bigtext.replace('\r\n', '\n').replace('\r', '\n').rstrip()
    full = "\n".join("   "+line for line in bigtext.split('\n'))
    if header:
        # Add "TODO: xxx" line above to make searching easier.
        full = "".join([" TODO: ", header, "\n\n", full, '\n'])
    return full

def adjust_figlet_comment(bigtext, header=''):
    """ Adjust figlet to make it a comment. """
    bigtext = bigtext.replace('\r\n', '\n').replace('\r', '\n').rstrip()
    full = "".join(["<!-- ", header, "\n", bigtext, "\n-->\n"])
    return full


class MediawikerInsertBigTextCommand(sublime_plugin.TextCommand):
    """
    Inserts big text. ST command string: mediawiker_insert_big_text.
    The run method accepts the following kwargs:
        text : Initial text value.
        prompt_msg : Show this message to the user. Set to False to disable user prompt completely.
        (Setting prompt_msg=False can be used to print text without user intervention).
    """
    def printText(self, text):
        """
        Prints the text. Can be overwritten by subclasses to change behaviour.
        Note that Edit objects may not be used after the TextCommand's run method has returned.
        Thus, if you have used e.g. show_input_panel to get input from the user,
        you will have to use run_command('text command string', kwargs) to perform edits.
        """
        #if edit is None:
        #    edit = self.edit
        #self.view.insert(edit, self.view.size(), text) # Doesn't work if you have finished the run() method.
        #pos = self.view.size() # At the end of the buffer. Use 0 for start of buffer;
        # selection is a sorted list of non-overlapping regions:
        region = self.view.sel()[-1]
        line = self.view.full_line(region)  # Returns a region.
        pos = line.end()     # We want to be at the end, NOT end+1.
        self.view.run_command('mediawiker_insert_text', {'position': pos, 'text': text})

    def adjustText(self, bigtext):
        """ Can be over-written by subclasses to modify the big-text. """
        return bigtext

    def run(self, edit, text=None, prompt_msg='Input text:'):
        """ This is the entry point where the command is invoked. """
        self.text = text or ''
        self.edit = edit
        # Note: the on_done, on_change, on_cancel functions are only called *AFTER* run is completed.
        if prompt_msg not in (False, None):
            sublime.active_window().show_input_panel(prompt_msg, self.text, self.set_text, None, None)
        else:
            self.set_text(text)

    def set_text(self, text):
        print("Setting self.text to: %s" % (text, ))
        self.text = text
        if self.text:
            bigtext = get_figlet_text(self.text) # Remove last newline.
            full = self.adjustText(bigtext)
            self.printText(full)
        else:
            print("No text input - self.text = %s" % (self.text, ))

class MediawikerInsertBigTodoCommand(MediawikerInsertBigTextCommand):
    """
    Inserts big 'TODO' text.
    mediawiker_insert_big_todo
    """
    def adjustText(self, bigtext):
        """ Can be over-written by subclasses to modify the big-text. """
        return adjust_figlet_todo(bigtext, self.text)

class MediawikerInsertBigCommentCommand(MediawikerInsertBigTextCommand):
    """
    Inserts big comment text.
    mediawiker_insert_big_comment
    """
    def adjustText(self, bigtext):
        """ Can be over-written by subclasses to modify the big-text. """
        return adjust_figlet_comment(bigtext, self.text)



class MediawikerNewExperimentCommand(sublime_plugin.WindowCommand):
    """
    Command string: mediawiker_new_experiment
    Create a new experiment:
    - exp folder, if mediawiker_experiments_basedir is specified.
    - new wiki page (in new buffer), if mediawiker_experiments_title_fmt is boolean true.
    - load buffer with template, if mediawiker_experiments_template
    --- and fill in template argument, as specified by mediawiker_experiments_template_args
    - TODO: How about making a link to the page and appending it to the experiments_overview_page
    This is a window command, since we might not have any views open when it is invoked.

    Question: Does Sublime wait for window commands to finish, or are they dispatched to run
    asynchronously in a separate thread? ST waits for one command to finish before a new is invoked.
    In other words: *Commands cannot be used as functions*. That makes ST plugin development a bit convoluted.
    It is generally best to avoid any "run_command" calls, until the end of any methods/commands.

    """

    def run(self):
        ### Loading all relevant settings: ###
        # The base directory where the user stores his experiments, e.g. /home/me/documents/experiments/
        self.exp_basedir = mw_get_setting('mediawiker_experiments_basedir')
        self.save_page_in_exp_folder = mw_get_setting('mediawiker_experiments_save_page_in_exp_folder', False)
        # How to format the folder, e.g. "{expid} {exp_titledesc}"
        self.exp_foldername_fmt = mw_get_setting('mediawiker_experiments_foldername_fmt')
        # Experiments overview page: Manually lists (and links) to all experiments.
        self.experiments_overview_page = mw_get_setting('mediawiker_experiments_overview_page')
        self.experiment_overview_link_format = mw_get_setting('mediawiker_experiments_overview_link_fmt', "\n* [[{}]]")
        self.template = mw_get_setting('mediawiker_experiments_template')
        # Constant args to feed to the template (Mostly for shared templates).
        self.template_kwargs = mw_get_setting('mediawiker_experiments_template_kwargs', {})
        # title format, e.g. "MyExperiments/{expid} {exp_titledesc}". If not set, no new buffer is created.
        self.title_fmt = mw_get_setting('mediawiker_experiments_title_fmt')
        # Which substitution mode to use:
        # "python-format" = template.format(**kwargs), "python-%" = template % kwargs, "mediawiki" = substitute_template_params(template, kwargs)
        self.template_subst_mode = mw_get_setting('mediawiker_experiments_template_subst_mode')
        # Building the experiment's buffer text incrementally by hand, inserting it into the view when complete.
        self.exp_buffer_text = ""

        # Start input chain:
        self.window.show_input_panel('Experiment ID:', '', self.expid_received, None, None)

    def expid_received(self, expid):
        """ Saves expid input and asks the user for titledesc. """
        self.expid = expid # empty string is OK.
        self.window.show_input_panel('Exp title desc:', '', self.exp_title_received, None, None)

    def exp_title_received(self, exp_titledesc):
        """ Saves titledesc input and asks the user for bigcomment text. """
        self.exp_titledesc = exp_titledesc # empty string is OK.
        self.window.show_input_panel('Big page comment:', self.expid, self.bigcomment_received, None, None)

    def bigcomment_received(self, bigcomment):
        """ Saves bigcomment input and invokes on_done. """
        self.bigcomment = bigcomment
        self.on_done()


    def on_done(self, dummy=None):
        """
        Called when all user input have been collected.
        """
        # Ways to format a date/datetime as string: startdate.strftime("%Y-%m-%d"), or "{:%Y-%m-%d}".format(startdate)
        startdate = date.today().isoformat()    # datetime.now()

        if not any((self.expid, self.exp_titledesc)):
            # If both expid and exp_title are empty, just abort:
            print("expid and exp_titledesc are both empty, aborting...")
            return

        ## 1. Make experiment folder, if appropriate: ##
        # If exp_foldername_fmt is not specified, use title_fmt (remove any '/' and whatever is before it)?
        foldername_fmt = self.exp_foldername_fmt or (self.title_fmt or '').split('/')[-1]
        if self.exp_basedir and foldername_fmt:
            if os.path.isdir(self.exp_basedir):
                self.foldername = foldername_fmt.format(expid=self.expid, exp_titledesc=self.exp_titledesc)
                self.folderpath = os.path.join(self.exp_basedir, self.foldername)
                try:
                    os.mkdir(self.folderpath)
                    msg = "Created new experiment directory: %s" % (self.folderpath,)
                except FileExistsError:
                    msg = "New exp directory already exists: %s" % (self.folderpath,)
                except (WindowsError, OSError, IOError) as e:
                    msg = "Error creating new exp directory '%s' :: %s" % (self.folderpath, repr(e))
            else:
                # We are not creating a new folder for the experiment because basedir doesn't exists:
                msg = "Specified experiment base dir does not exists: %s" % (self.exp_basedir,)
                self.foldername = self.folderpath = None
            print(msg)
            sublime.status_message(msg)

        ## 2. Make new view, if title_fmt is specified: ##
        if self.title_fmt:
            self.pagetitle = self.title_fmt.format(expid=self.expid, exp_titledesc=self.exp_titledesc)
            self.view = exp_view = sublime.active_window().new_file() # Make a new file/buffer/view
            self.window.focus_view(exp_view) # exp_view is now the window's active_view
            filename = mw_strquote(self.pagetitle)
            view_default_dir = self.folderpath if self.save_page_in_exp_folder and self.folderpath \
                                               else mw_get_setting('mediawiker_file_rootdir')
            if view_default_dir:
                print("Setting view's default dir to:", view_default_dir)
                exp_view.settings().set('default_dir', view_default_dir) # Update the view's working dir.
            exp_view.set_name(filename)
            # Manually set the syntax file to use (since the view does not have a file extension)
            self.view.set_syntax_file('Packages/Mediawiker/Mediawiki.tmLanguage')
        else:
            # We are not creating a new view, use the active view:
            self.view = exp_view = self.window.active_view()

        ## 3. Create big comment text: ##
        if self.bigcomment:
            exp_figlet_comment = get_figlet_text(self.bigcomment) # Makes the big figlet text
            self.exp_buffer_text += adjust_figlet_comment(exp_figlet_comment, self.foldername or self.bigcomment) # Adjusts the figlet to produce a comment

        ## 4. Generate template : ##
        if self.template:
            # Load the template: #
            if os.path.isfile(self.template):
                # User specified a local file:
                print("Using template:", self.template)
                with open(self.template) as fd:
                    template_content = fd.read()
                print("Template length:", len(template_content))
            else:
                # Assume template is a page on the server:
                # This will load the page into the window's active_view (asking for password, if required):
                # We have to manually obtain the template and do variable substitution
                #self.window.run_command("mediawiker_validate_connection_params", {"title": self.pagetitle, "action": 'mediawiker_show_page'})
                raise NotImplementedError("Obtaining templates from the server is not yet implemented...")

            # Perform template substitution (locally): #
            # Update kwargs with user input and today's date:
            self.template_kwargs.update({'expid': self.expid, 'exp_titledesc': self.exp_titledesc, 'startdate': startdate, 'date': startdate})
            if self.template_subst_mode == 'python-fmt':
                # template_kwargs must be dict/mapping: (template_args_order no longer supported)
                template_content = template_content.format(**self.template_kwargs)
            elif self.template_subst_mode == 'python-%':
                # "%s" string interpolation: template_vars must be tuple or dict (both will work):
                template_content = template_content % self.template_kwargs
            elif self.template_subst_mode in ('mediawiki', 'wiki', None) or True: # This is currently the default. Allows me to use wiki templates as local templates.
                # Use custom wiki template variable insertion function:
                # Get template args (defaults)  -- edit: I just use keep_unmatched=True.
                #template_params = get_template_params_dict(template_content, defaultvalue='')
                #print("Parameters in template:", template_params)
                #template_params.update(self.template_kwargs)
                template_content = substitute_template_params(template_content, self.template_kwargs, keep_unmatched=True)

            # Add template to buffer text string:
            self.exp_buffer_text = "".join(text.strip() for text in (self.exp_buffer_text, template_content))

        else:
            print('No template specified (settings key "mediawiker_experiments_template").')


        ## 6. Append self.exp_buffer_text to the view: ##
        exp_view.run_command('mediawiker_insert_text', {'position': exp_view.size(), 'text': self.exp_buffer_text})

        ## 7. Add a link to experiments_overview_page (local file): ##
        if self.experiments_overview_page:
            # Generate a link to this experiment:
            if self.pagetitle:
                link_text = self.experiment_overview_link_format.format(self.pagetitle)
            else:
                # Add a link to the current buffer's title, assuming the experiment header is the same as self.foldername
                link = "{}#{}".format(mw_get_title(), self.foldername.replace(' ', '_'))
                link_text = self.experiment_overview_link_format.format(link)

            # Insert link on experiments_overview_page. Currently, this must be a local file.
            # (We just edit the file on disk and let ST pick up the change if the file is opened in any view.)
            if os.path.isfile(self.experiments_overview_page):
                print("Adding link '%s' to file '%s'" % (link_text, self.experiments_overview_page))
                # We have a local file, append link:
                with open(self.experiments_overview_page, 'a') as fd:
                    # In python3, there is a bigger difference between binary 'b' mode and normal (text) mode.
                    # Do not open in binary 'b' mode when writing/appending strings. It is not supported in python 3.
                    # If you want to write strings to files opened in binary mode, you have to cast the string to bytes / encode it:
                    # >>> fd.write(bytes(mystring, 'UTF-8')) *or* fd.write(mystring.encode('UTF-8'))
                    fd.write(link_text) # The format should include newline if desired.
                print("Appended %s chars to file '%s" % (len(link_text), self.experiments_overview_page))
            else:
                # User probably specified a page on the wiki. (This is not yet supported.)
                # Even if this is a page on the wiki, you should check whether that page is already opened in Sublime.
                ## TODO: Implement specifying experiments_overview_page from server.
                print("Using experiment_overview_page from the server is not yet supported.")

        print("MediawikerNewExperimentCommand completed!\n")


class MediawikerFavoritesAddCommand(sublime_plugin.WindowCommand):
    """ Add current page to the favorites list. Command string: mediawiker_favorites_add  (WindowCommand) """
    def run(self):
        title = mw_get_title()
        mw_save_mypages(title=title, storage_name='mediawiker_favorites')


class MediawikerFavoritesOpenCommand(sublime_plugin.WindowCommand):
    """
    Open page from the favorites list.
    Command string: mediawiker_favorites_open (WindowCommand)
    """
    def run(self):
        self.window.run_command("mediawiker_page_list", {"storage_name": 'mediawiker_favorites'})


class MediawikerSavePageCommand(sublime_plugin.WindowCommand):
    """
    The default 'save' behaviour, invoked with e.g. ctrl+s (cmd+s) should be
    user-customizable, and certainly NOT override the user's ability to save the buffer
    using the normal ctrl+s keyboard shortcut.

    I, for one, hit ctrl+s every ten seconds or so, just out of habit.
    I *do not* want Mediawiker to push the page to the server that often (thus cluttering the history).
    I keep a local copy of the file during editing (which is synchronized via Dropbox
    to other running ST instances on other computers - works perfectly).

    Perhaps it is better to use an EventListener and use on_pre/post_save hooks to
    alter ctrl+s behaviour? Is that what the MediawikerLoad EventListener below is trying to do?
    """
    def run(self):
        on_save_action = mw_get_setting('mediawiker_on_save_action')
        # on_save_action can be a string or list, specifying what actions to take:
        if 'savefile' in on_save_action:
            # How do you save the view buffer?
            pass
        if 'publish' in on_save_action:
            self.window.run_command("mediawiker_page", {"action": "mediawiker_publish_page"})


class MediawikerLoad(sublime_plugin.EventListener):
    """
    What is this and how is this used?
    And what does mediawiker_is_here and mediawiker_wiki_instead_editor mean?
    This is an EventListener subclass. Like the other sublime_plugin classes, ST will take care of
    instantiation etc. It automatically binds a series of methods to ST events. For instance:
        on_activated is automatically invoked when a view is activated.
    """
    def on_activated(self, view):
        """
        Invoked whenever a view is activated.
        Used to set Mediawiker conditional settings (if we have a wiki page).
        The mediawiker_is_here setting key, for instance, is used in the "context-aware" binding
        of F5 to reopen page:
            "keys": ["f5"], "command": "mediawiker_reopen_page", "context": [{"key": "setting.mediawiker_is_here", "operand": true}]
        """
        if view.settings().get('syntax').endswith('Mediawiker/Mediawiki.tmLanguage'):
            # Mediawiki mode
            view.settings().set('mediawiker_is_here', True)
            view.settings().set('mediawiker_wiki_instead_editor', mw_get_setting('mediawiker_wiki_instead_editor'))
