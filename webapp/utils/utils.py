#!/usr/bin/env python
# -*- coding: utf-8 -*-
import time
import hashlib
import logging
import re

from models import User
from apis import APIPermissionError
from config import configs


COOKIE_NAME = "awesession"
_COOKIE_KEY = configs.session.secret

# 定义EMAIL和HASH的格式规范
_RE_EMAIL = re.compile(r"^[a-z0-9\.\-\_]+\@[a-z0-9\-\_]+(\.[a-z0-9\-\_]+){1,4}$")
_RE_SHA1 = re.compile(r"^[0-9a-f]{40}$")

# 查看是否是管理员用户
def check_admin(request):
    if request.__user__ is None or not request.__user__.admin:
        raise APIPermissionError()

# 获取页码信息
def get_page_index(page_str):
    p = 1
    try:
        p = int(page_str)
    except ValueError as e:
        pass
    if p < 1:
        p = 1
    return p

# 计算加密cookie
def user2cookie(user, max_age):
    # build cookie string by: id-expires-sha1
    expires = str(int(time.time()) + max_age)
    s = f"{user.id}-{user.passwd}-{expires}-{_COOKIE_KEY}"
    L = [user.id, expires, hashlib.sha1(s.encode("utf-8")).hexdigest()]
    return "-".join(L)

# 文本转HTML
# 先用filter函数对输入的文本进行过滤处理，断行，去掉首尾空白字符
# 再用map函数对每一行的特殊符号进行转换，最后将字符串装入html的<p>标签中
def text2html(text):
    lines = map(lambda s: "<p>%s</p>" % s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"),
                filter(lambda s: s.strip() != "", text.split("\n")))
    return "".join(lines)

# 解密cookie
async def cookie2user(cookie_str):
    if not cookie_str:
        return None
    try:
        L = cookie_str.split("-")
        if len(L) != 3:
            return None
        uid, expires, sha1 = L
        if int(expires) < time.time():
            return None
        user = await User.find(uid)
        if user is None:
            return None
        s = f"{uid}-{user.passwd}-{expires}-{_COOKIE_KEY}"
        if sha1 != hashlib.sha1(s.encode("utf-8")).hexdigest():
            logging.info("invalid sha1")
            return None
        user.passwd = "******"
        return user
    except Exception as e:
        logging.exception(e)
        return None