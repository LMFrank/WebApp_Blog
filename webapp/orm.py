#!/usr/bin/env python
# -*- coding: utf-8 -*-
import asyncio
import logging
import aiomysql


def log(sql, args=()):
    logging.info(f"SQL:{sql}")

async def create_pool(loop, **kw):
    logging.info("create database connection pool...")
    global __pool
    __pool = await aiomysql.create_pool(
        host=kw.get("host", "localhost"),
        port=kw.get("port", 3306),
        user=kw["user"],
        password=kw["password"],
        db=kw["db"],
        charset=kw.get("charset", "utf8"),
        autocommit=kw.get("autocommit", True),
        maxsize=kw.get("maxsize", 10),
        minsize=kw.get("minsize", 1),
        loop=loop
    )

async def select(sql, args, size=None):
    log(sql, args)
    with (await __pool) as conn:
        cur = await conn.cursor(aiomysql.DictCursor)
        await cur.execute(sql.replace("?", "%s"), args or ())
        if size:
            rs = await cur.fetchmany(size)  # 一次性返回size条查询结果，结果是一个list，里面是tuple
        else:
            rs = await cur.fetchall()  # 一次性返回所有的查询结果
        await cur.close()
        logging.info(f"row returned: {len(rs)}")
        return rs

async def execute(sql, args, autocommit=True):
    log(sql)
    with (await __pool) as conn:
        try:
            cur = await conn.cursor()
            await cur.execute(sql.replace("?", "%s"), args)
            affected = cur.rowcount
            await cur.close()
        except BaseException as e:
            raise
        return affected


# 在当前类中查找所有的类属性(attrs)，如果找到Field属性，就将其保存到__mappings__的dict中，
# 同时从类属性中删除Field(防止实例属性遮住类的同名属性)
class ModelMetaclass(type):

    def __new__(cls, name, bases, attrs):
        # 排除Model类本身
        if name == "Model":
            return type.__new__(cls, name, bases, attrs)
        tablename = attrs.get("__table__", None) or name
        logging.info(f"found model: {name} (table: {tablename})")
        # 获取所有的Field和主键名
        mappings = dict()
        fields = [] # fields保存的是除主键外的属性名
        primarykey = None
        # 这个k是表示字段名
        for k, v in attrs.items():
            if isinstance(v, Field):
                logging.info(f"found mapping: {k} ==> {v}")
                mappings[k] = v
                if v.primary_key:
                    # 找到主键
                    if primarykey:
                        raise RuntimeError(f"Duplicate primary key for field: {k}")
                    primarykey = k
                else:
                    fields.append(k)

        if not primarykey:
            raise RuntimeError("Primary key not found")
        for k in mappings.keys():
            attrs.pop(k)

        # 使用反单引号" ` "区别MySQL保留字，提高兼容性
        escaped_fields = list(map(lambda f: "`%s`" % f, fields))
        attrs["__mappings__"] = mappings  # 保存属性和列的映射关系
        attrs["__table__"] = tablename
        attrs["__primary_key__"] = primarykey  # 主键属性名
        attrs["__fields__"] = fields  # 除主键外的属性名
        # 构造默认的SELECT, INSERT, UPDATE和DELETE语句:
        attrs["__select__"] = "SELECT `%s`, %s FROM `%s`" % (primarykey, ",".join(escaped_fields), tablename)
        attrs["__insert__"] = "insert into `%s` (%s, `%s`) values (%s)" % (tablename, ", ".join(escaped_fields), primarykey, create_args_string(len(escaped_fields) + 1))
        attrs["__update__"] = "update `%s` set %s where `%s`=?" % (tablename, ", ".join(map(lambda f: "`%s`=?" % (mappings.get(f).name or f), fields)), primarykey)
        attrs["__delete__"] = "delete from `%s` where `%s`=?" % (tablename, primarykey)
        return type.__new__(cls, name, bases, attrs)


class Model(dict, metaclass=ModelMetaclass):
    # 继承dict，方便直接使用self[key]
    def __init__(self, **kw):
        super(Model, self).__init__(**kw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"'Model' object has no attribute '{key}'")

    def __setattr__(self, key, value):
        self[key] = value

    def getValue(self, key):
        return getattr(self, key, None)

    def getValueOrDefault(self, key):
        value = getattr(self, key, None)
        if value is None:
            field = self.__mappings__[key]
            if field.default is not None:
                value = field.default() if callable(field.default) else field.default
                logging.debug(f"using default value for {key}: {str(value)}")
                setattr(self, key, value)
        return value

    @classmethod
    async def findAll(cls, where=None, args=None, **kw):
        # 根据WHERE条件查找
        sql = [cls.__select__]
        if where:
            sql.append("where")
            sql.append(where)
        if args is None:
            args = []

        orderby = kw.get("orderby", None)
        if orderby:
            sql.append("order by")
            sql.append(orderby)

        limit = kw.get("limit", None)
        if limit is not None:
            sql.append("limit")
            if isinstance(limit, int):
                # 如果limit为一个整数n，那就将查询结果的前n个结果返回
                sql.append("?")
                args.append(limit)
            elif isinstance(limit, tuple) and len(limit) == 2:
                # 如果limit为一个两个值的tuple，则前一个值代表索引，后一个值代表从这个索引开始要取的结果数
                sql.append("?, ?")
                args.extend(limit)  # 用extend是把tuple的小括号去掉
            else:
                raise ValueError(f"Invalid limit value: {str(limit)}")
        rs = await select(" ".join(sql), args)  # 返回的rs是一个元素是tuple的list
        return [cls(**r) for r in rs]  # **r是关键字参数，构成了一个cls类的列表，其实就是每一条记录对应的类实例

    @classmethod
    async def findNumber(cls, selectfield, where=None, args=None):
        # 根据WHERE条件查找，但返回的是整数，适用于select count(*)类型的sql
        sql = ["select %s _num_ from `%s`" % (selectfield, cls.__table__)]
        if where:
            sql.append("where")
            sql.append(where)
        rs = await select(" ".join(sql), args, 1)
        if len(rs) == 0:
            return None
        return rs[0]["_num_"]

    @classmethod
    async def find(cls, pk):
        rs = await select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__), [pk], 1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])  # 返回一条记录，以dict的形式返回，因为cls的父类继承了dict类

    async def save(self):
        args = list(map(self.getValueOrDefault, self.__fields__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = await execute(self.__insert__, args)
        if rows != 1:
            logging.warning(f"failed to insert record: affected rows: {rows}" % rows)

    async def update(self):
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = await execute(self.__update__, args)
        if rows != 1:
            logging.warning(f"failed to update by primary key: affected rows: {rows}" % rows)

    async def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = await execute(self.__delete__, args)
        if rows != 1:
            logging.warning(f"failed to remove by primary key: affected rows: {rows}" % rows)


class Field(object):

    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default

    def __str__(self):
        return f"<{self.__class__.__name__}, {self.column_type}: {self.name}>"


class StringField(Field):

    def __init__(self, name=None, primary_key=False, default=None, ddl="varchar(100)"):
        super().__init__(name, ddl, primary_key, default)


class BooleanField(Field):

    def __init__(self, name=None, default=False):
        super().__init__(name, 'boolean', False, default)


class IntegerField(Field):

    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'bigint', primary_key, default)


class FloatField(Field):

    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'real', primary_key, default)


class TextField(Field):

    def __init__(self, name=None, default=None):
        super().__init__(name, 'text', False, default)


def create_args_string(num):
    # 用于输出元类中创建sql_insert语句中的占位符
    L = []
    for n in range(num):
        L.append("?")
    return ", ".join(L)
