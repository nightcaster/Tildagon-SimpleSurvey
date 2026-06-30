import asyncio
import math
import app
import json
import os
from events.input import BUTTON_TYPES, ButtonDownEvent, ButtonUpEvent
from tildagonos import tildagonos
from system.eventbus import eventbus
from app_components import Menu, TextDialog, clear_background
from app_components.background import Background as bg
from system.patterndisplay.events import PatternDisable, PatternEnable

try:
    import settings
except ImportError:
    settings = None

# Font Sizes Configurations

# 1. Polling & Option Selection Screen
FONT_SIZE_QUESTION_MID = 24      # Survey question text inside the outer results circle
FONT_SIZE_POLLING_VOTES = 18     # Total votes count below the centered question
FONT_SIZE_OPTION_LBL = 16        # Option labels and individual counts around perimeter
FONT_SIZE_BANNER = 16            # Hold-to-exit countdown/warning overlay message

# 2. Vote Recorded Screen (Success)
FONT_SIZE_SUCCESS_LBL = 26       # Centered name of option voted for
FONT_SIZE_SUCCESS_VOTES = 16     # Option's vote count below option name

# 3. View Results Screen
FONT_SIZE_RESULTS_TITLE = 16     # Survey name title at the top
FONT_SIZE_RESULTS_QUESTION = 18  # Survey question text below title
FONT_SIZE_RESULTS_DETAILS = 16   # Vote count and percent list items at the bottom
FONT_SIZE_RESULTS_EXIT = 11      # CANCEL button exit instructions at the bottom

# 4. Circular Gauge Helper
FONT_SIZE_GAUGE = 20             # Center total vote count on standalone gauge

BUTTON_NUM_TO_NAME = {
    1: "UP",
    2: "RIGHT",
    3: "CONFIRM",
    4: "DOWN",
    5: "LEFT",
    6: "CANCEL"
}
BUTTON_NAME_TO_NUM = {v: k for k, v in BUTTON_NUM_TO_NAME.items()}

