#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pylint: disable=invalid-name,line-too-long

"""

Utility module for Mediawikier package.

To import from within Sublime:
>>> from Mediawiker import mwutils as mw
"""

from __future__ import print_function
import sys
import os
import re
import urllib
import base64
from hashlib import md5
import uuid

import sublime

pythonver = sys.version_info[0]

# Load local modules:
if pythonver >= 3:
    from . import mwclient
    from .lib.cache_decorator import cached_property
else:
    import mwclient
    from lib.cache_decorator import cached_property



### SETTINGS HANDLING ###

def get_setting(key, default_value=None):
    """
    Returns setting for key <key>, defaulting to default_value if not present (default: None)
    Note that the returned object seems to be a copy;
    changes, even to mutable entries, cannot simply be persisted with sublime.save_settings.
    You have to keep a reference to the original settings object and make changes to this.
    """
    settings = sublime.load_settings('Mediawiker.sublime-settings')
    return settings.get(key, default_value)


def set_setting(key, value):
    """ Set setting for key <key>, to value <value>. """
    settings = sublime.load_settings('Mediawiker.sublime-settings')
    settings.set(key, value)
    sublime.save_settings('Mediawiker.sublime-settings')


def get_site_params(name=None):
    """ Get site parameters for active site, or site <name> if specified. """
    if name is None:
        name = get_setting('mediawiki_site_active')
    sites = get_setting('mediawiki_site')
    return sites[name]


def get_view_site():
    try:
        return sublime.active_window().active_view().settings().get('mediawiker_site', get_setting('mediawiki_site_active'))
    except:
        # st2 exception on start.. sublime not available on activated..
        return get_setting('mediawiki_site_active')


### CONNECTION HANDLING ###

def enco(value):
    ''' for md5 hashing string must be encoded '''
    if pythonver >= 3:
        return value.encode('utf-8')
    return value


def deco(value):
    ''' for py3 decode from bytes '''
    if pythonver >= 3:
        return value.decode('utf-8')
    return value


def get_digest_header(header, username, password, path):
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
        ha1 = md5(enco('%s:%s:%s' % (username, realm, password))).hexdigest()
    elif algorithm == 'MD5-Sess':
        ha1 = md5(enco('%s:%s:%s' % (md5(enco('%s:%s:%s' % (username, realm, password))), nonce, cnonce))).hexdigest()

    if 'auth-int' in qop:
        ha2 = md5(enco('%s:%s:%s' % (METHOD, digest_uri, md5(entity_body)))).hexdigest()
    elif 'auth' in qop:
        ha2 = md5(enco('%s:%s' % (METHOD, digest_uri))).hexdigest()

    if 'auth' in qop or 'auth-int' in qop:
        response = md5(enco('%s:%s:%s:%s:%s:%s' % (ha1, nonce, nc, cnonce, qop, ha2))).hexdigest()
    else:
        response = md5(enco('%s:%s:%s' % (ha1, nonce, ha2))).hexdigest()

    # auth = 'username="%s", realm="%s", nonce="%s", uri="%s", response="%s", opaque="%s", qop="%s", nc=%s, cnonce="%s"' %
    # (username, realm, nonce, digest_uri, response, opaque, qop, nc, cnonce)
    auth_tpl = 'username="%s", realm="%s", nonce="%s", uri="%s", response="%s", qop="%s", nc=%s, cnonce="%s"'

    return auth_tpl % (username, realm, nonce, digest_uri, response, qop, nc, cnonce)


def http_auth(http_auth_header, host, path, login, password):
    sitecon = None
    DIGEST_REALM = 'Digest realm'
    BASIC_REALM = 'Basic realm'

    # http_auth_header = e[1].getheader('www-authenticate')
    custom_headers = {}
    realm = None
    if http_auth_header.startswith(BASIC_REALM):
        realm = BASIC_REALM
    elif http_auth_header.startswith(DIGEST_REALM):
        realm = DIGEST_REALM

    if realm is not None:
        if realm == BASIC_REALM:
            auth = deco(base64.standard_b64encode(enco('%s:%s' % (login, password))))
            custom_headers = {'Authorization': 'Basic %s' % auth}
        elif realm == DIGEST_REALM:
            auth = get_digest_header(http_auth_header, login, password, '%sapi.php' % path)
            custom_headers = {'Authorization': 'Digest %s' % auth}

        if custom_headers:
            sitecon = mwclient.Site(host=host, path=path, custom_headers=custom_headers)
    else:
        error_message = 'HTTP connection failed: Unknown realm.'
        sublime.status_message(error_message)
        raise Exception(error_message)
    return sitecon


