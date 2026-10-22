#! ./venv/Scripts/pythonw.exe

import urllib.request
import threading
import asyncio
import pygame
import openvr
import json
import time
import copy
import os
import re

from schema_updater import to_latest, get_blank_schema
from vrchat_oscquery.asyncio import vrc_osc
from vrchat_oscquery.common import vrc_client, dict_to_dispatcher
from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser, AsyncServiceInfo
from custom_logger import setup_logging
from pathlib import Path

SERVICE = "_oscjson._tcp.local."

OSC_PATH = Path.home() / "AppData" / "LocalLow" / "VRChat" / "VRChat" / "OSC"

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
              "Earmuffs",
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
HOLD_TIME = 0.5
GRACE_PERIOD = 1.0

JSON_SCHEMA_VERSION = 2

ACTIVE_PATH = Path(__file__).resolve().parent
BINARY_PATH = str(ACTIVE_PATH / "venv" / "Scripts" / "pythonw.exe")
OPENVR_APP_ID = "megamaz.VRChatParameterCrossSaver"
VR_MANIFEST = {
    "applications": [
        {
            "app_key":OPENVR_APP_ID,
            "launch_type": "binary",
            "binary_path_windows": BINARY_PATH,
            "arguments": str(ACTIVE_PATH / "main.pyw"),
            "working_directory": str(ACTIVE_PATH),
            "is_dashboard_overlay": True,
            "strings": {
                "en_us": {
                    "name": "VRChat Parameter Cross-Saver"
                }
            }
        }
    ]
}

log = setup_logging()
vr = openvr.init(openvr.VRApplication_Utility)

# FIXME create temporary override for logging of invalid OSC messages.
# remove this once https://feedback.vrchat.com/open-beta/p/1931-invalid-osc-messages gets patched.
# although this can remain an issue for parameter names with complex unicode characters. needs testing
from pythonosc.osc_server import AsyncIOOSCUDPServer
orig = AsyncIOOSCUDPServer._OSCProtocolFactory.datagram_received
def bad_unicode_catcher(self, data, addr):
    try:
        orig(self, data, addr)
    except UnicodeDecodeError:
        log.error(f"Bad packet from {addr} (len={len(data)}): {data}")
AsyncIOOSCUDPServer._OSCProtocolFactory.datagram_received = bad_unicode_catcher

client = vrc_client()

if not os.path.exists("./params.json"):
    log.info("No save file found, creating blank data.")
    with open("./params.json", "w", encoding="utf-8") as create_data:
        json.dump(get_blank_schema(JSON_SCHEMA_VERSION), create_data, indent=5)

log.info("Loading saved data")
with open("./params.json", "r", encoding="utf-8") as preload_params:
    preload_data = json.load(preload_params)
    # check for schema update
    if preload_data.get("version", 1) < JSON_SCHEMA_VERSION:
        preload_data = to_latest(preload_data, preload_data.get("version", 1))
    elif preload_data.get("version", 1) > JSON_SCHEMA_VERSION:
        log.warning("Saved data schema too new, moving to 'params.json.new', and loading blank data as save data.")
        os.rename("./params.json", "./params.json.new")
        preload_data = get_blank_schema(JSON_SCHEMA_VERSION)
    else:
        log.debug("Schema version match")

    live_tracked_params = preload_data["params"]
    whitelist:list = preload_data["whitelist"]

log.debug(f"Saved parameter values: {json.dumps(live_tracked_params, indent=4)}")
running = True

def steamvr_install():
    apps = openvr.VRApplications()
    manifest_path = ACTIVE_PATH / "app.vrmanifest"
    manifest_path.write_text(json.dumps(VR_MANIFEST))
    apps.addApplicationManifest(str(manifest_path))
    apps.setApplicationAutoLaunch(OPENVR_APP_ID, True)
    log.info("App installed")

def steamvr_setup_check():
    apps = openvr.VRApplications()
    log.info("Setting up SteamVR auto-launch")
    if not apps.isApplicationInstalled(OPENVR_APP_ID):
        log.info("Detected app not installed, installing")
        steamvr_install()
    elif apps.getApplicationPropertyString(OPENVR_APP_ID, openvr.VRApplicationProperty_BinaryPath_String) != BINARY_PATH:
        log.info("Detected path change, reinstalling")
        apps.setApplicationAutoLaunch(OPENVR_APP_ID, False)
        old_dir = apps.getApplicationPropertyString(OPENVR_APP_ID, openvr.VRApplicationProperty_WorkingDirectory_String)
        apps.removeApplicationManifest(old_dir)
        log.info("App uninstalled")
        steamvr_install()
    else:
        log.info("App already installed")

