import asyncio
import math
import app
import json
import os
from events.input import BUTTON_TYPES, ButtonDownEvent, ButtonUpEvent
from tildagonos import tildagonos
from system.eventbus import eventbus
from app_components import Menu, TextDialog, clear_background
from system.patterndisplay.events import PatternDisable, PatternEnable

BUTTON_NUM_TO_NAME = {
    1: "UP",
    2: "RIGHT",
    3: "CONFIRM",
    4: "DOWN",
    5: "LEFT",
    6: "CANCEL"
}
BUTTON_NAME_TO_NUM = {v: k for k, v in BUTTON_NUM_TO_NAME.items()}

class SimpleSurveyApp(app.App):
    def __init__(self):
        super().__init__()
        self.state = "MAIN_MENU"
        self.menu = None
        self.dialog = None
        self.overlays = []
        self.surveys = []
        self.current_survey = None
        self.is_running = True
        self._render_update = None
        self._menu_result = None
        self.success_color = None
        self.success_label = ""
        self.success_button = 1
        self.anim_time = 0.0
        self.animation_duration = 2.0
        self.fade_duration = 0.5
        self.cancel_is_held = False
        self.cancel_press_time = 0.0
        
        # Load surveys from JSON
        self._load_surveys()
        
        # Initialize main menu
        self._init_main_menu()
        
        # Register for button events
        eventbus.on(ButtonDownEvent, self._handle_buttondown, self)
        eventbus.on(ButtonUpEvent, self._handle_buttonup, self)

    def minimise(self):
        from system.scheduler.events import RequestStopAppEvent
        eventbus.emit(RequestStopAppEvent(self))

    def _load_surveys(self):
        try:
            try:
                # Find path relative to app.py
                app_dir = os.path.dirname(__file__)
                if not app_dir:
                    app_dir = "."
            except Exception:
                app_dir = "."
            
            self.data_path = os.path.join(app_dir, "surveys.json")
            
            with open(self.data_path, "r") as f:
                self.surveys = json.load(f)
        except Exception as e:
            print(f"Error loading surveys: {e}")
            self.surveys = []

    def _save_surveys(self):
        try:
            with open(self.data_path, "w") as f:
                json.dump(self.surveys, f)
        except Exception as e:
            print(f"Error saving surveys: {e}")

    def _init_main_menu(self):
        if self.menu:
            self.menu._cleanup()
            
        menu_items = [s["name"] for s in self.surveys] + ["Create Survey", "Exit"]
        self.menu = Menu(
            self,
            menu_items=menu_items,
            select_handler=self._handle_main_menu_select,
            back_handler=self._handle_main_menu_back
        )

    def _handle_main_menu_select(self, item, idx):
        if item == "Create Survey":
            self.state = "CREATING"
        elif item == "Exit":
            self._cleanup_all()
            self.minimise()
        else:
            # Selected a survey
            self.current_survey = self.surveys[idx]
            self.state = "SURVEY_MENU"
            self._init_survey_menu()

    def _handle_main_menu_back(self):
        self._cleanup_all()
        self.minimise()

    def _init_survey_menu(self):
        if self.menu:
            self.menu._cleanup()
            
        self.menu = Menu(
            self,
            menu_items=["Start Polling", "View Results", "Delete Survey", "Back"],
            select_handler=self._handle_survey_menu_select,
            back_handler=self._go_to_main_menu
        )

    def _handle_survey_menu_select(self, item, idx):
        if item == "Start Polling":
            if self.menu:
                self.menu._cleanup()
                self.menu = None
            self.state = "ACTIVE_POLLING"
            self._set_option_leds()
        elif item == "View Results":
            if self.menu:
                self.menu._cleanup()
                self.menu = None
            self.state = "VIEW_RESULTS"
        elif item == "Delete Survey":
            self.surveys.remove(self.current_survey)
            self._save_surveys()
            self.current_survey = None
            self._go_to_main_menu()
        elif item == "Back":
            self._go_to_main_menu()

    def _go_to_main_menu(self):
        self.state = "MAIN_MENU"
        self._init_main_menu()

    def _handle_menu_select(self, item, idx):
        self._menu_result = item

    async def _run_creator_flow(self):
        self.state = "CREATING_IN_PROGRESS"
        
        # 1. Get Survey Name
        dialog = TextDialog("Survey Name", self)
        name = await dialog.run(self._render_update)
        if not name:
            self.state = "MAIN_MENU"
            self._init_main_menu()
            return

        # 2. Get Question
        dialog = TextDialog("Question", self)
        question = await dialog.run(self._render_update)
        if not question:
            self.state = "MAIN_MENU"
            self._init_main_menu()
            return

        # 3. Get Options
        options = []
        color_options = [
            ("Red", [255, 0, 0]),
            ("Yellow", [255, 255, 0]),
            ("Green", [0, 255, 0]),
            ("Cyan", [0, 255, 255]),
            ("Blue", [0, 0, 255]),
            ("Magenta", [255, 0, 255]),
            ("Orange", [255, 128, 0]),
            ("White", [255, 255, 255])
        ]
        preferred_buttons = [1, 4, 2, 5, 3, 6]
        
        for i in range(6):
            dialog = TextDialog(f"Opt {i+1} Label (blank to end)", self)
            label = await dialog.run(self._render_update)
            if not label:
                break
                
            # Select color using Menu
            color_items = [c[0] for c in color_options]
            self._menu_result = None
            if self.menu:
                self.menu._cleanup()
                
            self.menu = Menu(
                self,
                menu_items=color_items,
                select_handler=self._handle_menu_select
            )
            await self._render_update()
            
            while self._menu_result is None:
                await asyncio.sleep(0.05)
                
            color_name = self._menu_result
            self._menu_result = None
            
            color_val = [255, 255, 255]
            for c in color_options:
                if c[0] == color_name:
                    color_val = c[1]
                    break
                    
            # Select Button mapping using Menu
            assigned_buttons = [opt["button"] for opt in options]
            available_buttons = [b for b in preferred_buttons if b not in assigned_buttons]
            button_items = [f"Button {b} ({BUTTON_NUM_TO_NAME[b]})" for b in available_buttons]
            
            if self.menu:
                self.menu._cleanup()
                
            self.menu = Menu(
                self,
                menu_items=button_items,
                select_handler=self._handle_menu_select
            )
            await self._render_update()
            
            while self._menu_result is None:
                await asyncio.sleep(0.05)
                
            button_choice = self._menu_result
            self._menu_result = None
            
            chosen_btn = int(button_choice.split(" ")[1])
            
            options.append({
                "label": label,
                "color": color_val,
                "button": chosen_btn,
                "votes": 0
            })
            
        if len(options) == 0:
            self.state = "MAIN_MENU"
            self._init_main_menu()
            return
            
        import time
        survey_id = f"survey_{int(time.time())}"
        self.surveys.append({
            "id": survey_id,
            "name": name,
            "question": question,
            "options": options
        })
        self._save_surveys()
        
        self.state = "MAIN_MENU"
        self._init_main_menu()
        await self._render_update()

    def _get_btn_num(self, event):
        for k, v in BUTTON_TYPES.items():
            if v in event.button:
                return BUTTON_NAME_TO_NUM.get(k)
        return None

    def _handle_buttondown(self, event):
        if self.dialog:
            return
        if self.state in ["MAIN_MENU", "SURVEY_MENU", "CREATING_IN_PROGRESS"]:
            return
            
        btn_num = self._get_btn_num(event)
        
        if self.state == "ACTIVE_POLLING":
            if btn_num == 6:
                # If there's an option on button 6, use hold timeout, otherwise exit immediately
                has_btn_6_option = any(opt["button"] == 6 for opt in self.current_survey["options"])
                if has_btn_6_option:
                    self.cancel_is_held = True
                    self.cancel_press_time = 0.0
                    if self._render_update:
                        asyncio.create_task(self._render_update())
                else:
                    self._clear_leds()
                    self.state = "SURVEY_MENU"
                    self._init_survey_menu()
                    if self._render_update:
                        asyncio.create_task(self._render_update())
                return
            elif btn_num is not None:
                self._record_vote(btn_num)
        elif self.state == "VIEW_RESULTS":
            if btn_num == 6:
                self.state = "SURVEY_MENU"
                self._init_survey_menu()
                if self._render_update:
                    asyncio.create_task(self._render_update())

    def _handle_buttonup(self, event):
        if self.dialog:
            return
        if self.state in ["MAIN_MENU", "SURVEY_MENU", "CREATING_IN_PROGRESS"]:
            return
            
        btn_num = self._get_btn_num(event)
        if self.state == "ACTIVE_POLLING" and btn_num == 6:
            if self.cancel_is_held:
                duration = self.cancel_press_time
                self.cancel_is_held = False
                self.cancel_press_time = 0.0
                if duration < 3.0:
                    self._record_vote(6)
                if self._render_update:
                    asyncio.create_task(self._render_update())

    def _record_vote(self, btn_num):
        opt = None
        for o in self.current_survey["options"]:
            if o["button"] == btn_num:
                opt = o
                break
                
        if opt is not None:
            opt["votes"] += 1
            self._save_surveys()
            
            self.state = "VOTE_SUCCESS"
            self.success_color = opt["color"]
            self.success_label = opt["label"]
            self.success_button = opt["button"]
            self.anim_time = 0.0
            
            self._update_success_leds(self.success_button, self.success_color, 0.0)
            if self._render_update:
                asyncio.create_task(self._render_update())

    def _set_option_leds(self):
        eventbus.emit(PatternDisable())
        for i in range(19):
            tildagonos.leds[i] = (0, 0, 0)
            
        for opt in self.current_survey["options"]:
            btn_num = opt["button"]
            color = opt["color"]
            leds = self._get_button_leds(btn_num)
            for led_idx in leds:
                tildagonos.leds[led_idx] = tuple(color)
        tildagonos.leds.write()

    def _set_all_leds(self, color):
        eventbus.emit(PatternDisable())
        for i in range(19):
            tildagonos.leds[i] = tuple(color)
        tildagonos.leds.write()

    def _clear_leds(self):
        for i in range(19):
            tildagonos.leds[i] = (0, 0, 0)
        tildagonos.leds.write()
        eventbus.emit(PatternEnable())

    def _get_button_leds(self, button_num):
        if button_num == 1:
            return [12, 1]
        else:
            idx = (button_num - 1) * 2
            return [idx, idx + 1]

    def _cleanup_all(self):
        if self.menu:
            self.menu._cleanup()
            self.menu = None
        if self.dialog:
            self.dialog._cleanup()
            self.dialog = None
        self._clear_leds()
        eventbus.remove(ButtonDownEvent, self._handle_buttondown, self)
        eventbus.remove(ButtonUpEvent, self._handle_buttonup, self)

    def _update_success_leds(self, button_num, color, t):
        eventbus.emit(PatternDisable())
        for i in range(19):
            tildagonos.leds[i] = (0, 0, 0)
            
        T_prop = 1.0
        outer_leds = [12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        
        i1 = (button_num - 1) * 2
        i2 = i1 + 1
        
        if t >= self.animation_duration:
            # Fade out
            fade_pct = max(0.0, 1.0 - (t - self.animation_duration) / self.fade_duration)
            faded = tuple(int(c * fade_pct) for c in color)
            for led_idx in outer_leds:
                tildagonos.leds[led_idx] = faded
        elif t >= T_prop:
            # All outer LEDs lit
            for led_idx in outer_leds:
                tildagonos.leds[led_idx] = tuple(color)
        else:
            # Propagating
            step = int((t / T_prop) * 6)
            for j in range(step + 1):
                idx_l = (i1 - j) % 12
                idx_r = (i2 + j) % 12
                tildagonos.leds[outer_leds[idx_l]] = tuple(color)
                tildagonos.leds[outer_leds[idx_r]] = tuple(color)
                
        tildagonos.leds.write()

    def update(self, delta):
        dt = delta / 1000.0
        if self.state in ["MAIN_MENU", "SURVEY_MENU", "CREATING_IN_PROGRESS"] and self.menu:
            self.menu.update(delta)
            
        if self.state == "ACTIVE_POLLING" and self.cancel_is_held:
            self.cancel_press_time += dt
            if self.cancel_press_time >= 3.0:
                self.cancel_is_held = False
                self.cancel_press_time = 0.0
                self._clear_leds()
                self.state = "SURVEY_MENU"
                self._init_survey_menu()
                if self._render_update:
                    asyncio.create_task(self._render_update())
            
        if self.state == "VOTE_SUCCESS":
            self.anim_time += dt
            self._update_success_leds(self.success_button, self.success_color, self.anim_time)
            
            if self.anim_time >= self.animation_duration + self.fade_duration:
                self._clear_leds()
                self.state = "ACTIVE_POLLING"
                self._set_option_leds()
                if self._render_update:
                    asyncio.create_task(self._render_update())

    def _wrap_text(self, text, ctx, max_width):
        words = text.split(" ")
        lines = []
        current_line = ""
        for word in words:
            test_line = current_line + " " + word if current_line else word
            if ctx.text_width(test_line) <= max_width:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        return lines

    def _draw_circular_gauge(self, ctx, x, y, radius, thickness, options, draw_center_text=True):
        ctx.save()
        ctx.line_width = thickness
        
        total_votes = sum(o["votes"] for o in options)
        
        if total_votes == 0:
            ctx.rgb(0.15, 0.15, 0.15)
            ctx.begin_path()
            ctx.arc(x, y, radius, 0, 2 * math.pi, False).stroke()
            
            if draw_center_text:
                ctx.rgb(0.5, 0.5, 0.5)
                ctx.font_size = 14
                ctx.text_align = ctx.CENTER
                ctx.text_baseline = ctx.MIDDLE
                ctx.move_to(x, y).text("0")
        else:
            start_angle = -math.pi / 2
            for opt in options:
                votes = opt["votes"]
                if votes == 0:
                    continue
                pct = votes / total_votes
                angle_size = pct * 2 * math.pi
                end_angle = start_angle + angle_size
                
                color = opt["color"]
                color_float = tuple(c / 255.0 for c in color)
                ctx.rgb(*color_float)
                
                ctx.begin_path()
                ctx.arc(x, y, radius, start_angle, end_angle, False).stroke()
                start_angle = end_angle
                
            if draw_center_text:
                ctx.rgb(1.0, 1.0, 1.0)
                ctx.font_size = 14
                ctx.text_align = ctx.CENTER
                ctx.text_baseline = ctx.MIDDLE
                ctx.move_to(x, y).text(str(total_votes))
            
        ctx.restore()

    def _draw_option_labels(self, ctx, options):
        ctx.save()
        ctx.font_size = 11
        ctx.text_baseline = ctx.MIDDLE
        
        for opt in options:
            btn_num = opt["button"]
            lbl = opt["label"]
            votes = opt["votes"]
            color = opt["color"]
            color_float = tuple(c / 255.0 for c in color)
            
            ctx.rgb(*color_float)
            
            if btn_num == 1:
                ctx.text_align = ctx.CENTER
                ctx.move_to(0, -68).text(lbl)
                ctx.move_to(0, -56).text(f"({votes})")
            elif btn_num == 2:
                ctx.text_align = ctx.RIGHT
                ctx.move_to(75, -45).text(lbl)
                ctx.move_to(75, -33).text(f"({votes})")
            elif btn_num == 3:
                ctx.text_align = ctx.RIGHT
                ctx.move_to(75, 45).text(lbl)
                ctx.move_to(75, 57).text(f"({votes})")
            elif btn_num == 4:
                ctx.text_align = ctx.CENTER
                ctx.move_to(0, 68).text(lbl)
                ctx.move_to(0, 80).text(f"({votes})")
            elif btn_num == 5:
                ctx.text_align = ctx.LEFT
                ctx.move_to(-75, 45).text(lbl)
                ctx.move_to(-75, 57).text(f"({votes})")
            elif btn_num == 6:
                ctx.text_align = ctx.LEFT
                ctx.move_to(-75, -45).text(lbl)
                ctx.move_to(-75, -33).text(f"({votes})")
                
        ctx.restore()

    def _draw_active_question(self, ctx):
        ctx.save()
        # Title
        ctx.rgb(0.5, 0.8, 0.5)
        ctx.font_size = 10
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = getattr(ctx, "TOP", "top")
        ctx.move_to(0, -95).text(self.current_survey["name"])
        
        # Question
        ctx.rgb(1.0, 1.0, 1.0)
        ctx.font_size = 14
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        
        question = self.current_survey["question"]
        lines = self._wrap_text(question, ctx, 180)
        start_y = -40
        for idx, line in enumerate(lines[:3]):
            ctx.move_to(0, start_y + idx * 18).text(line)
            
        # Prompt
        ctx.rgb(0.7, 0.7, 0.7)
        ctx.font_size = 12
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        ctx.move_to(0, 40).text("Press any key")
        ctx.move_to(0, 56).text("to view options")
        
        # Exit instruction
        ctx.rgb(0.9, 0.3, 0.3)
        ctx.font_size = 9
        ctx.text_align = ctx.CENTER
        ctx.move_to(0, 85).text("CANCEL: Back")
        ctx.restore()

    def _draw_active_polling(self, ctx):
        ctx.save()
        
        # Circular gauge surrounding the screen
        self._draw_circular_gauge(ctx, 0, 0, 114, 6, self.current_survey["options"], draw_center_text=False)
        
        # Question in the center
        ctx.rgb(1.0, 1.0, 1.0)
        ctx.font_size = 13
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        
        question = self.current_survey["question"]
        lines = self._wrap_text(question, ctx, 130)
        
        total_votes = sum(o["votes"] for o in self.current_survey["options"])
        
        start_y = -((len(lines) + 1) * 8)
        for idx, line in enumerate(lines):
            ctx.move_to(0, start_y + idx * 16).text(line)
            
        ctx.rgb(0.7, 0.7, 0.7)
        ctx.font_size = 11
        ctx.move_to(0, start_y + len(lines) * 16 + 8).text(f"Votes: {total_votes}")
        
        # Option labels
        self._draw_option_labels(ctx, self.current_survey["options"])
        
        # Hold CANCEL button to exit note banner
        if self.cancel_is_held and self.cancel_press_time >= 1.0:
            ctx.save()
            ctx.rgb(0.08, 0.08, 0.08)
            ctx.rectangle(-85, -30, 170, 60).fill()
            ctx.rgb(0.8, 0.2, 0.2)
            ctx.line_width = 1.5
            ctx.rectangle(-85, -30, 170, 60).stroke()
            
            ctx.rgb(1.0, 1.0, 1.0)
            ctx.font_size = 11
            ctx.text_align = ctx.CENTER
            ctx.text_baseline = ctx.MIDDLE
            
            rem = max(1, int(4.0 - self.cancel_press_time))
            ctx.move_to(0, -12).text("Keep holding to return")
            ctx.move_to(0, 12).text(f"to menu in {rem}s...")
            ctx.restore()
            
        ctx.restore()

    def _draw_vote_success(self, ctx):
        ctx.save()
        
        # Calculate animation time and target colors
        t = self.anim_time
        color = self.success_color
        
        fade_pct = 1.0
        if t >= self.animation_duration:
            fade_pct = max(0.0, 1.0 - (t - self.animation_duration) / self.fade_duration)
            
        # Flood effect coordinates (distance from button)
        T_flood = 1.0
        if t < T_flood:
            r_flood = 2.5 * 120 * (t / T_flood)
        else:
            r_flood = 300
            
        # Find pressed button angle/coords
        btn_num = self.success_button
        theta = -math.pi / 2 + (btn_num - 1) * math.pi / 3
        xb = 120 * math.cos(theta)
        yb = 120 * math.sin(theta)
        
        # Draw background flood
        color_float = [c / 255.0 for c in color]
        ctx.rgb(color_float[0] * fade_pct, color_float[1] * fade_pct, color_float[2] * fade_pct)
        ctx.arc(xb, yb, r_flood, 0, 2 * math.pi, True).fill()
        
        # Calculate contrast text color
        brightness = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
        if brightness > 128:
            ctx.rgb(0, 0, 0)
        else:
            ctx.rgb(fade_pct, fade_pct, fade_pct)
            
        # Large text in center of screen
        ctx.font_size = 20
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        
        # Wrapping options label
        lines = self._wrap_text(self.success_label, ctx, 180)
        start_y = -((len(lines) - 1) * 12) - 10
        for idx, line in enumerate(lines):
            ctx.move_to(0, start_y + idx * 24).text(line)
            
        # Draw count below option text
        votes_count = 0
        for o in self.current_survey["options"]:
            if o["button"] == self.success_button:
                votes_count = o["votes"]
                break
        
        ctx.font_size = 14
        ctx.move_to(0, start_y + len(lines) * 24 + 10).text(f"Votes: {votes_count}")
            
        ctx.restore()

    def _draw_view_results(self, ctx):
        ctx.save()
        # Survey Name
        ctx.rgb(0.5, 0.8, 0.5)
        ctx.font_size = 10
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = getattr(ctx, "TOP", "top")
        ctx.move_to(0, -100).text(self.current_survey["name"])
        
        # Question
        ctx.rgb(1.0, 1.0, 1.0)
        ctx.font_size = 12
        question = self.current_survey["question"]
        lines = self._wrap_text(question, ctx, 180)
        for idx, line in enumerate(lines[:2]):
            ctx.move_to(0, -85 + idx * 14).text(line)
            
        # Gauge in middle
        self._draw_circular_gauge(ctx, 0, -5, 28, 8, self.current_survey["options"])
        
        # Option summary details
        start_y = 32
        options = self.current_survey["options"]
        total_votes = sum(o["votes"] for o in options)
        
        ctx.font_size = 10
        ctx.text_baseline = ctx.MIDDLE
        
        for idx, opt in enumerate(options[:6]):
            col = idx % 2
            row = idx // 2
            x = -80 if col == 0 else 10
            y = start_y + row * 16
            
            pct = (opt["votes"] / total_votes * 100) if total_votes > 0 else 0
            label_text = f"{opt['label']}: {opt['votes']} ({pct:.0f}%)"
            
            color = opt["color"]
            color_float = tuple(c / 255.0 for c in color)
            
            ctx.rgb(*color_float).rectangle(x, y - 4, 8, 8).fill()
            
            ctx.rgb(0.9, 0.9, 0.9)
            ctx.text_align = ctx.LEFT
            ctx.move_to(x + 12, y).text(label_text)
            
        ctx.rgb(0.6, 0.6, 0.6)
        ctx.font_size = 9
        ctx.text_align = ctx.CENTER
        ctx.move_to(0, 95).text("Press CANCEL to exit")
        ctx.restore()

    def draw(self, ctx):
        clear_background(ctx)
        
        if self.state in ["MAIN_MENU", "SURVEY_MENU", "CREATING_IN_PROGRESS"]:
            if self.menu:
                self.menu.draw(ctx)
        elif self.state == "ACTIVE_QUESTION":
            self._draw_active_question(ctx)
        elif self.state == "ACTIVE_POLLING":
            self._draw_active_polling(ctx)
        elif self.state == "VOTE_SUCCESS":
            self._draw_vote_success(ctx)
        elif self.state == "VIEW_RESULTS":
            self._draw_view_results(ctx)
            
        for overlay in self.overlays:
            overlay.draw(ctx)

    async def run(self, render_update):
        self._render_update = render_update
        eventbus.emit(PatternDisable())
        
        import time
        last_time = time.ticks_ms()
        while self.is_running:
            cur_time = time.ticks_ms()
            delta_ticks = time.ticks_diff(cur_time, last_time)
            
            if self.dialog:
                await self.dialog.run(render_update)
            else:
                self.update(delta_ticks)
                await render_update()
                
            if self.state == "CREATING":
                await self._run_creator_flow()
                
            await asyncio.sleep(0.05)
            last_time = cur_time

__app_export__ = SimpleSurveyApp