def get_connect(password=None):
    """ Returns a mwclient connection to the active MediaWiki site. """
    site_active = get_view_site()
    site_list = get_setting('mediawiki_site')
    site_params = site_list[site_active]
    site = site_params['host']
    path = site_params['path']
    username = site_params['username']
    if password is None:
        password = site_params['password']
    domain = site_params['domain']
    proxy_host = site_params.get('proxy_host', '')
    is_https = site_params.get('https', False)
    if is_https:
        sublime.status_message('Trying to get https connection to https://%s' % site)
    host = site if not is_https else ('https', site)
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
        # I have modified mwclient in order to be able to pass in custom cookies
        sitecon = mwclient.Site(host=host, path=path, inject_cookies=inject_cookies)
    except mwclient.HTTPStatusError as exc:
        e = exc.args if pythonver >= 3 else exc
        is_use_http_auth = site_params.get('use_http_auth', False)
        http_auth_login = site_params.get('http_auth_login', '')
        http_auth_password = site_params.get('http_auth_password', '')
        if e[0] == 401 and is_use_http_auth and http_auth_login:
            http_auth_header = e[1].getheader('www-authenticate')
            sitecon = http_auth(http_auth_header, host, path, http_auth_login, http_auth_password)
        else:
            sublime.status_message('HTTP connection failed: %s' % e[1])
            raise Exception('HTTP connection failed.')
    except mwclient.HTTPRedirectError as exc:
        # if redirect to '/login.php' page:
        msg = 'Connection to server failed. If you are logging in with an open_id session cookie, it may have expired. (HTTPRedirectError: %s)' % exc
        print(msg)
        sublime.status_message(msg)
        raise exc

    # if login is not empty - auth required
    if username:
        try:
            if sitecon is not None:
                sitecon.login(username=username, password=password, domain=domain)
                sublime.status_message('Logon successfully.')
            else:
                sublime.status_message('Login failed: connection unavailable.')
        except mwclient.LoginError as e:
            sublime.status_message('Login failed: %s' % e[1]['result'])
            return
    elif inject_cookies:
        sublime.status_message('Connected using cookies: %s' % ", ".join(inject_cookies.keys()))
        print('Connected using cookies: %s' % ", ".join(inject_cookies.keys()))
    else:
        sublime.status_message('Connection without authorization')
    return sitecon


class SiteconnMgr():
    """
    Site connection manager.
    Primitive attempt at saving connection between calls.
    Making a new mw.get_connect every time seems in-efficient...
    Currently just used to provide a cachable connection.
    """

    def __init__(self, password=None):
        self.password = password
        self.conn = None

    @cached_property(ttl=120)
    def Siteconn(self):
        """
        cached_property caches values using
        self._cache[propname] = (value, last_update)
        To expire use: del siteconmgr.Siteconn
        """
        return get_connect(self.password)

    def reset_conn(self, password=None):
        self.del_conn()
        return self.Siteconn

    def del_conn(self, ):
        del self.Siteconn


# wiki related functions..


def get_page_text(site, title):
    """ Get the content of a page by title. """
    denied_message = 'You have not rights to edit this page. Click OK button to view its source.'
    page = site.Pages[title]
    if page.can('edit'):
        return True, page.edit()
    else:
        if sublime.ok_cancel_dialog(denied_message):
            if page.can('read'):
                return False, page.edit(readonly=True)
            else:
                return False, ''
        else:
            return False, ''


def save_mypages(title, storage_name='mediawiker_pagelist'):

    title = title.replace('_', ' ')  # for wiki '_' and ' ' are equal in page name
    pagelist_maxsize = get_setting('mediawiker_pagelist_maxsize')
    site_active = get_view_site()
    mediawiker_pagelist = get_setting(storage_name, {})

    my_pages = mediawiker_pagelist.setdefault(site_active, [])

    if my_pages:
        if title in my_pages:
            # for sorting - remove *before* trimming size, not after.
            my_pages.remove(title)
        while len(my_pages) >= pagelist_maxsize:
            my_pages.pop(0)

    my_pages.append(title)
    set_setting(storage_name, mediawiker_pagelist)