BUTTON_NUM_TO_LETTER = {
    1: "A",
    2: "B",
    3: "C",
    4: "D",
    5: "E",
    6: "F"
}
BUTTON_LETTER_TO_NUM = {v: k for k, v in BUTTON_NUM_TO_LETTER.items()}

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
        self.held_buttons = set()
        self.cancel_button_released = True
        
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
        self.surveys = []
        paths_to_try = []
        
        # 1. Try relative to __file__
        try:
            if "/" in __file__:
                paths_to_try.append("/".join(__file__.split("/")[:-1]) + "/surveys.json")
            elif "\\" in __file__:
                paths_to_try.append("\\".join(__file__.split("\\")[:-1]) + "\\surveys.json")
        except Exception:
            pass
            
        # 2. Try standard badge/simulator paths
        paths_to_try.append("apps/simplesurvey/surveys.json")
        paths_to_try.append("apps/SimpleSurvey/surveys.json")
        paths_to_try.append("surveys.json")
        
        # Try loading from the first path that successfully opens
        for path in paths_to_try:
            try:
                with open(path, "r") as f:
                    self.surveys = json.load(f)
                self.data_path = path
                print(f"Loaded surveys from: {path}")
                return
            except Exception:
                continue
                
        # Fallback path if none existed
        self.data_path = "apps/simplesurvey/surveys.json"
        print("Could not load surveys.json, starting fresh.")

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
            if self.menu:
                self.menu._cleanup()
                self.menu = None
            self.state = "CREATING"
        elif item == "Exit":
            self._cleanup_all()
            self.minimise()
        else:
            # Selected a survey
            self.current_survey = self.surveys[idx]
            self.state = "SURVEY_MENU"
            self._init_survey_menu()

    def _handle_main_menu_back(self, from_menu_select=False):
        if not from_menu_select:
            if not self.cancel_button_released:
                return
        self._cleanup_all()
        self.minimise()

    def _init_survey_menu(self):
        if self.menu:
            self.menu._cleanup()
            
        self.menu = Menu(
            self,
            menu_items=["Start Polling", "View Results", "Edit Survey", "Reset Results", "Delete Survey", "Back"],
            select_handler=self._handle_survey_menu_select,
            back_handler=self._go_to_main_menu
        )

    def _handle_survey_menu_select(self, item, idx):
        if item == "Start Polling":
            has_question = bool(self.current_survey.get("question", "").strip())
            has_options = len(self.current_survey.get("options", [])) > 0
            
            if self.menu:
                self.menu._cleanup()
                self.menu = None
                
            if has_question and has_options:
                self.state = "ACTIVE_POLLING"
                self._set_option_leds()
            else:
                self.state = "START_ERROR"
        elif item == "View Results":
            if self.menu:
                self.menu._cleanup()
                self.menu = None
            self.state = "VIEW_RESULTS"
        elif item == "Edit Survey":
            self.state = "EDIT_SURVEY"
            self._init_edit_survey_menu()
        elif item == "Reset Results":
            if self.menu:
                self.menu._cleanup()
                self.menu = None
            self.confirm_action = "RESET"
            self.state = "CONFIRM_ACTION"
            self.anim_time = 0.0
        elif item == "Delete Survey":
            if self.menu:
                self.menu._cleanup()
                self.menu = None
            self.confirm_action = "DELETE"
            self.state = "CONFIRM_ACTION"
            self.anim_time = 0.0
        elif item == "Back":
            self._go_to_main_menu(from_menu_select=True)

    def _go_to_main_menu(self, from_menu_select=False):
        if not from_menu_select:
            if not self.cancel_button_released:
                return
            self.cancel_button_released = False
        self.state = "MAIN_MENU"
        self._init_main_menu()

    async def _run_creation_flow(self):
        self.state = "CREATING_IN_PROGRESS"
        
        dialog = TextDialog("Survey Name", self)
        self.dialog = dialog
        name = await dialog.run(self._render_update)
        self.dialog = None
        
        if not name:
            self.state = "MAIN_MENU"
            self._init_main_menu()
            return
            
        import time
        survey_id = f"survey_{int(time.time())}"
        new_survey = {
            "id": survey_id,
            "name": name,
            "question": "",
            "options": []
        }
        self.surveys.append(new_survey)
        self._save_surveys()
        
        self.current_survey = new_survey
        self.state = "EDIT_SURVEY"
        self._init_edit_survey_menu()
        await self._render_update()

    def _get_option_for_button(self, btn_num):
        for opt in self.current_survey["options"]:
            if opt["button"] == btn_num:
                return opt
        return None

    def _init_edit_survey_menu(self):
        if self.menu:
            self.menu._cleanup()
            
        items = [
            f"Name: {self.current_survey['name']}",
            f"Question: {self.current_survey['question'] if self.current_survey['question'] else '(None)'}"
        ]
        for btn in range(1, 7):
            letter = BUTTON_NUM_TO_LETTER[btn]
            opt = self._get_option_for_button(btn)
            if opt:
                items.append(f"Slot {letter}: {opt['label']}")
            else:
                items.append(f"Slot {letter}: [Empty]")
        items.append("Back")
        
        self.menu = Menu(
            self,
            menu_items=items,
            select_handler=self._handle_edit_survey_select,
            back_handler=self._handle_edit_survey_back
        )

    def _handle_edit_survey_select(self, item, idx):
        if idx == 0:
            self._edit_survey_name()
        elif idx == 1:
            self._edit_survey_question()
        elif 2 <= idx <= 7:
            btn_num = idx - 1
            self._edit_survey_slot(btn_num)
        elif idx == 8:
            self._handle_edit_survey_back(from_menu_select=True)

    def _handle_edit_survey_back(self, from_menu_select=False):
        if not from_menu_select:
            if not self.cancel_button_released:
                return
            self.cancel_button_released = False
        self.state = "SURVEY_MENU"
        self._init_survey_menu()

    def _edit_survey_name(self):
        asyncio.create_task(self._async_edit_name())

    async def _async_edit_name(self):
        self.state = "EDITING_SURVEY_DETAILS"
        if self.menu:
            self.menu._cleanup()
            self.menu = None
        dialog = TextDialog("Survey Name", self)
        self.dialog = dialog
        new_name = await dialog.run(self._render_update)
        self.dialog = None
        
        if new_name:
            self.current_survey["name"] = new_name
            self._save_surveys()
            
        self.state = "EDIT_SURVEY"
        self._init_edit_survey_menu()

    def _edit_survey_question(self):
        asyncio.create_task(self._async_edit_question())

    async def _async_edit_question(self):
        self.state = "EDITING_SURVEY_DETAILS"
        if self.menu:
            self.menu._cleanup()
            self.menu = None
        dialog = TextDialog("Question", self)
        self.dialog = dialog
        new_q = await dialog.run(self._render_update)
        self.dialog = None
        
        if new_q:
            self.current_survey["question"] = new_q
            self._save_surveys()
            
        self.state = "EDIT_SURVEY"
        self._init_edit_survey_menu()

    def _edit_survey_slot(self, btn_num):
        opt = self._get_option_for_button(btn_num)
        if opt is None:
            asyncio.create_task(self._async_create_slot_option(btn_num))
        else:
            self.editing_option = opt
            self.state = "EDIT_SLOT"
            self._init_edit_slot_menu()

    async def _async_create_slot_option(self, btn_num):
        self.state = "EDITING_SURVEY_DETAILS"
        if self.menu:
            self.menu._cleanup()
            self.menu = None
        dialog = TextDialog(f"Opt {BUTTON_NUM_TO_LETTER[btn_num]} Label", self)
        self.dialog = dialog
        label = await dialog.run(self._render_update)
        self.dialog = None
        
        if label:
            opt = {
                "label": label,
                "color": [255, 0, 0],
                "button": btn_num,
                "votes": 0
            }
            self.current_survey["options"].append(opt)
            self._save_surveys()
            
            self.editing_option = opt
            self.state = "EDIT_SLOT"
            self._init_edit_slot_menu()
        else:
            self.state = "EDIT_SURVEY"
            self._init_edit_survey_menu()

    def _init_edit_slot_menu(self):
        if self.menu:
            self.menu._cleanup()
            
        color_name = self._get_color_name(self.editing_option["color"])
        items = [
            f"Value: {self.editing_option['label']}",
            f"Color: {color_name}",
            "Clear Option",
            "Back"
        ]
        self.menu = Menu(
            self,
            menu_items=items,
            select_handler=self._handle_edit_slot_select,
            back_handler=self._handle_edit_slot_back
        )

    def _handle_edit_slot_select(self, item, idx):
        if idx == 0:
            asyncio.create_task(self._async_edit_slot_value())
        elif idx == 1:
            self._init_color_select_menu()
        elif idx == 2:
            self.current_survey["options"].remove(self.editing_option)
            self._save_surveys()
            self.editing_option = None
            self.state = "EDIT_SURVEY"
            self._init_edit_survey_menu()
        elif idx == 3:
            self._handle_edit_slot_back(from_menu_select=True)

    def _handle_edit_slot_back(self, from_menu_select=False):
        if not from_menu_select:
            if not self.cancel_button_released:
                return
            self.cancel_button_released = False
        self.editing_option = None
        self.state = "EDIT_SURVEY"
        self._init_edit_survey_menu()

    async def _async_edit_slot_value(self):
        self.state = "EDITING_SURVEY_DETAILS"
        if self.menu:
            self.menu._cleanup()
            self.menu = None
        dialog = TextDialog("Option Value", self)
        self.dialog = dialog
        new_val = await dialog.run(self._render_update)
        self.dialog = None
        
        if new_val:
            self.editing_option["label"] = new_val
            self._save_surveys()
            
        self.state = "EDIT_SLOT"
        self._init_edit_slot_menu()

    def _get_color_name(self, rgb):
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
        for name, val in color_options:
            if val == rgb:
                return name
        return "Custom"

    def _init_color_select_menu(self):
        if self.menu:
            self.menu._cleanup()
            
        color_items = [
            "Red",
            "Yellow",
            "Green",
            "Cyan",
            "Blue",
            "Magenta",
            "Orange",
            "White",
            "Custom RGB",
            "Back"
        ]
        
        current_color = self.editing_option["color"]
        current_name = self._get_color_name(current_color)
        
        initial_pos = 0
        if current_name == "Custom":
            initial_pos = 8
        else:
            for i, name in enumerate(color_items):
                if name == current_name:
                    initial_pos = i
                    break
                    
        self.custom_rgb = list(current_color)
        self.state = "COLOR_SELECT"
        
        self.menu = Menu(
            self,
            menu_items=color_items,
            select_handler=self._handle_color_select,
            change_handler=self._handle_color_menu_change,
            back_handler=self._handle_color_back,
            position=initial_pos
        )
        self._handle_color_menu_change(color_items[initial_pos])

    def _handle_color_menu_change(self, item):
        color_map = {
            "Red": [255, 0, 0],
            "Yellow": [255, 255, 0],
            "Green": [0, 255, 0],
            "Cyan": [0, 255, 255],
            "Blue": [0, 0, 255],
            "Magenta": [255, 0, 255],
            "Orange": [255, 128, 0],
            "White": [255, 255, 255]
        }
        if item in color_map:
            self._set_button_leds_only(self.editing_option["button"], color_map[item])
        elif item == "Custom RGB":
            self._set_button_leds_only(self.editing_option["button"], self.custom_rgb)
        else:
            self._clear_leds()

    def _handle_color_select(self, item, idx):
        color_map = {
            "Red": [255, 0, 0],
            "Yellow": [255, 255, 0],
            "Green": [0, 255, 0],
            "Cyan": [0, 255, 255],
            "Blue": [0, 0, 255],
            "Magenta": [255, 0, 255],
            "Orange": [255, 128, 0],
            "White": [255, 255, 255]
        }
        if item in color_map:
            self.editing_option["color"] = color_map[item]
            self._save_surveys()
            self._clear_leds()
            self.state = "EDIT_SLOT"
            self._init_edit_slot_menu()
        elif item == "Custom RGB":
            self._init_custom_rgb_menu()
        elif item == "Back":
            self._handle_color_back(from_menu_select=True)

    def _handle_color_back(self, from_menu_select=False):
        if not from_menu_select:
            if not self.cancel_button_released:
                return
            self.cancel_button_released = False
        self._clear_leds()
        self.state = "EDIT_SLOT"
        self._init_edit_slot_menu()

    def _init_custom_rgb_menu(self):
        if self.menu:
            self.menu._cleanup()
            
        items = [
            f"R: {self.custom_rgb[0]}",
            f"G: {self.custom_rgb[1]}",
            f"B: {self.custom_rgb[2]}",
            "Confirm",
            "Cancel"
        ]
        self.state = "CUSTOM_RGB_MENU"
        self.menu = Menu(
            self,
            menu_items=items,
            select_handler=self._handle_custom_rgb_select,
            back_handler=self._handle_custom_rgb_back
        )
        self._set_button_leds_only(self.editing_option["button"], self.custom_rgb)

    def _handle_custom_rgb_select(self, item, idx):
        if idx == 0:
            self._start_edit_channel("R")
        elif idx == 1:
            self._start_edit_channel("G")
        elif idx == 2:
            self._start_edit_channel("B")
        elif idx == 3:
            self.editing_option["color"] = list(self.custom_rgb)
            self._save_surveys()
            self._clear_leds()
            self.state = "COLOR_SELECT"
            self._init_color_select_menu()
        elif idx == 4:
            self._handle_custom_rgb_back(from_menu_select=True)

    def _handle_custom_rgb_back(self, from_menu_select=False):
        if not from_menu_select:
            if not self.cancel_button_released:
                return
            self.cancel_button_released = False
        self._clear_leds()
        self.state = "COLOR_SELECT"
        self._init_color_select_menu()

    def _start_edit_channel(self, channel):
        if self.menu:
            self.menu._cleanup()
            self.menu = None
            
        self.state = "EDIT_CHANNEL"
        self.editing_channel = channel

    def _adjust_channel(self, val):
        idx = {"R": 0, "G": 1, "B": 2}[self.editing_channel]
        new_val = self.custom_rgb[idx] + val
        if new_val < 0:
            new_val = 0
        elif new_val > 255:
            new_val = 255
        self.custom_rgb[idx] = new_val
        self._set_button_leds_only(self.editing_option["button"], self.custom_rgb)

    def _set_button_leds_only(self, button_num, color):
        eventbus.emit(PatternDisable())
        for i in range(19):
            tildagonos.leds[i] = (0, 0, 0)
        scaled = self._scale_color(color)
        leds = self._get_button_leds(button_num)
        for led_idx in leds:
            tildagonos.leds[led_idx] = scaled
        tildagonos.leds.write()

    def _get_btn_num(self, event):
        for k, v in BUTTON_TYPES.items():
            if v in event.button:
                return BUTTON_NAME_TO_NUM.get(k)
        return None

    def _handle_buttondown(self, event):
        if self.dialog:
            return
        if self.state in [
            "MAIN_MENU", "SURVEY_MENU", "CREATING", "CREATING_IN_PROGRESS",
            "EDIT_SURVEY", "EDITING_SURVEY_DETAILS", "EDIT_SLOT",
            "COLOR_SELECT", "CUSTOM_RGB_MENU"
        ]:
            return
            
        btn_num = self._get_btn_num(event)
        if btn_num is None:
            return
            
        if btn_num in self.held_buttons:
            return
        self.held_buttons.add(btn_num)
        
        if self.state == "EDIT_CHANNEL":
            if btn_num == 1:
                self._adjust_channel(15)
            elif btn_num == 4:
                self._adjust_channel(-15)
            elif btn_num == 3 or btn_num == 6:
                self.state = "CUSTOM_RGB_MENU"
                self._init_custom_rgb_menu()
            if self._render_update:
                asyncio.create_task(self._render_update())
            return
        elif self.state == "START_ERROR":
            if btn_num == 6:
                if not self.cancel_button_released:
                    return
                self.cancel_button_released = False
                self.held_buttons.clear()
                self.state = "SURVEY_MENU"
                self._init_survey_menu()
                if self._render_update:
                    asyncio.create_task(self._render_update())
            return
        elif self.state == "CONFIRM_ACTION":
            if btn_num == 4: # D button to confirm
                if self.confirm_action == "RESET":
                    for opt in self.current_survey.get("options", []):
                        opt["votes"] = 0
                    self._save_surveys()
                    self.held_buttons.clear()
                    self.state = "SURVEY_MENU"
                    self._init_survey_menu()
                elif self.confirm_action == "DELETE":
                    self.surveys.remove(self.current_survey)
                    self._save_surveys()
                    self.current_survey = None
                    self.held_buttons.clear()
                    self.state = "MAIN_MENU"
                    self._init_main_menu()
                if self._render_update:
                    asyncio.create_task(self._render_update())
            elif btn_num == 6: # F button to cancel
                if not self.cancel_button_released:
                    return
                self.cancel_button_released = False
                self.held_buttons.clear()
                self.state = "SURVEY_MENU"
                self._init_survey_menu()
                if self._render_update:
                    asyncio.create_task(self._render_update())
            return
        elif self.state == "ACTIVE_POLLING":
            if btn_num == 6:
                # If there's an option on button 6, use hold timeout, otherwise exit immediately
                has_btn_6_option = any(opt["button"] == 6 for opt in self.current_survey["options"])
                if has_btn_6_option:
                    if not self.cancel_is_held:
                        self.cancel_is_held = True
                        self.cancel_press_time = 0.0
                    if self._render_update:
                        asyncio.create_task(self._render_update())
                else:
                    if not self.cancel_button_released:
                        return
                    self.cancel_button_released = False
                    self._clear_leds()
                    self.held_buttons.clear()
                    self.state = "SURVEY_MENU"
                    self._init_survey_menu()
                    if self._render_update:
                        asyncio.create_task(self._render_update())
                return
            elif btn_num is not None:
                self._record_vote(btn_num)
        elif self.state == "VIEW_RESULTS":
            if btn_num == 6:
                if not self.cancel_button_released:
                    return
                self.cancel_button_released = False
                self.held_buttons.clear()
                self.state = "SURVEY_MENU"
                self._init_survey_menu()
                if self._render_update:
                    asyncio.create_task(self._render_update())

    def _handle_buttonup(self, event):
        if self.dialog:
            return
            
        btn_num = self._get_btn_num(event)
        if btn_num is not None:
            self.held_buttons.discard(btn_num)
            if btn_num == 6:
                self.cancel_button_released = True
            
        if self.state == "WAITING_FOR_CANCEL_RELEASE" and btn_num == 6:
            self.state = "SURVEY_MENU"
            self._init_survey_menu()
            if self._render_update:
                asyncio.create_task(self._render_update())
            return
            
        if self.state in [
            "MAIN_MENU", "SURVEY_MENU", "CREATING", "CREATING_IN_PROGRESS",
            "EDIT_SURVEY", "EDITING_SURVEY_DETAILS", "EDIT_SLOT",
            "COLOR_SELECT", "CUSTOM_RGB_MENU", "START_ERROR", "CONFIRM_ACTION"
        ]:
            return
            
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

    def _scale_color(self, color):
        brightness = 0.1
        if settings:
            try:
                b = settings.get("pattern_brightness")
                if b is not None:
                    brightness = b
            except Exception:
                pass
        return tuple(int(c * brightness) for c in color)

    def _set_option_leds(self):
        eventbus.emit(PatternDisable())
        for i in range(19):
            tildagonos.leds[i] = (0, 0, 0)
            
        for opt in self.current_survey["options"]:
            btn_num = opt["button"]
            color = self._scale_color(opt["color"])
            leds = self._get_button_leds(btn_num)
            for led_idx in leds:
                tildagonos.leds[led_idx] = color
        tildagonos.leds.write()

    def _set_all_leds(self, color):
        eventbus.emit(PatternDisable())
        scaled = self._scale_color(color)
        for i in range(19):
            tildagonos.leds[i] = scaled
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
        self.held_buttons.clear()
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
        
        scaled_color = self._scale_color(color)
        
        if t >= self.animation_duration:
            # Fade out
            fade_pct = max(0.0, 1.0 - (t - self.animation_duration) / self.fade_duration)
            faded = tuple(int(c * fade_pct) for c in scaled_color)
            for led_idx in outer_leds:
                tildagonos.leds[led_idx] = faded
        elif t >= T_prop:
            # All outer LEDs lit
            for led_idx in outer_leds:
                tildagonos.leds[led_idx] = scaled_color
        else:
            # Propagating
            step = int((t / T_prop) * 6)
            for j in range(step + 1):
                idx_l = (i1 - j) % 12
                idx_r = (i2 + j) % 12
                tildagonos.leds[outer_leds[idx_l]] = scaled_color
                tildagonos.leds[outer_leds[idx_r]] = scaled_color
                
        tildagonos.leds.write()

    def update(self, delta):
        bg.update(delta)
        dt = delta / 1000.0
        if self.state in [
            "MAIN_MENU", "SURVEY_MENU", "CREATING_IN_PROGRESS",
            "EDIT_SURVEY", "EDIT_SLOT", "COLOR_SELECT", "CUSTOM_RGB_MENU"
        ] and self.menu:
            self.menu.update(delta)
            
        if self.state == "CONFIRM_ACTION":
            self.anim_time += dt
            
        if self.state == "ACTIVE_POLLING" and self.cancel_is_held:
            self.cancel_press_time += dt
            if self.cancel_press_time >= 3.0:
                self.cancel_is_held = False
                self.cancel_press_time = 0.0
                self._clear_leds()
                self.state = "WAITING_FOR_CANCEL_RELEASE"
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
                ctx.font_size = FONT_SIZE_GAUGE
                ctx.text_align = ctx.CENTER
                ctx.text_baseline = ctx.MIDDLE
                ctx.move_to(x, y).text("0")
        else:
            # Draw underlying gray ring for empty sectors
            ctx.rgb(0.15, 0.15, 0.15)
            ctx.begin_path()
            ctx.arc(x, y, radius, 0, 2 * math.pi, False).stroke()

            # Draw colored gauge segments contiguously, sorted by button number
            sorted_opts = sorted(options, key=lambda o: o["button"])
            start_angle = -math.pi / 2
            for opt in sorted_opts:
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
                ctx.font_size = FONT_SIZE_GAUGE
                ctx.text_align = ctx.CENTER
                ctx.text_baseline = ctx.MIDDLE
                ctx.move_to(x, y).text(str(total_votes))
            
        ctx.restore()

    def _draw_option_labels(self, ctx, options):
        ctx.save()
        ctx.font_size = FONT_SIZE_OPTION_LBL
        
        R = 90  # Radius inside the radial gauge (gauge is at R=114, thickness 10)
        
        for opt in options:
            btn_num = opt["button"]
            lbl = opt["label"]
            votes = f"({opt['votes']})"
            color = opt["color"]
            color_float = tuple(c / 255.0 for c in color)
            
            theta = -math.pi / 2 + (btn_num - 1) * math.pi / 3
            x = R * math.cos(theta)
            y = R * math.sin(theta)
            
            ctx.save()
            ctx.translate(x, y)
            ctx.rotate(theta + math.pi / 2)
            
            ctx.rgb(*color_float)
            ctx.text_align = ctx.CENTER
            ctx.text_baseline = ctx.MIDDLE
            
            ctx.move_to(0, -7).text(lbl)
            ctx.move_to(0, 7).text(votes)
            
            ctx.restore()
            
        ctx.restore()


    def _draw_active_polling(self, ctx):
        ctx.save()
        
        # Circular gauge surrounding the screen
        self._draw_circular_gauge(ctx, 0, 0, 114, 10, self.current_survey["options"], draw_center_text=False)
        
        # Question in the center
        ctx.rgb(1.0, 1.0, 1.0)
        ctx.font_size = FONT_SIZE_QUESTION_MID
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        
        question = self.current_survey["question"]
        lines = self._wrap_text(question, ctx, 130)
        
        total_votes = sum(o["votes"] for o in self.current_survey["options"])
        
        start_y = -((len(lines) + 1) * 8)
        for idx, line in enumerate(lines):
            ctx.move_to(0, start_y + idx * 16).text(line)
            
        ctx.rgb(0.7, 0.7, 0.7)
        ctx.font_size = FONT_SIZE_POLLING_VOTES
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
            ctx.font_size = FONT_SIZE_BANNER
            ctx.text_align = ctx.CENTER
            ctx.text_baseline = ctx.MIDDLE
            
            rem = max(1, int(4.0 - self.cancel_press_time))
            ctx.move_to(0, -12).text("Keep holding F to return")
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
        ctx.font_size = FONT_SIZE_SUCCESS_LBL
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
        
        ctx.font_size = FONT_SIZE_SUCCESS_VOTES
        ctx.move_to(0, start_y + len(lines) * 24 + 10).text(f"Votes: {votes_count}")
            
        ctx.restore()

    def _draw_view_results(self, ctx):
        ctx.save()
        # Survey Name
        ctx.rgb(0.5, 0.8, 0.5)
        ctx.font_size = FONT_SIZE_RESULTS_TITLE
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = getattr(ctx, "TOP", "top")
        ctx.move_to(0, -100).text(self.current_survey["name"])
        
        # Question
        ctx.rgb(1.0, 1.0, 1.0)
        ctx.font_size = FONT_SIZE_RESULTS_QUESTION
        question = self.current_survey["question"]
        lines = self._wrap_text(question, ctx, 180)
        for idx, line in enumerate(lines[:2]):
            ctx.move_to(0, -85 + idx * 14).text(line)
            
        # Get bottom of question text
        q_end_y = -85 + len(lines[:2]) * 14
        
        # Total votes
        options = self.current_survey["options"]
        total_votes = sum(o["votes"] for o in options)
        
        ctx.rgb(0.7, 0.7, 0.7)
        ctx.font_size = FONT_SIZE_RESULTS_DETAILS
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        ctx.move_to(0, q_end_y + 6).text(f"Total votes: {total_votes}")
        
        # Option summary details
        start_y = q_end_y + 22
        available_height = 80 - start_y
        step = min(24, max(15, available_height // len(options))) if len(options) > 0 else 20
        
        for idx, opt in enumerate(options[:6]):
            y = start_y + idx * step
            
            pct = (opt["votes"] / total_votes * 100) if total_votes > 0 else 0
            label_text = opt["label"]
            votes_text = f"{opt['votes']} ({pct:.0f}%)"
            
            # Draw label (left aligned)
            ctx.rgb(0.9, 0.9, 0.9)
            ctx.font_size = FONT_SIZE_RESULTS_DETAILS - 2
            ctx.text_align = ctx.LEFT
            ctx.text_baseline = ctx.MIDDLE
            ctx.move_to(-80, y).text(label_text)
            
            # Draw votes/percentage (right aligned)
            ctx.text_align = ctx.RIGHT
            ctx.move_to(80, y).text(votes_text)
            
            # Draw bar background
            ctx.rgb(0.15, 0.15, 0.15)
            ctx.rectangle(-80, y + 7, 160, 4).fill()
            
            # Draw colored indicator bar
            color = opt["color"]
            color_float = tuple(c / 255.0 for c in color)
            ctx.rgb(*color_float)
            bar_width = int(160 * (pct / 100))
            if bar_width > 0:
                ctx.rectangle(-80, y + 7, bar_width, 4).fill()
            
        ctx.rgb(0.6, 0.6, 0.6)
        ctx.font_size = FONT_SIZE_RESULTS_EXIT
        ctx.text_align = ctx.CENTER
        ctx.move_to(0, 95).text("Press CANCEL (F) to exit")
        ctx.restore()

    def _draw_edit_channel(self, ctx):
        ctx.save()
        bg.draw(ctx)
        
        # Title
        ctx.rgb(1.0, 1.0, 1.0)
        ctx.font_size = 20
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        ctx.move_to(0, -60).text(f"Edit {self.editing_channel} Channel")
        
        # Value
        idx = {"R": 0, "G": 1, "B": 2}[self.editing_channel]
        val = self.custom_rgb[idx]
        ctx.font_size = 40
        ctx.move_to(0, 0).text(str(val))
        
        # Helpers
        ctx.rgb(0.7, 0.7, 0.7)
        ctx.font_size = 14
        ctx.move_to(0, 50).text("UP / DOWN to adjust")
        ctx.move_to(0, 70).text("CONFIRM / CANCEL to save")
        ctx.restore()

    def _draw_start_error(self, ctx):
        ctx.save()
        bg.draw(ctx)
        
        ctx.rgb(1.0, 0.2, 0.2)
        ctx.font_size = 20
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        ctx.move_to(0, -50).text("Cannot Start Poll")
        
        ctx.rgb(1.0, 1.0, 1.0)
        ctx.font_size = 14
        ctx.move_to(0, -10).text("Survey needs a")
        ctx.move_to(0, 10).text("question and at least")
        ctx.move_to(0, 30).text("one option to start.")
        
        ctx.rgb(0.7, 0.7, 0.7)
        ctx.font_size = 12
        ctx.move_to(0, 75).text("Press CANCEL (F) to return")
        ctx.restore()

    def _draw_confirm_action(self, ctx):
        ctx.save()
        bg.draw(ctx)
        
        # Determine text based on action
        if self.confirm_action == "RESET":
            title = "Reset Results?"
            msg1 = "Are you sure you want to"
            msg2 = "reset all vote counts to 0?"
            survey_name = self.current_survey["name"]
        else:
            title = "Delete Survey?"
            msg1 = "Are you sure you want to"
            msg2 = "delete this survey?"
            survey_name = self.current_survey["name"]
            
        # Draw Title
        ctx.rgb(1.0, 0.3, 0.3)  # Soft red warning color
        ctx.font_size = 20
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        ctx.move_to(0, -60).text(title)
        
        # Draw Survey Name
        ctx.rgb(1.0, 1.0, 1.0)
        ctx.font_size = 15
        ctx.move_to(0, -35).text(survey_name)
        
        # Draw Messages
        ctx.rgb(0.8, 0.8, 0.8)
        ctx.font_size = 13
        ctx.move_to(0, -10).text(msg1)
        ctx.move_to(0, 8).text(msg2)
        
        # Confirm / Cancel instructions
        ctx.rgb(1.0, 1.0, 1.0)
        ctx.font_size = 15
        ctx.move_to(0, 32).text("Press D to Confirm")
        ctx.rgb(0.6, 0.6, 0.6)
        ctx.font_size = 13
        ctx.move_to(0, 95).text("Press F to Cancel")
        
        # Pulsating Arrow pointing to D (D is Button 4 at bottom, i.e., y-axis positive)
        dy = math.sin(self.anim_time * 6) * 5
        
        ctx.rgb(1.0, 0.4, 0.1) # Sleek orange/amber color
        ctx.begin_path()
        ctx.move_to(-8, 52 + dy)
        ctx.line_to(8, 52 + dy)
        ctx.line_to(8, 68 + dy)
        ctx.line_to(18, 68 + dy)
        ctx.line_to(0, 85 + dy)
        ctx.line_to(-18, 68 + dy)
        ctx.line_to(-8, 68 + dy)
        ctx.close_path()
        ctx.fill()
        
        ctx.restore()

    def draw(self, ctx):
        bg.draw(ctx)
        
        if self.state in [
            "MAIN_MENU", "SURVEY_MENU", "CREATING_IN_PROGRESS",
            "EDIT_SURVEY", "EDIT_SLOT", "COLOR_SELECT", "CUSTOM_RGB_MENU"
        ]:
            if self.menu:
                self.menu.draw(ctx)

        elif self.state == "ACTIVE_POLLING":
            self._draw_active_polling(ctx)
        elif self.state == "VOTE_SUCCESS":
            self._draw_vote_success(ctx)
        elif self.state == "VIEW_RESULTS":
            self._draw_view_results(ctx)
        elif self.state == "EDIT_CHANNEL":
            self._draw_edit_channel(ctx)
        elif self.state == "START_ERROR":
            self._draw_start_error(ctx)
        elif self.state == "CONFIRM_ACTION":
            self._draw_confirm_action(ctx)
            
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
                await self._run_creation_flow()
                
            await asyncio.sleep(0.05)
            last_time = cur_time

__app_export__ = SimpleSurveyApp
