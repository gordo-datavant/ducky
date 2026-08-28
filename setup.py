from setuptools import setup

APP = ["ducky.py"]

PLIST = {
    "CFBundleName":               "Ducky",
    "CFBundleDisplayName":        "Ducky",
    "CFBundleIdentifier":         "com.ducky.app",
    "CFBundleShortVersionString": "1.0",
    "CFBundleVersion":            "1",
    "LSMinimumSystemVersion":     "12.0",
    "NSUserNotificationAlertStyle": "alert",
    "NSHighResolutionCapable":    True,
    "NSPrincipalClass":           "NSApplication",
}

OPTIONS = {
    "argv_emulation": False,
    "iconfile":       "assets/duck.icns",
    "plist":          PLIST,
    "packages":       ["objc"],
    "includes": [
        "AppKit",
        "Foundation",
        "Quartz",
        "UserNotifications",
    ],
    "resources": ["assets"],
}

setup(
    name="Ducky",
    app=APP,
    options={"py2app": OPTIONS},
)