def build_param_dict(value=None, min=0, max=1, s_on_avatar_swap=False, s_on_world_swap=False) -> dict:
    """Builds a parameter dictionary to be stored. All function params have a default, so no parameters will build a default uninitialized dict."""
    data = {
        "min": min,
        "max": max,
        "saved": {
            "on_avatar_swap": s_on_avatar_swap,
            "on_world_swap": s_on_world_swap
        }
    }
    if value is not None:
        data["value"] = value

    return data

class ParamTracker:
    def __init__(self, init_confirm):
        self.lock = threading.Lock()
        self.current_avatar_id = None
        self.swap_time = 0.0
        self.confirmed_values = copy.deepcopy(init_confirm)
        self.pending = {}            # address -> Timer
        self.avatar_name = "Unknown"

    def handle_param_change(self, address, *args):
        value = args[0] if args else None
        with self.lock:
            if address in self.pending:
                self.pending[address].cancel()

            avatar_at_receipt = self.current_avatar_id
            swap_time_at_receipt = self.swap_time

            def commit():
                existing_contents = live_tracked_params.get(address, build_param_dict())
                with self.lock:
                    still_same_avatar = self.current_avatar_id == avatar_at_receipt
                    past_grace_period = (time.monotonic() - swap_time_at_receipt) >= GRACE_PERIOD
                    if still_same_avatar and past_grace_period:
                        log.debug(f"Committing value {value} to address {address} ")
                        self.confirmed_values[address] = build_param_dict(
                            value=value,
                            min=min(existing_contents["min"], value),
                            max=max(existing_contents["max"], value),
                            s_on_avatar_swap=existing_contents['saved']['on_avatar_swap'],
                            s_on_world_swap=existing_contents['saved']['on_world_swap']
                        )
                    else:
                        if not still_same_avatar:
                            log.debug(f"Rejected commit for {address}={value} (no longer same avatar)")
                        if not past_grace_period:
                            log.debug(f"Rejected commit for {address}={value} (not past grace period)")
                    self.pending.pop(address, None)

            t = threading.Timer(HOLD_TIME, commit)
            self.pending[address] = t
            t.start()

    def handle_avatar_change(self, address, new_avatar_id) -> dict:
        """Returns all saved params."""
        log.info("Handling avatar change event")
        with self.lock:
            log.debug(f"Discarding {len(self.pending)} updates.")
            for t in self.pending.values():
                t.cancel()
            self.pending.clear()
            self.current_avatar_id = new_avatar_id
            self.swap_time = time.monotonic()

            filtered_params = {}
            for param, content in self.confirmed_values.items():
                if content['saved']['on_avatar_swap']:
                    filtered_params[param] = content

            # delay saved param updates to avoid interfering with VRChat's new avatar update
            if new_avatar_id in whitelist:
                log.info("Avatar in whitelist, sending param update.")
                update = threading.Timer(GRACE_PERIOD, update_all_params, args=[self.confirmed_values,])
                update.start()

        return filtered_params

def _fetch(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)

async def get_current_avatar(mdns_timeout=5, http_timeout=3):
    found = asyncio.Event()
    endpoint = None
    tasks = set()

    async def resolve(zc, name):
        nonlocal endpoint
        info = AsyncServiceInfo(SERVICE, name)
        if await info.async_request(zc, 3000) and info.port:
            endpoint = (info.parsed_addresses()[0], info.port)
            found.set()

    def on_change(zeroconf, service_type, name, state_change):
        if state_change is ServiceStateChange.Removed:
            return
        if not name.startswith("VRChat-Client"):
            return
        t = asyncio.ensure_future(resolve(zeroconf, name))
        tasks.add(t)
        t.add_done_callback(tasks.discard)

    aiozc = AsyncZeroconf()
    browser = AsyncServiceBrowser(aiozc.zeroconf, SERVICE, handlers=[on_change])
    try:
        try:
            await asyncio.wait_for(found.wait(), mdns_timeout)
        except asyncio.TimeoutError:
            return None  # vrchat not running / osc off
        host, port = endpoint
        data = await asyncio.to_thread(
            _fetch, f"http://{host}:{port}/avatar/change", http_timeout
        )
        return data["VALUE"][0]
    finally:
        await browser.async_cancel()
        await aiozc.async_close()

def find_avatar_osc_config(avatar_id:str) -> (Path | None):
    matches = OSC_PATH.glob(f"*/Avatars/{avatar_id}.json")
    return max(matches, key=lambda p: p.stat().st_mtime, default=None)

def lerp(a, b, t):
    return a + (b-a)*t