### HANDLING PAGE TITLES, Quoting and unquoting ###


def strquote(string_value, quote_plus=None, safe=None):
    """
    str quote and unquote:
        quoting will replace reserved characters (: ; ? @ & = + $ , /) with encoded versions,
        unquoting will reverse the process.
        The parameter safe='/' specified which characters not to touch.
    quote_plus will further replace spaces with '+' and defaults to safe='' (i.e. all reserved are replaced.)
    Note that the 'safe' argument only applies when quoting; unquoting will always convert all.
    """
    # Support for "quote_plus": escapes '/' to '%2F' and space ' ' with '+' rather than '%20'
    if quote_plus is None:
        quote_plus = get_setting("mediawiki_quote_plus", False)
    if safe is None:
        safe = get_setting("mediawiker_quote_safe", '' if quote_plus else '/')
    if pythonver >= 3:
        quote = urllib.parse.quote_plus if quote_plus else urllib.parse.quote
        return quote(string_value, safe=safe)
    else:
        quote = urllib.quote_plus if quote_plus else urllib.quote
        return quote(string_value.encode('utf-8'), safe=safe)


def strunquote(string_value, quote_plus=None):
    """ Reverses the effect of strquote() """
    if quote_plus is None:
        quote_plus = get_setting("mediawiki_quote_plus", False)
    if pythonver >= 3:
        unquote = urllib.parse.unquote_plus if quote_plus else urllib.parse.unquote
        return unquote(string_value)
    else:
        unquote = urllib.unquote_plus if quote_plus else urllib.quote
        return unquote(string_value.encode('ascii')).decode('utf-8')


def pagename_clear(pagename):
    """ Return clear pagename if page-url was set instead of.."""
    site_active = get_view_site()
    site_list = get_setting('mediawiki_site')
    site = site_list[site_active]['host']
    pagepath = site_list[site_active]['pagepath']
    try:
        pagename = strunquote(pagename)
    except UnicodeEncodeError:
        pass
    except Exception:
        pass

    if site in pagename:
        pagename = re.sub(r'(https?://)?%s%s' % (site, pagepath), '', pagename)

    sublime.status_message('Page name was cleared.')
    return pagename


def get_title():
    """
    Returns page title of active tab from view_name or from file_name.
    Be careful to make sure that the round-trip:
        make_filename -> get_title() ->  make_filename()
    Maps 1:1.
    """

    view_name = sublime.active_window().active_view().name()
    if view_name:
        print("DEBUG: view_name: ", view_name, "strunquote(view_name)=", strunquote(view_name))
        return strunquote(view_name)
    else:
        # haven't view.name, try to get from view.file_name (without extension)
        file_name = sublime.active_window().active_view().file_name()
        if file_name:
            wiki_extensions = get_setting('mediawiker_files_extension')
            title, ext = os.path.splitext(os.path.basename(file_name))
            if ext[1:] in wiki_extensions and title:
                print("DEBUG: rewriting filename_stem %s -> %s" % (title, strunquote(title)))
                return strunquote(title)
            else:
                sublime.status_message('Unauthorized file extension for mediawiki publishing. Check your configuration for correct extensions.')
                return ''
    return ''


def get_filename(title):
    """
    Return a file-system friendly/compatible filename from title.
    """
    file_rootdir = get_setting('mediawiker_file_rootdir', None)
    if not file_rootdir:
        return strquote(title)
    use_subdirs = get_setting('mediawiker_use_subdirs', False)
    if use_subdirs:
        filename = os.path.join(file_rootdir, *(strquote(item) for item in os.path.split(title)))
        filedir = os.path.dirname(filename)
        if not os.path.isdir(filedir):
            print("Making dir:", filedir)
            os.makedirs(filedir)
        return filename
    return os.path.join(file_rootdir, strquote(title))


def get_hlevel(header_string, substring):
    return int(header_string.count(substring) / 2)


def get_category(category_full_name):
    ''' From full category name like "Category:Name" return tuple (Category, Name) '''
    if ':' in category_full_name:
        return category_full_name.split(':')
    else:
        return 'Category', category_full_name


