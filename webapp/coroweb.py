#!/usr/bin/env python
# -*- coding: utf-8 -*-
import asyncio
import os
import inspect
import logging
import functools

from urllib import parse
from aiohttp import web

from apis import APIError

"""
def handler_decorator(path,*,method):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args,**kw):
            return func(*args,**kw)
        wrapper.__route__ = path
        wrapper.__method__ = method
        return wrapper
    return decorator

get = functools.partial(handler_decorator,method='GET')
post = functools.partial(handler_decorator,method='POST')
"""

# python内置的functools.wraps装饰器作用是把装饰后的函数的__name__属性变为原始的属性，即func的属性
# 因为当不使用该装饰器时函数的__name__为wrapper，而不是func
def get(path):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = "GET"
        wrapper.__route__ = path
        return wrapper
    return decorator

def post(path):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = "POST"
        wrapper.__route__ = path
        return wrapper
    return decorator

# 关于inspect.Parameter的kind类型有5种：
# POSITIONAL_ONLY		只是位置参数
# POSITIONAL_OR_KEYWORD	可以是位置参数也可以是关键字参数
# VAR_POSITIONAL		相当于 *args
# KEYWORD_ONLY			相当于 *,key
# VAR_KEYWORD			相当于 **kw

def get_required_kw_args(fn):
    # 收集没有默认值的命名关键字参数
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default == inspect.Parameter.empty:
            args.append(name)
    return tuple(args)

def get_named_kw_args(fn):
    # 获取命名关键字参数
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            args.append(name)
    return tuple(args)

def has_named_kw_args(fn):
    # 判断有没有命名关键字参数
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            return True

def has_var_kw_arg(fn):
    # 判断有没有关键字参数
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True

def has_request_arg(fn):
    # 判断是否含有名字叫做'request'参数，且该参数要在其他普通的位置参数之后
    # request可以为VAR_POSITIONAL, KEYWORD_ONLY, VAR_KEYWORD中的一种
    # 即fn(POSITIONAL_ONLY, request, VAR_POSITIONAL, KEYWORD_ONLY, VAR_KEYWORD)
    sig = inspect.signature(fn)
    params = sig.parameters
    found = False
    for name, param in params.items():
        if name == 'request':
            found = True
            continue
        if found and (param.kind != inspect.Parameter.VAR_POSITIONAL and param.kind != inspect.Parameter.KEYWORD_ONLY and param.kind != inspect.Parameter.VAR_KEYWORD):
            raise ValueError('request parameter must be the last named parameter in function: %s%s' % (fn.__name__, str(sig)))
    return found


class RequestHandler(object):

    def __init__(self, app, fn):
        self._app = app
        self._func = fn
        self._has_request_arg = has_request_arg(fn)
        self._has_var_kw_arg = has_var_kw_arg(fn)
        self._has_named_kw_args = has_named_kw_args(fn)
        self._named_kw_args = get_named_kw_args(fn)
        self._required_kw_args = get_required_kw_args(fn)

    # RequestHandler本身是一个类，由于定义了__call__方法，因此将其实例视为函数
    # 该函数从request中获取必要参数，之后调用URL函数
    # 最后将结果转换为web.Response对象
    async def __call__(self, request):
        kw = None
        if self._has_var_kw_arg or self._has_named_kw_args or self._required_kw_args:
            if request.method == 'POST':
                if not request.content_type:
                    return web.HTTPBadRequest(text='Missing Content-Type.')
                ct = request.content_type.lower()
                if ct.startswith('application/json'):
                    params = await request.json()
                    if not isinstance(params, dict):
                        return web.HTTPBadRequest(text='JSON body must be object.')
                    kw = params
                elif ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'):
                    params = await request.post()
                    kw = dict(**params)
                else:
                    return web.HTTPBadRequest(text='Unsupported Content-Type: %s' % request.content_type)
            if request.method == 'GET':
                qs = request.query_string
                if qs:
                    kw = dict()
                    for k, v in parse.parse_qs(qs, True).items():
                        kw[k] = v[0]
        if kw is None:
            kw = dict(**request.match_info)
        else:
            if not self._has_var_kw_arg and self._named_kw_args:
                # 当函数参数没有关键字参数时，移去request除命名关键字参数外所有的参数信息
                copy = dict()
                for name in self._named_kw_args:
                    if name in kw:
                        copy[name] = kw[name]
                kw = copy
            # check named arg: 即加入命名关键字参数(没有附加默认值),request没有提供相应的数值，报错
            for k, v in request.match_info.items():
                if k in kw:
                    logging.warning('Duplicate arg name in named arg and kw args: %s' % k)
                kw[k] = v
        if self._has_request_arg:
            kw['request'] = request
        # check required kw:
        if self._required_kw_args:
            for name in self._required_kw_args:
                if not name in kw:
                    return web.HTTPBadRequest(text='Missing argument: %s' % name)
        logging.info('call with args: %s' % str(kw))
        try:
            r = await self._func(**kw)
            return r
        except APIError as e:
            return dict(error=e.error, data=e.data, message=e.message)


def add_static(app):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    app.router.add_static('/static/', path)
    logging.info('add static %s => %s' % ('/static/', path))

def add_route(app, fn):
    # 用来注册一个URL处理函数，验证函数是否包含URL的相应方法与路径信息，并将其函数变为协程
    method = getattr(fn, '__method__', None)
    path = getattr(fn, '__route__', None)
    if path is None or method is None:
        raise ValueError('@get or @post not defined in %s.' % str(fn))
    if not asyncio.iscoroutinefunction(fn) and not inspect.isgeneratorfunction(fn):
        fn = asyncio.coroutine(fn)
    logging.info('add route %s %s => %s(%s)' % (method, path, fn.__name__, ', '.join(inspect.signature(fn).parameters.keys())))
    app.router.add_route(method, path, RequestHandler(app, fn))


# 自动将module_name模块中所有符合条件的函数进行注册
# 只需要向这个函数提供要批量注册函数的文件路径，新编写的函数就会筛选，注册文件内所有符合注册条件的函数
def add_routes(app, module_name):
    n = module_name.rfind('.')
    if n == (-1):
        # 没有匹配项，rfind返回-1
        mod = __import__(module_name, globals(), locals())
    else:
        name = module_name[n+1:]
        mod = getattr(__import__(module_name[:n], globals(), locals(), [name]), name)
    for attr in dir(mod):  # dir()迭代出mod模块中所有的类，实例及函数等对象,str形式
        if attr.startswith('_'):
            # 忽略'_'开头的对象，直接继续for循环
            continue
        fn = getattr(mod, attr)
        # 确保是函数
        if callable(fn):
            # 确保视图函数存在method和path
            method = getattr(fn, '__method__', None)
            path = getattr(fn, '__route__', None)
            if method and path:
                add_route(app, fn)