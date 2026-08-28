import enum
import math
import random
import time
import uuid

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSAttributedString,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSImage,
    NSInformationalRequest,
    NSMenu,
    NSMenuItem,
    NSObject,
    NSRectFill,
    NSSound,
)
from Foundation import NSBundle, NSMakePoint, NSMakeRect, NSMakeSize, NSTimer, NSURL
from Quartz import CIContext, CIFilter, CIImage
import UserNotifications


_LONELINESS_THRESHOLD = 600   # seconds before duck gets lonely
_PERK_DURATION        = 3.0   # seconds the PERKED state lasts
_QUACK_INTERVAL_MIN   = 300   # 5 min minimum quack interval
_QUACK_INTERVAL_MAX   = 900   # 15 min maximum quack interval
_QUACK_GAP            = 0.32  # seconds between repeated quacks

_QUACK_MESSAGES = {
    "happy":  ["Quack!", "Hey, still here!", "*rubber duck noises*", "Quack quack! 🐾"],
    "lonely": ["...quack?", "Did you forget about me? 🥺", "*sad quack*"],
    "perked": ["Quack!! 🎉", "There you are!!", "Back in action! 🦆"],
}


class DuckMood(enum.Enum):
    HAPPY  = "happy"
    LONELY = "lonely"
    PERKED = "perked"


_ci_context_singleton = None


def _ci_context():
    global _ci_context_singleton
    if _ci_context_singleton is None:
        _ci_context_singleton = CIContext.context()
    return _ci_context_singleton


def _load_sound_pool(resource_path: str, filename: str, size: int = 4) -> list:
    path = f"{resource_path}/{filename}"
    url  = NSURL.fileURLWithPath_(path)
    pool = []
    for _ in range(size):
        snd = NSSound.alloc().initWithContentsOfURL_byReference_(url, False)
        if snd is not None:
            pool.append(snd)
    return pool


def _make_duck_icon(
    source: NSImage,
    hue_shift: float = 0.0,
    saturation: float = 1.0,
    brightness: float = 0.0,
) -> NSImage:
    if hue_shift == 0.0 and saturation == 1.0 and brightness == 0.0:
        return source

    ci = CIImage.imageWithData_(source.TIFFRepresentation())

    if hue_shift != 0.0:
        f = CIFilter.filterWithName_("CIHueAdjust")
        f.setDefaults()
        f.setValue_forKey_(ci, "inputImage")
        f.setValue_forKey_(hue_shift, "inputAngle")
        ci = f.valueForKey_("outputImage")

    if saturation != 1.0 or brightness != 0.0:
        f = CIFilter.filterWithName_("CIColorControls")
        f.setDefaults()
        f.setValue_forKey_(ci, "inputImage")
        f.setValue_forKey_(saturation, "inputSaturation")
        f.setValue_forKey_(brightness, "inputBrightness")
        ci = f.valueForKey_("outputImage")

    cg = _ci_context().createCGImage_fromRect_(ci, ci.extent())
    return NSImage.alloc().initWithCGImage_size_(cg, source.size())


