"""Select a macOS browser for an isolated official Codex sign-in."""
import json
import plistlib
import queue
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from process_launch import external_environment


_LIST_BROWSERS = '''
ObjC.import("AppKit");
const url = $.NSURL.URLWithString("https://auth.openai.com/");
const apps = $.NSWorkspace.sharedWorkspace.URLsForApplicationsToOpenURL(url);
JSON.stringify(ObjC.deepUnwrap(apps.valueForKey("path")));
'''


def installed_macos_browsers():
    try:
        result = subprocess.run(
            ['/usr/bin/osascript', '-l', 'JavaScript', '-e', _LIST_BROWSERS],
            capture_output=True, text=True, check=True, timeout=2,
            env=external_environment(),
        )
        paths = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    if not isinstance(paths, list):
        return []

    browsers = {}
    for location in paths:
        if not isinstance(location, str):
            continue
        path = Path(location)
        if not path.is_absolute() or path.suffix != '.app' or any(parent.suffix == '.app' for parent in path.parents):
            continue
        if '.cache' in path.parts or path.is_relative_to(Path.home() / 'Library/Caches'):
            continue
        try:
            with (path / 'Contents/Info.plist').open('rb') as stream:
                app = plistlib.load(stream)
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
        # Some apps register HTTPS only to open their own links.
        handles_html = any(
            'public.html' in item.get('LSItemContentTypes', ())
            or 'html' in item.get('CFBundleTypeExtensions', ())
            for item in app.get('CFBundleDocumentTypes', ())
        )
        identifier = app.get('CFBundleIdentifier')
        if handles_html and isinstance(identifier, str) and identifier:
            name = app.get('CFBundleDisplayName') or path.stem
            browsers.setdefault(identifier.casefold(), (name, path))
    return sorted(browsers.values(), key=lambda browser: browser[0].casefold())


def open_login_url(browser, url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'auth.openai.com'
            or parsed.path != '/oauth/authorize'):
        raise OSError('Codex 返回了无法识别的登录地址。')
    try:
        subprocess.run(
            ['/usr/bin/open', '-a', str(browser), url], check=True, timeout=10,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=external_environment(),
        )
    except (OSError, subprocess.SubprocessError):
        raise OSError('无法打开所选浏览器，请重新选择浏览器后重试。') from None


def login_with_browser(command, env, browser, timeout=240):
    """Let the official client own the callback and write credentials to its temporary home."""
    from quota import close_cli
    from version import VERSION

    messages = queue.Queue()
    process = subprocess.Popen(
        command, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace',
    )

    def receive():
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if isinstance(message, dict):
                    messages.put(message)
        finally:
            messages.put(None)

    def send(method, request_id=None, params=None):
        message = {'method': method}
        if request_id is not None:
            message.update(id=request_id, params=params)
        process.stdin.write(json.dumps(message) + '\n')
        process.stdin.flush()

    def wait_for(matches, wait_seconds, timeout_message):
        deadline = time.monotonic() + wait_seconds
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                message = messages.get(timeout=remaining)
            except queue.Empty:
                break
            if message is None:
                raise OSError('Codex 登录进程提前退出，请重试。')
            if matches(message):
                return message
        raise TimeoutError(timeout_message)

    def response(request_id):
        message = wait_for(
            lambda item: item.get('id') == request_id, 20, '启动 Codex 登录通道超时。',
        )
        if 'error' in message or not isinstance(message.get('result'), dict):
            raise OSError('Codex 无法启动指定浏览器登录。可重试或选择系统默认浏览器。')
        return message['result']

    reader = threading.Thread(target=receive, daemon=True)
    reader.start()
    try:
        send('initialize', 1, {'clientInfo': {'name': 'bailong', 'version': VERSION}})
        response(1)
        send('initialized')
        send('account/login/start', 2, {'type': 'chatgpt'})
        login = response(2)
        login_id, url = login.get('loginId'), login.get('authUrl')
        if login.get('type') != 'chatgpt' or not login_id or not isinstance(url, str):
            raise OSError('Codex 未返回有效的浏览器登录请求。')
        open_login_url(browser, url)
        completion = wait_for(
            lambda item: item.get('method') == 'account/login/completed'
            and (item.get('params') or {}).get('loginId') == login_id,
            timeout, '未在规定时间内完成浏览器授权，请重试。',
        )
        if completion['params'].get('success') is not True:
            raise OSError('Codex 浏览器授权未成功，请重试。')
    finally:
        close_cli(process)
        reader.join(timeout=1)
