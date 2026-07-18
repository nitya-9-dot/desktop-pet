from pathlib import Path
import os
import time

import objc
import Quartz

from AppKit import (
    NSApplication,
    NSWindow,
    NSBackingStoreBuffered,
    NSWindowStyleMaskBorderless,
    NSColor,
    NSFloatingWindowLevel,
    NSImageView,
    NSScreen,
    NSEvent,
    NSEventMaskLeftMouseDown,
    NSEventMaskMouseMoved,
    NSView,
    NSBezierPath,
    NSWorkspace,
)

from Foundation import (
    NSObject,
    NSMakeRect,
    NSMakePoint,
    NSTimer,
)

from animation import SpriteSheet
from reminders import ReminderSchedule


class TimerDelegate(NSObject):
    def initWithWindow_(self, window):
        self = objc.super(TimerDelegate, self).init()
        if self is None:
            return None

        self.window = window
        return self

    def tick_(self, timer):
        self.window.update()


class ReminderDelegate(NSObject):
    def initWithWindow_(self, window):
        self = objc.super(ReminderDelegate, self).init()
        if self is None:
            return None
        self.window = window
        return self

    def tick_(self, timer):
        for alert_type, message in self.window.reminders.due_reminders():
            self.window.enqueue_alert(alert_type, message)


