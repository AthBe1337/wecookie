# WeCookie HTTP API

本文档描述 WeCookie 当前 HTTP 服务的实际接口。服务默认由 Docker Compose
发布在宿主机 http://127.0.0.1:8090。接口只提供局域网使用场景，仍建议始终
配置 API_TOKEN。

## 1. 基本信息

| 项目 | 说明 |
| --- | --- |
| Base URL | http://<host>:8090 |
| API 前缀 | /api |
| 数据格式 | JSON（二维码接口例外，为 PNG） |
| 字符编码 | UTF-8 |
| 时间格式 | Unix 时间戳，JSON number，单位为秒，可能包含小数 |
| HTTP 方法 | GET、POST，具体见接口说明 |

API 服务绑定容器内的 0.0.0.0:8090，宿主机端口由 Compose 的 HTTP_PORT
配置。当前部署目录为 ~/Soft/wecookie。

## 2. 鉴权

当环境变量 API_TOKEN 非空时，所有 /api/* 请求都必须携带以下请求头：

~~~http
Authorization: Bearer <API_TOKEN>
~~~

示例：

~~~sh
TOKEN='replace-with-your-token'
BASE_URL='http://127.0.0.1:8090'

curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/api/status"
~~~

鉴权比较为完整字符串匹配。缺少请求头、Token 错误或格式不正确都会返回：

~~~http
HTTP/1.1 401 Unauthorized
Content-Type: application/json; charset=utf-8
~~~

~~~json
{"error":"unauthorized"}
~~~

当 API_TOKEN 为空时，服务不强制鉴权。生产或长期运行时不应依赖这一行为。

## 3. 登录状态

### GET /api/status

查询微信当前状态和匹配到的窗口信息。该接口不会点击窗口，也不会改变微信状态。

请求：

~~~sh
curl -sS -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/api/status"
~~~

成功响应：

~~~json
{
  "state": "logged_in",
  "windows": [
    {
      "id": 6291476,
      "x": 181,
      "y": 67,
      "width": 917,
      "height": 667
    }
  ],
  "updated_at": 1790963404.6457982
}
~~~

响应字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| state | string | 当前状态，见下表 |
| windows | array | 窗口列表；每项包含窗口 ID、位置和尺寸 |
| windows[].id | integer | X11 窗口 ID |
| windows[].x / y | integer | 窗口左上角坐标 |
| windows[].width / height | integer | 窗口尺寸，单位为像素 |
| updated_at | number | 本次状态查询的服务端时间 |

state 取值：

| 状态 | 含义 |
| --- | --- |
| logged_in | 检测到至少一个宽度不小于 900、高度不小于 650 的微信主窗口 |
| login_required | 检测到 292x396 的微信登录窗口，可能是二维码页、记住账号页或手机确认页 |
| unknown | 未能匹配上述窗口状态，或窗口信息尚未就绪 |

注意：login_required 不区分二维码、记住账号和手机确认页面。需要通过截图
或调用 POST /api/login 推进登录流程。

## 4. 获取登录画面

### GET /api/qr

返回当前 Xvfb 虚拟桌面的全屏截图，媒体类型为 image/png。接口名称保留为
qr，但返回内容不是裁剪后的二维码，而是 1280x800 的完整桌面截图，便于
确认当前登录页、二维码或手机确认提示。

请求：

~~~sh
curl -fS -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/api/qr" -o wechat-screen.png
file wechat-screen.png
~~~

成功响应：

~~~http
HTTP/1.1 200 OK
Content-Type: image/png
Content-Length: <bytes>
~~~

错误响应：

| HTTP 状态 | error | 说明 |
| --- | --- | --- |
| 401 | unauthorized | 鉴权失败 |
| 404 | not_found | 路径错误 |
| 409 | already_logged_in | 当前已经检测到登录主窗口 |
| 503 | screen_capture_failed | 无法从 Xvfb 读取桌面 |

503 可能包含额外的 detail 字段：

~~~json
{"error":"screen_capture_failed","detail":"..."}
~~~

## 5. 触发登录

### POST /api/login

尝试点击微信登录小窗口中的固定登录按钮。当前实现用于“记住账号”或类似页面，
点击后通常需要在手机上确认登录。请求体不会被读取，因此可发送空 body。

请求：

~~~sh
curl -sS -X POST \
  -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/api/login"
~~~

点击动作已发起：

~~~json
{"state":"mobile_confirmation"}
~~~

HTTP 状态为 200。

未找到可点击的 292x396 登录窗口时返回 HTTP 409：

~~~json
{"state":"login_required"}
~~~

这里的 state 是调用完成后的即时判断结果，实际值可能是 logged_in、login_required
或 unknown，不能替代后续的 /api/status 轮询。
建议等待手机确认后轮询状态：

~~~sh
while true; do
  curl -fsS -H "Authorization: Bearer $TOKEN" \
    "$BASE_URL/api/status"
  sleep 2
done
~~~

## 6. 抓取目标 Cookie

### GET /api/cookie
### POST /api/cookie

两个方法行为相同，均会执行一次抓取流程：

1. 确认微信处于 logged_in 状态。
2. 最小化可能遮挡聊天列表的旧网页窗口。
3. 激活微信主窗口。
4. 点击置顶聊天坐标 PINNED_CHAT_X,PINNED_CHAT_Y。
5. 等待聊天内容加载。
6. 点击最新消息链接坐标 OPEN_LINK_X,OPEN_LINK_Y。
7. 通过 mitmproxy 监听目标域名请求，从请求头读取 Cookie。
8. 将最新结果原子写入共享卷中的 latest-cookie.json。

默认坐标适配当前 1280x800、主窗口约 917x667 的固定布局：

~~~text
置顶聊天：350,185
最新链接：700,238
~~~

请求示例：

~~~sh
curl -sS --max-time 30 \
  -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/api/cookie"
~~~

成功响应：

~~~json
{
  "cookie": "name=value; another=value2",
  "host": "wx.weiweixiao.net",
  "url": "https://wx.weiweixiao.net/path/to/page",
  "updated_at": 1790963350.196888
}
~~~

响应字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| cookie | string | 目标请求 Cookie 请求头的完整字符串，应作为敏感凭据处理 |
| host | string | 捕获请求的目标主机 |
| url | string | 捕获请求的完整 URL，可能包含敏感查询参数 |
| updated_at | number | Cookie 捕获时间 |

Cookie 文件的默认路径是容器内 /data/latest-cookie.json，对应命名卷
wecookie_cookie-data。接口返回的 Cookie 可能来自本次请求，也可能是之前保存
的值：如果浏览器复用已有 Cookie、mitmproxy 没有看到新的 Cookie 请求头，服务会
在 COOKIE_REUSE_WAIT 时间内等待后返回已有文件内容。

错误响应：

| HTTP 状态 | error | 说明 |
| --- | --- | --- |
| 401 | unauthorized | 鉴权失败 |
| 404 | not_found | 路径错误 |
| 409 | wechat_not_logged_in | 微信尚未登录；响应包含当前 state |
| 409 | wechat_main_window_missing | 登录状态判断通过后，主窗口暂时消失 |
| 504 | cookie_capture_timeout | 等待内没有捕获 Cookie，且共享卷中没有可复用结果 |

未登录示例：

~~~json
{"error":"wechat_not_logged_in","state":"login_required"}
~~~

### 并发行为

Cookie 抓取使用进程内互斥锁。同一时间发起多个请求时，后续请求会等待前一个
抓取流程完成，不会并行操作微信窗口。调用方应避免高频并发调用。

## 7. 通用错误

除二维码接口外，错误响应均为：

~~~json
{"error":"<error-code>"}
~~~

当前通用错误码：

| HTTP 状态 | 错误码 | 触发条件 |
| --- | --- | --- |
| 401 | unauthorized | Token 缺失或错误 |
| 404 | not_found | GET/POST 请求使用了不支持的路径 |

服务当前未实现统一的请求 ID、分页、CORS 或 OpenAPI JSON 描述。未实现的 HTTP
方法由 Python HTTP 服务默认处理，通常返回 501，而不是上述 JSON 错误格式。

## 8. 配置项

运行配置位于 ~/Soft/wecookie/.env。其中 Token 按当前部署要求使用明文保存。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| API_TOKEN | 空 | Bearer Token；为空时关闭鉴权 |
| HTTP_PORT | 8090 | 宿主机映射端口，容器内固定为 8090 |
| TARGET_DOMAINS | wx.weiweixiao.net | mitmproxy 捕获的逗号分隔域名列表；匹配域名本身及其子域名 |
| COOKIE_TIMEOUT | 20 | 无历史 Cookie 时的最长捕获等待秒数 |
| COOKIE_SETTLE_SECONDS | 3.0 | 检测到文件更新后，等待流量稳定的秒数 |
| COOKIE_REUSE_WAIT | 6.0 | 已有 Cookie 但未检测到新请求时的最长等待秒数 |
| PINNED_CHAT_X | 350 | 置顶聊天点击 X 坐标 |
| PINNED_CHAT_Y | 185 | 置顶聊天点击 Y 坐标 |
| OPEN_LINK_X | 700 | 最新链接点击 X 坐标 |
| OPEN_LINK_Y | 238 | 最新链接点击 Y 坐标 |
| WINDOW_HIDE_DELAY | 0.5 | 隐藏旧网页窗口后的等待秒数 |
| FOCUS_DELAY | 0.8 | 激活微信主窗口后的等待秒数 |
| CHAT_OPEN_DELAY | 1.5 | 打开置顶聊天后的等待秒数 |
| MAIN_WINDOW_WIDTH | 917 | 主窗口尺寸匹配参考宽度 |
| MAIN_WINDOW_HEIGHT | 667 | 主窗口尺寸匹配参考高度 |

坐标依赖固定的 Xvfb 分辨率和微信窗口布局。改变窗口位置、尺寸、聊天排序或消息
内容后，应重新校准坐标并更新 .env。

## 9. 推荐调用流程

### 首次登录

~~~sh
BASE_URL='http://127.0.0.1:8090'
TOKEN='replace-with-your-token'

curl -fS -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/api/status"
curl -fS -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/api/qr" -o wechat-screen.png
curl -fS -X POST -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/api/login"

# 在手机上确认后，再检查状态
curl -fS -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/api/status"
~~~

### 获取 Cookie

~~~sh
curl -fS --max-time 30 \
  -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/api/cookie"
~~~

调用方应将 cookie 和 url 字段视为秘密，避免写入普通日志、错误追踪系统或
聊天消息。Cookie 失效时，重新调用接口即可触发页面加载并获取最新值。

## 10. 部署与重启

~~~sh
cd ~/Soft/wecookie
docker compose config --quiet
docker compose up -d --build
docker compose ps
~~~

不要使用 docker compose down -v，否则会删除微信登录资料和 Cookie 数据卷。