class AppDelegate(NSObject):
    def init(self):
        self = objc.super(AppDelegate, self).init()
        if self is None:
            return None
        self._mood              = DuckMood.HAPPY
        self._silent            = False
        self._last_tap          = time.time()
        self._icons             = {}
        self._pool_quack        = []     # round-robin NSSound pool, normal
        self._pool_chatter      = []     # round-robin NSSound pool, chattery
        self._pool_idx          = 0
        self._bonus_sounds      = []     # one-shot random bonus sounds
        self._quacks_remaining  = 0
        self._use_chatter       = False
        self._pat_streak        = 0      # consecutive pats for bonus quacks
        self._perk_timer        = None
        self._quack_timer       = None
        self._un_center         = None
        return self

    # -- NSApplicationDelegate ------------------------------------------------

    def applicationDidFinishLaunching_(self, notification):
        res = NSBundle.mainBundle().resourcePath()

        img_path  = f"{res}/assets/duck.png"
        base_icon = NSImage.alloc().initWithContentsOfFile_(img_path)
        if base_icon is None:
            size = 512.0
            font = NSFont.systemFontOfSize_(size * 0.80)
            astr = NSAttributedString.alloc().initWithString_attributes_(
                "🦆", {NSFontAttributeName: font}
            )
            ss        = astr.size()
            base_icon = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
            base_icon.lockFocus()
            NSColor.clearColor().set()
            NSRectFill(NSMakeRect(0, 0, size, size))
            astr.drawAtPoint_(NSMakePoint((size - ss.width) / 2, (size - ss.height) / 2))
            base_icon.unlockFocus()

        self._icons = {
            DuckMood.HAPPY:  _make_duck_icon(base_icon),
            DuckMood.LONELY: _make_duck_icon(base_icon, hue_shift=math.pi, saturation=0.4, brightness=-0.05),
            DuckMood.PERKED: _make_duck_icon(base_icon, saturation=1.8, brightness=0.1),
        }
        self._set_mood(DuckMood.HAPPY)

        self._pool_quack   = _load_sound_pool(res, "assets/sounds/quack.wav")
        self._pool_chatter = _load_sound_pool(res, "assets/sounds/quack_chatter.wav") or self._pool_quack

        sounds_dir = f"{res}/assets/sounds"
        import os
        if os.path.isdir(sounds_dir):
            for fname in os.listdir(sounds_dir):
                if fname.lower().endswith(".mp3"):
                    url = NSURL.fileURLWithPath_(f"{sounds_dir}/{fname}")
                    snd = NSSound.alloc().initWithContentsOfURL_byReference_(url, False)
                    if snd is not None:
                        self._bonus_sounds.append(snd)

        self._un_center = UserNotifications.UNUserNotificationCenter.currentNotificationCenter()
        opts = (
            UserNotifications.UNAuthorizationOptionAlert
            | UserNotifications.UNAuthorizationOptionSound
        )
        self._un_center.requestAuthorizationWithOptions_completionHandler_(
            opts, lambda granted, err: None
        )

        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            30.0, self, "checkLoneliness:", None, True
        )
        self._schedule_quack()

    def applicationShouldHandleReopen_hasVisibleWindows_(self, app, hasVisibleWindows):
        self._pat()
        return True

    def applicationDockMenu_(self, sender):
        menu  = NSMenu.alloc().init()

        title = "Silent Mode ✓" if self._silent else "Silent Mode"
        item  = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            title, "toggleSilent:", ""
        )
        item.setTarget_(self)
        menu.addItem_(item)

        login_on = self._login_item_enabled()
        title    = "Launch at Login ✓" if login_on else "Launch at Login"
        item     = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            title, "toggleLoginItem:", ""
        )
        item.setTarget_(self)
        menu.addItem_(item)

        return menu

    # -- Timer selectors ------------------------------------------------------

    def checkLoneliness_(self, timer):
        if self._mood == DuckMood.HAPPY:
            if time.time() - self._last_tap >= _LONELINESS_THRESHOLD:
                self._set_mood(DuckMood.LONELY)

    def finishPerk_(self, timer):
        self._perk_timer  = None
        self._last_tap    = time.time()
        self._pat_streak  = 0
        self._set_mood(DuckMood.HAPPY)

    def fireQuack_(self, timer):
        self._quack_timer = None
        if not self._silent:
            self._send_quack_notification()
        self._schedule_quack()

    def playNextQuack_(self, timer):
        if self._quacks_remaining > 0:
            self._fire_one_quack(self._use_chatter)
            self._quacks_remaining -= 1
            if self._quacks_remaining > 0:
                NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    _QUACK_GAP, self, "playNextQuack:", None, False
                )

    # -- Menu actions ---------------------------------------------------------

    def toggleSilent_(self, sender):
        self._silent   = not self._silent
        self._last_tap = time.time()

    def toggleLoginItem_(self, sender):
        try:
            from ServiceManagement import SMAppService
            service = SMAppService.mainAppService()
            if service.status() == 1:  # SMAppServiceStatusEnabled
                service.unregisterAndReturnError_(None)
            else:
                service.registerAndReturnError_(None)
        except Exception:
            pass
        self._last_tap = time.time()

    # -- Internal helpers -----------------------------------------------------

    @objc.python_method
    def _pat(self):
        self._last_tap   = time.time()
        self._pat_streak = min(self._pat_streak + 1, 6)
        if self._perk_timer is not None:
            self._perk_timer.invalidate()
            self._perk_timer = None
        was_lonely = self._mood == DuckMood.LONELY
        self._set_mood(DuckMood.PERKED)
        if not self._silent:
            NSApplication.sharedApplication().requestUserAttention_(NSInformationalRequest)
            if self._pat_streak >= 5 and self._bonus_sounds:
                # Enough pats — play a random bonus sound
                snd = random.choice(self._bonus_sounds)
                snd.stop()
                snd.play()
            else:
                # More pats = more quacks (capped at 5); lonely rescue always chattery
                base  = random.randint(2, 4) if was_lonely else random.randint(1, 2)
                count = min(base + self._pat_streak // 2, 5)
                self._play_quacks(count, chattery=was_lonely or self._pat_streak >= 4)
        self._perk_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            _PERK_DURATION, self, "finishPerk:", None, False
        )

    @objc.python_method
    def _play_quacks(self, count: int, chattery: bool = False):
        self._use_chatter      = chattery
        self._quacks_remaining = count - 1
        self._fire_one_quack(chattery)
        if self._quacks_remaining > 0:
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                _QUACK_GAP, self, "playNextQuack:", None, False
            )

    @objc.python_method
    def _fire_one_quack(self, chattery: bool = False):
        pool = self._pool_chatter if chattery else self._pool_quack
        if not pool:
            return
        snd = pool[self._pool_idx % len(pool)]
        self._pool_idx = (self._pool_idx + 1) % len(pool)
        snd.stop()
        snd.play()

    @objc.python_method
    def _login_item_enabled(self) -> bool:
        try:
            from ServiceManagement import SMAppService
            return SMAppService.mainAppService().status() == 1
        except Exception:
            return False

    @objc.python_method
    def _set_mood(self, mood: DuckMood):
        self._mood = mood
        NSApplication.sharedApplication().setApplicationIconImage_(self._icons[mood])

    @objc.python_method
    def _schedule_quack(self):
        delay = random.uniform(_QUACK_INTERVAL_MIN, _QUACK_INTERVAL_MAX)
        self._quack_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            delay, self, "fireQuack:", None, False
        )

    @objc.python_method
    def _send_quack_notification(self):
        content = UserNotifications.UNMutableNotificationContent.alloc().init()
        content.setTitle_("Quack! 🦆")
        content.setBody_(random.choice(_QUACK_MESSAGES[self._mood.value]))
        content.setSound_(UserNotifications.UNNotificationSound.defaultSound())
        req = UserNotifications.UNNotificationRequest.requestWithIdentifier_content_trigger_(
            str(uuid.uuid4()), content, None
        )
        self._un_center.addNotificationRequest_withCompletionHandler_(req, None)


def main():
    app      = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()


if __name__ == "__main__":
    main()
