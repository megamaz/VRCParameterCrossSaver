#! ./venv/Scripts/pythonw.exe

import threading
import asyncio
import pygame
import json
import copy
import os
import re

from vrchat_oscquery.asyncio import vrc_osc
from vrchat_oscquery.common import vrc_client, dict_to_dispatcher
from custom_logger import setup_logging

FONT_SIZE = 18
# Parameters that will show up in the list but aren't parameters that can be saved (or parameters that aren't worth saving)
UNSAVEABLE = ["ScaleFactor", 
              "ScaleFactorInverse",
              "ScaleModified",
              "EyeHeightAsPercent",
              "AFK",
              "Upright",
              "AngularY",
              "VelocityX",
              "VelocityY",
              "VelocityZ",
              "VelocityMagnitude",
              "Grounded",
              "Seated",
              "TrackingType",
              "VRMode",
              "MuteSelf",
              "IsLocal",
              "PreviewMode",
              "Viseme",
              "Voice",
              "GestureLeft",
              "GestureLeftWeight",
              "GestureRight",
              "GestureRightWeight",
              "InStation",
              "EarMuffs",
              "IsOnFriendsList",
              "AvatarVersion",
              "IsAnimatorEnabled"]

# list of VRCF-controlled parameters that shouldn't be controlled.
# TODO if a user is mean and decides to name their param something that matches this pattern, they'll be blocked from saving it.
# but who would do that?
VRCF_UNSAVEABLE_PATTERNS = [
    r"^VF\d+_SyncData(Bool|Num|Float)\d+", # VRCF Unlimited Parameters controlled variables
    r"^VF\d+_SyncIndex\d+",                # ^^
    r"^VF\d+_VF\d+",                       # some parameters are doubles of existing ones
    r"^VF\d+_TC",                          # VRCF Tracking state tracker for each limb
    r"^VF\d+_.*SPS",                       # VRCF SPS State trackers and managers
    r"VF\d+_.*"                            # this one technically blocks all VF parameters making all the above ones redundant lol
]

# only allow saving EyeHeightAsMeters, so that it can be manually handled later.
EYE_HEIGHT_PARAM = "EyeHeightAsMeters"

# vrchat sends out saved param updates immediately before the avatar change event, all within 0.1 seconds.
# this hold time needs to be small to avoid real changes from being discarded, and short so that it doesn't catch fake changes.
HOLD_TIME = 0.25 

client = vrc_client()

active_state = "IDLE"
log = setup_logging()

if not os.path.exists("./params.json"):
    open("./params.json", "w", encoding="utf-8").write(r"{}")

registered_params = json.load(open("./params.json", "r", encoding="utf-8"))
running = True

class ParamTracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.current_avatar_id = None
        self.confirmed_values = {}   # what you actually trust/save
        self.pending = {}            # address -> Timer

    def on_param_update(self, address, *args):
        value = args[0] if args else None
        with self.lock:
            if address in self.pending:
                self.pending[address].cancel()

            avatar_at_receipt = self.current_avatar_id

            def commit():
                existing_contents = registered_params.get(address, {"min":0, "max":1, "saved":{"on_avatar_swap": False, "on_world_swap": False}})
                log.debug(f"Committing value {value} to address {address} ")
                with self.lock:
                    if self.current_avatar_id == avatar_at_receipt:
                        self.confirmed_values[address] = {
                            'value': value,
                            "min": min(existing_contents["min"], value),
                            "max": max(existing_contents["max"], value),
                            "saved": {
                                "on_avatar_swap": existing_contents['saved']['on_avatar_swap'],
                                "on_world_swap": existing_contents['saved']['on_world_swap']
                            }
                        }
                    self.pending.pop(address, None)

            t = threading.Timer(HOLD_TIME, commit)
            self.pending[address] = t
            t.start()

    def on_avatar_change(self, address, new_avatar_id):

        with self.lock:
            log.debug(f"Discarding {len(self.pending)} updates.")
            for t in self.pending.values():
                t.cancel()
            self.pending.clear()
            self.current_avatar_id = new_avatar_id

            update_all_params(self.confirmed_values)
            self.confirmed_values = copy.deepcopy(registered_params)


tracker = ParamTracker()
tracker.confirmed_values.update(registered_params)

def lerp(a, b, t):
    return a + (b-a)*t

def set_param(name, value):
    if name == EYE_HEIGHT_PARAM:
        log.debug(f"Sent out height param to {value}")
        client.send_message("/avatar/eyeheight", value)
        return

    log.debug(f"Sent out param {name} to {value}")
    client.send_message(f"/avatar/parameters/{name}", value)

def update_all_params(param_content):
    log.info(f"Updating all saved parameters")
    for param, content in param_content.items():
        if not content["saved"]["on_avatar_swap"]:
            continue

        set_param(param, content['value'])

def is_fury_param(p:str):
    return any([re.match(pat, p) is not None for pat in VRCF_UNSAVEABLE_PATTERNS])

def on_avatar_change(address, *args):
    log.info(f"Received avatar change event to {args[0]}")
    tracker.on_avatar_change(address, args[0])

def on_parameter(address, *args):
    # we keep the registered params for live updates
    global registered_params

    value = args[0]
    address = address[len("/avatar/parameters/"):]

    existing_contents = registered_params.get(address, {"min":0, "max":1, "saved":{"on_avatar_swap": False, "on_world_swap": False}})

    registered_params[address] = {
        "value": value,
        "min": min(existing_contents["min"], value),
        "max": max(existing_contents["max"], value),
        "saved": {
            "on_avatar_swap": existing_contents['saved']['on_avatar_swap'],
            "on_world_swap": existing_contents['saved']['on_world_swap']
        }
    }

    if registered_params[address]["saved"]["on_avatar_swap"]:
        log.debug(f"Saved param update: {address}={value}")
        tracker.on_param_update(address, *args)