def set_param(name, value):
    if name == EYE_HEIGHT_PARAM:
        log.debug(f"Sent out height param to {value}")
        client.send_message("/avatar/eyeheight", value)
        return

    log.debug(f"Sent out param {name}={value}")
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
    global live_tracked_params
    log.info(f"Received avatar change event to {args[0]}")

    live_tracked_params = tracker.handle_avatar_change(address, args[0])

    # preload all params instead of waiting for it to be discovered
    config_path = find_avatar_osc_config(args[0])
    if config_path is not None:
        log.info("Discovered avatar OSC config file, preloading parameters")
        with open(config_path, "r", encoding="utf-8-sig") as load_osc:
            config_data = json.load(load_osc)
        for param in config_data["parameters"]:
            if live_tracked_params.get(param['name']) is None:
                live_tracked_params[param['name']] = build_param_dict()
        tracker.avatar_name = config_data["name"]
    else:
        log.warning("Couldn't find OSC config file for current avatar, we either tried to find it too soon or the avatar is an SDK Test avatar.")

def on_parameter(address, *args):
    global live_tracked_params

    value = args[0]
    address = address[len("/avatar/parameters/"):]

    existing_contents = live_tracked_params.get(address, {"min":0, "max":1, "saved":{"on_avatar_swap": False, "on_world_swap": False}})

    live_tracked_params[address] = build_param_dict(
        value=value,
        min=min(existing_contents["min"], value),
        max=max(existing_contents["max"], value),
        s_on_avatar_swap=existing_contents['saved']['on_avatar_swap'],
        s_on_world_swap=existing_contents['saved']['on_world_swap']
    )

    if live_tracked_params[address]["saved"]["on_avatar_swap"] and tracker.current_avatar_id in whitelist:
        log.debug(f"Saved param change: {address}={value}")
        tracker.handle_param_change(address, *args)

def pygame_loop(stop_event:threading.Event):
    global running
    global live_tracked_params
    global whitelist

    log.info("Starting pygame loop")

    pygame.init()
    pygame.display.set_caption("Parameter Cross-Saver")

    screen = pygame.display.set_mode((730, 600), pygame.RESIZABLE | pygame.HWSURFACE | pygame.DOUBLEBUF)
    font = pygame.font.SysFont(None, FONT_SIZE)
    font_italics = pygame.font.SysFont(None, FONT_SIZE, italic=True)
    bigger_font = pygame.font.SysFont(None, 50)
    bigger_font_italics = pygame.font.SysFont(None, 50, italic=True)
    clock = pygame.time.Clock()
    padding = (5, 5)
    offset = 50

    while running and not stop_event.is_set():
        screen.fill((30, 30, 30))
        initial_click_pos = (-1, -1)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break
            if event.type == pygame.MOUSEWHEEL:
                offset += event.y * 30

            if event.type == pygame.MOUSEBUTTONDOWN:
                initial_click_pos = event.pos
                if event.button == 1:
                    if event.pos[1] <= 55: # whitelist click
                        if event.pos[0] >= 645 and tracker.current_avatar_id is not None:
                            log.debug("Received whitelist click.")
                            if tracker.current_avatar_id in whitelist:
                                whitelist.remove(tracker.current_avatar_id)
                                log.debug(f"Avatar '{tracker.current_avatar_id}' removed from whitelist.")
                            else:
                                log.debug(f"Avatar '{tracker.current_avatar_id}' added to whitelist, sending param update.")
                                whitelist.append(tracker.current_avatar_id)
                                update_all_params(tracker.confirmed_values)

                    else: # param click
                        # discover the param at that Y value
                        param_index = int((event.pos[1] - offset) / (FONT_SIZE + padding[1])) - 1
                        params = list(live_tracked_params.keys())
                        if param_index < len(params) and params[param_index] not in UNSAVEABLE:
                            param_name = params[param_index]
                            param_content = live_tracked_params[param_name]
                            if event.pos[0] >= 705 and event.pos[0] <= 722:
                                log.debug(f"Received click for parameter {param_name}")
                                param_content['saved']['on_avatar_swap'] = not param_content['saved']['on_avatar_swap']
                                tracker.confirmed_values[param_name] = param_content
                            elif event.pos[0] <= 700: # handle bool value setting here to prevent it from switching every frame
                                if param_content.get("value") is not None:
                                    if type(param_content['value']) == bool:
                                        set_param(param_name, not param_content['value'])

            if event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((730, max(event.h, 300)), pygame.RESIZABLE | pygame.HWSURFACE | pygame.DOUBLEBUF)

        if pygame.mouse.get_pressed()[0]:
            pos = pygame.mouse.get_pos()
            if initial_click_pos[0] <= 700 and pos[1] > 55:
                # compute the value to set it to based on the mouse's X position
                # 700 is max, 0 is minimum
                if param_content.get("value") is not None:
                    if type(param_content['value']) != bool:
                        t = pos[0]/700
                        t = max(0.0, min(t, 1.0))
                        new_value = lerp(param_content['min'], param_content['max'], t)
                        if type(param_content['value']) == int:
                            new_value = int(new_value)
                        set_param(param_name, new_value)
            
                        
        index = 1

        for param, content in live_tracked_params.items():
            # for drawing
            is_item_saveable = param not in UNSAVEABLE
            param_is_vrcfury = is_fury_param(param)

            padded_y_pos = (FONT_SIZE + padding[1]) * index + offset
            if padded_y_pos < 0 or padded_y_pos > pygame.display.get_window_size()[1]:
                index += 1
                continue

            color = (0, 130, 0)
            if param in UNSAVEABLE:
                color = (130, 0, 0)
            elif param_is_vrcfury:
                color = (130, 130, 0)
            pygame.draw.rect(screen, (60, 60, 60), (0, padded_y_pos, 700, FONT_SIZE))

            if content.get('value') is not None:
                label_text = font.render(f"{param}", True, (255, 255, 255))
                if type(content['value']) == float:
                    value_text = font.render(f"{content['value']:.4f}", True, (255, 255, 255))
                else:
                    value_text = font.render(str(content['value']), True, (255, 255, 255))

                value = (content["value"] - content["min"]) / (content["max"] - content["min"])

                pygame.draw.rect(screen, color, (0, padded_y_pos, 700 * value, FONT_SIZE))
            else:
                label_text = font_italics.render(f"{param}", True, (200, 200, 200))
                value_text = font.render(f"??", True, (255, 255, 255))

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

        if tracker.current_avatar_id is None:
            whitelist_label = bigger_font_italics.render(f"Whitelist avatar: {tracker.avatar_name}", True, (200, 200, 200))
            pygame.draw.rect(screen, (120, 120, 120), (700 - 50 - padding[0], padding[1], 50, 50), 6)
        else:
            whitelist_label = bigger_font.render(f"Whitelist avatar: {tracker.avatar_name}", True, (255, 255, 255))
            pygame.draw.rect(screen, (255, 255, 255), (700 - 50 - padding[0], padding[1], 50, 50), 0 if tracker.current_avatar_id in whitelist else 6)    

        screen.blit(whitelist_label, (10, 10))
        # screen.blit(checkboxes_label, (653, 55))

        pygame.display.flip()
        clock.tick(60)

