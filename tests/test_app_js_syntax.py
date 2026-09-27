"""app.js обязан хотя бы разбираться браузером.

27.09 правка загрузки показа объявила `const still` второй раз в той же
функции. Все тесты прошли — они читают app.js как текст, — а приложение не
открылось бы ни у кого: браузер не запускает файл с синтаксической ошибкой
вовсе. Поймано только прогоном в браузере. Теперь файл разбирает node, тот
же движок, что у Chromium.
"""

import shutil
import subprocess

import pytest

NODE = shutil.which("node") or "/opt/node22/bin/node"


@pytest.mark.skipif(not shutil.which("node") and not __import__("os").path.exists(NODE),
                    reason="node не установлен")
def test_app_js_parses():
    result = subprocess.run([NODE, "--check", "webapp/static/app.js"],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr[-2000:]
