### WebAPP_Blog

该项目基于廖雪峰老师的WEB实战项目，[教程传送门]( https://www.liaoxuefeng.com/wiki/1016959663602400/1018138095494592 )。相反于使用成熟python web框架，该项目从底层构建web框架、ORM、MVC、API、前端及部署。

该教程从底层构建框架，开始学习时确实有一定困难，结合他人学习笔记，我尽量做了注释，希望可以帮助到大家

最终的网站效果如图，主要实现了以下功能：

- 用户的注册、登录、注销
- 发布新博客，且可以编辑已有博客
- 用户可以发布博客评论
- 管理员可以管理用户、博客及博客评论

![index](https://github.com/LMFrank/WebApp_Blog/blob/master/images/index.bmp)

### 开发环境

- python：3.7.6
- 基于aiohttp构建web框架
- 前端模板使用jinja2
- mysql异步驱动模块：aiomysql

### 主要模块

- `coreweb.py`：web框架，处理url，对url及静态资源进行映射,使用了`inspect`模块

- `app.py`：启动web app，实现各个中间件对数据的处理、模板渲染
- `orm.py`：自己搭建的orm框架，建立类与数据库表的映射，对数据库进行封装 
- `handlers.py`：编写业务逻辑的模块 
- `models.py`：建立数据模型 

### 运行流程

http请求 ----> logger_factory（输出请求信息） ----> auth_factory（对`url/manage`拦截，解析cookie，检查是否是管理员） ----> data_factory（处理数据，打印post提交的数据） ----> url映射 ----> RequestHandler（从request中获取必要参数，之后调用URL函数） ----> response_factory（构建返回数据，渲染模板）

### 提升开发效率

成熟的web框架开启debug模式后，不关闭服务器也可以自动reload。项目中pymonitor.py文件利用`watchdog`接收文件变化的通知，如果是`.py`文件，就自动重启`app.py`进程。利用Python自带的`subprocess`实现进程的启动和终止，并把输入输出重定向到当前进程的输入输出中。

### 补充

- 背景动态粒子特效： https://github.com/yzyly1992/JavaScript_FX 