def pygame_loop():
    global running
    global registered_params

    log.info("Starting pygame loop")

    pygame.init()
    pygame.display.set_caption("Parameter Cross-Saver")

    screen = pygame.display.set_mode((730, 600), pygame.RESIZABLE | pygame.HWSURFACE | pygame.DOUBLEBUF)
    font = pygame.font.SysFont(None, FONT_SIZE)
    bigger_font = pygame.font.SysFont(None, 50)
    clock = pygame.time.Clock()
    padding = (5, 5)
    offset = 50

    while running:
        screen.fill((30, 30, 30))
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break
            if event.type == pygame.MOUSEWHEEL:
                offset += event.y * 30

            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    # discover the param at that Y value
                    param_index = int((event.pos[1] - offset) / (FONT_SIZE + padding[1])) - 1
                    params = list(registered_params.keys())
                    if param_index < len(params) and params[param_index] not in UNSAVEABLE:
                        param_name = params[param_index]
                        param_content = registered_params[param_name]
                        if event.pos[0] >= 705 and event.pos[0] <= 722:
                            log.debug(f"Received click for parameter {param_name}")
                            param_content['saved']['on_avatar_swap'] = not param_content['saved']['on_avatar_swap']
                            tracker.confirmed_values[param_name] = param_content
                        elif event.pos[0] <= 700:
                            # compute the value to set it to based on the mouse's X position
                            # 700 is max, 0 is minimum
                            if type(param_content['value']) == bool:
                                set_param(param_name, not param_content['value'])
                            else:
                                t = event.pos[0]/700
                                set_param(param_name, lerp(param_content['min'], param_content['max'], t))

                        # elif event.pos[0] >= 728 and event.pos[0] <= 746:
                        #     registered_params[params[param_index]]['saved']['on_world_swap'] = not registered_params[params[param_index]]['saved']['on_world_swap']
            
            if event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((730, max(event.h, 300)), pygame.RESIZABLE | pygame.HWSURFACE | pygame.DOUBLEBUF)
                        
        index = 1

        for param, content in registered_params.items():
            # for drawing
            is_item_saveable = param not in UNSAVEABLE
            param_is_vrcfury = is_fury_param(param)

            padded_y_pos = (FONT_SIZE + padding[1]) * index + offset
            label_text = font.render(f"{param}", True, (255, 255, 255))
            if type(content['value']) == float:
                value_text = font.render(f"{content['value']:.4f}", True, (255, 255, 255))
            else:
                value_text = font.render(str(content['value']), True, (255, 255, 255))

            value = (content["value"] - content["min"]) / (content["max"] - content["min"])

            # value_saved = tracker.confirmed_values.get(param)
            # if value_saved:
            #     value_saved = (value_saved['value'] - content["min"]) / (content["max"] - content["min"])

            color = (0, 130, 0)
            if param in UNSAVEABLE:
                color = (130, 0, 0)
            elif param_is_vrcfury:
                color = (130, 130, 0)

            pygame.draw.rect(screen, (60, 60, 60), (0, padded_y_pos, 700, FONT_SIZE))
            # if value_saved:
            #     pygame.draw.rect(screen, color, (0, padded_y_pos, 700 * value_saved, FONT_SIZE/2))
            pygame.draw.rect(screen, color, (0, padded_y_pos, 700 * value, FONT_SIZE))

            screen.blit(label_text, (padding[0], padded_y_pos + padding[1]/2))

            value_rect = value_text.get_rect(topright=(700, padded_y_pos + padding[1] / 2))
            screen.blit(label_text, (padding[0], padded_y_pos + padding[1]/2))
            screen.blit(value_text, value_rect)

            # saved statuses
            if is_item_saveable:
                pygame.draw.rect(screen, (255, 255, 255), (700 + padding[0], padded_y_pos, FONT_SIZE, FONT_SIZE), 0 if content['saved']['on_avatar_swap'] else 2)
            else:
                pygame.draw.rect(screen, (120, 120, 120), (700 + padding[0], padded_y_pos, FONT_SIZE, FONT_SIZE), 2)
            # pygame.draw.rect(screen, (255, 255, 255), (700 + FONT_SIZE + padding[0] * 2, padded_y_pos, FONT_SIZE, FONT_SIZE), 0 if content['saved']['on_world_swap'] else 2)
            
            index += 1

        pygame.draw.rect(screen, (30, 30, 30), (0, 0, 820, 70))
        instruction_text = bigger_font.render("Check boxes on right to mark as saved.", True, (255, 255, 255))
        # checkboxes_label = font.render("on avi swap | on world swap", True, (255, 255, 255))
        screen.blit(instruction_text, (10, 10))
        # screen.blit(checkboxes_label, (653, 55))

        pygame.display.flip()
        clock.tick(60)
            

async def main():
    global running
    pygame_thread = threading.Thread(
        target=pygame_loop,
        daemon=True,
    )

    pygame_thread.start()

    server = vrc_osc("Parameter Cross-Saver", dict_to_dispatcher({
        "/avatar/parameters/*" : on_parameter,
        "/avatar/change" : on_avatar_change
    }))

    try:
        update_all_params(registered_params)
        await server
        while True:
            await asyncio.sleep(1)
            if not running:
                break

    finally:
        server.close()
        filtered_params = {}
        for param, content in registered_params.items():
            if content['saved']['on_avatar_swap']:
                filtered_params[param] = content

        json.dump(filtered_params, open("./params.json", "w", encoding="utf-8"))

if __name__ == "__main__":
    asyncio.run(main())