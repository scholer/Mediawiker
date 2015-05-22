#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pylint: disable=invalid-name,line-too-long


import sys
import logging
import sublime

logger = logging.getLogger(__name__)


### Add pyfiglet library to path: ###
# (pyfiglet is used to print big ascii letters and is used by e.g. MediawikerInsertBigTodoTextCommand)
# pwaller's original pyfiglet uses pkg_resources module,
# which is not available in Sublime Text.
# The packaged pyfiglet.zip therefore includes pkg_resources.py.
try:
    # Use up-to-date external library, if available:
    from pyfiglet import Figlet
except ImportError:
    # Use included library:
    PYFIGLET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib', 'pyfiglet.zip')
    sys.path.append(PYFIGLET_PATH)
    try:
        from pyfiglet import Figlet
        print("Imported pyfiglet from local zip library.")
    except ImportError:
        print("Could not import local pyfiglet from zip; big text will not be available.")

# Pyfiglet usage functions. Re-factored out so they can be used elsewhere as well:
def get_figlet_text(text):
    """ Returns a big "ascii art"-like text spelling the words in text. """
    font = 'colossal' # This is case *sensitive* (on *nix and if pyfiglet is zipped).
    try:
        printer = Figlet(font)
    except NameError:
        print("ERROR, could not import pyfiglet, big text not available.")
        print("sys.path=", sys.path)
        return text
    printer.Font.smushMode = 64
    return printer.renderText(text)

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



## Set up logging:
def init_logging(args=None, prefix="Mediawiker"):
    """
    Set up standard logging system:
    Comments include other examples of how to set up logging,
    both a streamhandler (output to console per default) and a filehandler.
    """
    # Examples of different log formats:
    loguserfmt = "%(asctime)s %(levelname)-5s %(name)20s:%(lineno)-4s%(funcName)20s() %(message)s"
    logtimefmt = "%H:%M:%S" # For output to user in console
    # basicConfig only has an effect if no logging system have been set up:
    logging.basicConfig(level=logging.DEBUG, format=loguserfmt, datefmt=logtimefmt)    # filename='example.log',



## Cookie functions

def get_login_cookie_key_and_value(site_name=None, cookie_key=None):
    """ Used to get the name of the cookie used as login cookie. """
    ## TODO: Implement get_login_cookie_key better.
    site_params = get_site_params(site_name)
    try:
        cookies = site_params['cookies']
    except KeyError:
        return None, None
    if not cookies:
        return None, None
    if len(cookies) == 1:
        return next((k, v) for k, v in cookies.items())
    if cookie_key is None:
        if 'login_cookie_name' in site_params:
            cookie_key = site_params['login_cookie_name']
        elif 'open_id_session_id' in cookies:
            cookie_key = 'open_id_session_id'
        else:
            return None, None
    return cookie_key, cookies[cookie_key]


def get_login_cookie(cookie_key='open_id_session_id', site_name=None, default=None):
    """ Get login cookie for active site, or site <site_name> if specified. """
    site_params = get_site_params(site_name)
    try:
        return site_params['cookies'][cookie_key]
    except KeyError:
        return default

def set_login_cookie(value, cookie_key='open_id_session_id', site_name=None):
    """ Set login cookie for active site, or site <site_name> if specified. """
    site_params = get_site_params(site_name)
    site_params['cookies'][cookie_key] = value
    print("Updated site_params:")
    print(site_params)
    # mw.save_settings()
    # sublime.save_settings('Mediawiker.sublime-settings')
    # Above doesn't seem to work, attempting manual:
    # Uhm... what is the settings object exactly? Is it a simple dict or something more stupid?
    # Indeed. It is a sublime.Settings object, which is just a thin wrapper around
    # sublime_api.settings_*(self.settings_id, ...) functions
    settings = sublime.load_settings('Mediawiker.sublime-settings')
    if site_name is None:
        site_name = settings.get('mediawiki_site_active')
    sites = settings.get('mediawiki_site')
    #print("Re-loaded site_params:")
    #print(sites[site_name])    # This was just to prove that the above doesn't work...
    sites[site_name]['cookies'][cookie_key] = value
    settings.set('mediawiki_site', sites)   # Saving the complete 'mediawiki_site' entry, otoh, will persist the change.
    sublime.save_settings('Mediawiker.sublime-settings')

