import asyncio
import math
import app
import json
from events.input import BUTTON_TYPES, ButtonDownEvent
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
        self.success_timer = 0.0
        
        # Load surveys from JSON
        self._load_surveys()
        
        # Initialize main menu
        self._init_main_menu()
        
        # Register for button down events
        eventbus.on(ButtonDownEvent, self._handle_buttondown, self)

    def _load_surveys(self):
        try:
            import sys
            try:
                # Find path relative to app.py
                app_dir = "/".join(__file__.split("/")[:-1])
                if not app_dir:
                    app_dir = "."
            except Exception:
                app_dir = "."
            
            self.data_path = f"{app_dir}/surveys.json"
            
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
            self.state = "ACTIVE_QUESTION"
            self._clear_leds()
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

    def _handle_buttondown(self, event):
        if self.dialog:
            return
        if self.state in ["MAIN_MENU", "SURVEY_MENU", "CREATING_IN_PROGRESS"]:
            return
            
        if self.state == "ACTIVE_QUESTION":
            self._handle_active_question_button(event)
        elif self.state == "ACTIVE_POLLING":
            self._handle_active_polling_button(event)
        elif self.state == "VIEW_RESULTS":
            self._handle_view_results_button(event)

    def _handle_active_question_button(self, event):
        if event.button == BUTTON_TYPES["CANCEL"]:
            self.state = "SURVEY_MENU"
            self._init_survey_menu()
            if self._render_update:
                asyncio.create_task(self._render_update())
            return
            
        self.state = "ACTIVE_POLLING"
        self._set_option_leds()
        if self._render_update:
            asyncio.create_task(self._render_update())

    def _handle_active_polling_button(self, event):
        btn_num = None
        for k, v in BUTTON_TYPES.items():
            if event.button == v:
                btn_num = BUTTON_NAME_TO_NUM.get(k)
                break
                
        if btn_num is not None:
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
                self.success_timer = 1.5
                self._set_all_leds(opt["color"])
                if self._render_update:
                    asyncio.create_task(self._render_update())
                return
                
        if btn_num == 6:
            # If CANCEL is pressed and is not an option, exit polling
            self._clear_leds()
            self.state = "ACTIVE_QUESTION"
            if self._render_update:
                asyncio.create_task(self._render_update())

    def _handle_view_results_button(self, event):
        self.state = "SURVEY_MENU"
        self._init_survey_menu()
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

    def update(self, delta):
        if self.state in ["MAIN_MENU", "SURVEY_MENU", "CREATING_IN_PROGRESS"] and self.menu:
            self.menu.update(delta)
            
        if self.state == "VOTE_SUCCESS":
            self.success_timer -= delta
            if self.success_timer <= 0:
                self._clear_leds()
                self.state = "ACTIVE_QUESTION"
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

    def _draw_circular_gauge(self, ctx, x, y, radius, thickness, options):
        ctx.save()
        ctx.line_width = thickness
        
        total_votes = sum(o["votes"] for o in options)
        
        if total_votes == 0:
            ctx.rgb(0.15, 0.15, 0.15)
            ctx.arc(x, y, radius, 0, 2 * math.pi, True).stroke()
            
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
                
                ctx.arc(x, y, radius, start_angle, end_angle, True).stroke()
                start_angle = end_angle
                
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
            color = opt["color"]
            color_float = tuple(c / 255.0 for c in color)
            
            ctx.rgb(*color_float)
            
            if btn_num == 1:
                ctx.text_align = ctx.CENTER
                ctx.move_to(0, -68).text(lbl)
            elif btn_num == 2:
                ctx.text_align = ctx.RIGHT
                ctx.move_to(75, -45).text(lbl)
            elif btn_num == 3:
                ctx.text_align = ctx.RIGHT
                ctx.move_to(75, 45).text(lbl)
            elif btn_num == 4:
                ctx.text_align = ctx.CENTER
                ctx.move_to(0, 68).text(lbl)
            elif btn_num == 5:
                ctx.text_align = ctx.LEFT
                ctx.move_to(-75, 45).text(lbl)
            elif btn_num == 6:
                ctx.text_align = ctx.LEFT
                ctx.move_to(-75, -45).text(lbl)
                
        ctx.restore()

    def _draw_active_question(self, ctx):
        ctx.save()
        # Title
        ctx.rgb(0.5, 0.8, 0.5)
        ctx.font_size = 10
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.TOP
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
        # Question at top
        ctx.rgb(0.8, 0.8, 0.8)
        ctx.font_size = 12
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.TOP
        question = self.current_survey["question"]
        lines = self._wrap_text(question, ctx, 180)
        for idx, line in enumerate(lines[:2]):
            ctx.move_to(0, -100 + idx * 14).text(line)
            
        # Circular gauge in center
        self._draw_circular_gauge(ctx, 0, 10, 32, 10, self.current_survey["options"])
        
        # Option labels
        self._draw_option_labels(ctx, self.current_survey["options"])
        ctx.restore()

    def _draw_vote_success(self, ctx):
        ctx.save()
        ctx.rgb(0.1, 0.8, 0.1)
        ctx.font_size = 24
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        ctx.move_to(0, -10).text("Success!")
        
        ctx.rgb(1.0, 1.0, 1.0)
        ctx.font_size = 14
        ctx.move_to(0, 20).text("Vote Recorded")
        ctx.restore()

    def _draw_view_results(self, ctx):
        ctx.save()
        # Survey Name
        ctx.rgb(0.5, 0.8, 0.5)
        ctx.font_size = 10
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.TOP
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
        
        while self.is_running:
            if self.dialog:
                await self.dialog.run(render_update)
                
            if self.state == "CREATING":
                await self._run_creator_flow()
                
            await asyncio.sleep(0.05)

__app_export__ = SimpleSurveyApp
