#!/usr/bin/env python
# -*- coding: utf-8 -*-
##    Copyright 2013 Rasmus Scholer Sorensen, rasmusscholer@gmail.com
##
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
##
# pylint: disable=W0212,R0903,C0103,W0201

# Parts of this code is copyright by Chris Arndt
# © 2011 Christopher Arndt, MIT License
# From https://wiki.python.org/moin/PythonDecoratorLibrary#Cached_Properties

"""

Intro note about python decorators:
* They are defined as though they were classes.
* They implement e.g. __init__, __call__, and __get__, similar to what you could do
  with other classes/object.

See class doc for specifics on how this cached_property works.

"""


import time
import logging
logger = logging.getLogger(__name__)

class cached_property(object):
    '''
    Decorator for making cached properties with read/write/expire ability.
    The property is evaluated only once within TTL period, unless specifically
    expired or re-set.

    Based on the original cached_property by Christopher Arndt, but with a few additions:

    *   I could never remember how to expire a cache, so I've implemented __del__ to do
        this now. To expire the cache, simply invoke
            del obj.MyCachedProperty
        where CachedProperty is the attribute on your object obj, as per the example below:

    *   I would like to be able to re-set the property if I do the calculations somewhere else.
        (However, this is probably usually Not A Good Idea (tm)).

    *   Setting ttl to a negative value should disable caching (it will always be expired).

    This decorator can be used to created a cached property like this::

            # the class containing the property must be a new-style class
            class MyClass(object):
                # create property whose value is cached for ten minutes
                @cached_property(ttl=600)   # Set cache time to 600 seconds
                def MyCachedProperty(self):
                    # will only be evaluated every 10 min.
                    return really_long_calculation()
            obj = MyClass()
            print obj.MyCachedProperty  # Slow first time.
            print obj.MyCachedProperty  # Fast
            newval = calculation_from_alternative_source()
            obj.MyCachedProperty = newval   # Re-set property with new value.
            print obj.MyCachedProperty  # Fast
            del obj.MyCachedProperty    # Expire the cache (does not actually delete the attribute)
            print obj.MyCachedProperty  # Slow.

    Alternatively, the cached property can be expired manually by deleting the cache entry:

        del obj._cache[<property name>]

    The value is cached  in the '_cache' attribute of the object instance that
    has the property getter method wrapped by this decorator. The '_cache'
    attribute value is a dictionary which has a key for every property of the
    object which is wrapped by this decorator. Each entry in the cache is
    created only when the property is accessed for the first time and is a
    two-element tuple with the last computed property value and the last time
    it was updated in seconds since the epoch.

    The default time-to-live (TTL) is 300 seconds (5 minutes). Set the TTL to
    zero for the cached value to never expire.

    Note that, unlike the property decorator, this decorator must be instantiated
    before it is used to wrap a method. This is because here the decoration is
    done by passing the method-to-be-wrapped to __call__, while in the property
    decorator the method-to-be-wrapped is passed to __init__ during instantiation.
    For this decorator, __init__ is used to customize the decorator, setting
    ttl and (in theory) other attributes.

    Thus, to use this property you MUST do:
        @cached_property()  # Notice the parenthesis
        def mymethod(...)
    this will NOT work:
        @cached_property    # Will not work without parenthesis;
        def mymethod        # since mymethod will then be passed to __init__

    '''
    def __init__(self, ttl=300):
        self.ttl = ttl

    def __call__(self, fget, doc=None):
        self.fget = fget
        self.__doc__ = doc or fget.__doc__
        self.__name__ = fget.__name__
        self.__module__ = fget.__module__
        return self

    def __get__(self, inst, owner):
        ## Note: putting now = time.time() at the top will make the cache behavior dependent on the calculation time.
        ## You could argue the cache time-to-live should be calculated from _after_ the calculation
        ## has finished, not from when it was started.
        ## (This is only important if calculation time (self.fget) is comparable to self.ttl)
        now = time.time()
        try:
            value, last_update = inst._cache[self.__name__]
            if self.ttl != 0 and now - last_update > self.ttl:
                raise AttributeError
        except (KeyError, AttributeError):
            value = self.fget(inst)
            try:
                cache = inst._cache
            except AttributeError:
                cache = inst._cache = {} # empty dict.
            cache[self.__name__] = (value, now) # Consider calling for another time.time() ?
        return value

    def __set__(self, inst, value):
        """
        Descriptor protocol:
            __set__(self, instance, value) --> None
        I override __set__ to ensure that the property is not automatically
        overwritten, e.g. if someone does:
        (class MyObj, instance myobj):
        @def cached_property
            def mycachedattr(self):
                return random.randint(0, 99)
        then later:
            myobj.mycachedattr = 2
        """
        logger.debug("__set__ invoked with inst '%s' and value '%s'", inst, value)
        now = time.time()
        try:
            cache = inst._cache
        except AttributeError:
            cache = inst._cache = {} # empty dict.
            logger.debug("No existing cache, created a new...")
        cache[self.__name__] = (value, now)

    def __delete__(self, inst):
        """
        The descriptor protocol uses __get__, __set__ and __delete__.
        Note that del <var> calls __delete__, not __del__.
        __del__ is called when an object is destroyed (e.g. by the GC),
        and should not be relied upon.
        """
        logger.debug("Deleting cache for property '%s'", self.__name__)
        try:
            del inst._cache[self.__name__]
        except AttributeError as e:
            logger.debug("inst '%s' doesn't have a _cache so nothing to delete. (%s)", inst, e)
        except KeyError as e:
            logger.debug("No key '%s' for _cache of inst '%s' so nothing to delete.", e, inst)