class WebOverlayView(NSView):
    """A click-through layer that draws the web while the pet is in the air."""

    def initWithFrame_pet_(self, frame, pet):
        self = objc.super(WebOverlayView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.pet = pet
        return self

    def drawRect_(self, dirty_rect):
        if self.pet.web_start is None or self.pet.web_target is None:
            return

        origin = self.pet.screen_origin
        start = self.pet.web_start
        target = self.pet.web_target
        path = NSBezierPath.bezierPath()
        path.setLineWidth_(2.0)
        path.moveToPoint_(NSMakePoint(start.x - origin.x, start.y - origin.y))
        path.lineToPoint_(NSMakePoint(target.x - origin.x, target.y - origin.y))
        NSColor.whiteColor().colorWithAlphaComponent_(0.85).setStroke()
        path.stroke()


class DesktopPetWindow:
    IDLE = "idle"
    JUMP = "jump"
    WALK = "walk"
    ALERT = "alert"
    SLEEP = "sleep"

    def __init__(self):

        self.app = NSApplication.sharedApplication()

        screen = NSScreen.mainScreen().frame()

        self.screen_origin = screen.origin
        self.screen_width = screen.size.width
        self.screen_height = screen.size.height

        self.width = 128
        self.height = 128

        self.x = 200
        self.y = 150

        self.dx = 4
        self.pet_is_visible = True
        self.last_mouse_movement = time.monotonic()
        self.obstacles = []
        self.obstacles_checked_at = 0.0
        self.web_start = None
        self.web_target = None
        self.flight_start = None
        self.flight_target = None

        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(
                self.x,
                self.y,
                self.width,
                self.height,
            ),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )

        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(NSColor.clearColor())
        self.window.setHasShadow_(False)
        self.window.setLevel_(NSFloatingWindowLevel)

        self.web_window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            screen,
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        self.web_window.setOpaque_(False)
        self.web_window.setBackgroundColor_(NSColor.clearColor())
        self.web_window.setHasShadow_(False)
        self.web_window.setIgnoresMouseEvents_(True)
        self.web_window.setLevel_(NSFloatingWindowLevel - 1)
        self.web_view = WebOverlayView.alloc().initWithFrame_pet_(
            NSMakeRect(0, 0, self.screen_width, self.screen_height), self
        )
        self.web_window.setContentView_(self.web_view)

        assets = Path(__file__).parent / "assets"

        self.walk_right = SpriteSheet(
            assets / "walk_right.png",
            15,
        )

        self.walk_left = SpriteSheet(
            assets / "walk_left.png",
            15,
        )

        self.idle = SpriteSheet(assets / "idle.png", 12)
        self.jump = SpriteSheet(assets / "jump.png", 15)
        self.sleep = SpriteSheet(assets / "sleep.png", 10, (128, 128))
        self.food_alert = SpriteSheet(assets / "food_alert.png", 10, (128, 128))
        self.water_alert = SpriteSheet(assets / "water_alert.png", 10, (128, 128))

        self.current = self.idle
        self.state = self.IDLE
        self.state_frames = 0
        self.walk_frames = 0
        self.idle_duration = self.idle.frame_count * 2
        self.walk_duration = 12 * 8
        self.alert_queue = []
        self.reminders = ReminderSchedule()

        self.image = NSImageView.alloc().initWithFrame_(
            NSMakeRect(
                0,
                0,
                self.width,
                self.height,
            )
        )

        self.image.setImage_(self.current.next_frame())

        self.window.setContentView_(self.image)

        self.window.makeKeyAndOrderFront_(None)

        self.app.activateIgnoringOtherApps_(True)

        self.timer = TimerDelegate.alloc().initWithWindow_(self)

        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1 / 12,
            self.timer,
            "tick:",
            None,
            True,
        )

        self.reminder_timer = ReminderDelegate.alloc().initWithWindow_(self)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0,
            self.reminder_timer,
            "tick:",
            None,
            True,
        )

        # A global monitor catches desktop clicks; the local monitor catches
        # clicks while this app is active.  Both leave the click untouched.
        self.global_click_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskLeftMouseDown, self._handle_global_click
        )
        self.local_click_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskLeftMouseDown, self._handle_local_click
        )
        self.global_mouse_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskMouseMoved, self._record_mouse_movement
        )
        self.local_mouse_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskMouseMoved, self._handle_local_mouse_movement
        )

    def update(self):
        self._update_visibility()

        if self.state != self.ALERT and time.monotonic() - self.last_mouse_movement >= 20:
            if self.state != self.SLEEP:
                self._start_animation(self.SLEEP, self.sleep)

        if self.state == self.SLEEP:
            pass
        elif self.state == self.ALERT:
            self.state_frames += 1
            if self.state_frames >= self.current.frame_count * 2:
                self._show_next_alert()
        elif self.state == self.WALK:
            self._walk()
        elif self.state == self.JUMP and self.flight_target is not None:
            self._jump_to_target()
        else:
            self.state_frames += 1

            if self.state == self.IDLE and self.state_frames >= self.idle_duration:
                self._start_animation(self.WALK, self._walking_sheet())

        self.image.setImage_(self.current.next_frame())

        self.window.setFrame_display_(
            NSMakeRect(
                self.x,
                self.y,
                self.width,
                self.height,
            ),
            True,
        )

    def _walk(self):
        if self._pet_overlaps_obstacle():
            self.x, self.y = self._safe_position(self.x, self.y)

        self.x += self.dx
        self.walk_frames += 1

        if self.x <= self.screen_origin.x:
            self.x = self.screen_origin.x
            self.dx = abs(self.dx)
            self._set_animation(self.walk_right)

        elif self.x >= self.screen_origin.x + self.screen_width - self.width:
            self.x = self.screen_origin.x + self.screen_width - self.width
            self.dx = -abs(self.dx)
            self._set_animation(self.walk_left)

        if self._pet_overlaps_obstacle():
            self.dx = -self.dx
            self._set_animation(self._walking_sheet())
            self.x, self.y = self._safe_position(self.x, self.y)

        if self.walk_frames >= self.walk_duration:
            self._start_animation(self.IDLE, self.idle)

    def _walking_sheet(self):
        return self.walk_right if self.dx > 0 else self.walk_left

    def enqueue_alert(self, alert_type, message):
        """Queue a food or water sheet; alerts never overlap or get lost."""
        self.alert_queue.append((alert_type, message))
        if self.state != self.ALERT:
            self._show_next_alert()

    def _show_next_alert(self):
        if not self.alert_queue:
            self._start_animation(self.IDLE, self.idle)
            return

        alert_type, message = self.alert_queue.pop(0)
        animation = self.food_alert if alert_type == "food" else self.water_alert
        self._start_animation(self.ALERT, animation)
        # Floating level plus this call keeps the alert visible above whichever
        # normal app window the user is currently working in.
        self.window.orderFrontRegardless()
        print(message)

    def _update_visibility(self):
        """Keep the pet on the Finder desktop, except while showing an alert."""
        should_show = self.state == self.ALERT or self._desktop_is_active()
        if should_show and not self.pet_is_visible:
            self.window.orderFrontRegardless()
            self.pet_is_visible = True
        elif not should_show and self.pet_is_visible:
            self.window.orderOut_(None)
            self.pet_is_visible = False

    def _handle_global_click(self, event):
        self._record_mouse_movement(event)
        self._handle_screen_click(event.locationInWindow())

    def _handle_local_click(self, event):
        self._record_mouse_movement(event)
        point = event.locationInWindow()
        if event.window() is self.window:
            point = self.window.convertPointToScreen_(point)
        self._handle_screen_click(point)
        return event

    def _record_mouse_movement(self, event):
        self.last_mouse_movement = time.monotonic()
        if self.state == self.SLEEP:
            self._start_animation(self.IDLE, self.idle)

    def _handle_local_mouse_movement(self, event):
        self._record_mouse_movement(event)
        return event

    def _handle_screen_click(self, point):
        """Idle when clicked directly; otherwise web-swing to the click."""
        if self.x <= point.x <= self.x + self.width and self.y <= point.y <= self.y + self.height:
            self._hide_web()
            self.flight_target = None
            self._start_animation(self.IDLE, self.idle)
            return

        if not self._desktop_is_active():
            return

        target_x = min(
            max(point.x - self.width / 2, self.screen_origin.x),
            self.screen_origin.x + self.screen_width - self.width,
        )
        target_y = min(
            max(point.y - self.height / 2, self.screen_origin.y),
            self.screen_origin.y + self.screen_height - self.height,
        )
        target_x, target_y = self._safe_position(target_x, target_y)
        self.flight_start = NSMakePoint(self.x, self.y)
        self.flight_target = NSMakePoint(target_x, target_y)
        self.web_start = NSMakePoint(self.x + self.width / 2, self.y + self.height / 2)
        self.web_target = NSMakePoint(point.x, point.y)
        self.web_window.orderFront_(None)
        self.web_view.setNeedsDisplay_(True)
        self._start_animation(self.JUMP, self.jump)

    @staticmethod
    def _desktop_is_active():
        """Web-swinging is enabled only while macOS Finder's desktop is active."""
        active_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return active_app is not None and active_app.bundleIdentifier() == "com.apple.finder"

    def _jump_to_target(self):
        self.state_frames += 1
        progress = min(self.state_frames / self.jump.frame_count, 1.0)
        arc_height = min(110, abs(self.flight_target.x - self.flight_start.x) * 0.2 + 45)
        self.x = self.flight_start.x + (self.flight_target.x - self.flight_start.x) * progress
        self.y = (
            self.flight_start.y
            + (self.flight_target.y - self.flight_start.y) * progress
            + 4 * arc_height * progress * (1 - progress)
        )

        if progress >= 1.0:
            self.x, self.y = self.flight_target.x, self.flight_target.y
            self.flight_target = None
            self._hide_web()
            self._start_animation(self.IDLE, self.idle)

    def _hide_web(self):
        self.web_start = None
        self.web_target = None
        self.web_window.orderOut_(None)

    def _visible_obstacles(self):
        """Return visible document/widget bounds in AppKit's bottom-left space."""
        now = time.monotonic()
        if now - self.obstacles_checked_at < 1.0:
            return self.obstacles

        self.obstacles_checked_at = now
        obstacles = []
        try:
            windows = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionOnScreenOnly,
                Quartz.kCGNullWindowID,
            )
            for window in windows:
                if window.get(Quartz.kCGWindowOwnerPID) == os.getpid():
                    continue
                if window.get(Quartz.kCGWindowAlpha, 1.0) <= 0:
                    continue
                bounds = window.get(Quartz.kCGWindowBounds)
                if not bounds:
                    continue
                width, height = bounds['Width'], bounds['Height']
                if width < 80 or height < 80:
                    continue
                # Ignore the desktop/background itself; only avoid documents,
                # widgets, and other visible floating windows.
                if width >= self.screen_width * 0.95 and height >= self.screen_height * 0.95:
                    continue
                x = self.screen_origin.x + bounds['X']
                y = self.screen_origin.y + self.screen_height - bounds['Y'] - height
                obstacles.append((x, y, width, height))
        except Exception:
            # macOS can withhold other-app window data until Screen Recording
            # permission is granted. Edge avoidance still works in that case.
            obstacles = []

        self.obstacles = obstacles
        return obstacles

    def _pet_overlaps_obstacle(self, x=None, y=None):
        x = self.x if x is None else x
        y = self.y if y is None else y
        padding = 12
        for left, bottom, width, height in self._visible_obstacles():
            if (
                x + self.width + padding > left
                and x - padding < left + width
                and y + self.height + padding > bottom
                and y - padding < bottom + height
            ):
                return True
        return False

    def _safe_position(self, x, y):
        """Find a nearby on-screen spot that does not cover a visible window."""
        min_x = self.screen_origin.x
        max_x = min_x + self.screen_width - self.width
        min_y = self.screen_origin.y
        max_y = min_y + self.screen_height - self.height

        def clamp(candidate_x, candidate_y):
            return min(max(candidate_x, min_x), max_x), min(max(candidate_y, min_y), max_y)

        candidates = [(x, y)]
        for distance in (160, 320, 480):
            candidates.extend(
                [
                    (x - distance, y),
                    (x + distance, y),
                    (x, y - distance),
                    (x, y + distance),
                ]
            )

        for candidate_x, candidate_y in candidates:
            candidate_x, candidate_y = clamp(candidate_x, candidate_y)
            if not self._pet_overlaps_obstacle(candidate_x, candidate_y):
                return candidate_x, candidate_y

        # If the whole screen is occupied, remain safely clamped on-screen.
        return clamp(x, y)

    def _set_animation(self, animation):
        """Switch direction and start the destination walk cycle at frame one."""
        if self.current is not animation:
            self.current = animation
            self.current.reset()

    def _start_animation(self, state, animation):
        """Start a non-walking animation from its first frame."""
        self.state = state
        self.state_frames = 0
        self.walk_frames = 0
        self.current = animation
        self.current.reset()

    def run(self):
        self.app.run()
