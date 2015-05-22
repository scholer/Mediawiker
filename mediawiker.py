#!/usr/bin/env python
# -*- coding: utf-8 -*-

# pylint: disable=W0142,C0302,C0301,C0103
# W0142="* or ** magic"
# C0302="Too many lines in module"
## Too many branches, variables and lines in function:
# pylint: disable=R0914,R0912,R0915
## ToDos, missing docstrings:
# pylint: disable=W0511,C0111
# pylintx: disable=W0611   ## Unused imports,
## Unable to import, no __init__, no member, too few lines, method-could-be-function, unused argument, attribute defined outside __init__
# pylint: disable=F0401,E1101,W0232,R0903,R0201,W0613,W0201,R0913

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

References:
# https://github.com/wbond/sublime_package_control/wiki/Sublime-Text-3-Compatible-Packages
# http://www.sublimetext.com/docs/2/api_reference.html
# http://www.sublimetext.com/docs/3/api_reference.html

"""


from __future__ import print_function
import os
import sys
import webbrowser
import re
import sublime
import sublime_plugin
from datetime import date
from functools import partial
import difflib


if sys.version_info[0] >= 3:
    from . import mwclient
    from .mwclient import errors
    from . import mwutils as mw
    try:
        from .lib.cookieshop.chrome_extract import get_chrome_cookies
    except ImportError as exc:
        print("ImportError while importing .lib.cookieshop.chrome_extract module:", exc)
        print("- get_chrome_cookies function will not be available...")
else:
    from mwclient import errors
    import mwutils as mw
    from lib.cookieshop.chrome_extract import get_chrome_cookies

    FileExistsError = WindowsError  # pylint: disable=W0622

# Initialize logging system (only kicks in if not initialized already...)
# mw.init_logging() # Edit: This is re-delegated to sublime_logging plugin...


# Define constants:
CATEGORY_NAMESPACE = 14  # category namespace number
IMAGE_NAMESPACE = 6  # image namespace number
TEMPLATE_NAMESPACE = 10  # template namespace number


# Initialize logging system (only kicks in if not initialized already...)
mw.init_logging()

# Module-level site manager:
sitemgr = mw.SiteconnMgr()



class MediawikerInsertTextCommand(sublime_plugin.TextCommand):

     def run(self, edit, position, text):
         self.view.insert(edit, position, text)


class MediawikerReplaceTextCommand(sublime_plugin.TextCommand):

    def run(self, edit, text):
        self.view.replace(edit, self.view.sel()[0], text)




##### WINDOW COMMANDS #######



class MediawikerTestCmdCommand(sublime_plugin.WindowCommand):
    """
    Used for quick testing inside sublime.
    Command string mediawiker_test_a
    """
    def run(self, action=None, textcommand=True, kwargs=None):
        if True:
            if kwargs is None:
                kwargs = {}
            print("Running test command: '%s'" % action)
            if textcommand:
                self.window.active_view().run_command(action, kwargs)
            else:
                self.window.run_command(action, kwargs)
        else:
            print("Custom test...")


class MediawikerReplaceTextCommand(sublime_plugin.TextCommand):

    def run(self, edit, text):
        self.view.replace(edit, self.view.sel()[0], text)


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

    run_in_new_window = False
    title = None

    def run(self, action, title='', site_active=None, args=None):
        """ Entry point, invoked with action keyword and optionally a pre-defined title. """
        self.action = action
        self.action_args = args
        actions_validate = ['mediawiker_publish_page', 'mediawiker_add_category',
                            'mediawiker_category_list', 'mediawiker_search_string_list',
                            'mediawiker_add_image', 'mediawiker_add_template',
                            'mediawiker_upload']

        if self.action == 'mediawiker_show_page':
            if mw.get_setting('mediawiker_newtab_ongetpage'):
                self.run_in_new_window = True

            panel = mw.InputPanelPageTitle()
            panel.on_done = self.on_done
            panel.get_title(title)

        else:
            if self.action == 'mediawiker_reopen_page':
                self.action = 'mediawiker_show_page'
            title = title if title else mw.get_title()
            self.on_done(title)

    def on_done(self, title):
        if title:
            title = mw.pagename_clear(title)

        self.title = title
        panel_passwd = mw.InputPanelPassword()
        panel_passwd.command_run = self.command_run
        panel_passwd.get_password()

    def command_run(self, password):
        # cases:
        # from view with page, opened from other site_active than in global settings - new page will be from the same site
        # from view with page, open page with another lang site - site param must be defined, will set it
        # from view with undefined site (new) open page by global site_active setting
        if not self.site_active:
            self.site_active = mw.get_view_site()

        if self.run_in_new_window:
            self.window.new_file()
            self.run_in_new_window = False

        self.window.active_view().settings().set('mediawiker_site', self.site_active)
        self.window.active_view().run_command(self.action, {"title": self.title, "password": password})


class MediawikerOpenPageCommand(sublime_plugin.WindowCommand):
    """
    Open a page, using mediawiker_page->mediawiker_validate_connection_params->mediawiker_show_page command chain.
    Command string: mediawiker_open_page (window command).
    """

    def run(self):
        self.window.run_command("mediawiker_page", {"action": "mediawiker_show_page"})


class MediawikerReopenPageCommand(sublime_plugin.WindowCommand):
    """
    Reopen the current views's page (in current view).
    Will overwrite current view's buffer content.
    Command string: mediawiker_reopen_page
    """
    def run(self):
        """
        Yeah, this is kind of a weird one. MediawikerPageCommand will intercept
        'mediawiker_reopen_page' action and use 'mediawiker_show_page' instead (plus some extra stuff to prepare).
        So, no - it is not an infinite loop, although it would seem like it ;-)
        """
        self.window.run_command("mediawiker_page", {"action": "mediawiker_reopen_page"})

class MediawikerAskReopenPageCommand(sublime_plugin.WindowCommand):
    """
    Reopen the current views's page (in current view).
    Will ask for confirmation before invoking the normal reopen page command.
    Command string: mediawiker_ask_reopen_page
    """
    def run(self):
        """ Command entry point. """
        do_reopen = sublime.ok_cancel_dialog("Re-open page? (Note: This will overwrite existing content in current view.)")
        if do_reopen:
            print("Reopening page, do_reopen =", do_reopen)
            self.window.run_command("mediawiker_page", {"action": "mediawiker_reopen_page"})
        else:
            print("Re-open page cancelled, do_reopen =", do_reopen)


class MediawikerPostPageCommand(sublime_plugin.WindowCommand):
    """
    Invoke MediawikerPublishPageCommand (text command) via MediawikerPage->ValidateParams chain.
    Command string: mediawiker_post_page
    """
    def run(self):
        """ Command entry point. """
        self.window.run_command("mediawiker_page", {"action": "mediawiker_publish_page"})


class MediawikerSetCategoryCommand(sublime_plugin.WindowCommand):
    """
    Invoke MediawikerAddCategoryCommand (text command) via MediawikerPage->ValidateParams chain.
    Command string: mediawiker_set_category
    """
    def run(self):
        """ Command entry point. """
        self.window.run_command("mediawiker_page", {"action": "mediawiker_add_category"})


class MediawikerInsertImageCommand(sublime_plugin.WindowCommand):
    """
    Invoke MediawikerAddImageCommand (text command) via MediawikerPage->ValidateParams chain.
    Command string: mediawiker_insert_image
    """
    def run(self):
        """ Command entry point. """
        self.window.run_command("mediawiker_page", {"action": "mediawiker_add_image"})


class MediawikerInsertTemplateCommand(sublime_plugin.WindowCommand):
    """
    Invoke MediawikerAddTemplateCommand (text command) via MediawikerPage->ValidateParams chain.
    Command string: mediawiker_insert_template
    """
    def run(self):
        """ Command entry point. """
        self.window.run_command("mediawiker_page", {"action": "mediawiker_add_template"})


class MediawikerFileUploadCommand(sublime_plugin.WindowCommand):
    """
    Alias to Upload TextCommand.
    Command string: mediawiker_file_upload
    """
    def run(self):
        """ Command entry point. """
        self.window.run_command("mediawiker_page", {"action": "mediawiker_upload"})


class MediawikerUpdateFileCommand(sublime_plugin.WindowCommand):
    """
    Command string: mediawiker_file_upload
    Invokes Upload TextCommand with ignorewarnings=True parameter, via the usual
    MediawikerPageCommand+MediawikerValidateConnectionParamsCommand chain.
    """
    def run(self):
        """ Command entry point. """
        self.window.run_command("mediawiker_page",
                                {"action": "mediawiker_upload", "args": {"ignorewarnings": True}})


class MediawikerCategoryTreeCommand(sublime_plugin.WindowCommand):
    """
    Invoke MediawikerCategoryListCommand (text command) via MediawikerPage->ValidateParams chain.
    Command string: mediawiker_category_tree
    """
    def run(self):
        """ Command entry point. """
        self.window.run_command("mediawiker_page", {"action": "mediawiker_category_list"})


class MediawikerSearchStringCommand(sublime_plugin.WindowCommand):
    """
    Invoke MediawikerSearchStringListCommand (text command) via MediawikerPage->ValidateParams chain.
    Command string: mediawiker_search_string
    """
    def run(self):
        """ Command entry point. """
        self.window.run_command("mediawiker_page", {"action": "mediawiker_search_string_list"})


class MediawikerPageListCommand(sublime_plugin.WindowCommand):
    """ Display a panel to the user with recent pages for the active site. Command string: mediawiker_page_list"""

    def run(self, storage_name='mediawiker_pagelist'):
        # site_name_active = mw.get_setting('mediawiki_site_active')
        site_name_active = mw.get_view_site()
        mediawiker_pagelist = mw.get_setting(storage_name, {})
        self.my_pages = mediawiker_pagelist.get(site_name_active, [])
        if self.my_pages:
            self.my_pages.reverse()
            # error 'Quick panel unavailable' fix with timeout..
            sublime.set_timeout(lambda: self.window.show_quick_panel(self.my_pages, self.on_done), 1)
        else:
            sublime.status_message('List of pages for wiki "%s" is empty.' % (site_name_active))

    def on_done(self, index):
        """ Invoked when the page (index) has been selected. """
        if index >= 0:
            # escape from quick panel return -1
            title = self.my_pages[index]
            try:
                self.window.run_command("mediawiker_page", {"title": title, "action": "mediawiker_show_page"})
            except ValueError as e:
                sublime.message_dialog(e)


class MediawikerEditPanelCommand(sublime_plugin.WindowCommand):
    """
    Displays a quick panel with available snippets and inserts the selected.
    """
    options = []
    SNIPPET_CHAR = u'\u24C8'

    def run(self):
        self.SNIPPET_CHAR = mw.get_setting('mediawiker_snippet_char')
        self.options = mw.get_setting('mediawiker_panel', {})
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
        #self.exp_basedir = mw.get_setting('mediawiker_experiments_basedir')
        #self.save_page_in_exp_folder = mw.get_setting('mediawiker_experiments_save_page_in_exp_folder', False)
        # How to format the folder, e.g. "{expid} {exp_titledesc}"
        #self.exp_foldername_fmt = mw.get_setting('mediawiker_experiments_foldername_fmt')
        # Experiments overview page: Manually lists (and links) to all experiments.
        #self.experiments_overview_page = mw.get_setting('mediawiker_experiments_overview_page')
        #self.experiment_overview_link_format = mw.get_setting('mediawiker_experiments_overview_link_fmt', "\n* [[{}]]")
        #self.template = mw.get_setting('mediawiker_experiments_template')
        # Constant args to feed to the template (Mostly for shared templates).
        #self.template_kwargs = mw.get_setting('mediawiker_experiments_template_kwargs', {})
        # title format, e.g. "MyExperiments/{expid} {exp_titledesc}". If not set, no new buffer is created.
        #self.title_fmt = mw.get_setting('mediawiker_experiments_title_fmt')
        # Which substitution mode to use:
        # "python-format" = template.format(**kwargs), "python-%" = template % kwargs, "mediawiki" = substitute_template_params(template, kwargs)
        #self.template_subst_mode = mw.get_setting('mediawiker_experiments_template_subst_mode')
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

        # Non-attribute settings:
        startdate = date.today().isoformat()    # datetime.now()
        exp_basedir = mw.get_setting('mediawiker_experiments_basedir')
        experiments_overview_page = mw.get_setting('mediawiker_experiments_overview_page')
        title_fmt = mw.get_setting('mediawiker_experiments_title_fmt')
        template = mw.get_setting('mediawiker_experiments_template')
        template_subst_mode = mw.get_setting('mediawiker_experiments_template_subst_mode')
        save_page_in_exp_folder = mw.get_setting('mediawiker_experiments_save_page_in_exp_folder', False)
        template_kwargs = mw.get_setting('mediawiker_experiments_template_kwargs', {})

        if not any((self.expid, self.exp_titledesc)):
            # If both expid and exp_title are empty, just abort:
            print("expid and exp_titledesc are both empty, aborting...")
            return

        ## 1. Make experiment folder, if appropriate: ##
        # If exp_foldername_fmt is not specified, use title_fmt (remove any '/' and whatever is before it)?
        foldername_fmt = mw.get_setting('mediawiker_experiments_foldername_fmt', (title_fmt or '').split('/')[-1])
        if exp_basedir and foldername_fmt:
            if os.path.isdir(exp_basedir):
                foldername = foldername_fmt.format(expid=self.expid, exp_titledesc=self.exp_titledesc)
                folderpath = os.path.join(exp_basedir, foldername)
                try:
                    os.mkdir(folderpath)
                    msg = "Created new experiment directory: %s" % (folderpath,)
                except FileExistsError:
                    msg = "New exp directory already exists: %s" % (folderpath,)
                except (WindowsError, OSError, IOError) as e:
                    msg = "Error creating new exp directory '%s' :: %s" % (folderpath, repr(e))
            else:
                # We are not creating a new folder for the experiment because basedir doesn't exists:
                msg = "Specified experiment base dir does not exists: %s" % (exp_basedir,)
                foldername = folderpath = None
            print(msg)
            sublime.status_message(msg)

        ## 2. Make new view, if title_fmt is specified: ##
        if title_fmt:
            self.pagetitle = title_fmt.format(expid=self.expid, exp_titledesc=self.exp_titledesc)
            self.view = exp_view = sublime.active_window().new_file() # Make a new file/buffer/view
            self.window.focus_view(exp_view) # exp_view is now the window's active_view
            filename = mw.strquote(self.pagetitle)
            view_default_dir = folderpath if save_page_in_exp_folder and folderpath \
                                          else mw.get_setting('mediawiker_file_rootdir')
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
            exp_figlet_comment = mw.get_figlet_text(self.bigcomment) # Makes the big figlet text
            self.exp_buffer_text += mw.adjust_figlet_comment(exp_figlet_comment, foldername or self.bigcomment) # Adjusts the figlet to produce a comment

        ## 4. Generate template : ##
        if template:
            # Load the template: #
            if os.path.isfile(template):
                # User specified a local file:
                print("Using template:", template)
                with open(template) as fd:
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
            template_kwargs.update({'expid': self.expid, 'exp_titledesc': self.exp_titledesc, 'startdate': startdate, 'date': startdate})
            if template_subst_mode == 'python-fmt':
                # template_kwargs must be dict/mapping: (template_args_order no longer supported)
                template_content = template_content.format(**template_kwargs)
            elif template_subst_mode == 'python-%':
                # "%s" string interpolation: template_vars must be tuple or dict (both will work):
                template_content = template_content % template_kwargs
            elif template_subst_mode in ('mediawiki', 'wiki', None) or True: # This is currently the default. Allows me to use wiki templates as local templates.
                # Use custom wiki template variable insertion function:
                # Get template args (defaults)  -- edit: I just use keep_unmatched=True.
                #template_params = get_template_params_dict(template_content, defaultvalue='')
                #print("Parameters in template:", template_params)
                #template_params.update(template_kwargs)
                template_content = mw.substitute_template_params(template_content, template_kwargs, keep_unmatched=True)

            # Add template to buffer text string:
            self.exp_buffer_text = "".join(text.strip() for text in (self.exp_buffer_text, template_content))

        else:
            print('No template specified (settings key "mediawiker_experiments_template").')


        ## 6. Append self.exp_buffer_text to the view: ##
        exp_view.run_command('mediawiker_insert_text', {'position': exp_view.size(), 'text': self.exp_buffer_text})

        ## 7. Add a link to experiments_overview_page (local file): ##
        if experiments_overview_page:
            # Generate a link to this experiment:
            link_fmt = mw.get_setting('mediawiker_experiments_overview_link_fmt', "\n* [[{}]]")
            if self.pagetitle:
                link_text = link_fmt.format(self.pagetitle)
            else:
                # Add a link to the current buffer's title, assuming the experiment header is the same as foldername
                link = "{}#{}".format(mw.get_title(), foldername.replace(' ', '_'))
                link_text = link_fmt.format(link)

            # Insert link on experiments_overview_page. Currently, this must be a local file.
            # (We just edit the file on disk and let ST pick up the change if the file is opened in any view.)
            if os.path.isfile(experiments_overview_page):
                print("Adding link '%s' to file '%s'" % (link_text, experiments_overview_page))
                # We have a local file, append link:
                with open(experiments_overview_page, 'a') as fd:
                    # In python3, there is a bigger difference between binary 'b' mode and normal (text) mode.
                    # Do not open in binary 'b' mode when writing/appending strings. It is not supported in python 3.
                    # If you want to write strings to files opened in binary mode, you have to cast the string to bytes / encode it:
                    # >>> fd.write(bytes(mystring, 'UTF-8')) *or* fd.write(mystring.encode('UTF-8'))
                    fd.write(link_text) # The format should include newline if desired.
                print("Appended %s chars to file '%s" % (len(link_text), experiments_overview_page))
            else:
                # User probably specified a page on the wiki. (This is not yet supported.)
                # Even if this is a page on the wiki, you should check whether that page is already opened in Sublime.
                ## TODO: Implement specifying experiments_overview_page from server.
                print("Using experiment_overview_page from the server is not yet supported.")

        print("MediawikerNewExperimentCommand completed!\n")


class MediawikerFavoritesAddCommand(sublime_plugin.WindowCommand):
    """ Add current page to the favorites list. Command string: mediawiker_favorites_add  (WindowCommand) """
    def run(self):
        title = mw.get_title()
        mw.save_mypages(title=title, storage_name='mediawiker_favorites')


class MediawikerFavoritesOpenCommand(sublime_plugin.WindowCommand):
    """
    Open page from the favorites list.
    Command string: mediawiker_favorites_open (WindowCommand)
    """
    def run(self):
        self.window.run_command("mediawiker_page_list", {"storage_name": 'mediawiker_favorites'})


class MediawikerSetLoginCookie(sublime_plugin.WindowCommand):
    """
    Set login cookie.
    Command string: mediawiker_set_login_cookie (WindowCommand)
    """
    def run(self, new_cookie=None):
        if new_cookie is None:
            new_cookie = mw.get_login_cookie(default='')
        # show_input_panel(caption, initial_text, on_done, on_change, on_cancel)
        self.window.show_input_panel('Set login cookie:', new_cookie, self.on_done, None, None)
    def on_done(self, new_cookie):
        if not new_cookie:
            msg = "No cookie input..."
        else:
            mw.set_login_cookie(new_cookie)
            msg = "Login cookie set :)"
        print(msg)
        sublime.status_message(msg)


class MediawikerExtractChromeLoginCookie(sublime_plugin.WindowCommand):
    """
    Extract login cookie from chrome's cookie database.
    Command string: mediawiker_extract_chrome_login_cookie (WindowCommand)
    argument <user_confirm> toggles whether the user is prompted with
    the updated cookie before it is updated in site_params.
    """
    def run(self, user_confirm=True):
        cookie_key, current_cookie = mw.get_login_cookie_key_and_value()
        msg = None
        if cookie_key is None:
            msg = "No login cookie defined in site params, aborting!"
            print(msg)
            sublime.status_message(msg)
            return
        site_params = mw.get_site_params()
        chrome_cookies = get_chrome_cookies(url=site_params['host'])
        if not chrome_cookies or cookie_key not in chrome_cookies:
            if not chrome_cookies:
                msg = "No cookies for domain %s could be obtained from Chrome, aborting!" % site_params['host']
            else:
                msg = "%s cookies found for domain %s, but none with key '%s', aborting!" % \
                      (len(chrome_cookies), site_params['host'], cookie_key)
            print(msg)
            sublime.status_message(msg)
            return
        # show_input_panel(caption, initial_text, on_done, on_change, on_cancel)
        new_cookie = chrome_cookies[cookie_key]
        if new_cookie == current_cookie:
            msg = "Login cookie already matches Chrome's login cookie!"
            print(msg)
            sublime.status_message(msg)
            return
        if user_confirm:
            self.window.run_command('mediawiker_set_login_cookie', {'new_cookie': new_cookie})
        else:
            mw.set_login_cookie(new_cookie)


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
        on_save_action = mw.get_setting('mediawiker_on_save_action')
        # on_save_action can be a string or list, specifying what actions to take:
        if 'savefile' in on_save_action:
            # How do you save the view buffer?
            pass
        if 'publish' in on_save_action:
            self.window.run_command("mediawiker_page", {"action": "mediawiker_publish_page"})



class MediawikerPageDiffVsServerCommand(sublime_plugin.WindowCommand):
    """
    command string: mediawiker_page_diff_vs_server
    Page diff vs server revision
    Display the difference between current buffer and the most recent version on the server.
    Inspired by:
    * https://github.com/sabhiram/sublime-clipboard-diff
    * https://github.com/colinta/SublimeFileDiffs
    * https://github.com/zsong/diffy
    * https://github.com/colinta/SublimeFileDiffs
    """
    def run(self):
        current_view = self.window.active_view()
        if not current_view:
            print("No active view, cannot diff...")
            return
        title = mw.get_title()
        view_text = current_view.substr(sublime.Region(0, current_view.size()))
        print("view_text len: ", len(view_text))
        diff_view = self.window.new_file()
        diff_view.set_scratch(True)     # Scratch buffers will never report as dirty.
        diff_title = "diff: " + title
        diff_view.set_name(diff_title)
        # The rest must be run in with a TextCommand to get an edit token...
        # OTOH: You can just run mediawiker_insert_text at the end when you have calculated your diff...
        #diff_view.run_command('mediawiker_page_diff_latest', {'title': diff_title, 'password': None, 'old_text': old_text)
        # If you want to split out to separate text command, it should be so that you can run it through
        # the MediawikerPageCommand->MediawikerValidateConnectionParamsCommand command chain...
        try:
            sitecon = mw.get_connect(password=None)
        except (mwclient.HTTPRedirectError, errors.HTTPRedirectError) as exc:
            msg = 'Connection to server failed. If you are logging in with an open_id session cookie, it may have expired.\n-- %s' % exc
            sublime.status_message(msg)
            return
        _, text = mw.get_page_text(sitecon, title)
        print("server page text len: ", len(text))
        if not text:
            # Uh, well, what if it does exist, but it is empty?
            msg = 'Wiki page %s does not exists.' % (title,)
            sublime.status_message(msg)
            diff_text = '<!-- %s -->' % msg
        else:
            new_lines = [l+"\n" for l in view_text.split("\n")]
            old_lines = [l+"\n" for l in text.split("\n")]
            print("new vs old number of lines: %s vs %s" % (len(new_lines), len(old_lines)))
            diff_lines = difflib.unified_diff(old_lines, new_lines, fromfile="Server revision", tofile="Buffer view")
            diff_text = "".join(diff_lines)
            print("len diff_text: %s" % (len(diff_text), ))
            if not diff_text:
                print("Diff text: ", diff_text)
                diff_text = "<<< No change between files... >>>"
            else:
                diff_view.set_syntax_file("Packages/Diff/Diff.tmLanguage")
        diff_view.run_command('mediawiker_insert_text', {'text': diff_text})




class MediawikerPageDiffLatestCommand(sublime_plugin.TextCommand):
    """
    Command string: mediawiker_page_diff_latest
    """
    def run(self, edit, title, password):
        pass





######### TEXT COMMANDS ###############

######## ######## ##     ## ########     ######  ##     ## ########   ######
   ##    ##        ##   ##     ##       ##    ## ###   ### ##     ## ##    ##
   ##    ##         ## ##      ##       ##       #### #### ##     ## ##
   ##    ######      ###       ##       ##       ## ### ## ##     ##  ######
   ##    ##         ## ##      ##       ##       ##     ## ##     ##       ##
   ##    ##        ##   ##     ##       ##    ## ##     ## ##     ## ##    ##
   ##    ######## ##     ##    ##        ######  ##     ## ########   ######



class MediawikerInsertTextCommand(sublime_plugin.TextCommand):
    """
    Command string: mediawiker_insert_text
    When run, insert text at position in the view.
    If position is None, insert at current position.
    Other commonly-used shortcuts are:
        cursor_position = self.view.sel()[0].begin()
        end_of_file = self.view.size()
        start_of_file = 0
    """
    def run(self, edit, position=None, text=''):
        """ TextCommand entry point, edit token is provided by Sublime. """
        if position is None:
            # Note: Probably better to use built-in command, "insert":
            # { "keys": ["enter"], "command": "insert", "args": {"characters": "\n"} }
            position = self.view.sel()[0].begin()
            #position = self.view.size()
        self.view.insert(edit, position, text)
        print("Inserted %s chars at pos %s" % (len(text), position))



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
        try:
            sitecon = mw.get_connect(password)
        except (mwclient.HTTPRedirectError, errors.HTTPRedirectError) as exc:
            msg = 'Connection to server failed. If you are logging in with an open_id session cookie, it may have expired.'
            sublime.status_message(msg)
            print(msg + "; Error:", exc)
            return
        is_writable, text = mw.get_page_text(sitecon, title)
        self.view.set_syntax_file('Packages/Mediawiker/Mediawiki.tmLanguage')
        self.view.settings().set('mediawiker_is_here', True)
        self.view.settings().set('mediawiker_wiki_instead_editor', mw.get_setting('mediawiker_wiki_instead_editor'))
        self.view.set_name(title)

        if is_writable:
            if not text:
                sublime.status_message('Wiki page %s does not exists. You can create new..' % (title))
                text = '<!-- New wiki page: Remove this with text of the new page -->'
            # insert text
            self.view.erase(edit, sublime.Region(0, self.view.size()))
            if mw.get_setting('mediawiker_title_to_filename', True):
                # If mediawiker_title_to_filename is specified, the title is cast to a
                # "filesystem friendly" alternative by quoting. When posting, this is converted
                # back to the original title.
                filename = mw.get_filename(title)
                print("mw.get_filename('%s') returned '%s' -- using this to set the name." % (title, filename))
                # I like to have a default directory where I store my mediawiki pages.
                # I use the settings key 'mediawiker_file_rootdir' to specify this directory,
                # which is prefixed to the file, if specified:
                # (should possibly be specified on a per-wiki basis.)
                # I then use the view's default_dir setting to change to this dir:
                # There are also some considerations for pages with '/' in the title,
                # this can either be quoted or we can place the file in a sub-directory.
                if mw.get_setting('mediawiker_file_rootdir', None):
                    # If mediawiker_file_rootdir is set, then filename is a path with rootdir
                    # Update the view's working dir to reflect this:
                    self.view.settings().set('default_dir', os.path.dirname(filename))
                    self.view.set_name(os.path.basename(filename))
                else:
                    self.view.set_name(filename)
            #self.view._wikipage_title = title # Save this.
            self.view.run_command('mediawiker_insert_text', {'position': 0, 'text': text})
        sublime.status_message('Page %s was opened successfully from %s.' % (title, mw.get_view_site()))
        self.view.set_scratch(True)
        # own is_changed flag instead of is_dirty for possib. to reset..
        self.view.settings().set('is_changed', False)


class MediawikerPublishPageCommand(sublime_plugin.TextCommand):
    my_pages = None
    page = None
    title = ''
    current_text = ''

    def run(self, edit, title, password):
        is_skip_summary = mw.get_setting('mediawiker_skip_summary', False)
        sitecon = mw.get_connect(password)
        self.title = mw.get_title()
        if self.title:
            self.page = sitecon.Pages[self.title]
            if self.page.can('edit'):
                self.current_text = self.view.substr(sublime.Region(0, self.view.size()))
                if not is_skip_summary:
                    # summary_message = 'Changes summary (%s):' % mw.get_setting('mediawiki_site_active')
                    summary_message = 'Changes summary (%s):' % mw.get_view_site()
                    self.view.window().show_input_panel(summary_message, '', self.on_done, None, None)
                else:
                    self.on_done('')
            else:
                sublime.status_message('You have not rights to edit this page')
        else:
            sublime.status_message('Can\'t publish page with empty title')
            return

    def on_done(self, summary):
        summary = '%s%s' % (summary, mw.get_setting('mediawiker_summary_postfix', ' (by SublimeText.Mediawiker)'))
        mark_as_minor = mw.get_setting('mediawiker_mark_as_minor')
        try:
            if self.page.can('edit'):
                # invert minor settings command '!'
                if summary[0] == '!':
                    mark_as_minor = not mark_as_minor
                    summary = summary[1:]
                self.page.save(self.current_text, summary=summary.strip(), minor=mark_as_minor)
                self.view.set_scratch(True)
                self.view.settings().set('is_changed', False)  # reset is_changed flag
                sublime.status_message('Wiki page %s was successfully published to wiki.' % (self.title))
                mw.save_mypages(self.title)
            else:
                sublime.status_message('You have not rights to edit this page')
        except errors.EditError as e:
            sublime.status_message('Can\'t publish page %s (%s)' % (self.title, e))


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
        self.items = [mw.strunquote(self.get_header(x)) for x in self.regions]
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
            url = mw.get_page_url(self.items[self.selected])
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
        link_url = mw.strunquote(header.group(1))
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
            level = mw.get_hlevel(header_text, "=")
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
    site_on = '> '
    site_off = ' ' * 4
    site_active = ''

    def run(self):
        # self.site_active = mw.get_setting('mediawiki_site_active')
        self.site_active = mw.get_view_site()
        sites = mw.get_setting('mediawiki_site')
        # self.site_keys = map(self.is_checked, list(sites.keys()))
        self.site_keys = [self.is_checked(x) for x in sites.keys()]
        sublime.set_timeout(lambda: self.window.show_quick_panel(self.site_keys, self.on_done), 1)

    def is_checked(self, site_key):
        checked = self.site_on if site_key == self.site_active else self.site_off
        return '%s%s' % (checked, site_key)

    def on_done(self, index):
        # not escaped
        if index >= 0:
            site_active = self.site_keys[index].strip()
            if site_active.startswith(self.site_on):
                site_active = site_active[len(self.site_on):]
            # force to set site_active in global and in view settings
            current_syntax = self.window.active_view().settings().get('syntax')
            if current_syntax is not None and current_syntax.endswith('Mediawiker/Mediawiki.tmLanguage'):
                self.window.active_view().settings().set('mediawiker_site', site_active)
            mw.set_setting("mediawiki_site_active", site_active)


class MediawikerOpenPageInBrowserCommand(sublime_plugin.WindowCommand):
    def run(self):
        url = mw.get_page_url()
        if url:
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
        self.sitecon = mw.get_connect(password)
        self.category_root = mw.get_category(mw.get_setting('mediawiker_category_root'))[1]
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
        self.delimiter = mw.get_setting('mediawiker_csvtable_delimiter', '|')
        table_header = '{|'
        table_footer = '|}'
        table_properties = ' '.join(['%s="%s"' % (prop, value) for prop, value in mw.get_setting('mediawiker_wikitable_properties', {}).items()])
        cell_properties = ' '.join(['%s="%s"' % (prop, value) for prop, value in mw.get_setting('mediawiker_wikitable_cell_properties', {}).items()])
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



class MediawikerTableWikiToSimpleCommand(sublime_plugin.TextCommand):
    ''' convert selected (or under cursor) wiki table to Simple table (TableEdit plugin). Command string: mediawiker_table_wiki_to_simple '''

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
            # Note: Sublime Text 3 commands are run "outside" the current scope. Trying to catch anything is mute.
            self.view.run_command('table_editor_enable_for_current_view', {'prop': 'enable_table_editor'})

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
        table_properties = ' '.join(['%s="%s"' % (prop, value) for prop, value in mw.get_setting('mediawiker_wikitable_properties', {}).items()])

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
        cell_properties = ' '.join(['%s="%s"' % (prop, value) for prop, value in mw.get_setting('mediawiker_wikitable_cell_properties', {}).items()])
        cell_properties = '%s | ' % cell_properties if cell_properties else ''
        try:
            return delimiter.join(' %s%s ' % (cell_properties, cell['cell_data'].strip()) for cell in rowlist)
        except (ValueError, KeyError) as e:
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
            category_root = mw.get_category(self.get_category_current())[1]
        else:
            category_root = mw.get_category(mw.get_setting('mediawiker_category_root'))[1]
        sublime.active_window().show_input_panel('Wiki root category:', category_root, self.show_list, None, None)

    def show_list(self, category_root):
        if not category_root:
            return
        self.pages = {}
        self.pages_names = []

        category_root = mw.get_category(category_root)[1]

        if not self.category_path:
            self.update_category_path('%s:%s' % (self.get_category_prefix(), category_root))

        if len(self.category_path) > 1:
            self.add_page(self.get_category_prev(), CATEGORY_NAMESPACE, False)

        for page in self.get_list_data(category_root):
            if page.namespace == CATEGORY_NAMESPACE and not self.category_prefix:
                self.category_prefix = mw.get_category(page.name)[0]
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
        sitecon = mw.get_connect(self.password)
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
        search_pre = ''
        selection = self.view.sel()
        search_pre = self.view.substr(selection[0]).strip()
        sublime.active_window().show_input_panel('Wiki search:', search_pre, self.show_results, None, None)

    def show_results(self, search_value=''):
        # TODO: paging?
        self.pages_names = []
        self.search_limit = mw.get_setting('mediawiker_search_results_count')
        if search_value:
            self.search_result = self.do_search(search_value)
        if self.search_result:
            for _ in range(self.search_limit):
                try:
                    page_data = self.search_result.next()
                    self.pages_names.append([page_data['title'], page_data['snippet']])
                except (ValueError, KeyError) as e:
                    print("Exception during search_result generation:", repr(e))
            te = ''
            search_number = 1
            for pa in self.pages_names:
                te += '### %s. %s\n* [%s](%s)\n\n%s\n' % (search_number, pa[0], pa[0], mw.get_page_url(pa[0]), self.antispan(pa[1]))
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
        sitecon = mw.get_connect(self.password)
        namespace = mw.get_setting('mediawiker_search_namespaces')
        return sitecon.search(search=string_value, what='text', limit=self.search_limit, namespace=namespace)


class MediawikerAddImageCommand(sublime_plugin.TextCommand):
    password = ''
    image_prefix_min_lenght = 4
    images_names = []

    def run(self, edit, password, title=''):
        self.password = password
        self.image_prefix_min_lenght = mw.get_setting('mediawiker_image_prefix_min_length', 4)
        sublime.active_window().show_input_panel('Wiki image prefix (min %s):' % self.image_prefix_min_lenght, '', self.show_list, None, None)

    def show_list(self, image_prefix):
        if len(image_prefix) >= self.image_prefix_min_lenght:
            sitecon = mw.get_connect(self.password)
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
        self.sitecon = mw.get_connect(self.password)
        templates = self.sitecon.allpages(prefix=image_prefix, namespace=TEMPLATE_NAMESPACE)  # images list by prefix
        for template in templates:
            self.templates_names.append(template.page_title)
        sublime.set_timeout(lambda: sublime.active_window().show_quick_panel(self.templates_names, self.on_done), 1)

    def on_done(self, idx):
        if idx >= 0:
            template = self.sitecon.Pages['Template:%s' % self.templates_names[idx]]
            text = template.edit()
            params_text = mw.get_template_params_str(text)
            index_of_cursor = self.view.sel()[0].begin()
            # Create "{{myTemplate:}}
            template_text = '{{%s%s}}' % (self.templates_names[idx], params_text)
            self.view.run_command('mediawiker_insert_text', {'position': index_of_cursor, 'text': template_text})



class MediawikerUploadCommand(sublime_plugin.TextCommand):
    """
    Command string: mediawiker_upload
    Uploads a single file, prompts the user for (1) filepath, (2) destination filename and (3) description.
    Arguments:
        password:       User password (if required).
        title:          Not used (placeholder required for the whole MediawikerPageCommand+MediawikerValidateConnectionParamsCommand)
        ignorewarnings: Add "ignorewarnings"=true parameter to the query (required to upload a
                        new/updated version of an existing image.)
                        (NOT IMPLEMENTED YET).
    """

    password = None
    file_path = None
    file_destname = None
    file_descr = None

    def run(self, edit, password, title='', ignorewarnings=False):
        self.password = password
        self.ignorewarnings = ignorewarnings
        if ignorewarnings or True:
            print("MediawikerUploadCommand: Using ignorewarnings =", ignorewarnings)
        sublime.active_window().show_input_panel('File path:', '', self.get_destfilename, None, None)

    def get_destfilename(self, file_path):
        file_path = file_path.strip('"')    # Strip leading and trailing quotation marks
        if file_path:
            self.file_path = file_path
            file_destname = os.path.basename(file_path)
            sublime.active_window().show_input_panel('Destination file name [%s]:' % (file_destname), file_destname, self.get_filedescr, None, None)

    def get_filedescr(self, file_destname):
        if not file_destname:
            file_destname = os.path.basename(self.file_path)
        self.file_destname = file_destname
        sublime.active_window().show_input_panel('File description:', '', self.on_done, None, None)

    def on_done(self, file_descr=''):
        sitecon = mw.get_connect(self.password)
        if file_descr:
            self.file_descr = file_descr
        else:
            self.file_descr = '%s as %s' % (os.path.basename(self.file_path), self.file_destname)
        try:
            with open(self.file_path, 'rb') as f:
                sitecon.upload(f, self.file_destname, self.file_descr, ignore=self.ignorewarnings)
            sublime.status_message('File %s successfully uploaded to wiki as %s' % (self.file_path, self.file_destname))
        except IOError as e:
            sublime.message_dialog('Upload io error: %s' % e)
            return
        except ValueError as e:
            # This might happen in predata['token'] = image.get_token('edit'), if e.g. title is invalid.
            sublime.message_dialog('Upload error, invalid destination file name/title:\n %s' % e)
            return
        link_text = '[[File:%(destname)s]]' % {'destname': self.file_destname}
        self.view.run_command('mediawiker_insert_text', {'position': None, 'text': link_text})



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
        # Also stripping leading and trailing quotation marks:
        files = [[field.strip("\"' \t") for field in line.split(fieldsep)] for line in lines]
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

        #sitecon = mw.get_connect(self.password)
        # dict used to change how images are inserted.
        image_link_options = {'caption': '', 'options': '', 'filedescription_as_caption': False,
                              'image_extensions': '.jpg,.jpeg,.bpm,.png,.gif,.svg,.tif,.tiff',
                              'link_fmt': '\n[[File:%(destname)s|%(options)s|%(caption)s]]\n',
                              'file_link_fmt': '[[File:%(destname)s]]'}
        image_link_options.update(mw.get_setting('mediawiker_insert_image_options', {}))
        # Update with options from first line of view:
        if view_image_link_options:
            image_link_options.update(view_image_link_options)
        # http://www.mediawiki.org/wiki/Help:Images
        # If semantic mediawiki is used, the user might want to chage the link format to:
        # [[Has image::File:%(destname)s|%(options)s|%(caption)s]]
        link_fmt = image_link_options.pop('link_fmt')
        filedescription_as_caption = image_link_options.pop('filedescription_as_caption')

        self.appendText("\n\nUploading %s files...:\n(Each line is interpreted as: filepath, destname, filedesc, link_options, link_caption\n" % len(self.files))

        for row in self.files:
            filepath = row[0]
            destname = row[1] if len(row) > 1 and row[1] else os.path.basename(filepath)
            filedesc = row[2] if len(row) > 2 else '%s as %s' % (os.path.basename(filepath), destname)
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

            print("Queued %s for upload" % os.path.basename(filepath))
            # In Sublime Text 3, set_timeout_async is thread safe, so using cached sitemgr shouldn't be an issue.
            sublime.set_timeout_async(partial(self.uploadafile, filepath, destname, filedesc, link_fmt, file_image_link_options), 0)


    def uploadafile(self, filepath, destname, filedesc, link_fmt, file_image_link_options): #**kwargs):
        """
        I can't get this to work:
            sublime.set_timeout_async(partial(self.view.run_command, 'mediawiker_upload_a_file', kwargs), 0)
        so I wrap it with this method.
        kwargs must include:
        """
        kwargs = {'filepath': filepath, 'destname': destname, 'filedesc': filedesc, 'link_fmt': link_fmt,
                  #'sitecon': sitecon,
                  #'sitecon': None,
                  'file_image_link_options': file_image_link_options}
        print("kwargs: %s" % (kwargs, ))
        # sublime's run_command only takes python native data types; you cannot include e.g. a sitecon object :-\
        self.view.run_command('mediawiker_upload_single_file', kwargs)
        #self.view.run_command('mediawiker_insert_text', {'position': None, 'text': destname+'\n'})


class MediawikerUploadSingleFileCommand(sublime_plugin.TextCommand):
    """
    mediawiker_upload_single_file
    Upload a single file.
    Meant to be run as part of batch upload with set_timeout_async,
    so the UI does not become unresponsive.

    Oh, by the way, if you ever have a "TypeError: Value required" when invoking
    run_command(...) - make sure that the command you are running have the *Command
    ending and are otherwise correctly named and invokable.
    OH, also -- it seems you can only pass "simple" values to commands - lists/dicts with text,
    numbers and so on. Trying to pass e.g. a "sitecon" mwclient Site connection object
    will raise the error above. Sigh.

    Parameters:
        ignorewarnings: Add "ignorewarnings"=true parameter to the query (required to upload a
                        new/updated version of an existing image.)
                        (NOT IMPLEMENTED YET).
    """

    def appendText(self, text, edit=None):
        """
        Convenience appendText method.
        We can use this instead of invoking mediawiker_insert_text command only because,
        we do not have any user input and thus do not rely on any callbacks.
        (I.e. the command's run() has not returned).
        """
        if edit is None:
            edit = self.edit
        self.view.insert(edit, self.view.size(), text)


    def run(self, edit, filepath, destname, filedesc, link_fmt, file_image_link_options, ignorewarnings=False):
        """ Main run """
        self.edit = edit
        sitecon = sitemgr.Siteconn
        print("mediawiker_upload_single_file run invoked with edit: %s and destname '%s'" % (edit, destname))
        #return
        try:
            with open(filepath, 'rb') as f:
                print("\nAttempting to upload file %s to destination '%s' (description: '%s')...\n" % (filepath, destname, filedesc))
                upload_info = sitecon.upload(f, destname, filedesc, ignore=ignorewarnings)
                print("MediawikerUploadSingleFileCommand(): upload_info:", upload_info)
            if 'warnings' in upload_info:
                msg = "Warnings while uploading file '%s': %s \nIt is likely that this file has not been properly uploaded." % (destname, upload_info.get('warnings'))
            else:
                msg = 'File %s successfully uploaded to wiki as %s' % (filepath, destname)
            sublime.status_message(msg)
            print(msg)
            image_link = link_fmt % file_image_link_options
            print("Link:", image_link)
            self.appendText(image_link+'\n')
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
        #except Exception as e:
        #    # Does this include login/login-cookie errors?
        #    # Should I break the for-loop in this case?
        #    print("UPLOAD ERROR:", repr(e))
        #    #import traceback
        #    #traceback.print_exc()
        #    sublime.message_dialog('Upload error: %s' % e)
        #    msg = "\n--- Other EXCEPTION '%s' while uploading file %s to destination '%s'" % (repr(e), filepath, destname)
        #    self.appendText(msg)
        #    print(msg)



### PYFIGLET (Big text) COMMANDS ###


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
            bigtext = mw.get_figlet_text(self.text) # Remove last newline.
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
        return mw.adjust_figlet_todo(bigtext, self.text)

class MediawikerInsertBigCommentCommand(MediawikerInsertBigTextCommand):
    """
    Inserts big comment text.
    mediawiker_insert_big_comment
    """
    def adjustText(self, bigtext):
        """ Can be over-written by subclasses to modify the big-text. """
        return mw.adjust_figlet_comment(bigtext, self.text)




#######  EVENT LISTENERS   #########


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
        if view.settings().get('syntax') is not None and view.settings().get('syntax').endswith('Mediawiker/Mediawiki.tmLanguage'):
            current_site = mw.get_view_site()
            # TODO: move method to check mediawiker view to mwutils
            # Mediawiki mode
            view.settings().set('mediawiker_is_here', True)
            view.settings().set('mediawiker_wiki_instead_editor', mw.get_setting('mediawiker_wiki_instead_editor'))
            view.settings().set('mediawiker_site', current_site)

    def on_modified(self, view):
        if view.settings().get('mediawiker_is_here', False):
            is_changed = view.settings().get('is_changed', False)

            if is_changed:
                view.set_scratch(False)
            else:
                view.settings().set('is_changed', True)


class MediawikerCompletionsEvent(sublime_plugin.EventListener):

    def on_query_completions(self, view, prefix, locations):
        if view.settings().get('mediawiker_is_here', False):
            view = sublime.active_window().active_view()

            # internal links completions
            cursor_position = view.sel()[0].begin()
            line_region = view.line(view.sel()[0])
            line_before_position = view.substr(sublime.Region(line_region.a, cursor_position))
            internal_link = ''
            if line_before_position.rfind('[[') > line_before_position.rfind(']]'):
                internal_link = line_before_position[line_before_position.rfind('[[') + 2:]

            completions = []
            if internal_link:
                word_cursor_min_len = mw.get_setting('mediawiker_page_prefix_min_length', 3)
                if len(internal_link) >= word_cursor_min_len:
                    namespaces = [ns.strip() for ns in mw.get_setting('mediawiker_search_namespaces').split(',')]
                    sitecon = mw.get_connect()
                    pages = []
                    for ns in namespaces:
                        pages = sitecon.allpages(prefix=internal_link, namespace=ns)
                        for p in pages:
                            print(p.name)
                            # name - full page name with namespace
                            # page_title - title of the page wo namespace
                            # For (Main) namespace, shows [page_title (Main)], makes [[page_title]]
                            # For other namespace, shows [page_title namespace], makes [[name|page_title]]
                            if int(ns):
                                ns_name = p.name.split(':')[0]
                                page_insert = '%s|%s' % (p.name, p.page_title)
                            else:
                                ns_name = '(Main)'
                                page_insert = p.page_title
                            page_show = '%s\t%s' % (p.page_title, ns_name)
                            completions.append((page_show, page_insert))

            return completions


class MediawikerShowPageLanglinksCommand(sublime_plugin.WindowCommand):
    ''' alias to Get page command '''

    def run(self):
        self.window.run_command("mediawiker_page", {"action": "mediawiker_page_langlinks"})


class MediawikerPageLanglinksCommand(sublime_plugin.TextCommand):

    def run(self, edit, title, password):
        sitecon = mw.get_connect(password)
        # selection = self.view.sel()
        # search_pre = self.view.substr(selection[0]).strip()
        selected_text = self.view.substr(self.view.sel()[0]).strip()
        title = selected_text if selected_text else title
        self.mw_get_page_langlinks(sitecon, title)

        self.lang_prefixes = []
        for lang_prefix in self.links.keys():
            self.lang_prefixes.append(lang_prefix)

        self.links_names = ['%s: %s' % (lp, self.links[lp]) for lp in self.lang_prefixes]
        if self.links_names:
            sublime.active_window().show_quick_panel(self.links_names, self.on_done)
        else:
            sublime.status_message('Unable to find laguage links for "%s"' % title)

    def mw_get_page_langlinks(self, site, title):
        self.links = {}
        page = site.Pages[title]
        linksgen = page.langlinks()
        if linksgen:
            while True:
                try:
                    prop = linksgen.next()
                    self.links[prop[0]] = prop[1]
                except StopIteration:
                    break

    def on_done(self, index):
        if index >= 0:
            self.lang_prefix = self.lang_prefixes[index]
            self.page_name = self.links[self.lang_prefix]

            self.process_options = ['Open selected page', 'Replace selected text']
            sublime.active_window().show_quick_panel(self.process_options, self.process)

    def process(self, index):
        if index == 0:
            site_active_new = None
            site_active = mw.get_view_site()
            sites = mw.get_setting('mediawiki_site')
            host = sites[site_active]['host']
            domain_first = '.'.join(host.split('.')[-2:])
            # NOTE: only links like lang_prefix.site.com supported.. (like en.wikipedia.org)
            host_new = '%s.%s' % (self.lang_prefix, domain_first)
            # if host_new exists in settings we can open page
            for site in sites:
                if sites[site]['host'] == host_new:
                    site_active_new = site
                    break
            if site_active_new:
                # open page with force site_active_new
                sublime.active_window().run_command("mediawiker_page", {"title": self.page_name, "action": "mediawiker_show_page", "site_active": site_active_new})
            else:
                sublime.status_message('Settings not found for host %s.' % (host_new))
        elif index == 1:
            self.view.run_command('mediawiker_replace_text', {'text': self.page_name})