def get_page_url(page_name=''):
    """ Returns URL of page with title of the active document, or <page_name> if given. """
    site_active = get_view_site()
    site_list = get_setting('mediawiki_site')
    site = site_list[site_active]["host"]

    is_https = False
    if 'https' in site_list[site_active]:
        is_https = site_list[site_active]["https"]

    proto = 'https' if is_https else 'http'
    pagepath = site_list[site_active]["pagepath"]
    if not page_name:
        # For URLs, we need to quote spaces to '%20' rather than '+' and not replace '/' with '%2F'
        # Thus, force use of quote rather than quote_plus and use safe='/'.
        page_name = strquote(get_title(), quote_plus=False, safe='/')
    if page_name:
        return '%s://%s%s%s' % (proto, site, pagepath, page_name)
    else:
        return ''



### TEMPLATE HANDLING, PARSING, INTERPOLATION ###


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

def make_template_example_usage(template):
    """
    TODO: Add test for this and other simple functions.
    """
    params = get_template_params_dict(template)
    template_name = get_filename(template)
    params_str = "\n".join("| {0}=Example {0}".format(key) for key in sorted(params.keys()))
    return "Usage:\n{{ %s\n%s\n}}" % (template_name, params_str)

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
    if keep_unmatched:
        def repl(match):
            return params.get(match.group(1), match.group(0))
    else:
        def repl(match):
            return params.get(match.group(1), defaultvalue)
    return re.sub(pattern, repl, template)


# classes..

class InputPanel:

    def __init__(self):
        self.window = sublime.active_window()

    def show_input(self, panel_title='Input', value_pre=''):
        self.window.show_input_panel(panel_title, value_pre, self.on_done, self.on_change, None)

    def on_done(self, value):
        pass

    def on_change(self, value):
        pass


class InputPanelPageTitle(InputPanel):

    def get_title(self, title):
        if not title:
            title_pre = ''
            # use clipboard or selected text for page name
            if bool(get_setting('mediawiker_clipboard_as_defaultpagename')):
                title_pre = sublime.get_clipboard().strip()
            if not title_pre:
                selection = self.window.active_view().sel()
                title_pre = self.window.active_view().substr(selection[0]).strip()
            self.show_input('Wiki page name:', title_pre)
        else:
            self.on_done(title)

    def on_change(self, title):
        if title:
            pagename_cleared = pagename_clear(title)
            if title != pagename_cleared:
                self.window.show_input_panel('Wiki page name:', pagename_cleared, self.on_done, self.on_change, None)


class InputPanelPassword(InputPanel):

    ph = None
    is_hide_password = False

    def get_password(self):
        # site_active = mw.get_setting('mediawiki_site_active')
        site_active = get_view_site()
        site_list = get_setting('mediawiki_site')
        password = site_list[site_active]["password"]
        if site_list[site_active]["username"]:
            # auth required if username exists in settings
            if not password:
                self.is_hide_password = get_setting('mediawiker_password_input_hide')
                if self.is_hide_password:
                    self.ph = PasswordHider()
                # need to ask for password
                # window.show_input_panel('Password:', '', self.on_done, self.on_change, None)
                self.show_input('Password:', '')
            else:
                # return password
                self.on_done(password)
        else:
            # auth is not required
            self.on_done('')

    def on_change(self, str_val):
        if str_val and self.is_hide_password and self.ph:
            password = self.ph.hide(str_val)
            if password != str_val:
                # self.window.show_input_panel('Password:', password, self.on_done, self.on_change, None)
                self.show_input('Password:', password)

    def on_done(self, password):
        if password and self.is_hide_password and self.ph:
            password = self.ph.done()
        self.command_run(password)  # defined in executor


class PasswordHider():

    password = ''
    PASSWORD_CHAR = u'\u25CF'

    def hide(self, password):
        if len(password) < len(self.password):
            self.password = self.password[:len(password)]
        else:
            try:
                self.password = '%s%s' % (self.password, password.replace(self.PASSWORD_CHAR, ''))
            except:
                pass
        return self.PASSWORD_CHAR * len(self.password)

    def done(self):
        try:
            return self.password
        except:
            pass
        finally:
            self.password = ''
