#!/usr/bin/env python\n
# -*- coding: utf-8 -*-


from __future__ import print_function
FOR_MEDIAWIKER = True
import sys
pythonver = sys.version_info[0]


if pythonver >= 3:
    import urllib.request as urllib_compat  # , urllib.error    # pylint: disable=F0401,E0611
    import urllib.parse as urlparse_compat                      # pylint: disable=F0401,E0611
    import http.client as http_compat                           # pylint: disable=F0401

    if FOR_MEDIAWIKER and sys.platform.startswith('linux'):
        # for mediawiker's ssl under linux under sublime 3
        # ssl was loaded from mediawiker
        # under sublime 3 needs to reload ssl required modules
        import imp      # I don't want to overwrite builtin reload()
        imp.reload(http_compat)
        print('Mediawiker: http_compat reloaded.')

else:
    import urllib2 as urllib_compat
    import urlparse as urlparse_compat
    import httplib as http_compat

import socket
import time

import upload
import errors

from client import __ver__


class Request(urllib_compat.Request):
    def __init__(self, url, data=None, headers={}, origin_req_host=None, unverifiable=False, head=False):
        urllib_compat.Request.__init__(self, url, data, headers, origin_req_host, unverifiable)
        self.add_header('User-Agent', 'MwClient-' + __ver__)
        self.head = head

    def get_method(self):
        if self.head:
            return 'HEAD'
        return urllib_compat.Request.get_method(self)


class CookieJar(dict):
    def __init__(self, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)

    def extract_cookies(self, response):
        if pythonver >= 3:
            # getallmatchingheaders had been broken in python 3:
            # http://bugs.python.org/issue5053
            # http://bugs.python.org/issue13425
            # There is a get_all method which is python 3 only that does what getallmatchingheaders did (correctly).
            # Additionally, get_all returns None by default if there are no matching headers.
            #for cookie in response.msg.getallmatchingheaders('Set-Cookie'):
            for cookie in response.msg.get_all('Set-Cookie', []):
                self.parse_cookie(cookie.strip())
        else:
            for cookie in response.msg.getallmatchingheaders('Set-Cookie'):
                self.parse_cookie(cookie.strip())
        if response.getheader('set-cookie2', None):
            # TODO: value is undefined..
            # raise RuntimeError('Set-Cookie2', value)
            raise RuntimeError('Set-Cookie2', '')

    def parse_cookie(self, cookie):
        if not cookie:
            return

        if pythonver >= 3:
            #after get_all from extract_cookies cookie string will be like "mwikidb_session=fmfnljv3seokdedqgra0qdasi5; path=/; HttpOnly", splits no needs
            i = cookie.strip().split('=')
        else:
            value, attrs = cookie.split(': ', 1)[1].split(';', 1)
            i = value.strip().split('=')

        if len(i) == 1 and i[0] in self:
            del self[i[0]]
        else:
            self[i[0]] = i[1]

    def get_cookie_header(self):
        if pythonver >= 3:
            return '; '.join(('%s=%s' % i for i in list(self.items())))
        else:
            return '; '.join(('%s=%s' % i for i in self.iteritems()))

    def __iter__(self):
        if pythonver >= 3:
            for k, v in list(self.items()):
                yield Cookie(k, v)
        else:
            for k, v in self.iteritems():
                yield Cookie(k, v)


class Cookie(object):
    def __init__(self, name, value):
        self.name = name
        self.value = value