def steamvr_quitting() -> bool:
    event = openvr.VREvent_t()
    while vr.pollNextEvent(event):
        if event.eventType == openvr.VREvent_Quit:
            return True
    return False       

async def main():
    global running


    stop_signal = threading.Event()
    pygame_thread = threading.Thread(
        target=pygame_loop,
        daemon=True,
        args=(stop_signal,)
    )
    vr_quitting = False

    pygame_thread.start()

    server = vrc_osc("Parameter Cross-Saver", dict_to_dispatcher({
        "/avatar/parameters/*" : on_parameter,
        "/avatar/change" : on_avatar_change
    }))

    try:
        # sending out internally saved values, before the server started
        # no risk of this containing stale data
        # log.debug("Updating saved parameters with data from save file")
        # update_all_params(live_tracked_params)

        steamvr_setup_check()
        log.info("Starting VRChat OSC Session")
        await server
        on_avatar_change("/avatar/change", await get_current_avatar())
        vr_quitting = steamvr_quitting()
        while running and pygame_thread.is_alive() and not vr_quitting:
            vr_quitting = steamvr_quitting()
            await asyncio.sleep(0.25)
        if pygame_thread.is_alive():
            log.info("Pygame thread still alive, signaling to stop...")
            stop_signal.set()
            pygame_thread.join()

    except:
        log.exception("Crash occured.")

    finally:
        log.info("Closing OSC Session")
        server.close()

        try:
            log.info("Saving parameters to local file")
            filtered_params = {}
            for param, content in tracker.confirmed_values.items():
                if content['saved']['on_avatar_swap']:
                    filtered_params[param] = content

            with open("./params.json", "w", encoding="utf-8") as save:
                save_data = {
                    "version": JSON_SCHEMA_VERSION,
                    "whitelist": whitelist,
                    "params": filtered_params
                }
                json.dump(save_data, save, indent=5)
        except:
            log.exception("Failed to save parameters.")
    
        # gather info about exit data
        exit_code = (
            (stop_signal.is_set()     << 3) |
            (vr_quitting              << 2) |
            (running                  << 1) |
            (pygame_thread.is_alive() << 0)
        )
        log.info(f"Program finished with exit code '{hex(exit_code).upper().replace("X", "x")}'")

        vr.acknowledgeQuit_Exiting()
        openvr.shutdown()
        if pygame_thread.is_alive():
            log.info("Pygame thread still alive, signaling to stop...")
            stop_signal.set()
            pygame_thread.join()

if __name__ == "__main__":
    tracker = ParamTracker(live_tracked_params)
    asyncio.run(main())