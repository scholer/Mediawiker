__ver__ = '0.7.0'

import sys
pythonver = sys.version_info[0]

if pythonver >= 3:
    import urllib.parse
else:
    import urllib
    #import urlparse

import time
import random
import sys
import weakref
#import socket

try:
    import json
except ImportError:
    import simplejson as json
import httpmw
import upload

import errors
import listing
#import page
import compatibility

try:
    import gzip
except ImportError:
    gzip = None

if pythonver >= 3:
    from io import StringIO, BytesIO
else:
    try:
        from cStringIO import StringIO
    except(ImportError):
        from StringIO import StringIO


def parse_timestamp(t):
    if t == '0000-00-00T00:00:00Z':
        return (0, 0, 0, 0, 0, 0, 0, 0)
    return time.strptime(t, '%Y-%m-%dT%H:%M:%SZ')


class WaitToken(object):
    def __init__(self):
        if pythonver >= 3:
            self.id = '%x' % random.randint(0, sys.maxsize)
        else:
            self.id = '%x' % random.randint(0, sys.maxint)

    def __hash__(self):
        return hash(self.id)


class Site(object):
    api_limit = 500

    def __init__(self, host, path='/w/', ext='.php', pool=None, retry_timeout=30, max_retries=25, wait_callback=lambda *x: None,
                 max_lag=3, compress=True, force_login=True, do_init=True, custom_headers=None, inject_cookies=None):
        # Setup member variables
        self.host = host    # host is here a two-tuple of strings: (<scheme>, <hostname>), but can also be just <hostname> if https is not specified!
        self.path = path
        self.ext = ext
        self.credentials = None
        self.compress = compress

        self.retry_timeout = retry_timeout
        self.max_retries = max_retries
        self.wait_callback = wait_callback
        self.max_lag = str(max_lag)
        self.force_login = force_login

        # The token string => token object mapping
        self.wait_tokens = weakref.WeakKeyDictionary()

        # Site properties
        self.blocked = False    # Whether current user is blocked
        self.hasmsg = False  # Whether current user has new messages
        self.groups = []    # Groups current user belongs to
        self.rights = []    # Rights current user has
        self.tokens = {}    # Edit tokens of the current user
        self.version = None

        self.namespaces = self.default_namespaces
        self.writeapi = False
        self.custom_headers = custom_headers if custom_headers is not None else {}

        # Setup connection
        if pool is None:
            self.connection = httpmw.HTTPPool()
        else:
            self.connection = pool

        if inject_cookies:
            # Not sure if this should be host as a (scheme, hostname) tuple or just host as a string:
            # Here, only the hostname is used, not the scheme:
            # I guess it can be both...
            if isinstance(host, tuple):
                scheme, hostname = host
            else:
                hostname = host
            self.connection.cookies[hostname] = httpmw.CookieJar(inject_cookies)

        # Page generators
        self.pages = listing.PageList(self)
        self.categories = listing.PageList(self, namespace=14)
        self.images = listing.PageList(self, namespace=6)

        # Compat page generators
        self.Pages = self.pages
        self.Categories = self.categories
        self.Images = self.images

        # Initialization status
        self.initialized = False

        if do_init:
            try:
                self.site_init()
            except errors.APIError as e:
                # Private wiki, do init after login
                if e.code not in (u'unknown_action', u'readapidenied'):
                    raise

    def site_init(self):
        meta = self.api('query', meta='siteinfo|userinfo', siprop='general|namespaces', uiprop='groups|rights')

        # Extract site info
        self.site = meta['query']['general']
        if pythonver >= 3:
            self.namespaces = dict(((i['id'], i.get('*', '')) for i in list(meta['query']['namespaces'].values())))
        else:
            self.namespaces = dict(((i['id'], i.get('*', '')) for i in meta['query']['namespaces'].itervalues()))
        self.writeapi = 'writeapi' in self.site

        # Determine version
        if self.site['generator'].startswith('MediaWiki '):
            version = self.site['generator'][10:].split('.')

            def split_num(s):
                i = 0
                while i < len(s):
                    if s[i] < '0' or s[i] > '9':
                        break
                    i += 1
                if s[i:]:
                    return (int(s[:i]), s[i:], )
                else:
                    return (int(s[:i]), )
            self.version = sum((split_num(s) for s in version), ())

            if len(self.version) < 2:
                raise errors.MediaWikiVersionError('Unknown MediaWiki %s' % '.'.join(version))
        else:
            raise errors.MediaWikiVersionError('Unknown generator %s' % self.site['generator'])

        # Require 1.11 until some compatibility issues are fixed
        self.require(1, 11)

        # User info
        userinfo = compatibility.userinfo(meta, self.require(1, 12, raise_error=False))
        self.username = userinfo['name']
        self.groups = userinfo.get('groups', [])
        self.rights = userinfo.get('rights', [])
        self.initialized = True

    default_namespaces = {0: u'', 1: u'Talk', 2: u'User', 3: u'User talk', 4: u'Project', 5: u'Project talk',
                          6: u'Image', 7: u'Image talk', 8: u'MediaWiki', 9: u'MediaWiki talk', 10: u'Template', 11: u'Template talk',
                          12: u'Help', 13: u'Help talk', 14: u'Category', 15: u'Category talk', -1: u'Special', -2: u'Media'}

    def __repr__(self):
        return "<Site object '%s%s'>" % (self.host, self.path)

    def api(self, action, *args, **kwargs):
        """ An API call. Handles errors and returns dict object. """
        kwargs.update(args)
        if action == 'query':
            if 'meta' in kwargs:
                kwargs['meta'] += '|userinfo'
            else:
                kwargs['meta'] = 'userinfo'
            if 'uiprop' in kwargs:
                kwargs['uiprop'] += '|blockinfo|hasmsg'
            else:
                kwargs['uiprop'] = 'blockinfo|hasmsg'

        token = self.wait_token()
        while True:
            info = self.raw_api(action, **kwargs)
            if not info:
                info = {}
            res = self.handle_api_result(info, token=token)
            if res:
                return info

    def handle_api_result(self, info, kwargs=None, token=None):
        if token is None:
            token = self.wait_token()

        try:
            userinfo = compatibility.userinfo(info, self.require(1, 12, raise_error=None))
        except KeyError:
            userinfo = ()

        if 'blockedby' in userinfo:
            self.blocked = (userinfo['blockedby'], userinfo.get('blockreason', u''))
        else:
            self.blocked = False

        self.hasmsg = 'message' in userinfo
        self.logged_in = 'anon' not in userinfo

        if 'error' in info:
            if info['error']['code'] in ('internal_api_error_DBConnectionError', ):
                self.wait(token)
                return False
            if '*' in info['error']:
                raise errors.APIError(info['error']['code'], info['error']['info'], info['error']['*'])
            raise errors.APIError(info['error']['code'], info['error']['info'], kwargs)
        return True

    @staticmethod
    def _to_str(data):
        if pythonver >= 3:
            return str(data).encode('utf-8')
        else:
            if type(data) is unicode:
                return data.encode('utf-8')
            return str(data)

    @staticmethod
    def _query_string(*args, **kwargs):
        kwargs.update(args)
        if pythonver >= 3:
            qs = urllib.parse.urlencode([(k, Site._to_str(v)) for k, v in kwargs.items() if k != 'wpEditToken'])
            if 'wpEditToken' in kwargs:
                qs += '&wpEditToken=' + urllib.parse.quote(Site._to_str(kwargs['wpEditToken']))
        else:
            qs = urllib.urlencode([(k, Site._to_str(v)) for k, v in kwargs.iteritems() if k != 'wpEditToken'])
            if 'wpEditToken' in kwargs:
                qs += '&wpEditToken=' + urllib.quote(Site._to_str(kwargs['wpEditToken']))
        return qs

    def raw_call(self, script, data):
        url = self.path + script + self.ext
        headers = {}
        if not issubclass(data.__class__, upload.Upload):
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        if self.compress and gzip:
            headers['Accept-Encoding'] = 'gzip'

        if self.custom_headers:
            headers.update(self.custom_headers)

        token = self.wait_token((script, data))
        while True:
            try:
                stream = self.connection.post(self.host, url, data=data, headers=headers)
                if stream.getheader('Content-Encoding') == 'gzip':
                    # BAD.
                    if pythonver >= 3:
                        seekable_stream = BytesIO(stream.read())
                    else:
                        seekable_stream = StringIO(stream.read())
                    stream = gzip.GzipFile(fileobj=seekable_stream)
                return stream
            except errors.HTTPStatusError as exc:
                e = exc.args if pythonver >= 3 else exc
                if e[0] == 503 and e[1].getheader('X-Database-Lag'):
                    self.wait(token, int(e[1].getheader('Retry-After')))
                elif e[0] < 500 or e[0] > 599:
                    raise
                else:
                    self.wait(token)
            except errors.HTTPRedirectError:
                raise
            except errors.HTTPError:
                self.wait(token)
            except ValueError:
                self.wait(token)

    def raw_api(self, action, *args, **kwargs):
        kwargs['action'] = action
        kwargs['format'] = 'json'
        data = self._query_string(*args, **kwargs)
        if pythonver >= 3:
            json_data = self.raw_call('api', data).read().decode('utf-8')
        else:
            json_data = self.raw_call('api', data).read()
        try:
            return json.loads(json_data)
        except ValueError:
            if json_data.startswith('MediaWiki API is not enabled for this site.'):
                raise errors.APIDisabledError
            raise

    def raw_index(self, action, *args, **kwargs):
        kwargs['action'] = action
        kwargs['maxlag'] = self.max_lag
        data = self._query_string(*args, **kwargs)
        return self.raw_call('index', data).read().decode('utf-8', 'ignore')

    def wait_token(self, args=None):
        token = WaitToken()
        self.wait_tokens[token] = (0, args)
        return token

    def wait(self, token, min_wait=0):
        retry, args = self.wait_tokens[token]
        self.wait_tokens[token] = (retry + 1, args)
        if retry > self.max_retries and self.max_retries != -1:
            raise errors.MaximumRetriesExceeded(self, token, args)
        self.wait_callback(self, token, retry, args)

        timeout = self.retry_timeout * retry
        if timeout < min_wait:
            timeout = min_wait
        time.sleep(timeout)
        return self.wait_tokens[token]

    def require(self, major, minor, revision=None, raise_error=True):
        if self.version is None:
            if raise_error is None:
                return
            raise RuntimeError('Site %s has not yet been initialized' % repr(self))

        if revision is None:
            if self.version[:2] >= (major, minor):
                return True
            elif raise_error:
                raise errors.MediaWikiVersionError('Requires version %s.%s, current version is %s.%s' % ((major, minor) + self.version[:2]))
            else:
                return False
        else:
            raise NotImplementedError

    # Actions
    def email(self, user, text, subject, cc=False):
        #TODO: Use api!
        postdata = {}
        postdata['wpSubject'] = subject
        postdata['wpText'] = text
        if cc:
            postdata['wpCCMe'] = '1'
        postdata['wpEditToken'] = self.tokens['edit']
        postdata['uselang'] = 'en'
        postdata['title'] = u'Special:Emailuser/' + user

        data = self.raw_index('submit', **postdata)
        if 'var wgAction = "success";' not in data:
            if 'This user has not specified a valid e-mail address' in data:
                # Dirty hack
                raise errors.NoSpecifiedEmailError(user)
            raise errors.EmailError(data)

    def login(self, username=None, password=None, cookies=None, domain=None):
        if self.initialized:
            self.require(1, 10)

        if username and password:
            self.credentials = (username, password, domain)
        if cookies:
            if self.host not in self.conn.cookies:
                self.conn.cookies[self.host] = httpmw.CookieJar()
            self.conn.cookies[self.host].update(cookies)

        if self.credentials:
            wait_token = self.wait_token()
            kwargs = {
                'lgname': self.credentials[0],
                'lgpassword': self.credentials[1]
            }
            if self.credentials[2]:
                kwargs['lgdomain'] = self.credentials[2]
            while True:
                login = self.api('login', **kwargs)
                if login['login']['result'] == 'Success':
                    break
                elif login['login']['result'] == 'NeedToken':
                    kwargs['lgtoken'] = login['login']['token']
                elif login['login']['result'] == 'Throttled':
                    self.wait(wait_token, login['login'].get('wait', 5))
                else:
                    raise errors.LoginError(self, login['login'])

        if self.initialized:
            info = self.api('query', meta='userinfo', uiprop='groups|rights')
            userinfo = compatibility.userinfo(info, self.require(1, 12, raise_error=False))
            self.username = userinfo['name']
            self.groups = userinfo.get('groups', [])
            self.rights = userinfo.get('rights', [])
            self.tokens = {}
        else:
            self.site_init()

    def upload(self, fileobj=None, filename=None, description='', ignore=False, file_size=None, url=None, session_key=None):
        """
        Parameters:
            fileobj: File-like object with the data to upload.
            filename: Destination filename (on the wiki).
            description: Add this description to the file (on the wiki).
            ignore: Add "ignorewarnings"=true parameter to the query
                    (required to upload a new/updated version of an existing image.)
        """
        if self.version[:2] < (1, 16):
            print("DEBUG: upload() - Using old upload method...")
            return compatibility.old_upload(self, fileobj=fileobj, filename=filename, description=description, ignore=ignore, file_size=file_size)

        image = self.Images[filename]
        if not image.can('upload'):
            raise errors.InsufficientPermission(filename)

        predata = {}

        predata['comment'] = description
        if ignore:
            predata['ignorewarnings'] = 'true'
        # This will likely invoke an api call.
        # If image.name (title) is invalid, then this could cause an exception.
        # (Would be KeyError for old mwclient code, is now ValueError)
        # If an exception is raised, should we do anything about it? - No, we can't do much from here.
        predata['token'] = image.get_token('edit') # May raise KeyError/ValueError
        predata['action'] = 'upload'
        predata['format'] = 'json'
        predata['filename'] = filename
        if url:
            predata['url'] = url
        if session_key:
            predata['session_key'] = session_key

        if fileobj is None:
            postdata = self._query_string(predata)
        else:
            if type(fileobj) is str:
                file_size = len(fileobj)
                fileobj = StringIO(fileobj)
            if file_size is None:
                fileobj.seek(0, 2)          # Seek to end of file.
                file_size = fileobj.tell()
                fileobj.seek(0, 0)

            postdata = upload.UploadFile('file', filename, file_size, fileobj, predata)

        wait_token = self.wait_token()
        while True:
            try:
                data = self.raw_call('api', postdata).read()
                if pythonver >= 3:
                    info = json.loads(data.decode('utf-8'))
                else:
                    info = json.loads(data)
                if not info:
                    info = {}
                if self.handle_api_result(info, kwargs=predata):
                    return info.get('upload', {}) # 'upload' should be the only key...
            except errors.HTTPStatusError as exc:
                e = exc.args if pythonver >= 3 else exc
                if e[0] == 503 and e[1].getheader('X-Database-Lag'):
                    self.wait(wait_token, int(e[1].getheader('Retry-After')))
                elif e[0] < 500 or e[0] > 599:
                    raise
                else:
                    self.wait(wait_token)
            except errors.HTTPError:
                self.wait(wait_token)
            fileobj.seek(0, 0)

    def parse(self, text, title=None):
        kwargs = {'text': text}
        if title is not None:
            kwargs['title'] = title
        result = self.api('parse', **kwargs)
        return result['parse']

    # def block: requires 1.12
    # def unblock: requires 1.12
    # def patrol: requires 1.14
    # def import: requires 1.15

    # Lists
    def allpages(self, start=None, prefix=None, namespace='0', filterredir='all', minsize=None, maxsize=None, prtype=None, prlevel=None, limit=None, dir='ascending', filterlanglinks='all', generator=True):
        self.require(1, 9)

        pfx = listing.List.get_prefix('ap', generator)
        kwargs = dict(listing.List.generate_kwargs(pfx, ('from', start), prefix=prefix, minsize=minsize, maxsize=maxsize, prtype=prtype, prlevel=prlevel, namespace=namespace, filterredir=filterredir, dir=dir, filterlanglinks=filterlanglinks))
        return listing.List.get_list(generator)(self, 'allpages', 'ap', limit=limit, return_values='title', **kwargs)

    # TODO: def allimages(self): requires 1.12

    def alllinks(self, start=None, prefix=None, unique=False, prop='title', namespace='0', limit=None, generator=True):
        self.require(1, 11)

        pfx = listing.List.get_prefix('al', generator)
        kwargs = dict(listing.List.generate_kwargs(pfx, ('from', start), prefix=prefix, prop=prop, namespace=namespace))
        if unique:
            kwargs[pfx + 'unique'] = '1'
        return listing.List.get_list(generator)(self, 'alllinks', 'al', limit=limit, return_values='title', **kwargs)

    def allcategories(self, start=None, prefix=None, dir='ascending', limit=None, generator=True):
        self.require(1, 12)

        pfx = listing.List.get_prefix('ac', generator)
        kwargs = dict(listing.List.generate_kwargs(pfx, ('from', start), prefix=prefix, dir=dir))
        return listing.List.get_list(generator)(self, 'allcategories', 'ac', limit=limit, **kwargs)

    def allusers(self, start=None, prefix=None, group=None, prop=None, limit=None):
        self.require(1, 11)

        kwargs = dict(listing.List.generate_kwargs('au', ('from', start), prefix=prefix, group=group, prop=prop))
        return listing.List(self, 'allusers', 'au', limit=limit, **kwargs)

    def blocks(self, start=None, end=None, dir='older', ids=None, users=None, limit=None, prop='id|user|by|timestamp|expiry|reason|flags'):
        self.require(1, 12)
        # TODO: Fix. Fix what?
        kwargs = dict(listing.List.generate_kwargs('bk', start=start, end=end, dir=dir, users=users, prop=prop))
        return listing.List(self, 'blocks', 'bk', limit=limit, **kwargs)

    def deletedrevisions(self, start=None, end=None, dir='older', namespace=None, limit=None, prop='user|comment'):
        # TODO: Fix
        self.require(1, 12)
        kwargs = dict(listing.List.generate_kwargs('dr', start=start, end=end, dir=dir, namespace=namespace, prop=prop))
        return listing.List(self, 'deletedrevs', 'dr', limit=limit, **kwargs)

    def exturlusage(self, query, prop=None, protocol='http', namespace=None, limit=None):
        self.require(1, 11)
        kwargs = dict(listing.List.generate_kwargs('eu', query=query, prop=prop, protocol=protocol, namespace=namespace))
        return listing.List(self, 'exturlusage', 'eu', limit=limit, **kwargs)

    def logevents(self, type=None, prop=None, start=None, end=None, dir='older', user=None, title=None, limit=None):
        self.require(1, 9)
        kwargs = dict(listing.List.generate_kwargs('le', prop=prop, type=type, start=start, end=end, dir=dir, user=user, title=title))
        return listing.List(self, 'logevents', 'le', limit=limit, **kwargs)

    # def protectedtitles requires 1.15
    def random(self, namespace, limit=20):
        self.require(1, 12)
        kwargs = dict(listing.List.generate_kwargs('rn', namespace=namespace))
        return listing.List(self, 'random', 'rn', limit=limit, **kwargs)

    def recentchanges(self, start=None, end=None, dir='older', namespace=None, prop=None, show=None, limit=None, type=None):
        self.require(1, 9)
        kwargs = dict(listing.List.generate_kwargs('rc', start=start, end=end, dir=dir, namespace=namespace, prop=prop, show=show, type=type))
        return listing.List(self, 'recentchanges', 'rc', limit=limit, **kwargs)

    def search(self, search, namespace='0', what='title', redirects=False, limit=None):
        self.require(1, 11)
        kwargs = dict(listing.List.generate_kwargs('sr', search=search, namespace=namespace, what=what))
        if redirects:
            kwargs['srredirects'] = '1'
        return listing.List(self, 'search', 'sr', limit=limit, **kwargs)

    def usercontributions(self, user, start=None, end=None, dir='older', namespace=None, prop=None, show=None, limit=None):
        self.require(1, 9)
        kwargs = dict(listing.List.generate_kwargs('uc', user=user, start=start, end=end, dir=dir, namespace=namespace, prop=prop, show=show))
        return listing.List(self, 'usercontribs', 'uc', limit=limit, **kwargs)

    def users(self, users, prop='blockinfo|groups|editcount'):
        self.require(1, 12)
        return listing.List(self, 'users', 'us', ususers='|'.join(users), usprop=prop)

    def watchlist(self, allrev=False, start=None, end=None, namespace=None, dir='older', prop=None, show=None, limit=None):
        self.require(1, 9)
        kwargs = dict(listing.List.generate_kwargs('wl', start=start, end=end, namespace=namespace, dir=dir, prop=prop, show=show))
        if allrev:
            kwargs['wlallrev'] = '1'
        return listing.List(self, 'watchlist', 'wl', limit=limit, **kwargs)

    def expandtemplates(self, text, title=None, generatexml=False):
        self.require(1, 11)
        kwargs = {}
        if title is None:
            kwargs['title'] = title
        if generatexml:
            kwargs['generatexml'] = '1'

        result = self.api('expandtemplates', text=text, **kwargs)

        if generatexml:
            return result['expandtemplates']['*'], result['parsetree']['*']
        else:
            return result['expandtemplates']['*']