class HTTPPersistentConnection(object):
    http_class = http_compat.HTTPConnection
    scheme_name = 'http'

    def __init__(self, host, pool=None):
        self.cookies = {}
        self.pool = pool
        # Checking with "if pool:" gives unexpected result if pool is given but empty. Using "if pool is None:" instead.
        if pool is not None:
            print("DEBUG: Using existing pool's dict of cookiejars:")
            self.cookies = pool.cookies
        print("DEBUG: pool=%s, bool(pool)=%s" % (pool, bool(pool)))
        print("DEBUG: self.pool=%s, self.cookies=%s" % (pool, self.cookies))
        self._conn = self.http_class(host)
        self._conn.connect()
        self.last_request = time.time()

    def request(self, method, host, path, headers, data, raise_on_not_ok=True, auto_redirect=True):
        """
        Note that cookies are sent as a header item.
        Assuming you have your cookies as a dict, you can do:
            headers['Cookie'] = ";".join("{}={}".format(k, v) for k, v in cookies.items())
        """

        # Strip scheme
        if type(host) is tuple:
            host = host[1]

        # Dirty hack...
        if (time.time() - self.last_request) > 60:
            self._conn.close()
            self._conn.connect()

        _headers = headers
        headers = {}

        headers['Connection'] = 'Keep-Alive'
        headers['User-Agent'] = 'MwClient/' + __ver__
        headers['Host'] = host
        if host in self.cookies:
            headers['Cookie'] = self.cookies[host].get_cookie_header()
        if issubclass(data.__class__, upload.Upload):
            headers['Content-Type'] = data.content_type
            headers['Content-Length'] = str(data.length)
        elif data:
            headers['Content-Length'] = str(len(data))

        if _headers:
            headers.update(_headers)
        print("DEBUG: self=%s, headers=%s, data='%s', host='%s', path='%s'" % (self, headers, data, host, path))
        print("DEBUG: self.cookies=%s" % self.cookies)

        try:
            self._conn.request(method, path, headers=headers)
            if issubclass(data.__class__, upload.Upload):
                for s in data:
                    if pythonver >= 3:
                        if type(s) is str:
                            self._conn.send(bytes(s, 'utf-8'))
                        else:
                            self._conn.send(s)
                    else:
                        self._conn.send(s)
            elif data:
                if pythonver >= 3:
                    self._conn.send(bytearray(data, 'utf-8'))
                else:
                    self._conn.send(data)

            self.last_request = time.time()
            try:
                res = self._conn.getresponse()
            except http_compat.BadStatusLine:
                self._conn.close()
                self._conn.connect()
                self._conn.request(method, path, data, headers)
                res = self._conn.getresponse()
        except socket.error as e:
            self._conn.close()
            raise errors.HTTPError(e)

        if not host in self.cookies:
            self.cookies[host] = CookieJar()
        self.cookies[host].extract_cookies(res)

        print("DEBUG: res=%s, res.status=%s, res.__dict__=%s" % (res, res.status, res.__dict__))

        if res.status >= 300 and res.status <= 399 and auto_redirect:
            res.read()

            location = urlparse_compat.urlparse(res.getheader('Location'))
            if res.status in (302, 303):
                if 'Content-Type' in headers:
                    del headers['Content-Type']
                if 'Content-Length' in headers:
                    del headers['Content-Length']
                method = 'GET'
                data = ''
            old_path = path
            path = location[2]
            if location[4]:
                path = path + '?' + location[4]

            if location[0].lower() != self.scheme_name:
                # This is not a right error message when redirect is not a fully-qualified url, but is e.g. '/login.php?modauthopenid.referrer=http%3A%2F%2Flab.wyss.harvard.edu%2F104%2Fapi.php%3F'
                # In this case, location[0] is simply ''.
                raise errors.HTTPRedirectError('Only HTTP connections are supported' + "self.scheme_name='%s', location[0]='%s', location=%s" % (self.scheme_name, location[0], location), res.getheader('Location'))
                #raise errors.HTTPRedirectError('Only HTTP connections are supported', res.getheader('Location'))

            if self.pool is None:
                if location[1] != host:
                    raise errors.HTTPRedirectError('Redirecting to different hosts not supported', res.getheader('Location'))

                return self.request(method, host, path, headers, data)
            else:
                if host == location[1] and path == old_path:
                    conn = self.__class__(location[1], self.pool)
                    self.pool.append(([location[1]], conn))
                return self.pool.request(method, location[1], path, headers, data, raise_on_not_ok, auto_redirect)

        if res.status != 200 and raise_on_not_ok:
            try:
                raise errors.HTTPStatusError(res.status, res)
            finally:
                res.close()

        return res

    def get(self, host, path, headers=None):
        return self.request('GET', host, path, headers, None)

    def post(self, host, path, headers=None, data=None):
        return self.request('POST', host, path, headers, data)

    def head(self, host, path, headers=None, auto_redirect=False):
        res = self.request('HEAD', host, path, headers, data=None, raise_on_not_ok=False, auto_redirect=auto_redirect)
        res.read()
        return res.status, res.getheaders()

    def close(self):
        self._conn.close()

    def fileno(self):
        return self._conn.sock.fileno()


class HTTPConnection(HTTPPersistentConnection):
    def request(self, method, host, path, headers, data, raise_on_not_ok=True, auto_redirect=True):
        if not headers:
            headers = {}
        headers['Connection'] = 'Close'
        res = HTTPPersistentConnection.request(self, method, host, path, headers, data, raise_on_not_ok, auto_redirect)
        return res


class HTTPSPersistentConnection(HTTPPersistentConnection):
    #Sublime havent socket module compiled with SSL support: use http until will be resolved
    try:
        http_class = http_compat.HTTPSConnection
        scheme_name = 'https'
        if FOR_MEDIAWIKER and sys.platform.startswith('linux'):
            print('Mediawiker: HTTPS is available.')
    except Exception as e:
        print('HTTPS is not available in this python environment, trying http: %s' % e)
        http_class = http_compat.HTTPConnection
        scheme_name = 'http'


class HTTPPool(list):
    """
    List-like class for storing http connections.
    Each element is expected to be a two-tuple of:
        ([<list of hosts>], connection)
    Each element in [<list of hosts>] is two-tuple:
        (scheme, host)
    where scheme is either 'http' or 'https', and
    """

    def __init__(self):
        list.__init__(self)
        self.cookies = {}

    def find_connection(self, host, scheme='http'):
        if type(host) is tuple:
            scheme, host = host

        for hosts, conn in self:
            if (scheme, host) in hosts:
                return conn

        redirected_host = None
        for hosts, conn in self:
            status, headers = conn.head(host, '/')
            if status == 200:
                hosts.append((scheme, host))
                return conn
            if status >= 300 and status <= 399:
                # BROKEN!
                headers = dict(headers)
                location = urlparse_compat.urlparse(headers.get('location', ''))
                if (location[0], location[1]) == (scheme, host):
                    hosts.append((scheme, host))
                    return conn
        if scheme == 'http':
            cls = HTTPPersistentConnection
        elif scheme == 'https':
            cls = HTTPSPersistentConnection
        else:
            raise RuntimeError('Unsupported scheme', scheme)
        conn = cls(host, self)
        self.append(([(scheme, host)], conn))
        return conn

    def get(self, host, path, headers=None):
        return self.find_connection(host).get(host, path, headers)

    def post(self, host, path, headers=None, data=None):
        return self.find_connection(host).post(host, path, headers, data)

    def head(self, host, path, headers=None, auto_redirect=False):
        return self.find_connection(host).head(host, path, headers, auto_redirect)

    def request(self, method, host, path, headers, data, raise_on_not_ok, auto_redirect):
        return self.find_connection(host).request(method, host, path, headers, data, raise_on_not_ok, auto_redirect)

    def close(self):
        for hosts, conn in self:
            conn.close()
