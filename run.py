#!/usr/bin/env python3
from navigator import Application
from navigator.ext.locale import LocaleSupport
from navigator.ext.memcache import Memcache
from app import Main

app = Application(Main, enable_jinja2=True)

## installing extensions:
mcache = Memcache()
mcache.setup(app)

# support localization:
locale = LocaleSupport(
    localization=[
        "en",
        "es",
        "pt",
        "en_US",
        "es_ES",
        "pt_BR",
        "it_IT",
        "fr_FR",
        "ja_JP",
        "ko_KR",
        "tr_TR",
        "de_DE",
        "zh_CN",
        "zh_TW",
        "zh_Hans_CN",
        "zh_Hant_TW"
    ],
    domain="nav"
)
locale.setup(app)

# Enable WebSockets Support
app.add_websockets()

if __name__ == "__main__":
    try:
        app.run()
    except KeyboardInterrupt:
        print("EXIT FROM APP =========")
