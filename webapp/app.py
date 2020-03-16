#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
from logging.handlers import RotatingFileHandler
import asyncio
import os
import time
from datetime import datetime
import json
from aiohttp import web
from jinja2 import Environment, FileSystemLoader

from config import configs
import orm
from coroweb import add_routes, add_static
from handlers import cookie2user, COOKIE_NAME

logger = logging.getLogger()
logger.setLevel(logging.INFO)
log_path = os.path.dirname(os.getcwd()) + '/logs/'
log_name = log_path + 'log'
fh = RotatingFileHandler(log_name, maxBytes=1024 * 1024 * 100, backupCount=10)
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(filename)s[line:%(lineno)d] - %(levelname)s: %(message)s")
fh.setFormatter(formatter)
logger.addHandler(fh)


def init_jinja2(app, **kw):
    logging.info('init jinja2...')
    options = dict(
        # 自动转义xml/html的特殊字符
        autoescape=kw.get('autoescape', True),
        # 代码块的开始、结束标志
        block_start_string=kw.get('block_start_string', '{%'),
        block_end_string=kw.get('block_end_string', '%}'),
        # 变量的开始、结束标志
        variable_start_string=kw.get('variable_start_string', '{{'),
        variable_end_string=kw.get('variable_end_string', '}}'),
        # 自动加载修改后的模板文件
        auto_reload=kw.get('auto_reload', True)
    )
    # 获取模板文件夹路径
    path = kw.get('path', None)
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    logging.info('set jinja2 template path: %s' % path)
    # Environment类是jinja2的核心类，用来保存配置、全局对象以及模板文件的路径
    # FileSystemLoader类加载path路径中的模板文件
    env = Environment(loader=FileSystemLoader(path), **options)
    # 过滤器集合
    filters = kw.get('filters', None)
    if filters is not None:
        for name, f in filters.items():
            # filters是Environment类的属性：过滤器字典
            env.filters[name] = f
    # 所有的一切是为了给app添加__templating__字段
    # 前面将jinja2的环境配置都赋值给env了，这里再把env存入app的dict中，这样app就知道要到哪儿去找模板，怎么解析模板
    app['__templating__'] = env


# 以下是middleware,可以把通用的功能从每个URL处理函数中拿出来集中放到一个地方
# URL处理日志工厂
async def logger_factory(app, handler):
    async def logger_middleware(request):
        logging.info(f"Request: {request.method} {request.path}")
        return await handler(request)
    return logger_middleware

# 认证处理工厂--把当前用户绑定到request上，并对URL/manage/进行拦截，检查当前用户是否是管理员身份
async def auth_factory(app, handler):
    async def auth(request):
        logging.info('check user: %s %s' % (request.method, request.path))
        request.__user__ = None
        cookie_str = request.cookies.get(COOKIE_NAME)
        if cookie_str:
            user = await cookie2user(cookie_str)
            if user:
                logging.info('set current user: %s' % user.email)
                request.__user__ = user
        if request.path.startswith('/manage/') and (request.__user__ is None or not request.__user__.admin):
            return web.HTTPFound('/signin')
        return await handler(request)
    return auth

# 数据处理工厂
async def data_factory(app, handler):
    async def parse_data(request):
        if request.method == 'POST':
            if request.content_type.startswith('application/json'):
                request.__data__ = await request.json()
                logging.info('request json: %s' % str(request.__data__))
            elif request.content_type.startswith('application/x-www-form-urlencoded'):
                request.__data__ = await request.post()
                logging.info('request form: %s' % str(request.__data__))
        return await handler(request)
    return parse_data

# 响应返回处理工厂
async def response_factory(app, handler):
    async def response(request):
        logging.info('Response handler...')
        r = await handler(request)
        if isinstance(r, web.StreamResponse):
            return r
        if isinstance(r, bytes):
            resp = web.Response(body=r)
            resp.content_type = 'application/octet-stream'
            return resp
        if isinstance(r, str):
            if r.startswith('redirect:'):
                return web.HTTPFound(r[9:])
            resp = web.Response(body=r.encode('utf-8'))
            resp.content_type = 'text/html;charset=utf-8'
            return resp
        if isinstance(r, dict):
            template = r.get('__template__')
            if template is None:
                resp = web.Response(body=json.dumps(r, ensure_ascii=False, default=lambda o: o.__dict__).encode('utf-8'))
                resp.content_type = 'application/json;charset=utf-8'
                return resp
            else:
                r['__user__'] = request.__user__
                resp = web.Response(body=app['__templating__'].get_template(template).render(**r).encode('utf-8'))
                resp.content_type = 'text/html;charset=utf-8'
                return resp
        if isinstance(r, int) and 100 <= r < 600:
            return web.Response(r)
        if isinstance(r, tuple) and len(r) == 2:
            t, m = r
            if isinstance(t, int) and 100 <= t < 600:
                return web.Response(t, str(m))
        # default:
        resp = web.Response(body=str(r).encode('utf-8'))
        resp.content_type = 'text/plain;charset=utf-8'
        return resp
    return response


# 时间转换
def datetime_filter(t):
    delta = int(time.time() - t)
    if delta < 60:
        return f"1分钟前"
    if delta < 3600:
        return f"{delta // 60}分钟前"
    if delta < 86400:
        return f"{delta // 3600}小时前"
    if delta < 604800:
        return f"{delta // 86400}天前"
    dt = datetime.fromtimestamp(t)
    return f"{dt.year}年{dt.month}月{dt.day}日"


async def init(loop):
    # 新版本写法
    await orm.create_pool(loop=loop, **configs.db)
    app = web.Application(middlewares=[logger_factory, auth_factory, response_factory])  # loop参数已弃用
    init_jinja2(app, filters=dict(datetime=datetime_filter))
    add_routes(app, 'handlers')
    add_static(app)

    # srv = await loop.create_server(app.make_handler(), '127.0.0.1', 9000)
    # logging.info('server started at http://127.0.0.1:9000...')
    # return srv

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 9000)
    logging.info("server started at http://127.0.0.1:9000...")
    await site.start()


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init(loop))
    loop.run_forever()
