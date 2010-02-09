"""
deferargs module
Provides the deferargs decorator, which lets you write functions that think
they take and return normal values, when they can actually be passed and will
return Deferreds!

This code is free to use, copy, modify, and redistribute. You can use it in
any code to do anything you want, but there is no warranty.

Usage is like: (Not a doctest)

>>> @deferargs
... def printResults(*args, **kwargs):
...     print args
...     print kwargs
...     return (args, kwargs)
... 
>>> args, kwargs = printResults(getPage("www.google.com")
>>> page = args[0] # This is actually a Deferred
>>>

Error handling can be done much like a try/except block.
@catch(errtype) is your 'except errtype' and any number of
them can follow after the @deferargs decorated function.

@deferargs
def foo():
    assert False
@catch(AssertionError)
def onAssert(error):
    print "OOPS"
@catch()
def onOthers(error):
    print "I WOULD BE REACHED FOR ANYTHING NOT CAUGHT ABOVE."
@cleanup
def _(r):
    print "The result was: ", r

There is also a method of doing this without defining a function
to be called later, but instead having it execute immediately like
a normal try/except/finally. To do this, decorate the first function
with attempt, instead of deferargs. If you use attempt, you must have
a @catch() block!


Note: Currently, nesting of these forms is not allowed. I don't know
what will happen if you try it.

"""

from twisted.internet import defer

_last_deferfunc = None
_attempting = None

class deferfunc(object):
    
    deepArgHandler = {}

    def __init__(self, f, deepTypes=[]):
        self.function = f
        self.errbacks = []
        self.error_handled = False
        self.deferred = None
        self.deepTypes = deepTypes
    
    def handleArg(self, arg):
        if isinstance(arg, defer.Deferred):
            self.defers.append(arg)
            return arg
        elif self.deepTypes:
            d = self.handleDeepArg(arg)
            if d is arg:
                return defer.succeed(arg)
        else:
            return defer.succeed(arg)

    def handleDeepArg(self, arg):
        for t in self.deepTypes:
            if issubclass(type(arg), t):
                return self.deepArgHandler[t](self, arg)
        return arg
    
    def handleDeepList(self, arg):
        for i, a in enumerate(arg):
            arg[i] = self.handleArg(a)
            self.defers.append(arg[i])
            acb=arg[i].addCallback
            @acb
            def update(r):
                arg[i] = r
        return arg
    deepArgHandler[list] = handleDeepList

    def __call__(self, *args, **kwargs):
        args = list(args)
        self.defers = []
        f = self.function

        for i, arg in enumerate(args):
            d=self.handleArg(arg)
            @d.addCallback
            def update(r):
                args[i] = r

        for k, v in kwargs.items():
            d=self.handleArg(v)
            @d.addCallback
            def setResultingArg(r):
                kwargs[k] = r

        if self.defers:
            d = defer.DeferredList(self.defers, fireOnOneErrback=True, consumeErrors=True)
            @d.addCallback
            def callWithResults(_results):
                return f(*args, **kwargs)
        else:
            d = defer.Deferred()
        self.deferred = d
        for errback in self.errbacks:
            d.addErrback(errback)
        if not self.defers:
            try:
                r = f(*args, **kwargs)
                d.callback(r)
            except Exception, e:
                d.errback(e)
        if hasattr(self, 'cleanup'):
            cleanup_d = defer.Deferred()
            cleanup_d.addCallback(self.cleanup)
            d.chainDeferred(cleanup_d)
        return d

def deferargs(*args, **kwargs):
    if len(args)==1 and isinstance(args[0], type(deferargs)):
        new_f = deferfunc(args[0], **kwargs)
        global _last_deferfunc
        _last_deferfunc = new_f
        return new_f
    else:
        deepTypes = kwargs.setdefault('deepTypes', [])
        dec = lambda f: deferargs(f, deepTypes=deepTypes)
        return dec


def catch(errtype=None):
    assert _last_deferfunc is not None, "@catch must follow a function."
    lastCatchForAttempt = False
    if errtype is None:
        lastCatchForAttempt = True
        errtype = Exception
    runnow = False
    global _attempting
    if _attempting is not None and lastCatchForAttempt:
        runnow = True
    def dec(f, forfunc=_last_deferfunc, runnow=runnow):
        def errback(error):
            r = error.trap(errtype)
            if issubclass(r,errtype) and not forfunc.error_handled:
                forfunc.error_handled = True
                r = f(error)
                return r
        _last_deferfunc.errbacks.append(errback)
        if runnow:
            global _attempting
            r = _attempting()
        return errback
    return dec


def attempt(f):
    f = deferargs(f)
    global _attempting
    _attempting = f
    return f


def deferargscall(f, *args, **kwargs):
    return deferargs(f)(*args, **kwargs)


def cleanup(f):
    global _last_deferfunc
    if hasattr(_last_deferfunc.deferred, 'result'):
        _last_deferfunc.deferred.addCallback(f)
    else:
        _last_deferfunc.cleanup = f
    return f


if __name__ == '__main__':
    from twisted.internet import reactor
    
    @deferargs
    def test(*args, **kwargs):
        return (args, kwargs)
    @deferargs
    def testequal(a, b):
        assert a == b
    testequal(test(1, 2, foo=3), ((1,2),{'foo':3}))
    testequal(test(1, defer.succeed(2), foo=defer.succeed(3)), ((1,2),{'foo':3}))
    
    reactor.runUntilCurrent()
    
    @deferargs
    def testing_catch():
        assert False
    assert_caught = []
    @catch(AssertionError)
    def onAssertError(error):
        assert_caught.append(True)
    @catch()
    def onAnyError(error):
        assert False
    testing_catch()
    
    assert assert_caught
    reactor.runUntilCurrent()
    
    #print "Catch Test 2"
    
    @deferargs
    def testing_catch2():
        assert False
    assert_caught2 = []
    @catch()
    def onAnyError2(error):
        assert_caught2.append(True)
    testing_catch2()
    
    reactor.runUntilCurrent()
    assert assert_caught2
    
    #print "Attempt/catch"
    
    @attempt
    def this():
        assert False
    assert_caught = []
    @catch(AssertionError)
    def onAssertError(error):
        assert_caught.append(True)
    @catch()
    def catchAll(error):
        assert_caught[:] = []
    assert assert_caught, assert_caught
    
    #print "Attempt/catch all"
    
    @attempt
    def this():
        assert False
    assert_caught = []
    @catch()
    def catchAll(error):
        assert_caught.append(True)
    assert assert_caught, assert_caught
    
    
    #print "Attemp/Catch/Cleanup"
    
    @attempt
    def this():
        assert False
    assert_caught = []
    cleanup_called = []
    @catch(AssertionError)
    def onAssertError(error):
        assert_caught.append(True)
    @catch()
    def catchAll(error):
        assert_caught[:] = []
    @cleanup
    def _(result):
        cleanup_called.append(True)
    assert assert_caught, assert_caught
    
    @deferargs
    def this():
        assert False
    assert_caught = []
    cleanup_called = []
    @catch(AssertionError)
    def onAssertError(error):
        assert_caught.append(True)
    @catch()
    def catchAll(error):
        assert_caught[:] = []
    @cleanup
    def _(result):
        cleanup_called.append(True)
    
    this()
    reactor.runUntilCurrent()
    assert assert_caught, assert_caught
    
    def f(a):
        assert a == 10
    deferargscall(f, defer.succeed(10))
    
    @deferargs(deepTypes=[list])
    def test(lst):
        assert lst == [1,2], lst
    test([1, defer.succeed(2)])
    reactor.runUntilCurrent()

